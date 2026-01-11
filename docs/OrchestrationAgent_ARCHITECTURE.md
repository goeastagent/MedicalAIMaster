# OrchestrationAgent 아키텍처

> ExtractionAgent와 AnalysisAgent를 연결하는 경량 오케스트레이터

## 📖 개요

OrchestrationAgent는 **ExtractionAgent**와 **AnalysisAgent(CodeGen)**를 연결하는 **얇은 조율 레이어**입니다.

```
최소 구현 (MVP First)
├── 복잡한 그래프 없이 순차 실행
├── 3개 컴포넌트만 연결: Extraction → DataContext → CodeGen
└── 필요해지면 확장
```

---

## 🔄 전체 흐름

```
사용자 질의
"2023년 위암 환자의 심박수 평균을 성별로 비교해줘"
                    │
                    ▼
        ┌─────────────────────────────────┐
        │  Step 1: ExtractionAgent 호출    │
        │  쿼리 → Execution Plan 생성      │
        └─────────────────────────────────┘
                    │
                    ▼
        ┌─────────────────────────────────┐
        │  Step 2: DataContext로 데이터 로드│
        │  Plan 해석 → runtime_data 준비   │
        └─────────────────────────────────┘
                    │
                    ▼
        ┌─────────────────────────────────┐
        │  Step 3: CodeGenerator로 분석    │
        │  Python 코드 생성 → Sandbox 실행 │
        └─────────────────────────────────┘
                    │
                    ▼
분석 결과 반환
{"status": "success", "result": {...}, "code": "..."}
```

---

## 🎯 Public API

```python
from OrchestrationAgent.src import Orchestrator

orchestrator = Orchestrator()

# 전체 파이프라인 실행
result = orchestrator.run("위암 환자의 심박수 평균을 구해줘")

# Execution Plan이 있는 경우
result = orchestrator.run_with_plan(query, execution_plan)

# 데이터가 이미 있는 경우 (분석만 실행)
result = orchestrator.run_analysis_only(query, runtime_data)
```

---

## 📋 OrchestrationResult

```python
class OrchestrationResult:
    status: Literal["success", "error", "partial"]
    result: Optional[Any]           # 분석 결과
    generated_code: Optional[str]   # 생성된 Python 코드
    error_message: Optional[str]    # 에러 메시지
    error_stage: Optional[str]      # 실패 단계 (extraction/data_load/analysis)
    execution_time_ms: float        # 실행 시간
    data_summary: Dict              # 데이터 요약
    retry_count: int                # 재시도 횟수
```

---

## 📁 파일 구조

```
OrchestrationAgent/
├── src/
│   ├── __init__.py
│   ├── orchestrator.py    # 메인 클래스 (~800줄)
│   ├── models.py          # 입출력 모델
│   └── config.py          # 설정
├── examples/
│   └── example_end_to_end.py
└── test_e2e_hr_mean.py    # E2E 테스트
```

---

## 🔧 사용 예시

```python
# 기본 사용
orchestrator = Orchestrator()
result = orchestrator.run("위암 환자의 심박수 평균")

if result.status == "success":
    print("분석 결과:", result.result)
    print("생성된 코드:", result.generated_code)
else:
    print("에러:", result.error_message)
    print("실패 단계:", result.error_stage)
```

자세한 내용은 `OrchestrationAgent/ARCHITECTURE.md`를 참조하세요.
