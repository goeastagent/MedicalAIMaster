# src/agents/nodes/directory_catalog.py
"""
Directory Catalog Node

디렉토리 레벨 메타데이터를 수집하여 DB에 저장합니다.
LLM 호출 없이 순수하게 규칙 기반으로 데이터 수집만 수행합니다.

저장 테이블:
- directory_catalog: 디렉토리 단위 메타데이터

수집 정보:
- 디렉토리 계층 구조 (parent_dir_id)
- 파일 확장자별 카운트
- 파일명 샘플 (LLM 분석용)
- 총 파일 크기
"""

import os
import fnmatch
from typing import Dict, Any, List, Optional
from collections import defaultdict
from datetime import datetime

from src.agents.state import AgentState
from src.database import (
    get_db_manager,
    DirectorySchemaManager,
    insert_directory,
)
from src.config import DirectoryCatalogConfig

from ..base import BaseNode, DatabaseMixin
from ..registry import register_node


@register_node
class DirectoryCatalogNode(BaseNode, DatabaseMixin):
    """
    Directory Catalog Node (Rule-based)
    
    디렉토리 레벨 메타데이터를 수집하여 DB에 저장합니다.
    LLM 호출 없이 순수하게 규칙 기반으로 데이터 수집만 수행합니다.
    """
    
    name = "directory_catalog"
    description = "디렉토리 구조 분석 및 메타데이터 수집"
    order = 100
    requires_llm = False
    
    # =========================================================================
    # Main Execution
    # =========================================================================
    
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        디렉토리 구조를 분석하여 DB에 저장
        
        Args:
            state: AgentState (input_directory 또는 input_files 필드 필요)
        
        Returns:
            업데이트된 상태:
            - phase1_result: 처리 결과
            - phase1_dir_ids: 생성된 dir_id 목록
            - logs: 로그 메시지
        """
        print("\n" + "="*80)
        print("📁 [Directory Catalog] 디렉토리 구조 분석 시작")
        print("="*80)
        
        started_at = datetime.now().isoformat()
        
        # 입력 디렉토리 결정
        input_directory = state.get("input_directory")
        input_files = state.get("input_files", [])
        
        if not input_directory and input_files:
            # input_files에서 공통 상위 디렉토리 추출
            input_directory = self._find_common_parent_directory(input_files)
            if input_directory:
                print(f"   📂 Inferred directory from input_files: {input_directory}")
        
        if not input_directory:
            return self._create_error_result(
                "No input directory provided", started_at
            )
        
        # 디렉토리 존재 확인
        if not os.path.isdir(input_directory):
            return self._create_error_result(
                f"Directory not found: {input_directory}", started_at
            )
        
        print(f"   📂 Input directory: {input_directory}\n")
        
        # 스키마 확인/생성
        self._ensure_schema()
        
        # 디렉토리 트리 처리
        result = self._process_directory_tree(
            root_path=input_directory,
            recursive=True,
            verbose=True
        )
        
        completed_at = datetime.now().isoformat()
        result["started_at"] = started_at
        result["completed_at"] = completed_at
        
        # 로그 생성
        logs = [
            f"📁 [Directory Catalog] 완료: {result['processed_dirs']}개 디렉토리 처리, "
            f"{result['total_files']}개 파일 탐지"
        ]
        
        if result.get("dir_ids"):
            short_ids = [did[:8] for did in result["dir_ids"][:5]]
            if len(result["dir_ids"]) > 5:
                short_ids.append(f"... (+{len(result['dir_ids']) - 5})")
            logs.append(f"   📋 Dir IDs: {short_ids}")
        
        if result.get("error"):
            logs.append(f"   ⚠️ Error: {result['error']}")
        
        # 요약 출력
        print(f"\n✅ [Directory Catalog] 완료:")
        print(f"   📊 총 디렉토리: {result['total_dirs']}개")
        print(f"   ✅ 처리 완료: {result['processed_dirs']}개")
        print(f"   📄 총 파일: {result['total_files']}개")
        
        return {
            "logs": logs,
            "phase1_result": result,
            "phase1_dir_ids": result.get("dir_ids", [])
        }
    
    # =========================================================================
    # Directory Processing Methods
    # =========================================================================
    
    def _process_directory_tree(
        self,
        root_path: str,
        recursive: bool = True,
        verbose: bool = True,
        current_depth: int = 0,
        parent_dir_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        디렉토리 트리 처리 (재귀)
        
        Args:
            root_path: 루트 디렉토리 경로
            recursive: 하위 디렉토리 포함 여부
            verbose: 진행 상황 출력
            current_depth: 현재 깊이 (내부 사용)
            parent_dir_id: 부모 디렉토리 ID (내부 사용)
        
        Returns:
            처리 결과 딕셔너리
        """
        root_path = os.path.abspath(root_path)
        
        # 깊이 제한 체크
        if current_depth > DirectoryCatalogConfig.MAX_DEPTH:
            if verbose:
                print(f"   ⚠️ Max depth reached: {root_path}")
            return self._empty_result()
        
        # 디렉토리 스캔
        dir_info = self._scan_directory(root_path)
        
        if "error" in dir_info:
            return {**self._empty_result(), "error": dir_info["error"]}
        
        # 파일명 샘플 수집
        filename_samples = self._collect_filename_samples(dir_info["files"])
        
        # 디렉토리 타입 분류
        dir_type = self._classify_directory_type(dir_info["file_extensions"])
        
        # DB 저장
        try:
            dir_id = insert_directory(
                dir_path=dir_info["dir_path"],
                dir_name=dir_info["dir_name"],
                parent_dir_id=parent_dir_id,
                file_count=dir_info["file_count"],
                file_extensions=dir_info["file_extensions"],
                total_size_bytes=dir_info["total_size_bytes"],
                subdir_count=len(dir_info["subdirs"]),
                filename_samples=filename_samples
            )
            
            # dir_type 업데이트
            if dir_type:
                self._update_dir_type(dir_id, dir_type)
            
            if verbose:
                short_id = dir_id[:8]
                type_str = f" [{dir_type}]" if dir_type else ""
                print(f"   ✅ [{short_id}] {dir_info['dir_name']}{type_str} ({dir_info['file_count']} files, {len(dir_info['subdirs'])} subdirs)")
            
        except Exception as e:
            if verbose:
                print(f"   ❌ Error processing {dir_info['dir_name']}: {e}")
            return {
                "total_dirs": 1,
                "processed_dirs": 0,
                "skipped_dirs": 0,
                "total_files": dir_info["file_count"],
                "dir_ids": [],
                "error": str(e)
            }
        
        # 결과 집계
        result = {
            "total_dirs": 1,
            "processed_dirs": 1,
            "skipped_dirs": 0,
            "total_files": dir_info["file_count"],
            "dir_ids": [dir_id]
        }
        
        # 재귀 처리 (하위 디렉토리)
        if recursive and dir_info["subdirs"]:
            for subdir_name in sorted(dir_info["subdirs"]):
                subdir_path = os.path.join(root_path, subdir_name)
                
                sub_result = self._process_directory_tree(
                    root_path=subdir_path,
                    recursive=True,
                    verbose=verbose,
                    current_depth=current_depth + 1,
                    parent_dir_id=dir_id
                )
                
                result["total_dirs"] += sub_result["total_dirs"]
                result["processed_dirs"] += sub_result["processed_dirs"]
                result["skipped_dirs"] += sub_result["skipped_dirs"]
                result["total_files"] += sub_result["total_files"]
                result["dir_ids"].extend(sub_result["dir_ids"])
        
        return result
    
    def _scan_directory(self, dir_path: str) -> Dict[str, Any]:
        """
        단일 디렉토리 스캔 (재귀하지 않음, 직계 자식만)
        
        Returns:
            디렉토리 정보 딕셔너리
        """
        dir_path = os.path.abspath(dir_path)
        dir_name = os.path.basename(dir_path)
        
        file_extensions: Dict[str, int] = defaultdict(int)
        total_size_bytes = 0
        files: List[str] = []
        subdirs: List[str] = []
        
        try:
            entries = os.listdir(dir_path)
        except PermissionError:
            print(f"   ⚠️ Permission denied: {dir_path}")
            return {
                "dir_path": dir_path,
                "dir_name": dir_name,
                "file_count": 0,
                "file_extensions": {},
                "total_size_bytes": 0,
                "files": [],
                "subdirs": [],
                "error": "Permission denied"
            }
        
        for entry in entries:
            entry_path = os.path.join(dir_path, entry)
            
            if os.path.isdir(entry_path):
                if not self._should_ignore_dir(entry):
                    subdirs.append(entry)
            elif os.path.isfile(entry_path):
                if not self._should_ignore_file(entry):
                    files.append(entry)
                    ext = self._get_file_extension(entry)
                    if ext:
                        file_extensions[ext] += 1
                    try:
                        total_size_bytes += os.path.getsize(entry_path)
                    except OSError:
                        pass
        
        return {
            "dir_path": dir_path,
            "dir_name": dir_name,
            "file_count": len(files),
            "file_extensions": dict(file_extensions),
            "total_size_bytes": total_size_bytes,
            "files": files,
            "subdirs": subdirs
        }
    
    # =========================================================================
    # Helper Methods: File Filtering
    # =========================================================================
    
    def _should_ignore_dir(self, dir_name: str) -> bool:
        """무시해야 할 디렉토리인지 확인"""
        return dir_name in DirectoryCatalogConfig.IGNORE_DIRS or dir_name.startswith('.')
    
    def _should_ignore_file(self, filename: str) -> bool:
        """무시해야 할 파일인지 확인"""
        for pattern in DirectoryCatalogConfig.IGNORE_PATTERNS:
            if fnmatch.fnmatch(filename, pattern):
                return True
        return False
    
    def _get_file_extension(self, filename: str) -> str:
        """파일 확장자 추출 (소문자)"""
        ext = os.path.splitext(filename)[1].lower()
        return ext[1:] if ext.startswith('.') else ext
    
    # =========================================================================
    # Helper Methods: Classification & Sampling
    # =========================================================================
    
    def _collect_filename_samples(
        self,
        files: List[str],
        max_samples: int = None
    ) -> List[str]:
        """
        파일명 샘플 수집 (다양한 샘플 확보)
        
        전략 (diverse):
        - 처음 N개: 시작 패턴 확인
        - 마지막 N개: 끝 패턴 확인
        - 중간 균등 분포: 전체 패턴 확인
        """
        if max_samples is None:
            max_samples = DirectoryCatalogConfig.FILENAME_SAMPLE_SIZE
        
        if len(files) <= max_samples:
            return sorted(files)
        
        strategy = DirectoryCatalogConfig.SAMPLE_STRATEGY
        
        if strategy == "first":
            return sorted(files[:max_samples])
        
        elif strategy == "random":
            import random
            return sorted(random.sample(files, max_samples))
        
        else:  # diverse (default)
            sorted_files = sorted(files)
            samples = []
            
            # 처음 N개
            first_n = max_samples // 4
            samples.extend(sorted_files[:first_n])
            
            # 마지막 N개
            last_n = max_samples // 4
            samples.extend(sorted_files[-last_n:])
            
            # 중간 균등 분포
            middle_n = max_samples - first_n - last_n
            middle_files = sorted_files[first_n:-last_n] if last_n > 0 else sorted_files[first_n:]
            
            if middle_files and middle_n > 0:
                step = max(1, len(middle_files) // middle_n)
                for i in range(0, len(middle_files), step):
                    if len(samples) >= max_samples:
                        break
                    if middle_files[i] not in samples:
                        samples.append(middle_files[i])
            
            return sorted(set(samples))
    
    def _classify_directory_type(self, file_extensions: Dict[str, int]) -> Optional[str]:
        """
        파일 확장자 분포에 따라 디렉토리 타입 분류
        
        Returns:
            "signal_files", "tabular_files", "metadata_files", "mixed", or None
        """
        if not file_extensions:
            return None
        
        total_files = sum(file_extensions.values())
        if total_files == 0:
            return None
        
        threshold = DirectoryCatalogConfig.TYPE_CLASSIFICATION_THRESHOLD
        
        # 각 타입별 파일 수 계산
        signal_count = sum(
            count for ext, count in file_extensions.items()
            if ext in DirectoryCatalogConfig.SIGNAL_EXTENSIONS
        )
        tabular_count = sum(
            count for ext, count in file_extensions.items()
            if ext in DirectoryCatalogConfig.TABULAR_EXTENSIONS
        )
        metadata_count = sum(
            count for ext, count in file_extensions.items()
            if ext in DirectoryCatalogConfig.METADATA_EXTENSIONS
        )
        
        # 비율 기반 분류
        if signal_count / total_files >= threshold:
            return "signal_files"
        elif tabular_count / total_files >= threshold:
            return "tabular_files"
        elif metadata_count / total_files >= threshold:
            return "metadata_files"
        else:
            return "mixed"
    
    # =========================================================================
    # Helper Methods: Database & Utils
    # =========================================================================
    
    def _ensure_schema(self):
        """스키마가 없으면 생성"""
        schema_manager = DirectorySchemaManager()
        if not schema_manager.table_exists('directory_catalog'):
            schema_manager.create_tables()
    
    def _update_dir_type(self, dir_id: str, dir_type: str):
        """디렉토리 타입 업데이트"""
        db = get_db_manager()
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE directory_catalog SET dir_type = %s WHERE dir_id = %s",
            (dir_type, dir_id)
        )
        conn.commit()
    
    def _find_common_parent_directory(self, file_paths: List[str]) -> Optional[str]:
        """파일 경로 리스트에서 공통 상위 디렉토리 추출"""
        if not file_paths:
            return None
        
        # 모든 파일의 디렉토리 경로 추출
        dir_paths = [os.path.dirname(os.path.abspath(f)) for f in file_paths]
        unique_dirs = set(dir_paths)
        
        if len(unique_dirs) == 1:
            return unique_dirs.pop()
        
        # 공통 접두사 찾기
        common = os.path.commonpath(list(unique_dirs))
        return common if common else None
    
    def _empty_result(self) -> Dict[str, Any]:
        """빈 결과 딕셔너리 반환"""
        return {
            "total_dirs": 0,
            "processed_dirs": 0,
            "skipped_dirs": 0,
            "total_files": 0,
            "dir_ids": []
        }
    
    def _create_error_result(self, error_msg: str, started_at: str) -> Dict[str, Any]:
        """에러 결과 생성"""
        print(f"   ❌ {error_msg}")
        return {
            "logs": [f"❌ [Directory Catalog] Error: {error_msg}"],
            "phase1_result": {
                **self._empty_result(),
                "started_at": started_at,
                "completed_at": datetime.now().isoformat(),
                "error": error_msg
            },
            "phase1_dir_ids": [],
            "error_message": error_msg
        }
    
    # =========================================================================
    # Convenience Methods (Standalone Execution)
    # =========================================================================
    
    @classmethod
    def run_standalone(
        cls,
        directory: str,
        recursive: bool = True,
        verbose: bool = True
    ) -> Dict[str, Any]:
        """
        독립 실행 (테스트/디버깅용)
        
        Args:
            directory: 처리할 디렉토리 경로
            recursive: 하위 디렉토리 포함 여부
            verbose: 진행 상황 출력
        
        Returns:
            처리 결과 딕셔너리
        """
        node = cls()
        node._ensure_schema()
        
        if verbose:
            print(f"[Directory Catalog] Processing directory: {directory}")
        
        return node._process_directory_tree(
            root_path=directory,
            recursive=recursive,
            verbose=verbose
        )
    
    @classmethod
    def get_stats(cls) -> dict:
        """directory_catalog 통계 조회"""
        schema_manager = DirectorySchemaManager()
        return schema_manager.get_stats()
