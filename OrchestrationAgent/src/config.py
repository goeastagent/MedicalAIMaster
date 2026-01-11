"""Orchestrator 설정"""

from dataclasses import dataclass, field
from typing import List, Literal


@dataclass
class OrchestratorConfig:
    """오케스트레이터 설정
    
    Example:
        config = OrchestratorConfig(max_retries=3, timeout_seconds=60)
        orchestrator = Orchestrator(config=config)
        
        # Map-Reduce 모드 활성화
        config = OrchestratorConfig(
            execution_mode="auto",
            mapreduce_threshold=100,
            batch_size=50,
        )
    """
    
    # === 코드 생성 ===
    max_retries: int = 2
    """코드 생성 실패 시 재시도 횟수"""
    
    timeout_seconds: int = 30
    """코드 실행 타임아웃 (초)"""
    
    # === ExtractionAgent ===
    auto_resolve_ambiguity: bool = True
    """모호성 발견 시 자동으로 첫 번째 후보 선택"""
    
    min_extraction_confidence: float = 0.5
    """최소 Extraction 신뢰도 (이하면 경고)"""
    
    # === DataContext ===
    preload_cohort: bool = True
    """Cohort 데이터 미리 로드"""
    
    cache_signals: bool = True
    """Signal 데이터 캐싱 활성화"""
    
    max_signal_cases: int = 10
    """Signal 로드 시 최대 케이스 수 (0이면 무제한, 테스트 시 제한 권장)"""
    
    # === 힌트 생성 ===
    generate_hints: bool = True
    """질의 기반 구현 힌트 자동 생성"""
    
    hint_keywords: List[str] = field(default_factory=lambda: [
        "평균", "mean", "비교", "그룹", "성별", "상관", "correlation",
        "분포", "distribution", "최대", "최소", "표준편차"
    ])
    """힌트 생성에 사용할 키워드"""
    
    # === Map-Reduce 모드 ===
    execution_mode: Literal["standard", "mapreduce", "auto"] = "standard"
    """실행 모드
    
    - standard: 기본 모드 (모든 데이터 메모리 로드 후 단일 코드 실행)
    - mapreduce: Map-Reduce 모드 (배치 처리, 대용량 데이터용)
    - auto: 자동 선택 (케이스 수에 따라 자동 전환)
    """
    
    mapreduce_threshold: int = 100
    """Map-Reduce 자동 전환 임계값
    
    execution_mode="auto"일 때, 케이스 수가 이 값을 초과하면 Map-Reduce 모드로 전환.
    """
    
    batch_size: int = 100
    """Map-Reduce 배치 크기
    
    한 번에 메모리에 로드할 케이스 수.
    메모리 사용량과 처리 속도의 균형을 조절.
    """
    
    mapreduce_max_workers: int = 4
    """Map Phase 병렬 워커 수
    
    배치 내 병렬 처리 워커 수. CPU 코어 수에 맞게 조절.
    """
    
    mapreduce_parallel: bool = True
    """Map Phase 병렬 처리 활성화
    
    False면 순차 처리 (디버깅 시 유용).
    """


# 기본 설정 인스턴스
DEFAULT_CONFIG = OrchestratorConfig()


# Map-Reduce 전용 설정 프리셋
MAPREDUCE_CONFIG = OrchestratorConfig(
    execution_mode="mapreduce",
    max_signal_cases=1000,  # 무제한
    batch_size=100,
    mapreduce_max_workers=4,
    mapreduce_parallel=True,
)


# 대용량 자동 전환 설정 프리셋
AUTO_SCALE_CONFIG = OrchestratorConfig(
    execution_mode="auto",
    max_signal_cases=1000,  # 무제한
    mapreduce_threshold=100,
    batch_size=100,
    mapreduce_max_workers=4,
)

