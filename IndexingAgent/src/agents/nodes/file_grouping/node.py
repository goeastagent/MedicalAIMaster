# src/agents/nodes/file_grouping/node.py
"""
File Grouping Node

[250] file_grouping_prep에서 수집한 정보를 바탕으로
LLM이 파일 그룹핑 전략을 결정하고 검증합니다.

주요 기능:
- LLM을 사용해 그룹핑 전략 결정 (pattern_based, partitioned, paired, single)
- file_group 테이블에 그룹 생성 (status='confirmed')
- file_catalog.group_id 업데이트
"""

import time
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

from shared.database.repositories import FileRepository, DirectoryRepository, FileGroupRepository
from shared.config import LLMConfig

from shared.langgraph import BaseNode, LLMMixin, DatabaseMixin
from shared.langgraph import register_node
from .prompts import FileGroupingPrompt


@register_node
class FileGroupingNode(BaseNode, LLMMixin, DatabaseMixin):
    """
    File Grouping Node (LLM-based)
    
    [250] file_grouping_prep에서 수집한 정보를 바탕으로
    LLM이 파일 그룹핑 전략을 결정하고 검증합니다.
    
    Input (from state):
        - directories_for_grouping: [250]에서 수집한 디렉토리 정보
        - grouping_prep_result: [250]의 결과 요약
    
    Output:
        - file_grouping_result: 그룹핑 결과 요약
        - file_groups: 생성된 그룹 정보 리스트
    """
    
    name = "file_grouping"
    description = "파일 그룹핑 전략 결정 및 그룹 생성 (LLM-based)"
    order = 350
    requires_llm = True
    
    # 프롬프트 클래스 연결
    prompt_class = FileGroupingPrompt
    
    # =========================================================================
    # Configuration
    # =========================================================================
    
    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = 2
    CONFIDENCE_THRESHOLD = 0.7
    BATCH_SIZE = 10  # 한 번에 분석할 최대 디렉토리 수
    
    # =========================================================================
    # Repository Access (Lazy Initialization)
    # =========================================================================
    
    @property
    def file_repo(self) -> FileRepository:
        """FileRepository 인스턴스 (lazy)"""
        if not hasattr(self, '_file_repo') or self._file_repo is None:
            self._file_repo = FileRepository()
        return self._file_repo
    
    @property
    def dir_repo(self) -> DirectoryRepository:
        """DirectoryRepository 인스턴스 (lazy)"""
        if not hasattr(self, '_dir_repo') or self._dir_repo is None:
            self._dir_repo = DirectoryRepository()
        return self._dir_repo
    
    @property
    def group_repo(self) -> FileGroupRepository:
        """FileGroupRepository 인스턴스 (lazy)"""
        if not hasattr(self, '_group_repo') or self._group_repo is None:
            self._group_repo = FileGroupRepository()
        return self._group_repo
    
    # =========================================================================
    # Main Execution
    # =========================================================================
    
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        파일 그룹핑 실행
        
        1. [250]에서 수집한 디렉토리 정보 로드
        2. LLM에게 그룹핑 전략 결정 요청
        3. 그룹 생성 및 파일 할당
        """
        started_at = datetime.now().isoformat()
        
        self.log("=" * 60)
        self.log("📦 파일 그룹핑 (LLM-based)")
        self.log("=" * 60)
        
        # 1. [250]에서 수집한 디렉토리 정보 가져오기
        directories = state.get('directories_for_grouping', [])
        
        if not directories:
            self.log("ℹ️ No directories to analyze for grouping")
            return {
                "file_grouping_result": {
                    "groups_created": 0,
                    "files_grouped": 0,
                    "files_ungrouped": 0,
                    "started_at": started_at,
                    "completed_at": datetime.now().isoformat()
                },
                "file_groups": []
            }
        
        self.log(f"📁 Directories to analyze: {len(directories)}")
        
        # 2. LLM 호출 (배치 처리)
        all_results = []
        total_llm_calls = 0
        
        for i in range(0, len(directories), self.BATCH_SIZE):
            batch = directories[i:i + self.BATCH_SIZE]
            batch_num = i // self.BATCH_SIZE + 1
            total_batches = (len(directories) + self.BATCH_SIZE - 1) // self.BATCH_SIZE
            
            self.log(f"📤 Batch {batch_num}/{total_batches} ({len(batch)} directories)", indent=1)
            
            results, llm_calls = self._call_llm_for_grouping(batch)
            all_results.extend(results)
            total_llm_calls += llm_calls
            
            self.log(f"✅ Got {len(results)} results", indent=2)
        
        # 3. 결과 처리 및 그룹 생성
        # dir_name → dir_id 매핑 생성 (LLM이 dir_name만 반환할 경우 대비)
        dir_id_map = {
            d.get('dir_name'): d.get('dir_id')
            for d in directories
            if d.get('dir_name') and d.get('dir_id')
        }
        
        groups_created = []
        total_files_grouped = 0
        
        for result in all_results:
            if result.get('should_group') and result.get('confidence', 0) >= self.CONFIDENCE_THRESHOLD:
                group_info = self._create_group_from_result(result, dir_id_map)
                if group_info:
                    groups_created.append(group_info)
                    total_files_grouped += group_info.get('file_count', 0)
                    
                    self.log(f"✅ Created group: {group_info['group_name']}", indent=1)
                    self.log(f"   Strategy: {group_info['grouping_strategy']}", indent=1)
                    self.log(f"   Files: {group_info['file_count']}", indent=1)
            else:
                dir_path = result.get('dir_path') or result.get('dir_name') or '?'
                reason = "low confidence" if result.get('should_group') else "not groupable"
                self.log(f"ℹ️ Skipped: {dir_path} ({reason})", indent=1)
        
        # 4. 통계 계산
        total_files = sum(d.get('file_count', 0) for d in directories)
        files_ungrouped = total_files - total_files_grouped
        
        # 5. 결과 출력
        self.log("=" * 60)
        self.log("✅ Grouping Complete!")
        self.log(f"   Groups created: {len(groups_created)}", indent=1)
        self.log(f"   Files grouped: {total_files_grouped}", indent=1)
        self.log(f"   Files ungrouped: {files_ungrouped}", indent=1)
        self.log(f"   LLM calls: {total_llm_calls}", indent=1)
        self.log("=" * 60)
        
        completed_at = datetime.now().isoformat()
        
        return {
            "file_grouping_result": {
                "groups_created": len(groups_created),
                "files_grouped": total_files_grouped,
                "files_ungrouped": files_ungrouped,
                "llm_calls": total_llm_calls,
                "started_at": started_at,
                "completed_at": completed_at
            },
            "file_groups": groups_created
        }
    
    # =========================================================================
    # LLM Integration
    # =========================================================================
    
    def _build_directories_context(self, directories: List[Dict]) -> str:
        """LLM 프롬프트용 디렉토리 컨텍스트 생성"""
        lines = []
        
        for dir_info in directories:
            dir_path = dir_info.get('dir_path', '?')
            dir_name = dir_info.get('dir_name', '?')
            file_count = dir_info.get('file_count', 0)
            ext_dist = dir_info.get('extension_distribution', {})
            samples = dir_info.get('filename_samples', [])
            patterns = dir_info.get('observed_patterns', [])
            size_stats = dir_info.get('size_stats', {})
            
            lines.append(f"\n## Directory: {dir_name}/")
            lines.append(f"Path: {dir_path}")
            lines.append(f"File count: {file_count}")
            
            # 확장자 분포
            if ext_dist:
                ext_str = ', '.join(f'"{k}": {v}' for k, v in ext_dist.items())
                lines.append(f"Extensions: {{{ext_str}}}")
            
            # 파일명 샘플
            if samples:
                sample_str = ', '.join(f'"{s}"' for s in samples[:10])
                lines.append(f"Filename samples: [{sample_str}]")
            
            # 크기 통계
            if size_stats:
                lines.append(f"Size range: {size_stats.get('min_mb', 0):.2f} MB - {size_stats.get('max_mb', 0):.2f} MB")
            
            # 관찰된 패턴 (Rule-based에서)
            if patterns:
                lines.append("Observed patterns (from Rule-based analysis):")
                for p in patterns:
                    p_type = p.get('type', '?')
                    p_desc = p.get('description', '')
                    p_ratio = p.get('ratio', 0)
                    lines.append(f"  - {p_type}: {p_desc} (ratio: {p_ratio})")
                    
                    # 패턴별 추가 정보
                    if p_type == 'numeric_only' and p.get('value_range'):
                        vr = p['value_range']
                        lines.append(f"    Range: {vr.get('min')} - {vr.get('max')}")
                    elif p_type == 'partitioned' and p.get('base_tables'):
                        for bt in p['base_tables']:
                            lines.append(f"    Base: {bt.get('base_name')}, partitions: {bt.get('partition_count')}")
                    elif p_type == 'paired_extensions':
                        lines.append(f"    Pair: {p.get('most_common_pair')}, count: {p.get('pair_frequency')}")
            else:
                lines.append("Observed patterns: none")
        
        return "\n".join(lines)
    
    def _call_llm_for_grouping(
        self,
        directories: List[Dict]
    ) -> Tuple[List[Dict], int]:
        """
        LLM을 호출하여 그룹핑 전략 결정
        
        Returns:
            (결과 목록, LLM 호출 횟수)
        """
        if not directories:
            return [], 0
        
        directories_context = self._build_directories_context(directories)
        
        # PromptTemplate을 사용하여 프롬프트 빌드
        prompt = self.prompt_class.build(directories_context=directories_context)
        
        llm_calls = 0
        results = []
        
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.call_llm_json(
                    prompt,
                    max_tokens=LLMConfig.MAX_TOKENS
                )
                llm_calls += 1
                
                if response and 'directories' in response:
                    results = response['directories']
                    return results, llm_calls
                else:
                    self.log(f"⚠️ Invalid LLM response format, attempt {attempt + 1}", indent=1)
                    
            except Exception as e:
                self.log(f"❌ LLM call failed (attempt {attempt + 1}): {e}", indent=1)
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAY_SECONDS)
        
        return results, llm_calls
    
    # =========================================================================
    # Group Creation
    # =========================================================================
    
    def _create_group_from_result(self, result: Dict, dir_id_map: Dict[str, str] = None) -> Optional[Dict]:
        """
        LLM 결과를 바탕으로 그룹 생성
        
        1. file_group 테이블에 그룹 레코드 생성
        2. file_catalog.group_id 업데이트
        
        Args:
            result: LLM 응답 결과
            dir_id_map: dir_name → dir_id 매핑 (LLM이 dir_name만 반환할 경우 사용)
        """
        dir_path = result.get('dir_path')
        dir_name = result.get('dir_name')
        group_name = result.get('group_name')
        strategy = result.get('grouping_strategy')
        pattern = result.get('filename_pattern')
        entity_source = result.get('entity_identifier_source')
        entity_key = result.get('entity_identifier_key')
        confidence = result.get('confidence', 0)
        reasoning = result.get('reasoning', '')
        
        if not group_name:
            return None
        
        # dir_path에서 dir_name 추출 (LLM이 dir_name을 반환하지 않는 경우)
        if not dir_name and dir_path:
            dir_name = dir_path.rstrip('/').split('/')[-1]
        
        # 디렉토리 정보 조회 (여러 방법 시도)
        dir_info = None
        dir_id = None
        
        # 1. dir_id_map에서 직접 조회 (가장 빠름)
        if dir_id_map and dir_name and dir_name in dir_id_map:
            dir_id = dir_id_map[dir_name]
            dir_info = self.dir_repo.get_directory_by_id(dir_id)
        
        # 2. dir_path로 조회
        if not dir_info and dir_path:
            dir_info = self.dir_repo.get_directory_by_path(dir_path)
        
        # 3. dir_name으로 조회
        if not dir_info and dir_name:
            dir_info = self.dir_repo.get_directory_by_name(dir_name)
        
        if not dir_info:
            self.log(f"⚠️ Directory not found: {dir_path or dir_name}", indent=2)
            return None
        
        dir_id = dir_info['dir_id']
        
        # grouping_criteria 구성
        grouping_criteria = {
            "strategy": strategy,
            "dir_path": dir_path,
            "pattern": pattern
        }
        
        # 확장자 정보 추가
        ext_dist = dir_info.get('file_extensions', {})
        if ext_dist:
            grouping_criteria["extensions"] = list(ext_dist.keys())
        
        try:
            # 1. 그룹 생성
            group_id = self.group_repo.create_group(
                group_name=group_name,
                grouping_criteria=grouping_criteria
            )
            
            if not group_id:
                self.log(f"⚠️ Failed to create group: {group_name}", indent=2)
                return None
            
            # 2. 디렉토리의 모든 파일을 그룹에 할당
            files = self.file_repo.get_files_by_dir_id(dir_id)
            file_ids = [f['file_id'] for f in files]
            
            if file_ids:
                updated_count = self.group_repo.add_files_to_group(group_id, file_ids)
            else:
                updated_count = 0
            
            # 3. 그룹 분석 정보 업데이트 (LLM 결과)
            self.group_repo.update_group_analysis(
                group_id=group_id,
                row_represents=None,  # entity_identification에서 나중에 채움
                entity_identifier_source=entity_source,
                entity_identifier_key=entity_key,
                confidence=confidence,
                reasoning=reasoning
            )
            
            # 4. 그룹 상태를 confirmed로 변경
            self.group_repo.confirm_group(
                group_id=group_id,
                reasoning=f"LLM confirmed with {confidence:.2f} confidence: {reasoning}"
            )
            
            return {
                "group_id": group_id,
                "group_name": group_name,
                "grouping_strategy": strategy,
                "filename_pattern": pattern,
                "entity_identifier_source": entity_source,
                "entity_identifier_key": entity_key,
                "file_count": updated_count,
                "confidence": confidence,
                "reasoning": reasoning
            }
            
        except Exception as e:
            self.log(f"❌ Error creating group: {e}", indent=2)
            import traceback
            traceback.print_exc()
            return None
    
    # =========================================================================
    # Standalone Execution
    # =========================================================================
    
    @classmethod
    def run_standalone(cls, directories_for_grouping: List[Dict]) -> Dict[str, Any]:
        """
        단독 실행용 메서드
        
        Args:
            directories_for_grouping: [250] 노드의 출력
        
        Returns:
            실행 결과 state
        """
        node = cls()
        initial_state = {
            'directories_for_grouping': directories_for_grouping
        }
        return node(initial_state)

