"""Orchestrator 설정"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class OrchestratorConfig:
    """오케스트레이터 설정
    
    Example:
        config = OrchestratorConfig(max_retries=3, timeout_seconds=60)
        orchestrator = Orchestrator(config=config)
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


# 기본 설정 인스턴스
DEFAULT_CONFIG = OrchestratorConfig()

