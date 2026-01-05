# src/agents/nodes/directory_pattern/node.py
"""
Directory Pattern Analysis Node

디렉토리 내 파일명 패턴을 LLM으로 분석하고, 파일명에서 ID/값을 추출하여 
다른 테이블과의 관계를 연결합니다.

✅ LLM 사용:
  1. 파일명 패턴 식별
  2. 패턴에서 추출 가능한 값이 Data Dictionary의 어떤 컬럼과 매칭되는지 판단

입력 (DB에서 읽기):
  - directory_catalog.filename_samples (이전 단계에서 수집)
  - column_metadata (이전 단계에서 분석됨)
  - file_group (그룹화된 파일 정보)

출력 (DB에 저장):
  - directory_catalog.filename_pattern, filename_columns
  - file_catalog.filename_values (배치 업데이트)
  - file_group.grouping_criteria.pattern_regex (패턴 정보)

수정된 로직 (v2):
  Phase 1: 그룹화된 파일 처리 (샘플 LLM 분석 + 패턴 전파)
  Phase 2: 비그룹 디렉토리 처리 (기존 디렉토리 단위 LLM 분석)
"""

import re
import json
from typing import Dict, Any, List, Optional
from datetime import datetime

from ...base import BaseNode, LLMMixin, DatabaseMixin
from ...registry import register_node
from src.config import DirectoryPatternConfig
from shared.database.repositories import FileGroupRepository
from .prompts import DirectoryPatternPrompt, GroupPatternPrompt


@register_node
class DirectoryPatternNode(BaseNode, LLMMixin, DatabaseMixin):
    """
    Directory Pattern Analysis Node (LLM-based)
    
    디렉토리 내 파일명 패턴을 LLM으로 분석하고,
    파일명에서 ID/값을 추출하여 다른 테이블과의 관계를 연결합니다.
    
    수정된 로직 (v2):
        Phase 1: 그룹화된 파일 처리 (샘플 LLM 분석 + 패턴 전파)
        Phase 2: 비그룹 디렉토리 처리 (기존 디렉토리 단위 LLM 분석)
    
    Input (DB에서 읽기):
        - directory_catalog.filename_samples (이전 단계에서 수집)
        - column_metadata (이전 단계에서 분석됨)
        - file_group (그룹화된 파일 정보)
    
    Output (DB에 저장):
        - directory_catalog.filename_pattern, filename_columns
        - file_catalog.filename_values (배치 업데이트)
        - file_group.grouping_criteria.pattern_regex (패턴 정보)
    """
    
    name = "directory_pattern"
    description = "디렉토리 파일명 패턴 분석"
    order = 700
    requires_llm = True
    
    # 프롬프트 클래스 연결
    prompt_class = DirectoryPatternPrompt
    group_prompt_class = GroupPatternPrompt
    
    def __init__(self):
        super().__init__()
        self._group_repo: Optional[FileGroupRepository] = None
    
    def _get_group_repo(self) -> FileGroupRepository:
        """FileGroupRepository 싱글톤 반환"""
        if self._group_repo is None:
            self._group_repo = FileGroupRepository()
        return self._group_repo
    
    # ═══════════════════════════════════════════════════════════════════════════
    # Phase 1: 그룹 패턴 분석
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _process_group_pattern(
        self, 
        group: Dict, 
        data_dictionary: Dict
    ) -> Dict[str, Any]:
        """
        그룹의 파일명 패턴을 LLM으로 분석하고 전체 파일에 적용
        
        Args:
            group: 그룹 정보 (group_id, group_name, all_filenames 등)
            data_dictionary: Data Dictionary 정보
        
        Returns:
            {
                'success': bool,
                'pattern_regex': str or None,
                'files_updated': int,
                'needs_review': bool,
                'review_type': str or None
            }
        """
        group_id = group['group_id']
        group_name = group['group_name']
        all_filenames = group.get('all_filenames', [])
        file_count = group.get('file_count', 0)
        criteria = group.get('grouping_criteria', {})
        extensions = criteria.get('extensions', [])
        
        self.log(f"📦 Analyzing group: {group_name} ({file_count} files)", indent=1)
        
        # 샘플 파일명 선택 (최대 10개)
        sample_filenames = self._select_sample_filenames(all_filenames, sample_size=10)
        
        if len(sample_filenames) < 3:
            self.log(f"⚠️ Not enough samples for group {group_name}", indent=2)
            return {'success': False, 'needs_review': False}
        
        # LLM 분석
        llm_result = self._call_llm_for_group_pattern(
            group_name=group_name,
            file_count=file_count,
            extensions=extensions,
            sample_filenames=sample_filenames,
            data_dictionary=data_dictionary
        )
        
        if not llm_result or not llm_result.get('has_pattern'):
            self.log(f"❌ No pattern found for group {group_name}", indent=2)
            return {'success': False, 'needs_review': False}
        
        pattern_regex = llm_result.get('pattern_regex')
        columns = llm_result.get('columns', [])
        sample_extractions = llm_result.get('sample_extractions', [])
        confidence = llm_result.get('confidence', 0.0)
        
        # 패턴 검증
        validation_result = self._validate_pattern(
            pattern_regex=pattern_regex,
            columns=columns,
            sample_filenames=sample_filenames,
            llm_extractions=sample_extractions
        )
        
        if not validation_result['valid']:
            # 검증 실패 → human review 필요
            self.log(f"⚠️ Pattern validation failed: {validation_result['reason']}", indent=2)
            
            group_repo = self._get_group_repo()
            group_repo.mark_needs_human_review(
                group_id=group_id,
                review_type='pattern_validation_failed',
                review_context={
                    'pattern_regex': pattern_regex,
                    'columns': columns,
                    'failed_samples': validation_result.get('failed_samples', []),
                    'llm_extractions': sample_extractions,
                    'validation_reason': validation_result['reason']
                },
                reasoning=f"Pattern validation failed: {validation_result['reason']}"
            )
            
            return {
                'success': False,
                'needs_review': True,
                'review_type': 'pattern_validation_failed'
            }
        
        # 낮은 신뢰도 체크
        if confidence < 0.7:
            self.log(f"⚠️ Low confidence ({confidence:.2f}) for group {group_name}", indent=2)
            
            group_repo = self._get_group_repo()
            group_repo.mark_needs_human_review(
                group_id=group_id,
                review_type='low_confidence',
                review_context={
                    'pattern_regex': pattern_regex,
                    'columns': columns,
                    'sample_extractions': sample_extractions,
                    'confidence': confidence,
                    'reasoning': llm_result.get('reasoning')
                },
                reasoning=f"Low pattern confidence: {confidence:.2f}"
            )
            
            return {
                'success': False,
                'needs_review': True,
                'review_type': 'low_confidence'
            }
        
        # 검증 성공 → 패턴 저장 및 전체 파일에 적용
        group_repo = self._get_group_repo()
        group_repo.update_group_pattern(
            group_id=group_id,
            pattern_regex=pattern_regex,
            pattern_columns=columns,
            confidence=confidence
        )
        
        # 전체 파일에 filename_values 적용
        files_updated = self._apply_pattern_to_group_files(
            group_id=group_id,
            pattern_regex=pattern_regex,
            columns=columns
        )
        
        self.log(f"✅ Pattern applied: {pattern_regex} → {files_updated} files", indent=2)
        
        return {
            'success': True,
            'pattern_regex': pattern_regex,
            'files_updated': files_updated,
            'needs_review': False
        }
    
    def _select_sample_filenames(
        self, 
        filenames: List[str], 
        sample_size: int = 10
    ) -> List[str]:
        """
        대표 샘플 파일명 선택
        
        전략: first 2 + last 2 + random middle
        """
        if len(filenames) <= sample_size:
            return filenames
        
        # 정렬된 상태에서 선택
        sorted_names = sorted(filenames)
        
        result = []
        # First 2
        result.extend(sorted_names[:2])
        # Last 2
        result.extend(sorted_names[-2:])
        
        # Middle samples (나머지)
        remaining = sample_size - len(result)
        if remaining > 0:
            middle = sorted_names[2:-2]
            step = max(1, len(middle) // remaining)
            for i in range(0, len(middle), step):
                if len(result) < sample_size:
                    result.append(middle[i])
        
        return result
    
    def _call_llm_for_group_pattern(
        self,
        group_name: str,
        file_count: int,
        extensions: List[str],
        sample_filenames: List[str],
        data_dictionary: Dict
    ) -> Optional[Dict]:
        """
        그룹 샘플 파일명에 대해 LLM 패턴 분석 호출
        """
        sample_str = "\n".join([f"- {fn}" for fn in sample_filenames])
        
        prompt = self.group_prompt_class.build(
            group_name=group_name,
            file_count=file_count,
            extensions=json.dumps(extensions),
            sample_filenames=sample_str,
            data_dictionary=json.dumps(data_dictionary, indent=2, ensure_ascii=False)
        )
        
        try:
            result = self.call_llm_json(prompt)
            if result.get("error"):
                self.log(f"❌ LLM error: {result.get('error')}", indent=2)
                return None
            return result
        except Exception as e:
            self.log(f"❌ LLM call failed: {e}", indent=2)
            return None
    
    def _validate_pattern(
        self,
        pattern_regex: str,
        columns: List[Dict],
        sample_filenames: List[str],
        llm_extractions: List[Dict]
    ) -> Dict[str, Any]:
        """
        LLM이 제시한 패턴이 실제로 동작하는지 검증
        
        검증 기준:
        1. regex가 유효한가?
        2. 모든 샘플 파일명에 매칭되는가?
        3. 추출된 값이 LLM이 제시한 값과 일치하는가?
        
        Returns:
            {'valid': bool, 'reason': str, 'failed_samples': list}
        """
        # 1. Regex 유효성 검사
        try:
            compiled = re.compile(pattern_regex)
        except re.error as e:
            return {
                'valid': False,
                'reason': f"Invalid regex: {e}",
                'failed_samples': []
            }
        
        failed_samples = []
        
        # 2. 모든 샘플에 매칭 테스트
        for filename in sample_filenames:
            match = compiled.match(filename)
            if not match:
                failed_samples.append({
                    'filename': filename,
                    'error': 'No match'
                })
                continue
            
            # 3. LLM 추출 결과와 비교 (있는 경우)
            llm_result = next(
                (e for e in llm_extractions if e.get('filename') == filename),
                None
            )
            
            if llm_result:
                for col in columns:
                    col_name = col.get('name')
                    position = col.get('position', 1)
                    
                    try:
                        extracted = match.group(position)
                    except IndexError:
                        failed_samples.append({
                            'filename': filename,
                            'error': f"Capture group {position} not found"
                        })
                        continue
                    
                    expected = llm_result.get('values', {}).get(col_name)
                    if expected and extracted != expected:
                        failed_samples.append({
                            'filename': filename,
                            'error': f"{col_name}: expected '{expected}', got '{extracted}'"
                        })
        
        # 80% 이상 성공이면 검증 통과
        success_rate = 1 - (len(failed_samples) / len(sample_filenames)) if sample_filenames else 0
        
        if success_rate >= 0.8:
            return {'valid': True, 'reason': 'OK', 'failed_samples': []}
        else:
            return {
                'valid': False,
                'reason': f"Pattern matched only {success_rate*100:.0f}% of samples",
                'failed_samples': failed_samples
            }
    
    def _apply_pattern_to_group_files(
        self,
        group_id: str,
        pattern_regex: str,
        columns: List[Dict]
    ) -> int:
        """
        검증된 패턴을 그룹 내 모든 파일에 적용하여 filename_values 업데이트
        
        Returns:
            업데이트된 파일 수
        """
        # file_repo를 통해 배치 업데이트
        return self.file_repo.update_filename_values_by_group_pattern(
            group_id=group_id,
            pattern_regex=pattern_regex,
            columns=columns
        )
    
    def _get_full_data_dictionary(self) -> Dict:
        """
        Data Dictionary 전체 수집 (두 소스 병합)
        """
        # semantic 정보 (parameter 테이블 기반)
        semantic_dict = self._collect_data_dictionary()
        
        # data_dictionary 테이블 기반 정보
        simple_dict = self._collect_data_dictionary_simple()
        
        return {
            "tables": semantic_dict,
            **simple_dict
        }
    
    # ═══════════════════════════════════════════════════════════════════════════
    # Phase 2: 기존 디렉토리 분석 (ungrouped)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _get_directories_for_analysis(self) -> List[Dict]:
        """
        Query directories from directory_catalog (DB)
        
        Uses: DirectoryRepository.get_directories_for_analysis()
        
        Data source: directory_catalog table (populated by previous step)
        - filename_samples: collected during directory scan
        - file_extensions: counted during scan
        - dir_type: classified during scan
        """
        try:
            directories = self.directory_repo.get_directories_for_analysis(
                min_files=DirectoryPatternConfig.MIN_FILES_FOR_PATTERN
            )
            
            # LLM에 전달할 샘플 수 제한
            for d in directories:
                samples = d.get('filename_samples', [])
                d['filename_samples'] = samples[:DirectoryPatternConfig.MAX_SAMPLES_PER_DIR]
            
            return directories
        except Exception as e:
            self.log(f"❌ Error getting directories: {e}")
            return []
    
    def _collect_data_dictionary(self) -> Dict[str, Any]:
        """
        Collect data dictionary from DB (previous steps results)
        
        Uses: DirectoryRepository.get_data_dictionary_for_pattern()
        - column_metadata + parameter: semantic_name, description, concept_category
        
        NO file reading - all from DB
        """
        return self.directory_repo.get_data_dictionary_for_pattern()
    
    def _collect_data_dictionary_simple(self) -> Dict[str, Any]:
        """
        Data Dictionary 간단 버전 - 이전 단계 결과가 없어도 동작
        
        Uses: DirectoryRepository.get_data_dictionary_simple()
        """
        return self.directory_repo.get_data_dictionary_simple()
    
    def _batch_directories(self, directories: List[Dict], batch_size: int) -> List[List[Dict]]:
        """디렉토리 목록을 배치로 분할"""
        batches = []
        for i in range(0, len(directories), batch_size):
            batches.append(directories[i:i + batch_size])
        return batches
    
    def _analyze_batch(
        self,
        directories: List[Dict], 
        data_dictionary: Dict
    ) -> List[Dict]:
        """
        Analyze directory batch with LLM
        
        Input: All from DB (directories from directory_catalog, data_dictionary from column_metadata)
        Output: Pattern analysis results
        """
        # Build directories info for prompt
        # Note: dir_id는 LLM에 보내지 않음 (외부에서 관리)
        dirs_info_parts = []
        for i, d in enumerate(directories):
            samples_str = "\n".join([f"  - {s}" for s in d['filename_samples']])
            dirs_info_parts.append(
                f"### Directory {i+1}: {d['dir_name']}\n"
                f"- File count: {d['file_count']}\n"
                f"- Extensions: {json.dumps(d['file_extensions'])}\n"
                f"- Type: {d['dir_type']}\n"
                f"- Filename samples:\n{samples_str}"
            )
        
        dirs_info = "\n\n".join(dirs_info_parts)
        
        # PromptTemplate 사용하여 프롬프트 빌드
        prompt = self.prompt_class.build(
            data_dictionary=json.dumps(data_dictionary, indent=2, ensure_ascii=False),
            directories_info=dirs_info
        )
        
        # dir_name → dir_id 매핑 생성 (LLM 외부에서 관리)
        name_to_id = {d['dir_name']: d['dir_id'] for d in directories}
        
        try:
            result = self.call_llm_json(prompt)
            
            if result.get("error"):
                self.log(f"❌ LLM returned error: {result.get('error')}", indent=1)
                return []
            
            # LLM 결과에 dir_id 추가 (dir_name으로 매핑)
            llm_results = result.get("directories", [])
            for r in llm_results:
                dir_name = r.get("dir_name")
                if dir_name and dir_name in name_to_id:
                    r["dir_id"] = name_to_id[dir_name]
                else:
                    self.log(f"⚠️ Unknown dir_name from LLM: {dir_name}", indent=1)
            
            return llm_results
            
        except Exception as e:
            self.log(f"❌ LLM call error: {e}", indent=1)
            return []
    
    def _save_pattern_results(self, results: List[Dict]):
        """
        Save pattern analysis results to directory_catalog
        
        Uses: DirectoryRepository.save_pattern_results()
        """
        saved_count = self.directory_repo.save_pattern_results(results)
        self.log(f"💾 Saved {saved_count} pattern results to directory_catalog", indent=1)
    
    def _update_filename_values(self, results: List[Dict]):
        """
        Batch update file_catalog.filename_values
        
        Uses: FileRepository.update_filename_values_by_pattern()
        """
        updated_total = 0
        
        for r in results:
            if not r.get("has_pattern") or not r.get("columns"):
                continue
            
            dir_id = r["dir_id"]
            pattern_regex = r.get("pattern_regex")
            
            if not pattern_regex:
                continue
            
            updated = self.file_repo.update_filename_values_by_pattern(
                dir_id=dir_id,
                pattern_regex=pattern_regex,
                columns=r["columns"]
            )
            updated_total += updated
        
        self.log(f"💾 Updated filename_values for {updated_total} files", indent=1)
    
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Directory Pattern Analysis 실행 (v2)
        
        수정된 로직:
        Phase 1: 그룹화된 파일 처리 (샘플 LLM 분석 + 패턴 전파)
        Phase 2: 비그룹 디렉토리 처리 (기존 디렉토리 단위 LLM 분석)
        
        Steps:
        1. Phase 1: confirmed 그룹들의 패턴 분석
           - 샘플 파일명으로 LLM 분석
           - 패턴 검증 후 전체 그룹에 적용
        2. Phase 2: 비그룹 디렉토리 분석
           - 기존 디렉토리 단위 LLM 분석
        3. 결과 저장 및 filename_values 업데이트
        """
        started_at = datetime.now()
        
        # 통계 초기화
        groups_processed = 0
        groups_patterns_found = 0
        groups_need_review = 0
        dirs_processed = 0
        dirs_patterns_found = 0
        llm_calls = 0
        files_updated = 0
        
        # Data Dictionary 수집 (Phase 1, 2 모두 사용)
        self.log("📖 Collecting data dictionary from DB...")
        data_dictionary = self._get_full_data_dictionary()
        
        # ═══════════════════════════════════════════════════════════════════════════
        # Phase 1: 그룹화된 파일 처리
        # ═══════════════════════════════════════════════════════════════════════════
        self.log("=" * 50)
        self.log("📦 Phase 1: Processing file groups...")
        
        group_repo = self._get_group_repo()
        groups = group_repo.get_confirmed_groups_for_pattern_analysis()
        
        if groups:
            self.log(f"📦 Found {len(groups)} groups to analyze", indent=1)
            
            for group in groups:
                group_result = self._process_group_pattern(group, data_dictionary)
                groups_processed += 1
                llm_calls += 1
                
                if group_result['success']:
                    groups_patterns_found += 1
                    files_updated += group_result.get('files_updated', 0)
                    self.log(f"✅ {group['group_name']}: pattern found, {group_result['files_updated']} files updated", indent=2)
                elif group_result.get('needs_review'):
                    groups_need_review += 1
                    self.log(f"⚠️ {group['group_name']}: needs human review ({group_result.get('review_type')})", indent=2)
                else:
                    self.log(f"❌ {group['group_name']}: no pattern found", indent=2)
        else:
            self.log("⚠️ No groups to analyze", indent=1)
        
        # ═══════════════════════════════════════════════════════════════════════════
        # Phase 2: 비그룹 디렉토리 처리 (기존 로직)
        # ═══════════════════════════════════════════════════════════════════════════
        self.log("=" * 50)
        self.log("📂 Phase 2: Processing ungrouped directories...")
        
        directories = self._get_directories_for_analysis()
        
        if directories:
            self.log(f"📂 Found {len(directories)} directories to analyze:", indent=1)
            for d in directories:
                self.log(f"- {d['dir_name']} ({d['file_count']} files)", indent=2)
            
            # 배치 처리
            all_results = []
            batches = self._batch_directories(directories, DirectoryPatternConfig.MAX_DIRS_PER_BATCH)
            
            for i, batch in enumerate(batches):
                self.log(f"Batch {i+1}/{len(batches)}: {len(batch)} directories", indent=2)
                batch_result = self._analyze_batch(batch, data_dictionary)
                all_results.extend(batch_result)
                llm_calls += 1
            
            # 결과 저장
            self._save_pattern_results(all_results)
            self._update_filename_values(all_results)
            
            dirs_processed = len(all_results)
            dirs_patterns_found = sum(1 for r in all_results if r.get("has_pattern"))
        else:
            self.log("⚠️ No ungrouped directories to analyze", indent=1)
            all_results = []
        
        # ═══════════════════════════════════════════════════════════════════════════
        # 결과 요약
        # ═══════════════════════════════════════════════════════════════════════════
        completed_at = datetime.now()
        duration = (completed_at - started_at).total_seconds()
        
        result = {
            "status": "completed",
            # Phase 1 결과
            "groups_processed": groups_processed,
            "groups_patterns_found": groups_patterns_found,
            "groups_need_review": groups_need_review,
            # Phase 2 결과
            "dirs_processed": dirs_processed,
            "dirs_patterns_found": dirs_patterns_found,
            # 전체 통계
            "total_patterns_found": groups_patterns_found + dirs_patterns_found,
            "llm_calls": llm_calls,
            "files_updated": files_updated,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_seconds": duration
        }
        
        dir_patterns = {r.get("dir_id", "unknown"): r for r in all_results}
        
        self.log("=" * 50)
        self.log("📊 Summary:")
        self.log(f"📦 Groups: {groups_processed} processed, {groups_patterns_found} patterns, {groups_need_review} need review", indent=1)
        self.log(f"📂 Directories: {dirs_processed} processed, {dirs_patterns_found} patterns", indent=1)
        self.log(f"📝 Files updated: {files_updated}", indent=1)
        self.log(f"🤖 LLM calls: {llm_calls}", indent=1)
        self.log(f"⏱️  Duration: {duration:.1f}s", indent=1)
        
        return {
            "directory_pattern_result": result,
            "directory_patterns": dir_patterns,
            "logs": [
                f"📁 [Directory Pattern] Groups: {groups_patterns_found}/{groups_processed}, "
                f"Dirs: {dirs_patterns_found}/{dirs_processed}, "
                f"Files: {files_updated}"
            ]
        }
    
    @classmethod
    def run_standalone(cls) -> Dict[str, Any]:
        """
        단독 실행용 메서드 (테스트용)
        
        Returns:
            실행 결과 state
        """
        node = cls()
        return node({})

