# src/database/repositories/dictionary_repository.py
"""
DictionaryRepository - data_dictionary 테이블 관련 조회

data_dictionary 테이블:
- dict_id, source_file_id, source_file_name
- parameter_key, parameter_desc, parameter_unit
- extra_info (JSONB), llm_confidence
"""

from typing import Dict, Any, List, Optional, Tuple
from .base import BaseRepository


class DictionaryRepository(BaseRepository):
    """
    data_dictionary 테이블 조회 Repository
    
    주요 메서드:
    - get_all_entries(): 모든 엔트리 조회
    - get_entry_by_key(): 키로 단일 엔트리 조회
    - get_key_to_id_map(): parameter_key → dict_id 매핑
    - build_llm_context(): LLM 프롬프트용 context 생성
    """
    
    def get_all_entries(self) -> List[Dict[str, Any]]:
        """
        모든 data_dictionary 엔트리 조회
        
        Returns:
            [
                {
                    "dict_id": str,
                    "parameter_key": str,
                    "parameter_desc": str,
                    "parameter_unit": str,
                    "extra_info": dict,
                    "source_file_id": str,
                    "source_file_name": str
                }
            ]
        """
        rows = self._execute_query("""
            SELECT dict_id, parameter_key, parameter_desc, parameter_unit,
                   extra_info, source_file_id, source_file_name
            FROM data_dictionary
            ORDER BY parameter_key
        """, fetch="all")
        
        return [self._row_to_dict(row) for row in rows]
    
    def get_entry_by_key(self, parameter_key: str) -> Optional[Dict[str, Any]]:
        """parameter_key로 단일 엔트리 조회"""
        row = self._execute_query("""
            SELECT dict_id, parameter_key, parameter_desc, parameter_unit,
                   extra_info, source_file_id, source_file_name
            FROM data_dictionary
            WHERE parameter_key = %s
        """, (parameter_key,), fetch="one")
        
        if not row:
            return None
        
        return self._row_to_dict(row)
    
    def get_entry_by_id(self, dict_id: str) -> Optional[Dict[str, Any]]:
        """dict_id로 단일 엔트리 조회"""
        row = self._execute_query("""
            SELECT dict_id, parameter_key, parameter_desc, parameter_unit,
                   extra_info, source_file_id, source_file_name
            FROM data_dictionary
            WHERE dict_id = %s
        """, (dict_id,), fetch="one")
        
        if not row:
            return None
        
        return self._row_to_dict(row)
    
    def get_key_to_id_map(self) -> Dict[str, str]:
        """
        parameter_key → dict_id 매핑 반환
        
        Phase 6에서 LLM이 반환한 key를 dict_id로 변환할 때 사용
        """
        entries = self.get_all_entries()
        return {e['parameter_key']: e['dict_id'] for e in entries}
    
    def get_entry_count(self) -> int:
        """전체 엔트리 수 조회"""
        row = self._execute_query("""
            SELECT COUNT(*) FROM data_dictionary
        """, fetch="one")
        
        return row[0] if row else 0
    
    def build_llm_context(self) -> Tuple[str, str, Dict[str, str]]:
        """
        LLM 프롬프트용 dictionary context 생성
        
        Returns:
            (dict_keys_list, dict_context, key_to_id_map)
            - dict_keys_list: 정확한 키 목록 문자열 (예: '"age", "hr", "sbp"')
            - dict_context: 상세 정의 문자열
            - key_to_id_map: {parameter_key: dict_id}
        """
        entries = self.get_all_entries()
        
        if not entries:
            return "", "", {}
        
        # Key 목록 (정확한 매칭용)
        keys = [f'"{e["parameter_key"]}"' for e in entries]
        dict_keys_list = ", ".join(keys)
        
        # 상세 정의 (LLM이 의미 파악용)
        lines = []
        key_to_id_map = {}
        
        for entry in entries:
            key = entry['parameter_key']
            desc = entry['parameter_desc'] or ''
            unit = entry['parameter_unit'] or '-'
            extra = entry.get('extra_info', {})
            
            key_to_id_map[key] = entry['dict_id']
            
            line = f'- "{key}": {desc}'
            if unit and unit != '-':
                line += f' ({unit})'
            if extra:
                extra_items = list(extra.items())[:2]  # 최대 2개
                if extra_items:
                    extra_str = ", ".join(f"{k}={v}" for k, v in extra_items)
                    line += f' [{extra_str}]'
            lines.append(line)
        
        dict_context = "\n".join(lines)
        
        return dict_keys_list, dict_context, key_to_id_map
    
    def resolve_dict_entry_id(
        self,
        llm_key: Optional[str],
        key_to_id_map: Dict[str, str] = None
    ) -> Tuple[Optional[str], str]:
        """
        LLM이 반환한 key를 dict_id와 status로 변환
        
        Args:
            llm_key: LLM이 반환한 dict_entry_key (None 가능)
            key_to_id_map: {parameter_key: dict_id} 매핑 (None이면 자동 조회)
        
        Returns:
            (dict_id or None, status)
            status: 'matched', 'not_found', 'null_from_llm'
        """
        if llm_key is None:
            return (None, 'null_from_llm')
        
        if key_to_id_map is None:
            key_to_id_map = self.get_key_to_id_map()
        
        if llm_key in key_to_id_map:
            return (key_to_id_map[llm_key], 'matched')
        
        # LLM이 key를 반환했지만 dictionary에 없음
        return (None, 'not_found')
    
    def _row_to_dict(self, row: tuple) -> Dict[str, Any]:
        """DB row를 dict로 변환"""
        (dict_id, key, desc, unit, extra, src_file_id, src_file_name) = row
        
        return {
            "dict_id": str(dict_id),
            "parameter_key": key,
            "parameter_desc": desc,
            "parameter_unit": unit,
            "extra_info": self._parse_json_field(extra),
            "source_file_id": str(src_file_id) if src_file_id else None,
            "source_file_name": src_file_name
        }

