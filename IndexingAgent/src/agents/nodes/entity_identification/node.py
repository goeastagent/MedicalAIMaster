# src/agents/nodes/entity_identification/node.py
"""
Entity Identification Node

데이터 파일(is_metadata=false)의 행이 무엇을 나타내는지(row_represents)와
고유 식별자 컬럼(entity_identifier)을 식별합니다.

주요 기능:
- LLM을 사용해 각 테이블의 row_represents 추론 (surgery, patient, lab_result 등)
- 컬럼 통계(unique count)를 활용해 entity_identifier 식별
- table_entities 테이블에 결과 저장
"""

import time
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

from ...state import AgentState
from ...models.llm_responses import (
    TableEntityResult,
    EntityIdentificationResponse,
    EntityIdentificationResult,
)
from ...base import BaseNode, LLMMixin, DatabaseMixin
from ...registry import register_node
from src.database import OntologySchemaManager
from src.config import EntityIdentificationConfig, LLMConfig
from .prompts import EntityIdentificationPrompt


@register_node
class EntityIdentificationNode(BaseNode, LLMMixin, DatabaseMixin):
    """
    Entity Identification Node (LLM-based)
    
    데이터 파일(is_metadata=false)의 행이 무엇을 나타내는지(row_represents)와
    고유 식별자 컬럼(entity_identifier)을 식별합니다.
    
    Input (from state):
        - data_files: is_metadata=false인 파일 경로 목록
        - data_semantic_result: 이전 단계 완료 정보 (column_metadata 분석 완료)
    
    Output:
        - entity_identification_result: EntityIdentificationResult 형태
        - table_entity_results: TableEntityResult 목록
    """
    
    name = "entity_identification"
    description = "Entity 식별 (row_represents, entity_identifier)"
    order = 800
    requires_llm = True
    
    # 프롬프트 클래스 연결
    prompt_class = EntityIdentificationPrompt
    
    def _load_data_files_with_columns(self, data_files: List[str]) -> List[Dict[str, Any]]:
        """
        데이터 파일과 그 컬럼 정보를 DB에서 로드
        
        Uses:
          - FileRepository.get_files_by_paths()
          - ColumnRepository.get_columns_with_stats()
          - ColumnRepository.get_columns_with_semantic()
        
        Returns:
            [
                {
                    "file_id": "uuid",
                    "file_name": "clinical_data.csv",
                    "row_count": 6388,
                    "columns": [
                        {
                            "original_name": "caseid",
                            "semantic_name": "Case ID",
                            "column_type": "categorical",
                            "concept_category": "Identifiers",
                            "unique_count": 6388,
                            ...
                        },
                        ...
                    ]
                },
                ...
            ]
        """
        if not data_files:
            return []
        
        files_info = []
        
        try:
            # 파일 정보 조회
            files = self.file_repo.get_files_by_paths(data_files)
            
            for f in files:
                file_id = f['file_id']
                file_name = f['file_name']
                file_path = f['file_path']
                
                # row_count 추출
                metadata = f.get('file_metadata', {})
                row_count = metadata.get('row_count', 0) if metadata else 0
                
                # 컬럼 정보 조회 (통계 + semantic)
                # get_columns_with_stats() + get_columns_with_semantic() 병합
                cols_stats = self.column_repo.get_columns_with_stats(file_id)
                cols_semantic = self.column_repo.get_columns_with_semantic(file_id)
                
                # 병합: col_id 기준
                semantic_map = {c['col_id']: c for c in cols_semantic}
                
                columns = []
                for col in cols_stats:
                    col_id = col['col_id']
                    sem_info = semantic_map.get(col_id, {})
                    
                    columns.append({
                        "original_name": col['original_name'],
                        "column_role": col.get('column_role'),
                        "semantic_name": sem_info.get('semantic_name'),
                        "column_type": col.get('column_type'),
                        "concept_category": sem_info.get('concept_category'),
                        "unique_count": col.get('unique_count'),
                        "column_info": col.get('column_info', {})
                    })
                
                # filename_values 추출 (파일명에서 추출된 값들)
                filename_values = f.get('filename_values', {})
                
                files_info.append({
                    "file_id": file_id,
                    "file_name": file_name,
                    "row_count": row_count or 0,
                    "file_path": file_path,
                    "columns": columns,
                    "filename_values": filename_values
                })
        
        except Exception as e:
            self.log(f"❌ Error loading data files: {e}")
            import traceback
            traceback.print_exc()
        
        return files_info
    
    def _build_tables_context(self, files_info: List[Dict[str, Any]]) -> str:
        """
        LLM 프롬프트용 테이블 컨텍스트 생성
        
        column_role을 활용하여 identifier 후보를 강조합니다.
        filename_values도 포함하여 파일명에서 추출된 값을 표시합니다.
        
        Args:
            files_info: _load_data_files_with_columns()의 결과
        
        Returns:
            포맷된 문자열
        """
        lines = []
        
        for file_info in files_info:
            file_name = file_info['file_name']
            row_count = file_info['row_count']
            columns = file_info['columns']
            filename_values = file_info.get('filename_values', {})
            
            lines.append(f"\n## {file_name}")
            lines.append(f"Rows: {row_count:,}")
            
            # filename_values 표시 (파일명에서 추출된 값)
            if filename_values:
                lines.append("Filename-extracted values (embedded in filename):")
                for key, value in filename_values.items():
                    lines.append(f"  - {key}: {value}")
            
            lines.append("Columns:")
            
            max_cols = EntityIdentificationConfig.MAX_COLUMNS_PER_TABLE
            display_cols = columns[:max_cols] if max_cols > 0 else columns
            
            for col in display_cols:
                name = col['original_name']
                col_role = col.get('column_role')
                semantic = col.get('semantic_name') or name
                concept = col.get('concept_category')
                col_type = col.get('column_type') or '-'
                unique_count = col.get('unique_count')
                
                # column_role에 따라 다른 형식으로 표시
                if col_role == 'identifier':
                    # identifier는 강조 표시
                    line = f"  - {name} 🔑[IDENTIFIER]"
                    if unique_count is not None:
                        line += f" unique: {unique_count:,}"
                        # row_count와 비교하여 unique identifier 후보 표시
                        if row_count > 0 and unique_count == row_count:
                            line += " ← matches row count!"
                elif col_role == 'parameter_name':
                    # parameter는 semantic 정보 포함
                    line = f"  - {name}"
                    if semantic and semantic != name:
                        line += f" ({semantic})"
                    if concept:
                        line += f" [{concept}]"
                elif col_role == 'timestamp':
                    line = f"  - {name} [timestamp]"
                elif col_role == 'attribute':
                    line = f"  - {name} [attribute]"
                    if unique_count is not None:
                        line += f" unique: {unique_count:,}"
                else:
                    # 기타 컬럼
                    line = f"  - {name} [{col_type}]"
                    if EntityIdentificationConfig.SHOW_UNIQUE_COUNTS and unique_count is not None:
                        line += f" unique: {unique_count:,}"
                
                lines.append(line)
            
            if max_cols > 0 and len(columns) > max_cols:
                lines.append(f"  ... and {len(columns) - max_cols} more columns")
        
        return "\n".join(lines)
    
    def _call_llm_for_entity_identification(
        self,
        files_info: List[Dict[str, Any]]
    ) -> Tuple[List[TableEntityResult], int]:
        """
        LLM을 호출하여 Entity 식별
        
        Args:
            files_info: 테이블 정보 목록
        
        Returns:
            (결과 목록, LLM 호출 횟수)
        """
        if not files_info:
            return [], 0
        
        tables_context = self._build_tables_context(files_info)
        
        # PromptTemplate을 사용하여 프롬프트 빌드
        prompt = self.prompt_class.build(tables_context=tables_context)
        
        self.log(f"📤 Sending {len(files_info)} tables to LLM...", indent=1)
        
        llm_calls = 0
        results = []
        
        for attempt in range(EntityIdentificationConfig.MAX_RETRIES):
            try:
                response = self.call_llm_json(
                    prompt,
                    max_tokens=LLMConfig.MAX_TOKENS
                )
                llm_calls += 1
                
                if response and 'tables' in response:
                    for table_data in response['tables']:
                        result = TableEntityResult(
                            file_name=table_data.get('file_name', ''),
                            row_represents=table_data.get('row_represents', 'unknown'),
                            entity_identifier=table_data.get('entity_identifier'),
                            confidence=float(table_data.get('confidence', 0.0)),
                            reasoning=table_data.get('reasoning', '')
                        )
                        results.append(result)
                    
                    return results, llm_calls
                else:
                    self.log(f"⚠️ Invalid LLM response format, attempt {attempt + 1}", indent=1)
                    
            except Exception as e:
                self.log(f"❌ LLM call failed (attempt {attempt + 1}): {e}", indent=1)
                if attempt < EntityIdentificationConfig.MAX_RETRIES - 1:
                    time.sleep(EntityIdentificationConfig.RETRY_DELAY_SECONDS)
        
        return results, llm_calls
    
    def _save_table_entities(
        self,
        files_info: List[Dict[str, Any]],
        llm_results: List[TableEntityResult]
    ) -> int:
        """
        LLM 결과를 table_entities 테이블에 저장
        
        Args:
            files_info: 파일 정보 (file_id 포함)
            llm_results: LLM 분석 결과
        
        Returns:
            저장된 엔티티 수
        """
        # file_name → file_id 매핑 생성
        name_to_info = {f['file_name']: f for f in files_info}
        
        entities_to_save = []
        
        for result in llm_results:
            file_info = name_to_info.get(result.file_name)
            if not file_info:
                self.log(f"⚠️ File not found: {result.file_name}", indent=1)
                continue
            
            entities_to_save.append({
                "file_id": file_info['file_id'],
                "row_represents": result.row_represents,
                "entity_identifier": result.entity_identifier,
                "confidence": result.confidence,
                "reasoning": result.reasoning
            })
        
        if entities_to_save:
            self.entity_repo.save_table_entities(entities_to_save)
        
        return len(entities_to_save)
    
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Entity Identification 실행
        
        데이터 파일의 행이 무엇을 나타내는지(row_represents)와
        고유 식별자 컬럼(entity_identifier)을 식별합니다.
        """
        started_at = datetime.now().isoformat()
        
        # 1. 데이터 파일 목록 가져오기
        data_files = state.get('data_files', [])
        
        if not data_files:
            self.log("ℹ️  No data files to analyze")
            return {
                "entity_identification_result": EntityIdentificationResult(
                    started_at=started_at,
                    completed_at=datetime.now().isoformat()
                ).model_dump(),
                "table_entity_results": []
            }
        
        self.log(f"📁 Data files to analyze: {len(data_files)}")
        for f in data_files[:5]:
            self.log(f"- {f}", indent=1)
        if len(data_files) > 5:
            self.log(f"... and {len(data_files) - 5} more", indent=1)
        
        # 2. Ontology 스키마 초기화
        schema_manager = OntologySchemaManager()
        schema_manager.create_tables()
        
        # 3. 데이터 파일과 컬럼 정보 로드
        self.log("📥 Loading data files with column info...")
        files_info = self._load_data_files_with_columns(data_files)
        
        if not files_info:
            self.log("⚠️  No file info loaded from database")
            return {
                "entity_identification_result": EntityIdentificationResult(
                    total_tables=len(data_files),
                    started_at=started_at,
                    completed_at=datetime.now().isoformat()
                ).model_dump(),
                "table_entity_results": []
            }
        
        self.log(f"✅ Loaded {len(files_info)} files with column info", indent=1)
        
        # 4. LLM 호출 (배치 처리)
        self.log("🤖 Calling LLM for entity identification...")
        
        all_results: List[TableEntityResult] = []
        total_llm_calls = 0
        
        # 배치 크기에 따라 분할
        batch_size = EntityIdentificationConfig.TABLE_BATCH_SIZE
        for i in range(0, len(files_info), batch_size):
            batch = files_info[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(files_info) + batch_size - 1) // batch_size
            
            self.log(f"📦 Batch {batch_num}/{total_batches} ({len(batch)} tables)", indent=1)
            
            results, llm_calls = self._call_llm_for_entity_identification(batch)
            all_results.extend(results)
            total_llm_calls += llm_calls
            
            self.log(f"✅ Got {len(results)} results", indent=2)
        
        # 5. DB 저장
        self.log("💾 Saving to table_entities...")
        saved_count = self._save_table_entities(files_info, all_results)
        self.log(f"✅ Saved {saved_count} table entities", indent=1)
        
        # 6. 통계 계산
        entities_identified = sum(1 for r in all_results if r.row_represents != 'unknown')
        identifiers_found = sum(1 for r in all_results if r.entity_identifier is not None)
        high_conf = sum(1 for r in all_results if r.confidence >= EntityIdentificationConfig.CONFIDENCE_THRESHOLD)
        low_conf = sum(1 for r in all_results if r.confidence < EntityIdentificationConfig.CONFIDENCE_THRESHOLD)
        
        # 7. 결과 출력
        self.log(f"Total tables: {len(files_info)}", indent=1)
        self.log(f"Analyzed: {len(all_results)}", indent=1)
        self.log(f"Entities identified: {entities_identified}", indent=1)
        self.log(f"With unique identifier: {identifiers_found}", indent=1)
        self.log(f"High confidence (≥{EntityIdentificationConfig.CONFIDENCE_THRESHOLD}): {high_conf}", indent=1)
        self.log(f"Low confidence: {low_conf}", indent=1)
        self.log(f"LLM calls: {total_llm_calls}", indent=1)
        
        # 상세 결과 출력
        self.log("📋 Entity Results:")
        for result in all_results:
            identifier_str = result.entity_identifier or "(none)"
            conf_emoji = "🟢" if result.confidence >= EntityIdentificationConfig.CONFIDENCE_THRESHOLD else "🟡"
            self.log(f"{conf_emoji} {result.file_name}", indent=1)
            self.log(f"row_represents: {result.row_represents}", indent=2)
            self.log(f"entity_identifier: {identifier_str}", indent=2)
            self.log(f"confidence: {result.confidence:.2f}", indent=2)
        
        # 8. 결과 반환
        completed_at = datetime.now().isoformat()
        
        phase_result = EntityIdentificationResult(
            total_tables=len(files_info),
            tables_analyzed=len(all_results),
            entities_identified=entities_identified,
            identifiers_found=identifiers_found,
            high_confidence=high_conf,
            low_confidence=low_conf,
            llm_calls=total_llm_calls,
            started_at=started_at,
            completed_at=completed_at
        )
        
        return {
            "entity_identification_result": phase_result.model_dump(),
            "table_entity_results": [r.model_dump() for r in all_results]
        }
    
    @classmethod
    def run_standalone(cls, data_files: List[str]) -> Dict[str, Any]:
        """
        단독 실행용 메서드
        
        Args:
            data_files: 분석할 데이터 파일 경로 리스트
        
        Returns:
            실행 결과 state
        """
        node = cls()
        initial_state = {
            'data_files': data_files
        }
        return node(initial_state)

