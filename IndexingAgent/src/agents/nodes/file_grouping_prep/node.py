# src/agents/nodes/file_grouping_prep/node.py
"""
File Grouping Prep Node

디렉토리별 파일 통계를 수집하고 패턴을 관찰합니다.
판단은 하지 않고, LLM 입력을 준비합니다.

수집하는 정보:
- 디렉토리별 파일 수, 확장자 분포
- 파일명 샘플 및 길이 통계
- 파일 크기 통계
- 관찰된 패턴 (숫자, 날짜 등) - 판단 없이 관찰만

출력:
- grouping_prep_result: 디렉토리별 요약 정보
- directories_for_grouping: LLM에게 전달할 디렉토리 요약 리스트
"""

import re
from typing import Dict, Any, List, Optional
from datetime import datetime
from collections import defaultdict

from src.database.repositories import DirectoryRepository, FileRepository

from ...base import BaseNode, DatabaseMixin
from ...registry import register_node


@register_node
class FileGroupingPrepNode(BaseNode, DatabaseMixin):
    """
    File Grouping Prep Node (Rule-based)
    
    디렉토리별 파일 통계를 수집하고 패턴을 관찰합니다.
    LLM이 그룹핑 전략을 결정할 수 있도록 입력을 준비합니다.
    """
    
    name = "file_grouping_prep"
    description = "디렉토리별 파일 통계 수집 및 패턴 관찰 (LLM 입력 준비)"
    order = 250
    requires_llm = False
    
    # =========================================================================
    # Configuration
    # =========================================================================
    
    # 샘플링 설정
    MAX_FILENAME_SAMPLES = 10  # LLM에게 전달할 최대 파일명 샘플 수
    MIN_FILES_FOR_ANALYSIS = 2  # 분석 대상 최소 파일 수
    
    # =========================================================================
    # Repository Access (Lazy Initialization)
    # =========================================================================
    
    @property
    def dir_repo(self) -> DirectoryRepository:
        """DirectoryRepository 인스턴스 (lazy)"""
        if not hasattr(self, '_dir_repo') or self._dir_repo is None:
            self._dir_repo = DirectoryRepository()
        return self._dir_repo
    
    @property
    def file_repo(self) -> FileRepository:
        """FileRepository 인스턴스 (lazy)"""
        if not hasattr(self, '_file_repo') or self._file_repo is None:
            self._file_repo = FileRepository()
        return self._file_repo
    
    # =========================================================================
    # Main Execution
    # =========================================================================
    
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        디렉토리별 파일 정보를 수집하고 패턴을 관찰
        
        Returns:
            - grouping_prep_result: 요약 통계
            - directories_for_grouping: LLM 입력용 디렉토리 정보 리스트
        """
        self.log("=" * 60)
        self.log("📁 파일 그룹핑 준비 (패턴 관찰)")
        self.log("=" * 60)
        
        # 1. 디렉토리 목록 조회
        directories = self._get_directories_with_files()
        self.log(f"📊 분석 대상 디렉토리: {len(directories)}개")
        
        # 2. 각 디렉토리별 상세 분석
        directories_for_grouping = []
        total_files = 0
        
        for dir_info in directories:
            dir_summary = self._analyze_directory(dir_info)
            
            if dir_summary:
                directories_for_grouping.append(dir_summary)
                total_files += dir_summary['file_count']
                
                # 로그 출력
                self._log_directory_summary(dir_summary)
        
        # 3. 결과 구성
        result = {
            "total_directories": len(directories_for_grouping),
            "total_files_analyzed": total_files,
            "directories_with_patterns": sum(
                1 for d in directories_for_grouping 
                if d.get('observed_patterns')
            ),
            "prepared_at": datetime.now().isoformat()
        }
        
        self.log("=" * 60)
        self.log("✅ 준비 완료!")
        self.log(f"→ {result['total_directories']}개 디렉토리 분석", indent=1)
        self.log(f"→ {result['total_files_analyzed']}개 파일 관찰", indent=1)
        self.log(f"→ {result['directories_with_patterns']}개 디렉토리에서 패턴 감지", indent=1)
        self.log("=" * 60)
        
        return {
            "grouping_prep_result": result,
            "directories_for_grouping": directories_for_grouping
        }
    
    # =========================================================================
    # Directory Analysis (via Repository)
    # =========================================================================
    
    def _get_directories_with_files(self) -> List[Dict]:
        """파일이 있는 디렉토리 목록 조회 (via DirectoryRepository)"""
        return self.dir_repo.get_directories_with_files(min_files=self.MIN_FILES_FOR_ANALYSIS)
    
    def _get_files_in_directory(self, dir_id: str) -> List[Dict]:
        """특정 디렉토리의 파일 목록 조회 (via FileRepository)"""
        return self.file_repo.get_files_by_dir_id(dir_id)
    
    def _analyze_directory(self, dir_info: Dict) -> Optional[Dict]:
        """
        디렉토리 분석 - 패턴 관찰 (판단 없이)
        
        Returns:
            디렉토리 요약 정보 (LLM 입력용)
        """
        dir_id = str(dir_info['dir_id'])
        file_count = dir_info.get('actual_file_count', 0)
        
        # 최소 파일 수 체크
        if file_count < self.MIN_FILES_FOR_ANALYSIS:
            return None
        
        # 파일 목록 조회
        files = self._get_files_in_directory(dir_id)
        
        if not files:
            return None
        
        # 확장자별 분류
        ext_distribution = self._get_extension_distribution(files)
        
        # 파일명 분석
        filename_analysis = self._analyze_filenames(files)
        
        # 파일 크기 통계
        size_stats = self._get_size_statistics(files)
        
        # 패턴 관찰 (판단 없이 관찰된 사실만)
        observed_patterns = self._observe_patterns(files)
        
        # 이미 그룹화된 파일 수
        already_grouped = sum(1 for f in files if f.get('group_id'))
        
        return {
            "dir_id": dir_id,
            "dir_path": dir_info['dir_path'],
            "dir_name": dir_info['dir_name'],
            "file_count": len(files),
            "already_grouped_count": already_grouped,
            
            # 확장자 분포
            "extension_distribution": ext_distribution,
            
            # 파일명 분석
            "filename_samples": filename_analysis['samples'],
            "filename_length_stats": filename_analysis['length_stats'],
            "common_prefix": filename_analysis['common_prefix'],
            "common_suffix": filename_analysis['common_suffix'],
            
            # 크기 통계
            "size_stats": size_stats,
            
            # 관찰된 패턴 (판단 없이)
            "observed_patterns": observed_patterns
        }
    
    # =========================================================================
    # Analysis Helpers
    # =========================================================================
    
    def _get_extension_distribution(self, files: List[Dict]) -> Dict[str, int]:
        """확장자별 파일 수 계산"""
        distribution = defaultdict(int)
        for f in files:
            ext = f.get('file_extension', 'unknown') or 'no_extension'
            distribution[ext] += 1
        return dict(distribution)
    
    def _analyze_filenames(self, files: List[Dict]) -> Dict[str, Any]:
        """파일명 분석"""
        filenames = [f['file_name'] for f in files if f.get('file_name')]
        
        if not filenames:
            return {
                'samples': [],
                'length_stats': {},
                'common_prefix': '',
                'common_suffix': ''
            }
        
        # 샘플 추출 (첫 N개, 중간, 마지막)
        samples = self._get_representative_samples(filenames)
        
        # 길이 통계
        lengths = [len(fn) for fn in filenames]
        length_stats = {
            'min': min(lengths),
            'max': max(lengths),
            'avg': round(sum(lengths) / len(lengths), 1)
        }
        
        # 공통 prefix/suffix 찾기
        common_prefix = self._find_common_prefix(filenames)
        common_suffix = self._find_common_suffix(filenames)
        
        return {
            'samples': samples,
            'length_stats': length_stats,
            'common_prefix': common_prefix,
            'common_suffix': common_suffix
        }
    
    def _get_representative_samples(self, filenames: List[str]) -> List[str]:
        """대표 샘플 추출"""
        if len(filenames) <= self.MAX_FILENAME_SAMPLES:
            return sorted(filenames)
        
        # 첫 3개, 중간 4개, 마지막 3개
        sorted_names = sorted(filenames)
        n = len(sorted_names)
        
        samples = []
        samples.extend(sorted_names[:3])  # 처음
        
        mid_start = n // 2 - 2
        samples.extend(sorted_names[mid_start:mid_start + 4])  # 중간
        
        samples.extend(sorted_names[-3:])  # 마지막
        
        # 중복 제거 및 정렬
        return sorted(list(set(samples)))
    
    def _find_common_prefix(self, strings: List[str]) -> str:
        """공통 prefix 찾기"""
        if not strings:
            return ''
        
        prefix = strings[0]
        for s in strings[1:]:
            while not s.startswith(prefix):
                prefix = prefix[:-1]
                if not prefix:
                    return ''
        return prefix
    
    def _find_common_suffix(self, strings: List[str]) -> str:
        """공통 suffix 찾기 (확장자 포함)"""
        if not strings:
            return ''
        
        reversed_strings = [s[::-1] for s in strings]
        reversed_suffix = self._find_common_prefix(reversed_strings)
        return reversed_suffix[::-1]
    
    def _get_size_statistics(self, files: List[Dict]) -> Dict[str, Any]:
        """파일 크기 통계"""
        sizes = [f.get('file_size_bytes', 0) or 0 for f in files]
        
        if not sizes:
            return {}
        
        return {
            'min_bytes': min(sizes),
            'max_bytes': max(sizes),
            'avg_bytes': round(sum(sizes) / len(sizes)),
            'total_bytes': sum(sizes),
            # MB 단위도 제공
            'min_mb': round(min(sizes) / (1024 * 1024), 2),
            'max_mb': round(max(sizes) / (1024 * 1024), 2),
            'avg_mb': round(sum(sizes) / len(sizes) / (1024 * 1024), 2)
        }
    
    # =========================================================================
    # Pattern Observation (No Judgment)
    # =========================================================================
    
    def _observe_patterns(self, files: List[Dict]) -> List[Dict]:
        """
        패턴 관찰 (판단 없이 관찰된 사실만 기록)
        
        관찰 항목:
        - 숫자로만 된 파일명 (1.csv, 2.csv, ...)
        - 숫자 prefix/suffix (case_001.csv, record_2024.csv)
        - 날짜 패턴 (2024-01-01.log)
        - 분할 파일 패턴 (table_1.csv, table_2.csv)
        - 쌍 파일 패턴 (.hea + .dat)
        
        Returns:
            관찰된 패턴 목록 (판단 없이 사실만)
        """
        patterns = []
        filenames = [f['file_name'] for f in files if f.get('file_name')]
        
        if not filenames:
            return patterns
        
        # 1. 순수 숫자 파일명 관찰
        numeric_only = self._observe_numeric_only_pattern(filenames)
        if numeric_only:
            patterns.append(numeric_only)
        
        # 2. 숫자 포함 패턴 관찰
        numeric_parts = self._observe_numeric_parts_pattern(filenames)
        if numeric_parts:
            patterns.append(numeric_parts)
        
        # 3. 날짜 패턴 관찰
        date_pattern = self._observe_date_pattern(filenames)
        if date_pattern:
            patterns.append(date_pattern)
        
        # 4. 분할 파일 패턴 관찰 (base_1, base_2)
        partition_pattern = self._observe_partition_pattern(filenames)
        if partition_pattern:
            patterns.append(partition_pattern)
        
        # 5. 확장자 쌍 관찰 (.hea + .dat)
        paired_ext = self._observe_paired_extensions(files)
        if paired_ext:
            patterns.append(paired_ext)
        
        return patterns
    
    def _observe_numeric_only_pattern(self, filenames: List[str]) -> Optional[Dict]:
        """순수 숫자 파일명 관찰 (1.vital, 2.vital)"""
        # 확장자 제거 후 숫자만 있는지 확인
        numeric_count = 0
        numeric_values = []
        
        for fn in filenames:
            name_without_ext = fn.rsplit('.', 1)[0] if '.' in fn else fn
            if name_without_ext.isdigit():
                numeric_count += 1
                numeric_values.append(int(name_without_ext))
        
        if numeric_count == 0:
            return None
        
        ratio = numeric_count / len(filenames)
        
        if ratio < 0.5:  # 50% 미만이면 무시
            return None
        
        return {
            'type': 'numeric_only',
            'description': '파일명이 순수 숫자 (예: 1.ext, 2.ext)',
            'matching_count': numeric_count,
            'total_count': len(filenames),
            'ratio': round(ratio, 2),
            'value_range': {
                'min': min(numeric_values) if numeric_values else None,
                'max': max(numeric_values) if numeric_values else None
            }
        }
    
    def _observe_numeric_parts_pattern(self, filenames: List[str]) -> Optional[Dict]:
        """숫자 부분이 포함된 패턴 관찰 (case_001.csv)"""
        # 숫자 부분 추출
        pattern = re.compile(r'(\d+)')
        
        files_with_numbers = 0
        number_positions = defaultdict(int)  # 위치별 카운트
        
        for fn in filenames:
            name_without_ext = fn.rsplit('.', 1)[0] if '.' in fn else fn
            matches = list(pattern.finditer(name_without_ext))
            
            if matches:
                files_with_numbers += 1
                # 숫자의 상대적 위치 기록
                for m in matches:
                    rel_pos = m.start() / len(name_without_ext) if name_without_ext else 0
                    position = 'start' if rel_pos < 0.3 else ('end' if rel_pos > 0.7 else 'middle')
                    number_positions[position] += 1
        
        if files_with_numbers == 0:
            return None
        
        ratio = files_with_numbers / len(filenames)
        
        if ratio < 0.5:
            return None
        
        return {
            'type': 'numeric_parts',
            'description': '파일명에 숫자 부분 포함 (예: case_001.csv)',
            'matching_count': files_with_numbers,
            'total_count': len(filenames),
            'ratio': round(ratio, 2),
            'number_positions': dict(number_positions)
        }
    
    def _observe_date_pattern(self, filenames: List[str]) -> Optional[Dict]:
        """날짜 패턴 관찰"""
        # 일반적인 날짜 패턴들
        date_patterns = [
            (r'\d{4}-\d{2}-\d{2}', 'YYYY-MM-DD'),
            (r'\d{4}\d{2}\d{2}', 'YYYYMMDD'),
            (r'\d{2}-\d{2}-\d{4}', 'DD-MM-YYYY'),
            (r'\d{2}/\d{2}/\d{4}', 'DD/MM/YYYY'),
        ]
        
        for pattern, format_name in date_patterns:
            regex = re.compile(pattern)
            matching = [fn for fn in filenames if regex.search(fn)]
            
            if len(matching) >= len(filenames) * 0.5:
                return {
                    'type': 'date_pattern',
                    'description': f'날짜 패턴 감지 ({format_name})',
                    'format': format_name,
                    'matching_count': len(matching),
                    'total_count': len(filenames),
                    'ratio': round(len(matching) / len(filenames), 2)
                }
        
        return None
    
    def _observe_partition_pattern(self, filenames: List[str]) -> Optional[Dict]:
        """분할 파일 패턴 관찰 (table_1.csv, table_2.csv)"""
        # base_N 또는 base-N 패턴
        pattern = re.compile(r'^(.+)[_-](\d+)\.(\w+)$')
        
        base_names = defaultdict(list)
        
        for fn in filenames:
            match = pattern.match(fn)
            if match:
                base, num, ext = match.groups()
                base_names[f"{base}.{ext}"].append(int(num))
        
        # 2개 이상의 파티션이 있는 베이스만
        partitioned = {k: v for k, v in base_names.items() if len(v) >= 2}
        
        if not partitioned:
            return None
        
        return {
            'type': 'partitioned',
            'description': '분할 파일 패턴 (예: table_1.csv, table_2.csv)',
            'base_tables': [
                {
                    'base_name': base,
                    'partition_count': len(nums),
                    'partition_range': {'min': min(nums), 'max': max(nums)}
                }
                for base, nums in partitioned.items()
            ]
        }
    
    def _observe_paired_extensions(self, files: List[Dict]) -> Optional[Dict]:
        """확장자 쌍 관찰 (.hea + .dat)"""
        # 파일명(확장자 제외)으로 그룹화
        by_stem = defaultdict(list)
        
        for f in files:
            fn = f.get('file_name', '')
            if '.' in fn:
                stem = fn.rsplit('.', 1)[0]
                ext = fn.rsplit('.', 1)[1]
                by_stem[stem].append(ext)
        
        # 2개 이상의 확장자를 가진 stem
        paired_stems = {k: v for k, v in by_stem.items() if len(v) >= 2}
        
        if not paired_stems:
            return None
        
        # 가장 흔한 확장자 조합
        ext_combinations = defaultdict(int)
        for exts in paired_stems.values():
            combo = tuple(sorted(set(exts)))
            ext_combinations[combo] += 1
        
        most_common = max(ext_combinations.items(), key=lambda x: x[1])
        
        return {
            'type': 'paired_extensions',
            'description': '동일 파일명에 여러 확장자 (예: record.hea + record.dat)',
            'paired_count': len(paired_stems),
            'most_common_pair': list(most_common[0]),
            'pair_frequency': most_common[1]
        }
    
    # =========================================================================
    # Logging Helpers
    # =========================================================================
    
    def _log_directory_summary(self, summary: Dict):
        """디렉토리 요약 로그"""
        self.log(f"\n📂 {summary['dir_name']}/", indent=1)
        self.log(f"파일 수: {summary['file_count']}", indent=2)
        
        if summary.get('already_grouped_count'):
            self.log(f"이미 그룹화됨: {summary['already_grouped_count']}", indent=2)
        
        # 확장자 분포
        ext_dist = summary.get('extension_distribution', {})
        if ext_dist:
            ext_str = ', '.join(f"{k}: {v}" for k, v in ext_dist.items())
            self.log(f"확장자: {ext_str}", indent=2)
        
        # 파일명 샘플
        samples = summary.get('filename_samples', [])
        if samples:
            sample_str = ', '.join(samples[:5])
            if len(samples) > 5:
                sample_str += f" ... (+{len(samples) - 5})"
            self.log(f"샘플: {sample_str}", indent=2)
        
        # 관찰된 패턴
        patterns = summary.get('observed_patterns', [])
        if patterns:
            self.log("관찰된 패턴:", indent=2)
            for p in patterns:
                self.log(f"- {p['type']}: {p['description']} ({p.get('ratio', 0)*100:.0f}%)", indent=3)
    
    # =========================================================================
    # Standalone Execution
    # =========================================================================
    
    @classmethod
    def run_standalone(cls, verbose: bool = True) -> Dict[str, Any]:
        """독립 실행 (테스트/디버깅용)"""
        node = cls()
        result = node.execute({})
        
        if verbose:
            for log in node._logs:
                print(log)
        
        return result

