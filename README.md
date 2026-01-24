# MedicalAIMaster

<p align="center">
  <b>자연어 질의 기반 의료 데이터 분석 AI 멀티 에이전트 시스템</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/PostgreSQL-15+-336791.svg" alt="PostgreSQL">
  <img src="https://img.shields.io/badge/Neo4j-5.0+-008CC1.svg" alt="Neo4j">
  <img src="https://img.shields.io/badge/LangGraph-0.0.20+-orange.svg" alt="LangGraph">
</p>

---

## Overview

MedicalAIMaster는 **자연어 질의**를 통해 의료 데이터를 분석할 수 있는 AI 에이전트 시스템입니다. LLM 기반 파이프라인을 통해 사용자의 질문을 이해하고, 적절한 데이터를 찾아 Python 코드를 자동 생성하여 분석 결과를 제공합니다.

```
사용자: "2023년 위암 환자의 심박수 평균을 성별로 비교해줘"
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                    MedicalAIMaster                               │
│                                                                  │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐ │
│  │IndexingAgent │   │Extraction    │   │Analysis              │ │
│  │ (데이터 인덱싱)│→ │ Agent        │→ │ Agent                │ │
│  │              │   │ (쿼리 해석)   │   │ (코드 생성/실행)      │ │
│  └──────────────┘   └──────────────┘   └──────────────────────┘ │
│         │                   │                    │              │
│         └───────────────────┴────────────────────┘              │
│                             │                                    │
│                    ┌────────────────┐                           │
│                    │Orchestration   │                           │
│                    │Agent (조율)     │                           │
│                    └────────────────┘                           │
└─────────────────────────────────────────────────────────────────┘
                    │
                    ▼
결과: {"male": 75.2, "female": 72.8}
```

---

## Features

- **자연어 질의 처리**: 복잡한 SQL이나 코드 없이 자연어로 데이터 분석 요청
- **자동 코드 생성**: LLM이 분석 Python 코드를 자동으로 생성 및 실행
- **멀티모달 데이터 지원**: 정형 데이터(CSV, Excel)와 생체신호 데이터(.vital, .edf) 동시 처리
- **지식 그래프 기반**: Neo4j 온톨로지를 통한 의미론적 데이터 탐색
- **안전한 실행 환경**: Sandbox에서 코드 실행, 위험 패턴 자동 차단

---

## Architecture

### 4개의 에이전트

| Agent | 역할 | 핵심 기술 |
|-------|------|----------|
| **IndexingAgent** | 데이터 파일을 분석하여 PostgreSQL/Neo4j에 메타데이터 인덱싱 | LangGraph, PostgreSQL, Neo4j |
| **ExtractionAgent** | 자연어 쿼리를 분석하여 Execution Plan JSON 생성 | LangGraph, LLM, 6-Phase Pipeline |
| **AnalysisAgent** | LLM 기반 Python 코드 자동 생성 및 Sandbox 실행 | CodeGen, Validator, Sandbox |
| **OrchestrationAgent** | 위 에이전트들을 조율하는 경량 레이어 | Pipeline Orchestration |

### 데이터 흐름

```
1. IndexingAgent: 데이터 파일 → PostgreSQL + Neo4j (사전 인덱싱)

2. 사용자 질의 처리:
   ┌───────────────────┐
   │ "심박수 평균 구해줘" │
   └─────────┬─────────┘
             │
             ▼
   ┌───────────────────┐     ┌─────────────────────┐
   │ ExtractionAgent   │────▶│ Execution Plan JSON │
   │ (쿼리 이해/매핑)   │     │ (어떤 데이터, 어디서) │
   └───────────────────┘     └──────────┬──────────┘
                                        │
                                        ▼
                            ┌───────────────────────┐
                            │ DataContext (데이터 로드)│
                            └──────────┬────────────┘
                                       │
                                       ▼
                            ┌───────────────────────┐
                            │ AnalysisAgent         │
                            │ (코드 생성 → 실행)     │
                            └──────────┬────────────┘
                                       │
                                       ▼
                            ┌───────────────────────┐
                            │ 분석 결과              │
                            └───────────────────────┘
```

---

## Installation

### Prerequisites

- Python 3.10+
- Docker (PostgreSQL, Neo4j 실행용)
- OpenAI API Key 또는 Anthropic API Key

### 1. Clone Repository

```bash
git clone https://github.com/your-username/MedicalAIMaster.git
cd MedicalAIMaster
```

### 2. Create Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r IndexingAgent/requirements.txt
pip install -r ExtractionAgent/requirements.txt
pip install -r AnalysisAgent/requirements.txt
pip install -r OrchestrationAgent/requirements.txt
```

### 4. Environment Setup

프로젝트 루트에 `.env` 파일을 생성합니다:

```bash
# LLM API Keys
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...  # (선택)

# PostgreSQL
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=medical_data
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres

# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
```

### 5. Start Database Services

```bash
cd IndexingAgent
./run_postgres_neo4j.sh
```

---

## Quick Start

### 1. 데이터 인덱싱 (최초 1회)

```bash
python IndexingAgent/test_full_pipeline_results.py
```

### 2. 분석 실행

```python
from OrchestrationAgent.src import Orchestrator

# 오케스트레이터 초기화
orchestrator = Orchestrator()

# 자연어 질의로 분석 실행
result = orchestrator.run("위암 환자의 심박수 평균을 성별로 비교해줘")

if result.status == "success":
    print("분석 결과:", result.result)
    print("생성된 코드:", result.generated_code)
else:
    print("에러:", result.error_message)
```

---

## Project Structure

```
MedicalAIMaster/
├── IndexingAgent/           # 데이터 인덱싱 에이전트
│   ├── src/
│   │   ├── agents/          # LangGraph 기반 노드들
│   │   ├── models/          # Pydantic 모델
│   │   └── database/        # DB 연결
│   └── run_postgres_neo4j.sh
│
├── ExtractionAgent/         # 쿼리 해석 에이전트
│   ├── src/
│   │   ├── agents/          # 6-Phase 파이프라인
│   │   ├── models/          # Entity/Plan 모델
│   │   └── facade.py        # Public API
│   └── ARCHITECTURE.md
│
├── AnalysisAgent/           # 코드 생성/실행 에이전트
│   ├── src/
│   │   ├── code_gen/        # 코드 생성/검증/실행
│   │   ├── context/         # 분석 컨텍스트
│   │   └── models/          # 입출력 모델
│   └── ARCHITECTURE.md
│
├── OrchestrationAgent/      # 오케스트레이션 레이어
│   ├── src/
│   │   ├── orchestrator.py  # 메인 오케스트레이터
│   │   └── models.py        # Result 모델
│   └── examples/
│
├── shared/                  # 공유 모듈
│   ├── config/              # 설정 관리
│   ├── data/                # DataContext
│   ├── database/            # DB 연결/Repository
│   ├── llm/                 # LLM 클라이언트
│   └── processors/          # 데이터 처리기
│
├── docs/                    # 상세 문서
│   ├── README.md
│   ├── IndexingAgent_ARCHITECTURE.md
│   ├── ExtractionAgent_ARCHITECTURE.md
│   ├── AnalysisAgent_ARCHITECTURE.md
│   └── OrchestrationAgent_ARCHITECTURE.md
│
├── data/                    # 인덱싱된 데이터
└── testdata/                # 테스트용 데이터
```

---

## Supported Data Formats

| 형식 | 확장자 | 설명 |
|------|--------|------|
| Tabular | `.csv`, `.xlsx`, `.parquet` | 정형 테이블 데이터 |
| Signal | `.vital`, `.edf` | 생체신호 시계열 데이터 |

---

## API Reference

### Orchestrator

```python
from OrchestrationAgent.src import Orchestrator

orchestrator = Orchestrator()

# 전체 파이프라인 실행
result = orchestrator.run(query: str) -> OrchestrationResult

# Execution Plan이 있는 경우
result = orchestrator.run_with_plan(query, execution_plan)

# 데이터가 이미 있는 경우 (분석만)
result = orchestrator.run_analysis_only(query, runtime_data)
```

### OrchestrationResult

```python
class OrchestrationResult:
    status: Literal["success", "error", "partial"]
    result: Optional[Any]           # 분석 결과
    generated_code: Optional[str]   # 생성된 Python 코드
    error_message: Optional[str]    # 에러 메시지
    error_stage: Optional[str]      # 실패 단계
    execution_time_ms: float        # 실행 시간
```

---

## Testing

```bash
# End-to-End 테스트
python OrchestrationAgent/test_e2e_hr_mean.py --mode full --max-cases 50

# 개별 에이전트 테스트
python IndexingAgent/test_full_pipeline_results.py
python ExtractionAgent/test_pipeline.py
```

---

## Security

MedicalAIMaster는 안전한 코드 실행을 위해 다음 보안 기능을 제공합니다:

- **Sandbox 실행**: 생성된 코드는 격리된 환경에서 실행
- **금지 패턴 차단**: `eval`, `exec`, `os.system`, `subprocess` 등 위험 함수 차단
- **Import 제한**: 허용된 모듈만 import 가능
- **변수 검증**: 사용 가능한 변수만 참조하도록 정적 분석

---

## Tech Stack

| Category | Technologies |
|----------|-------------|
| **Language** | Python 3.10+ |
| **LLM** | OpenAI GPT-4, Anthropic Claude, Google Gemini |
| **Framework** | LangGraph, LangChain |
| **Database** | PostgreSQL (메타데이터), Neo4j (온톨로지) |
| **Data Processing** | Pandas, NumPy, SciPy |
| **Bio-Signal** | VitalDB, MNE |
| **Validation** | Pydantic v2 |

---

## Documentation

상세 문서는 `docs/` 폴더에서 확인할 수 있습니다:

- [시스템 개요](docs/README.md)
- [IndexingAgent 아키텍처](docs/IndexingAgent_ARCHITECTURE.md)
- [ExtractionAgent 아키텍처](docs/ExtractionAgent_ARCHITECTURE.md)
- [AnalysisAgent 아키텍처](docs/AnalysisAgent_ARCHITECTURE.md)
- [OrchestrationAgent 아키텍처](docs/OrchestrationAgent_ARCHITECTURE.md)

---

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## Acknowledgments

- [LangGraph](https://github.com/langchain-ai/langgraph) - AI 에이전트 워크플로우
- [VitalDB](https://vitaldb.net/) - 생체신호 데이터셋
- [Neo4j](https://neo4j.com/) - 그래프 데이터베이스

---

<p align="center">
  Made with ❤️ for Medical AI Research
</p>
