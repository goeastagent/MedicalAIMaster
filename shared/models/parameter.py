# shared/models/parameter.py
"""
Parameter 모델 - 정규화된 파라미터 정보

DB의 param_info를 정규화하고, 컬럼명/의미/단위 등을 통합 관리합니다.
AnalysisAgent의 Context Engineering에서 LLM에게 정확한 컬럼 정보를 전달하는데 사용됩니다.
"""

from typing import Optional, List, Tuple, Dict, Any
from pydantic import BaseModel, Field


class ParameterInfo(BaseModel):
    """
    정규화된 파라미터 정보
    
    DB의 param_info를 정규화하고, 실제 데이터에서 추출한 정보를 통합합니다.
    LLM이 컬럼명을 정확히 이해하고 사용할 수 있도록 의미론적 정보를 포함합니다.
    
    Example:
        param = ParameterInfo(
            param_key="HR",
            semantic_name="Heart Rate",
            aliases=["심박수", "heart rate", "heartrate"],
            unit="bpm",
            description="분당 심박수 측정치",
            category="Vitals",
            dtype="float64",
            value_range=(30.0, 200.0)
        )
        
        # Alias 매칭
        param.matches_term("심박수")  # True
        param.matches_term("SpO2")    # False
        
        # 프롬프트용 출력
        print(param.to_prompt_line())
        # → "`HR` (float64) - Heart Rate / 심박수 [bpm]"
    """
    
    # === 필수 필드 ===
    param_key: str
    """실제 컬럼명 (canonical name). 코드에서 사용해야 하는 정확한 이름."""
    
    # === 의미론적 정보 (DB에서) ===
    semantic_name: Optional[str] = None
    """영문 의미명. 예: "Heart Rate", "Oxygen Saturation" """
    
    aliases: List[str] = Field(default_factory=list)
    """매칭 가능한 별칭들. 예: ["심박수", "heart rate", "HR"] """
    
    unit: Optional[str] = None
    """측정 단위. 예: "bpm", "%", "mmHg" """
    
    description: Optional[str] = None
    """상세 설명"""
    
    category: Optional[str] = None
    """분류. 예: "Vitals", "Demographics", "Lab" """
    
    # === 데이터에서 추출 (enrich_from_data) ===
    dtype: Optional[str] = None
    """실제 데이터 타입. 예: "float64", "int64" """
    
    value_range: Optional[Tuple[float, float]] = None
    """값 범위 (min, max). 데이터 품질 검증용"""
    
    # === 메타 ===
    source: Optional[str] = None
    """정보 출처. "db", "ontology", "inferred" """
    
    confidence: Optional[float] = None
    """DB 매칭 신뢰도 (0~1)"""
    
    def matches_term(self, term: str) -> bool:
        """
        주어진 용어가 이 파라미터와 매칭되는지 확인
        
        Args:
            term: 확인할 용어 (예: "심박수", "HR", "heart rate")
        
        Returns:
            매칭 여부
        """
        term_lower = term.lower().strip()
        
        # param_key 직접 매칭
        if self.param_key.lower() == term_lower:
            return True
        
        # aliases 매칭
        for alias in self.aliases:
            if alias.lower() == term_lower:
                return True
        
        # semantic_name 부분 매칭
        if self.semantic_name:
            semantic_lower = self.semantic_name.lower()
            if term_lower in semantic_lower or semantic_lower in term_lower:
                return True
        
        return False
    
    def get_korean_alias(self) -> Optional[str]:
        """한글 alias 반환 (있으면)"""
        for alias in self.aliases:
            if any('\uac00' <= c <= '\ud7a3' for c in alias):
                return alias
        return None
    
    def to_prompt_line(self) -> str:
        """
        프롬프트용 컬럼 설명 한 줄 생성
        
        Returns:
            예: "`HR` (float64) - Heart Rate / 심박수 [bpm]"
        """
        parts = [f"`{self.param_key}`"]
        
        # dtype
        if self.dtype:
            parts.append(f"({self.dtype})")
        
        # semantic_name
        if self.semantic_name:
            parts.append(f"- {self.semantic_name}")
            
            # 한글 alias 추가 (있으면)
            korean_alias = self.get_korean_alias()
            if korean_alias and korean_alias != self.semantic_name:
                parts.append(f"/ {korean_alias}")
        
        # unit
        if self.unit:
            parts.append(f"[{self.unit}]")
        
        return " ".join(parts)
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ParameterInfo":
        """
        DB param_info dict에서 생성
        
        Args:
            d: DB에서 가져온 param_info 딕셔너리
               예: {"param_keys": ["HR"], "semantic_name": "Heart Rate", ...}
        
        Returns:
            ParameterInfo 인스턴스
        """
        param_keys = d.get("param_keys", [])
        param_key = param_keys[0] if param_keys else d.get("param_key", "unknown")
        
        # aliases 구성
        aliases = []
        if d.get("term") and d["term"] != param_key:
            aliases.append(d["term"])
        if d.get("semantic_name"):
            aliases.append(d["semantic_name"])
        # 추가 alias가 있으면 포함
        aliases.extend(d.get("aliases", []))
        
        return cls(
            param_key=param_key,
            semantic_name=d.get("semantic_name"),
            aliases=list(set(aliases)),  # 중복 제거
            unit=d.get("unit"),
            description=d.get("description"),
            category=d.get("concept_category"),
            confidence=d.get("confidence") or d.get("match_confidence"),
            source="db"
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "param_key": self.param_key,
            "semantic_name": self.semantic_name,
            "aliases": self.aliases,
            "unit": self.unit,
            "description": self.description,
            "category": self.category,
            "dtype": self.dtype,
            "value_range": self.value_range,
            "source": self.source,
            "confidence": self.confidence,
        }
