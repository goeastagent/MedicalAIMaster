# ExtractionAgent/src/agents/nodes/parameter_resolver/ontology_cache.py
"""
OntologyCache — Neo4j 온톨로지 스타트업 캐시

Neo4j의 ConceptCategory-Parameter 그래프를 프로세스 시작 시 1회 로드하여
런타임에 O(1) 조회를 제공합니다.

주요 기능
─────────
1. get_category_params(categories)
   ConceptCategory 이름 목록으로 해당 파라미터 목록 반환.
   카테고리 쿼리(T-02)에서 LLM이 적은 후보 대신 전체 카테고리 파라미터를
   받을 수 있도록 DB 후보 목록을 확장하는 데 사용.

2. filter_by_measurement_type(params, hint)
   unit / concept 속성으로 "rate", "cumulative", "waveform", "concentration"
   타입을 추론해 후보를 필터링 (T-08/T-09).

3. get_param_info(param_key)
   param_key → {name, unit, concept} 빠른 조회 (O(1)).

Neo4j 연결이 실패하거나 비활성화된 경우에는 조용히 비활성화되어
기존 파이프라인에 영향을 주지 않습니다.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ─── unit 기반 측정 타입 규칙 ─────────────────────────────────────────────────
# 각 집합에 해당하는 unit을 가진 파라미터를 해당 타입으로 분류합니다.
_RATE_UNITS = {"/hr", "/min", "/h"}            # mL/hr, beats/min 등
_CUMULATIVE_UNITS = {"ml", "mg", "mcg", "g", "u", "mmol", "iu"}   # 누적 투여량
_CONCENTRATION_UNITS = {"mcg/ml", "ng/ml", "mg/ml", "mg/dl", "mmol/l", "%"}
_WAVEFORM_CONCEPTS = {"Waveform/Signal"}        # Neo4j concept 속성값
_WAVEFORM_UNITS = {"uv", "mv"}                  # 전기 신호 단위

# ConceptCategory 이름 정규화 맵 (사용자 표현 → Neo4j 노드 이름)
_CATEGORY_ALIASES: Dict[str, str] = {
    "vital": "Vital Signs",
    "vital signs": "Vital Signs",
    "vitals": "Vital Signs",
    "hemodynamic": "Hemodynamics",
    "hemodynamics": "Hemodynamics",
    "cardiac": "Hemodynamics",
    "drug": "Medication",
    "drugs": "Medication",
    "medication": "Medication",
    "medications": "Medication",
    "infusion": "Medication",
    "respiratory": "Respiratory",
    "ventilation": "Respiratory",
    "breathing": "Respiratory",
    "neuro": "Neurological",
    "neurological": "Neurological",
    "brain": "Neurological",
    "lab": "Laboratory:Chemistry",
    "laboratory": "Laboratory:Chemistry",
    "chemistry": "Laboratory:Chemistry",
    "coagulation": "Laboratory:Coagulation",
    "hematology": "Laboratory:Hematology",
    "waveform": "Waveform/Signal",
    "signal": "Waveform/Signal",
    "wave": "Waveform/Signal",
    "anesthesia": "Anesthesia",
    "anesthetic": "Anesthesia",
    "surgical": "Surgical",
    "device": "Device/Equipment",
    "equipment": "Device/Equipment",
}


class OntologyCache:
    """
    Neo4j 온톨로지 런타임 캐시 (Singleton-friendly).

    사용 예:
        cache = OntologyCache()
        cache.load()   # 스타트업 시 1회 호출

        # 카테고리로 파라미터 목록 얻기
        params = cache.get_category_params(["Medication", "Anesthesia"])

        # 측정 타입으로 필터링
        rate_params = cache.filter_by_measurement_type(params, "rate")

        # 특정 key 정보 조회
        info = cache.get_param_info("Orchestra/NEPI_RATE")
    """

    def __init__(self) -> None:
        # category → param dict list
        self._category_params: Dict[str, List[Dict[str, Any]]] = {}
        # param_key → {key, name, unit, concept}
        self._param_lookup: Dict[str, Dict[str, Any]] = {}
        self._enabled = False
        self._loaded = False

    # ──────────────────────────────────────────────────────────────────────────
    # 로드 (스타트업 1회)
    # ──────────────────────────────────────────────────────────────────────────

    def load(self) -> bool:
        """
        Neo4j에서 ConceptCategory-Parameter 그래프를 로드합니다.

        Returns:
            True  — 로드 성공 (캐시 활성화)
            False — Neo4j 비활성화 또는 연결 실패 (기존 경로로 폴백)
        """
        if self._loaded:
            return self._enabled

        try:
            from shared.config.database import Neo4jConfig
            if not Neo4jConfig.ENABLED:
                logger.info("[OntologyCache] Neo4j disabled in config — skipping load")
                self._loaded = True
                return False

            from neo4j import GraphDatabase
            driver = GraphDatabase.driver(
                Neo4jConfig.URI,
                auth=(Neo4jConfig.USER, Neo4jConfig.PASSWORD),
            )
            driver.verify_connectivity()

            with driver.session(database=Neo4jConfig.DATABASE) as session:
                self._load_from_session(session)

            driver.close()
            self._enabled = True
            logger.info(
                f"[OntologyCache] Loaded {len(self._category_params)} categories, "
                f"{len(self._param_lookup)} parameters"
            )

        except Exception as exc:
            logger.warning(f"[OntologyCache] Load failed — cache disabled: {exc}")
            self._enabled = False

        self._loaded = True
        return self._enabled

    def _load_from_session(self, session) -> None:
        """Cypher 쿼리로 전체 ConceptCategory-Parameter 관계 로드."""
        result = session.run("""
            MATCH (c:ConceptCategory)-[:CONTAINS]->(p:Parameter)
            RETURN c.name AS category,
                   p.key  AS key,
                   p.name AS name,
                   p.unit AS unit,
                   p.concept AS concept
            ORDER BY c.name, p.key
        """)

        for rec in result:
            cat = rec["category"] or "Other"
            param = {
                "param_key": rec["key"] or "",
                "semantic_name": rec["name"] or "",
                "unit": rec["unit"] or "",
                "concept_category": rec["concept"] or cat,
            }
            if not param["param_key"]:
                continue

            # category_params
            self._category_params.setdefault(cat, []).append(param)
            # param_lookup (마지막 카테고리가 덮어써도 무방)
            self._param_lookup[param["param_key"]] = param

    # ──────────────────────────────────────────────────────────────────────────
    # 공개 API
    # ──────────────────────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    def get_category_params(
        self,
        category_names: List[str],
        measurement_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        카테고리 이름 목록에 해당하는 파라미터 목록을 반환합니다.

        Args:
            category_names: ConceptCategory 이름 목록.
                            별칭(예: "drug")도 자동 정규화합니다.
            measurement_type: "rate" | "cumulative" | "waveform" |
                              "concentration" | "scalar" | None.
                              None이면 전체 반환.

        Returns:
            param dict 리스트 — 각 항목은 ParameterResolver의 db_matches
            포맷과 동일: {param_key, semantic_name, unit, concept_category}
        """
        if not self._enabled:
            return []

        normalized = [self._normalize_category(c) for c in category_names]
        seen: set = set()
        params: List[Dict[str, Any]] = []

        for cat in normalized:
            for p in self._category_params.get(cat, []):
                key = p["param_key"]
                if key not in seen:
                    seen.add(key)
                    params.append(p)

        if measurement_type:
            params = self.filter_by_measurement_type(params, measurement_type)

        return params

    def filter_by_measurement_type(
        self,
        params: List[Dict[str, Any]],
        measurement_type: str,
    ) -> List[Dict[str, Any]]:
        """
        unit / concept 속성 기반으로 측정 타입을 추론해 필터링합니다.

        Args:
            params: param dict 리스트
            measurement_type: "rate" | "cumulative" | "waveform" |
                              "concentration" | "scalar"

        Returns:
            필터된 param dict 리스트.
            필터 결과가 비어 있으면 원본 리스트를 반환합니다 (폴백).
        """
        if not params or not measurement_type:
            return params

        mt = measurement_type.lower()
        filtered = [p for p in params if self._matches_type(p, mt)]

        # 필터 결과가 비면 원본 반환 (precision 손실 방지)
        return filtered if filtered else params

    def get_param_info(self, param_key: str) -> Optional[Dict[str, Any]]:
        """param_key → {param_key, semantic_name, unit, concept_category} 빠른 조회."""
        return self._param_lookup.get(param_key)

    def list_categories(self) -> List[str]:
        """로드된 ConceptCategory 이름 목록 반환."""
        return sorted(self._category_params.keys())

    # ──────────────────────────────────────────────────────────────────────────
    # 내부 헬퍼
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_category(term: str) -> str:
        """
        사용자 카테고리 표현 → Neo4j ConceptCategory 이름으로 정규화.
        예: "drug" → "Medication", "hemodynamic" → "Hemodynamics"
        """
        key = term.strip().lower()
        return _CATEGORY_ALIASES.get(key, term.strip())

    @staticmethod
    def _matches_type(param: Dict[str, Any], measurement_type: str) -> bool:
        """파라미터가 주어진 측정 타입에 해당하는지 판단."""
        unit = (param.get("unit") or "").lower()
        concept = param.get("concept_category") or ""

        if measurement_type == "waveform":
            if concept in _WAVEFORM_CONCEPTS:
                return True
            if any(u in unit for u in _WAVEFORM_UNITS):
                return True
            return False

        if measurement_type == "rate":
            return any(suffix in unit for suffix in _RATE_UNITS)

        if measurement_type == "cumulative":
            unit_stripped = unit.replace(" ", "")
            return unit_stripped in _CUMULATIVE_UNITS

        if measurement_type == "concentration":
            unit_stripped = unit.replace(" ", "").lower()
            return unit_stripped in _CONCENTRATION_UNITS

        if measurement_type == "scalar":
            # waveform/rate/cumulative/concentration에 해당하지 않으면 scalar
            return not any([
                any(suffix in unit for suffix in _RATE_UNITS),
                unit.replace(" ", "") in _CUMULATIVE_UNITS,
                unit.replace(" ", "").lower() in _CONCENTRATION_UNITS,
                concept in _WAVEFORM_CONCEPTS,
                any(u in unit for u in _WAVEFORM_UNITS),
            ])

        return True


# ─── 프로세스 공유 싱글톤 ─────────────────────────────────────────────────────
_cache: Optional[OntologyCache] = None


def get_ontology_cache() -> OntologyCache:
    """
    OntologyCache 싱글톤 반환.

    최초 호출 시 Neo4j 로드를 수행합니다.
    ParameterResolverNode.__init__ 또는 process 시작 시 호출하세요.
    """
    global _cache
    if _cache is None:
        _cache = OntologyCache()
        _cache.load()
    return _cache
