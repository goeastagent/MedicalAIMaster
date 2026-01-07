"""OrchestrationAgent - 경량 오케스트레이터

ExtractionAgent와 AnalysisAgent(CodeGen)를 연결하는 조율 레이어.

사용법:
    from OrchestrationAgent.src import Orchestrator
    
    orchestrator = Orchestrator()
    result = orchestrator.run("위암 환자의 심박수 평균을 구해줘")
    
    if result.status == "success":
        print(result.result)
"""

from .orchestrator import Orchestrator
from .models import (
    OrchestrationRequest,
    OrchestrationResult,
)
from .config import OrchestratorConfig

__all__ = [
    "Orchestrator",
    "OrchestrationRequest",
    "OrchestrationResult",
    "OrchestratorConfig",
]

