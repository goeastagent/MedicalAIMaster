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

출력 (DB에 저장):
  - directory_catalog.filename_pattern, filename_columns
  - file_catalog.filename_values (배치 업데이트)
"""

import json
from typing import Dict, Any, List, Optional
from datetime import datetime

from ...state import AgentState
from ...base import BaseNode, LLMMixin, DatabaseMixin
from ...registry import register_node
from src.config import DirectoryPatternConfig
from .prompts import DirectoryPatternPrompt


@register_node
class DirectoryPatternNode(BaseNode, LLMMixin, DatabaseMixin):
    """
    Directory Pattern Analysis Node (LLM-based)
    
    디렉토리 내 파일명 패턴을 LLM으로 분석하고,
    파일명에서 ID/값을 추출하여 다른 테이블과의 관계를 연결합니다.
    
    Input (DB에서 읽기):
        - directory_catalog.filename_samples (이전 단계에서 수집)
        - column_metadata (이전 단계에서 분석됨)
    
    Output (DB에 저장):
        - directory_catalog.filename_pattern, filename_columns
        - file_catalog.filename_values (배치 업데이트)
    """
    
    name = "directory_pattern"
    description = "디렉토리 파일명 패턴 분석"
    order = 700
    requires_llm = True
    
    # 프롬프트 클래스 연결
    prompt_class = DirectoryPatternPrompt
    
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
        - file_catalog: primary_entity, entity_identifier_column
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
        Directory Pattern Analysis 실행
        
        All data is read from DB (no file re-reading):
        - directory_catalog: filename_samples, file_extensions
        - column_metadata: column info with semantic descriptions
        
        Steps:
        1. Query directories from directory_catalog
        2. Query data dictionary from column_metadata / data_dictionary
        3. Analyze patterns with LLM
        4. Save results to directory_catalog
        5. Batch update file_catalog.filename_values
        """
        started_at = datetime.now()
        
        # 1. 분석 대상 디렉토리 조회 (DB에서)
        self.log("📂 Querying directories from DB...")
        directories = self._get_directories_for_analysis()
        
        if not directories:
            self.log("⚠️ No directories to analyze (all already analyzed or file_count < MIN_FILES)", indent=1)
            return {
                "directory_pattern_result": {
                    "status": "skipped",
                    "reason": "no_directories",
                    "total_dirs": 0,
                    "analyzed_dirs": 0,
                    "patterns_found": 0
                },
                "directory_patterns": {},
                "logs": ["⚠️ [Directory Pattern] No directories to analyze"]
            }
        
        self.log(f"📂 Found {len(directories)} directories to analyze:", indent=1)
        for d in directories:
            self.log(f"- {d['dir_name']} ({d['file_count']} files, type={d['dir_type']})", indent=2)
        
        # 2. Data Dictionary 수집 (DB에서) - 두 소스 병합
        self.log("📖 Collecting data dictionary from DB...")
        
        # semantic 정보 (parameter 테이블 기반 - 컬럼별 의미)
        semantic_dict = self._collect_data_dictionary()
        
        # data_dictionary 테이블 기반 정보 (caseid 등 파라미터 정의 포함)
        simple_dict = self._collect_data_dictionary_simple()
        
        # 병합: 두 정보를 모두 LLM에 전달
        data_dictionary = {
            "tables": semantic_dict,  # file별 컬럼 semantic 정보
            **simple_dict  # dictionary_entries (caseid 등), id_columns_by_file
        }
        
        dict_entries_count = len(simple_dict.get('dictionary_entries', {}))
        self.log(f"📖 Data dictionary: {len(semantic_dict)} tables, {dict_entries_count} dictionary entries", indent=1)
        
        # 3. 배치 처리
        self.log(f"🤖 Analyzing patterns with LLM (batch_size={DirectoryPatternConfig.MAX_DIRS_PER_BATCH})...")
        
        all_results = []
        batches = self._batch_directories(directories, DirectoryPatternConfig.MAX_DIRS_PER_BATCH)
        
        for i, batch in enumerate(batches):
            self.log(f"Batch {i+1}/{len(batches)}: {len(batch)} directories", indent=1)
            batch_result = self._analyze_batch(batch, data_dictionary)
            all_results.extend(batch_result)
            self.log(f"✅ Got {len(batch_result)} results", indent=2)
        
        # 4. 결과 저장
        self.log("💾 Saving pattern results to directory_catalog...")
        self._save_pattern_results(all_results)
        
        # 5. filename_values 배치 업데이트
        self.log("💾 Updating file_catalog.filename_values...")
        self._update_filename_values(all_results)
        
        # 결과 요약
        completed_at = datetime.now()
        duration = (completed_at - started_at).total_seconds()
        
        patterns_found = sum(1 for r in all_results if r.get("has_pattern"))
        
        result = {
            "status": "completed",
            "total_dirs": len(directories),
            "analyzed_dirs": len(all_results),
            "patterns_found": patterns_found,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_seconds": duration
        }
        
        dir_patterns = {r["dir_id"]: r for r in all_results}
        
        self.log(f"📁 Directories analyzed: {len(all_results)}/{len(directories)}", indent=1)
        self.log(f"🔍 Patterns found: {patterns_found}", indent=1)
        for r in all_results:
            if r.get("has_pattern"):
                self.log(f"- {r.get('dir_id', 'unknown')[:8]}: {r.get('pattern')} (conf={r.get('confidence', 0):.2f})", indent=2)
        self.log(f"⏱️  Duration: {duration:.1f}s", indent=1)
        
        return {
            "directory_pattern_result": result,
            "directory_patterns": dir_patterns,
            "logs": [
                f"📁 [Directory Pattern] Analyzed {len(all_results)} directories, "
                f"found {patterns_found} patterns"
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

