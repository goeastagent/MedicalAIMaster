# shared/data/parameter_registry.py
"""
Parameter Registry - 파라미터 정보 통합 관리

역할:
1. DB param_info를 정규화된 ParameterInfo로 변환/관리
2. 실제 데이터에서 dtype, value_range 등 추출하여 보강
3. Alias 기반 파라미터 이름 해석 (질의 → canonical name)
4. LLM 프롬프트용 컬럼 설명 생성
"""

from typing import Dict, List, Optional, Any, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    import pandas as pd

from shared.models.parameter import ParameterInfo

logger = logging.getLogger(__name__)


class ParameterRegistry:
    """
    파라미터 레지스트리 - 파라미터 정보 통합 관리
    
    Usage:
        # DB param_info에서 생성
        registry = ParameterRegistry.from_param_info([
            {"param_keys": ["HR"], "semantic_name": "Heart Rate", "unit": "bpm"},
            {"param_keys": ["SpO2"], "semantic_name": "Oxygen Saturation", "unit": "%"},
        ])
        
        # 실제 데이터로 보강
        registry.enrich_from_data(sample_df)
        
        # Alias 해석
        registry.resolve_alias("심박수")  # → "HR"
        
        # 파라미터 정보 조회
        hr_info = registry.get("HR")
        print(hr_info.to_prompt_line())
        # → "`HR` (float64) - Heart Rate / 심박수 [bpm]"
    """
    
    def __init__(self):
        self._params: Dict[str, ParameterInfo] = {}  # param_key → ParameterInfo
        self._alias_map: Dict[str, str] = {}         # alias (lowercase) → param_key
    
    @classmethod
    def from_param_info(cls, param_info_list: List[Dict[str, Any]]) -> "ParameterRegistry":
        """
        DB param_info 리스트에서 Registry 생성
        
        Args:
            param_info_list: ExtractionAgent에서 가져온 param_info 리스트
                예: [{"param_keys": ["HR"], "semantic_name": "Heart Rate", ...}, ...]
        
        Returns:
            초기화된 ParameterRegistry
        """
        registry = cls()
        
        for pi_dict in param_info_list:
            try:
                param = ParameterInfo.from_dict(pi_dict)
                registry._add_param(param)
            except Exception as e:
                logger.warning(f"Failed to parse param_info: {pi_dict}, error: {e}")
                continue
        
        logger.debug(f"ParameterRegistry initialized with {len(registry)} parameters")
        return registry
    
    def _add_param(self, param: ParameterInfo) -> None:
        """파라미터 추가 및 alias 맵 업데이트"""
        self._params[param.param_key] = param
        
        # Alias 맵 구성 (lowercase)
        self._alias_map[param.param_key.lower()] = param.param_key
        for alias in param.aliases:
            alias_lower = alias.lower()
            if alias_lower not in self._alias_map:
                self._alias_map[alias_lower] = param.param_key
        if param.semantic_name:
            semantic_lower = param.semantic_name.lower()
            if semantic_lower not in self._alias_map:
                self._alias_map[semantic_lower] = param.param_key
    
    def get(self, key: str) -> Optional[ParameterInfo]:
        """
        param_key로 파라미터 정보 조회
        
        Args:
            key: 파라미터 키 (컬럼명)
        
        Returns:
            ParameterInfo 또는 None
        """
        return self._params.get(key)
    
    def resolve_alias(self, term: str) -> Optional[str]:
        """
        Alias를 canonical param_key로 해석
        
        Args:
            term: 사용자가 사용한 용어 (예: "심박수", "heart rate")
        
        Returns:
            해당하는 param_key (예: "HR") 또는 None
        """
        term_lower = term.lower().strip()
        
        # 직접 매칭
        if term_lower in self._alias_map:
            return self._alias_map[term_lower]
        
        # 부분 매칭 시도
        for alias, param_key in self._alias_map.items():
            if term_lower in alias or alias in term_lower:
                return param_key
        
        return None
    
    def get_all(self) -> List[ParameterInfo]:
        """전체 파라미터 목록 반환"""
        return list(self._params.values())
    
    def get_param_keys(self) -> List[str]:
        """전체 param_key 목록 반환"""
        return list(self._params.keys())
    
    def enrich_from_data(self, df: "pd.DataFrame") -> None:
        """
        실제 DataFrame에서 dtype, value_range 등 추출하여 보강
        
        Args:
            df: 샘플 DataFrame
        """
        import pandas as pd
        
        for col in df.columns:
            dtype_str = str(df[col].dtype)
            
            if col in self._params:
                # 기존 파라미터 보강
                param = self._params[col]
                param.dtype = dtype_str
                
                # 숫자형이면 value_range 추출
                if df[col].dtype in ['float64', 'float32', 'int64', 'int32']:
                    col_data = df[col].dropna()
                    if len(col_data) > 0:
                        param.value_range = (float(col_data.min()), float(col_data.max()))
            else:
                # DB에 없는 컬럼은 기본 정보로 추가
                new_param = ParameterInfo(
                    param_key=col,
                    dtype=dtype_str,
                    source="inferred"
                )
                self._params[col] = new_param
                self._alias_map[col.lower()] = col
                
        logger.debug(f"ParameterRegistry enriched with data, total params: {len(self)}")
    
    def to_column_descriptions(self) -> Dict[str, Dict[str, Any]]:
        """
        모든 파라미터를 ColumnDescription 호환 Dict로 변환
        
        Returns:
            Dict[param_key, {"name", "dtype", "semantic_name", "unit", "description"}]
        """
        result = {}
        for key, param in self._params.items():
            result[key] = {
                "name": param.param_key,
                "dtype": param.dtype or "unknown",
                "semantic_name": param.semantic_name,
                "unit": param.unit,
                "description": param.description,
            }
        return result
    
    def to_prompt_reference(self) -> str:
        """
        프롬프트용 파라미터 Quick Reference 테이블 생성
        
        Returns:
            Markdown 테이블 형식의 문자열
        """
        lines = ["## Parameter Quick Reference"]
        lines.append("| Column | Meaning | Unit |")
        lines.append("|--------|---------|------|")
        
        for param in self._params.values():
            semantic = param.semantic_name or param.param_key
            # 한글 alias 추가
            korean = param.get_korean_alias()
            if korean and param.semantic_name:
                semantic = f"{param.semantic_name} ({korean})"
            elif korean:
                semantic = korean
            
            unit = param.unit or "-"
            lines.append(f"| {param.param_key} | {semantic} | {unit} |")
        
        return "\n".join(lines)
    
    def get_param_prompt_lines(self) -> List[str]:
        """
        프롬프트용 파라미터 설명 라인 목록 반환
        
        Returns:
            ["  - `HR` (float64) - Heart Rate [bpm]", ...]
        """
        lines = []
        for param in self._params.values():
            lines.append(f"  - {param.to_prompt_line()}")
        return lines
    
    def __contains__(self, key: str) -> bool:
        """key in registry 지원"""
        return key in self._params
    
    def __len__(self) -> int:
        """len(registry) 지원"""
        return len(self._params)
    
    def __repr__(self) -> str:
        return f"ParameterRegistry({len(self)} params: {list(self._params.keys())[:5]}...)"
