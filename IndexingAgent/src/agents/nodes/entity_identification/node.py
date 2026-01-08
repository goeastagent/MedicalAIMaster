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

from IndexingAgent.src.models.llm_responses import (
    TableEntityResult,
    EntityIdentificationResult,
)
from shared.langgraph import BaseNode, LLMMixin, DatabaseMixin
from shared.langgraph import register_node
from shared.database import OntologySchemaManager
from shared.database.repositories import FileGroupRepository
from IndexingAgent.src.config import EntityIdentificationConfig, IndexingConfig
from shared.config import LLMConfig
from .prompts import EntityIdentificationPrompt, GroupEntityPrompt


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
    group_prompt_class = GroupEntityPrompt
    
    def __init__(self):
        super().__init__()
        self._group_repo: Optional[FileGroupRepository] = None
    
    def _get_group_repo(self) -> FileGroupRepository:
        """FileGroupRepository 싱글톤 반환"""
        if self._group_repo is None:
            self._group_repo = FileGroupRepository()
        return self._group_repo
    
    # ═══════════════════════════════════════════════════════════════════════════
    # Phase 1: 그룹 Entity 분석
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _analyze_group_entity(self, group: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        그룹의 샘플 파일로 Entity 분석
        
        Args:
            group: 그룹 정보 (group_id, group_name, grouping_criteria 등)
        
        Returns:
            {
                'row_represents': str,
                'entity_identifier_source': str,  # 'filename' or 'content'
                'entity_identifier_key': str,     # 'caseid'
                'confidence': float,
                'reasoning': str,
                'sample_file_ids': list
            }
            또는 None (분석 실패)
        """
        group_id = group['group_id']
        group_name = group['group_name']
        criteria = group.get('grouping_criteria', {})
        file_count = group.get('file_count', 0)
        sample_file_ids = group.get('sample_file_ids', [])
        
        self.log(f"📦 Analyzing group: {group_name} ({file_count} files)", indent=1)
        
        # 샘플 파일 선택
        group_repo = self._get_group_repo()
        
        if sample_file_ids:
            # 기존 샘플 파일 사용
            sample_file_id = sample_file_ids[0]
            sample_file = self.file_repo.get_file_by_id(sample_file_id)
        else:
            # 그룹에서 샘플 파일 선택
            sample_files = group_repo.get_sample_files_for_analysis(group_id, sample_size=1)
            if not sample_files:
                self.log(f"⚠️ No sample files for group {group_name}", indent=2)
                return None
            sample_file = sample_files[0]
            sample_file_id = sample_file['file_id']
        
        if not sample_file:
            self.log(f"⚠️ Sample file not found for group {group_name}", indent=2)
            return None
        
        sample_file_path = sample_file.get('file_path')
        self.log(f"🎯 Sample file: {sample_file_path.split('/')[-1] if sample_file_path else 'unknown'}", indent=2)
        
        # 샘플 파일의 컬럼 정보 로드
        files_info = self._load_data_files_with_columns([sample_file_path])
        if not files_info:
            self.log(f"⚠️ No column info for sample file", indent=2)
            return None
        
        sample_info = files_info[0]
        
        # 그룹 컨텍스트 빌드
        group_context = self._build_group_entity_context(
            group_name=group_name,
            file_count=file_count,
            criteria=criteria,
            sample_info=sample_info
        )
        
        # LLM 호출
        prompt = self.group_prompt_class.build(group_context=group_context)
        
        try:
            response = self.call_llm_json(prompt)
            
            if not response or response.get('error'):
                self.log(f"❌ LLM error: {response.get('error') if response else 'No response'}", indent=2)
                return None
            
            # 응답 파싱
            row_represents = response.get('row_represents', 'unknown')
            entity_source = response.get('entity_identifier_source', 'filename')
            entity_key = response.get('entity_identifier_key')
            confidence = float(response.get('confidence', 0.0))
            reasoning = response.get('reasoning', '')
            
            # pattern_columns에서 entity_key 추출 (fallback)
            if not entity_key:
                pattern_columns = criteria.get('pattern_columns', [])
                if pattern_columns:
                    entity_key = pattern_columns[0].get('name')
            
            self.log(f"✅ row_represents: {row_represents}", indent=2)
            self.log(f"✅ entity_identifier: {entity_source}/{entity_key}", indent=2)
            self.log(f"✅ confidence: {confidence:.2f}", indent=2)
            
            return {
                'row_represents': row_represents,
                'entity_identifier_source': entity_source,
                'entity_identifier_key': entity_key,
                'confidence': confidence,
                'reasoning': reasoning,
                'sample_file_ids': [sample_file_id]
            }
            
        except Exception as e:
            self.log(f"❌ LLM call failed: {e}", indent=2)
            return None
    
    def _build_group_entity_context(
        self,
        group_name: str,
        file_count: int,
        criteria: Dict,
        sample_info: Dict
    ) -> str:
        """
        그룹 Entity 분석용 LLM 컨텍스트 빌드
        """
        lines = []
        
        # 그룹 정보
        lines.append("## File Group Information")
        lines.append(f"- Group Name: {group_name}")
        lines.append(f"- Total Files: {file_count}")
        lines.append(f"- Extensions: {criteria.get('extensions', [])}")
        
        # 패턴 정보
        pattern_regex = criteria.get('pattern_regex')
        pattern_columns = criteria.get('pattern_columns', [])
        if pattern_regex:
            lines.append(f"- Filename Pattern: {pattern_regex}")
            if pattern_columns:
                cols_str = ', '.join([c.get('name', '?') for c in pattern_columns])
                lines.append(f"- Pattern Columns: {cols_str}")
        
        # 샘플 파일 정보
        lines.append("")
        lines.append("## Sample File")
        lines.append(f"- File Name: {sample_info.get('file_name', 'unknown')}")
        lines.append(f"- Row Count: {sample_info.get('row_count', 0):,}")
        
        # filename_values
        filename_values = sample_info.get('filename_values', {})
        if filename_values:
            lines.append("- Filename-extracted values:")
            for key, value in filename_values.items():
                lines.append(f"  - {key}: {value}")
        
        # 컬럼 정보
        columns = sample_info.get('columns', [])
        if columns:
            lines.append("")
            lines.append("## Sample File Columns")
            
            # identifier 컬럼 먼저
            id_cols = [c for c in columns if c.get('column_role') == 'identifier']
            param_cols = [c for c in columns if c.get('column_role') == 'parameter_name']
            other_cols = [c for c in columns if c.get('column_role') not in ('identifier', 'parameter_name')]
            
            if id_cols:
                lines.append("Identifier columns:")
                for col in id_cols:
                    unique = col.get('unique_count')
                    lines.append(f"  - {col['original_name']} 🔑 (unique: {unique:,})" if unique else f"  - {col['original_name']} 🔑")
            
            if param_cols:
                lines.append("Parameter columns (first 10):")
                for col in param_cols[:10]:
                    semantic = col.get('semantic_name') or col['original_name']
                    lines.append(f"  - {col['original_name']} ({semantic})")
                if len(param_cols) > 10:
                    lines.append(f"  ... and {len(param_cols) - 10} more")
            
            if other_cols:
                lines.append("Other columns (first 5):")
                for col in other_cols[:5]:
                    lines.append(f"  - {col['original_name']} [{col.get('column_type', '-')}]")
                if len(other_cols) > 5:
                    lines.append(f"  ... and {len(other_cols) - 5} more")
        
        return "\n".join(lines)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # Phase 2: 비그룹 파일 분석 (기존 로직)
    # ═══════════════════════════════════════════════════════════════════════════
    
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
        Entity Identification 실행 (v2)
        
        수정된 로직:
        Phase 1: 그룹화된 파일 처리 (그룹 단위 분석 + 전파)
        Phase 2: 비그룹 파일 처리 (기존 개별 분석)
        """
        started_at = datetime.now().isoformat()
        
        # Ontology 스키마 초기화
        schema_manager = OntologySchemaManager()
        schema_manager.create_tables()
        
        # 통계 초기화
        groups_processed = 0
        group_files_propagated = 0
        ungrouped_files_processed = 0
        total_llm_calls = 0
        all_results: List[TableEntityResult] = []
        
        # ═══════════════════════════════════════════════════════════════════════════
        # Phase 1: 그룹화된 파일 처리
        # ═══════════════════════════════════════════════════════════════════════════
        self.log("=" * 50)
        self.log("📦 Phase 1: Processing file groups...")
        
        group_repo = self._get_group_repo()
        groups = group_repo.get_groups_for_entity_analysis()
        groups_skipped = 0
        
        if groups:
            self.log(f"📦 Found {len(groups)} groups to analyze", indent=1)
            
            # Skip already analyzed groups (FORCE_REANALYZE=false인 경우)
            groups_to_process = groups
            if not IndexingConfig.FORCE_REANALYZE:
                groups_to_process, groups_skipped = self._filter_unanalyzed_groups_entity(groups)
                if groups_skipped > 0:
                    self.log(f"⏭️  Skipping {groups_skipped} already analyzed groups", indent=1)
            
            for group in groups_to_process:
                group_result = self._analyze_group_entity(group)
                total_llm_calls += 1
                
                if group_result:
                    groups_processed += 1
                    
                    # file_group 테이블 업데이트
                    group_repo.update_group_analysis(
                        group_id=group['group_id'],
                        row_represents=group_result['row_represents'],
                        entity_identifier_source=group_result['entity_identifier_source'],
                        entity_identifier_key=group_result['entity_identifier_key'],
                        confidence=group_result['confidence'],
                        reasoning=group_result['reasoning'],
                        sample_file_ids=group_result.get('sample_file_ids')
                    )
                    
                    # 그룹 내 모든 파일에 table_entities 전파
                    propagated = self.entity_repo.bulk_save_group_entities(
                        group_id=group['group_id'],
                        row_represents=group_result['row_represents'],
                        entity_identifier_key=group_result['entity_identifier_key'],
                        confidence=group_result['confidence'],
                        reasoning=group_result['reasoning']
                    )
                    group_files_propagated += propagated
                    
                    self.log(f"✅ {group['group_name']}: {group_result['row_represents']} → {propagated} files", indent=2)
                else:
                    self.log(f"⚠️ {group['group_name']}: Analysis failed", indent=2)
        else:
            self.log("⚠️ No groups to analyze", indent=1)
        
        # ═══════════════════════════════════════════════════════════════════════════
        # Phase 2: 비그룹 파일 처리 (기존 로직)
        # ═══════════════════════════════════════════════════════════════════════════
        self.log("=" * 50)
        self.log("📄 Phase 2: Processing ungrouped files...")
        
        ungrouped_files = self.file_repo.get_ungrouped_data_files()
        ungrouped_skipped = 0
        
        if ungrouped_files:
            self.log(f"📄 Found {len(ungrouped_files)} ungrouped files to analyze", indent=1)
            
            # Skip already analyzed files (FORCE_REANALYZE=false인 경우)
            if not IndexingConfig.FORCE_REANALYZE:
                original_count = len(ungrouped_files)
                ungrouped_files = self._filter_unanalyzed_files_entity(ungrouped_files)
                ungrouped_skipped = original_count - len(ungrouped_files)
                if ungrouped_skipped > 0:
                    self.log(f"⏭️  Skipping {ungrouped_skipped} already analyzed files", indent=1)
            
            if ungrouped_files:
                # 파일 정보 로드
                files_info = self._load_data_files_with_columns(ungrouped_files)
                
                if files_info:
                    # 배치 처리
                    batch_size = EntityIdentificationConfig.TABLE_BATCH_SIZE
                    for i in range(0, len(files_info), batch_size):
                        batch = files_info[i:i + batch_size]
                        batch_num = i // batch_size + 1
                        total_batches = (len(files_info) + batch_size - 1) // batch_size
                        
                        self.log(f"📦 Batch {batch_num}/{total_batches} ({len(batch)} tables)", indent=2)
                        
                        results, llm_calls = self._call_llm_for_entity_identification(batch)
                        all_results.extend(results)
                        total_llm_calls += llm_calls
                    
                    # DB 저장
                    saved_count = self._save_table_entities(files_info, all_results)
                    ungrouped_files_processed = saved_count
                    self.log(f"✅ Saved {saved_count} table entities", indent=2)
            else:
                self.log("✅ All ungrouped files already analyzed", indent=1)
        else:
            self.log("⚠️ No ungrouped files to analyze", indent=1)
        
        # ═══════════════════════════════════════════════════════════════════════════
        # 결과 요약
        # ═══════════════════════════════════════════════════════════════════════════
        completed_at = datetime.now().isoformat()
        
        # 통계 계산
        entities_identified = sum(1 for r in all_results if r.row_represents != 'unknown')
        identifiers_found = sum(1 for r in all_results if r.entity_identifier is not None)
        high_conf = sum(1 for r in all_results if r.confidence >= EntityIdentificationConfig.CONFIDENCE_THRESHOLD)
        low_conf = sum(1 for r in all_results if r.confidence < EntityIdentificationConfig.CONFIDENCE_THRESHOLD)
        
        self.log("=" * 50)
        self.log("📊 Summary:")
        self.log(f"📦 Groups processed: {groups_processed}", indent=1)
        self.log(f"📁 Group files propagated: {group_files_propagated}", indent=1)
        self.log(f"📄 Ungrouped files processed: {ungrouped_files_processed}", indent=1)
        self.log(f"🤖 LLM calls: {total_llm_calls}", indent=1)
        self.log(f"🎯 High confidence: {high_conf}", indent=1)
        
        # 결과 출력 (비그룹 파일만)
        if all_results:
            self.log("📋 Ungrouped Entity Results:")
            for result in all_results[:10]:  # 최대 10개만
                identifier_str = result.entity_identifier or "(none)"
                conf_emoji = "🟢" if result.confidence >= EntityIdentificationConfig.CONFIDENCE_THRESHOLD else "🟡"
                self.log(f"{conf_emoji} {result.file_name}: {result.row_represents} [{identifier_str}]", indent=1)
            if len(all_results) > 10:
                self.log(f"... and {len(all_results) - 10} more", indent=1)
        
        phase_result = EntityIdentificationResult(
            total_tables=groups_processed + ungrouped_files_processed,
            tables_analyzed=groups_processed + len(all_results),
            entities_identified=groups_processed + entities_identified,
            identifiers_found=groups_processed + identifiers_found,
            high_confidence=groups_processed + high_conf,
            low_confidence=low_conf,
            llm_calls=total_llm_calls,
            started_at=started_at,
            completed_at=completed_at
        )
        
        return {
            "entity_identification_result": phase_result.model_dump(),
            "table_entity_results": [r.model_dump() for r in all_results],
            "groups_processed": groups_processed,
            "group_files_propagated": group_files_propagated,
            "logs": [
                f"🎯 [Entity Identification] Groups: {groups_processed} ({group_files_propagated} files), "
                f"Ungrouped: {ungrouped_files_processed}, LLM calls: {total_llm_calls}"
            ]
        }
    
    # =========================================================================
    # Skip Already Analyzed
    # =========================================================================
    
    def _filter_unanalyzed_groups_entity(
        self, 
        groups: List[Dict[str, Any]]
    ) -> tuple:
        """
        이미 Entity 분석이 완료된 그룹 필터링
        
        Args:
            groups: 그룹 목록
        
        Returns:
            (분석할 그룹 목록, 스킵된 그룹 수)
        """
        if not groups:
            return [], 0
        
        group_repo = self._get_group_repo()
        
        # llm_analyzed_at이 NULL인 그룹만 (get_groups_for_entity_analysis가 이미 필터링하지만 확인용)
        to_process = []
        for group in groups:
            group_id = group.get('group_id')
            full_group = group_repo.get_group_by_id(group_id)
            if full_group and full_group.get('llm_analyzed_at') is None:
                to_process.append(group)
        
        skipped_count = len(groups) - len(to_process)
        return to_process, skipped_count
    
    def _filter_unanalyzed_files_entity(
        self, 
        file_paths: List[str]
    ) -> List[str]:
        """
        이미 Entity 분석이 완료된 파일 필터링
        
        table_entities에 해당 파일이 없는 것만 반환
        
        Args:
            file_paths: 파일 경로 목록
        
        Returns:
            분석할 파일 경로 목록
        """
        if not file_paths:
            return []
        
        # table_entities에 없는 파일만 필터링
        to_process = []
        for file_path in file_paths:
            if not self.entity_repo.has_entity_for_file_path(file_path):
                to_process.append(file_path)
        
        return to_process
    
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

