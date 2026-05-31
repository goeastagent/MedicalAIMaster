# MedicalAIMaster 문서

> 멀티모달 의료 데이터 분석을 위한 AI 에이전트 시스템

## 📖 프로젝트 개요

MedicalAIMaster는 **자연어 질의**로 의료 데이터를 분석할 수 있는 AI 에이전트 시스템입니다.

```
사용자: "2023년 위암 환자의 심박수 평균을 성별로 비교해줘"
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                    MedicalAIMaster                               │
│                                                                  │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐ │
│  │IndexingAgent │   │Extraction    │   │Analysis              │ │
│  │ (데이터 인덱싱)│→│ Agent        │→│ Agent                │ │
│  │              │   │ (쿼리 해석)  │   │ (코드 생성/실행)     │ │
│  └──────────────┘   └──────────────┘   └──────────────────────┘ │
│         │                   │                    │              │
│         └───────────────────┴────────────────────┘              │
│                             │                                    │
│                    ┌────────────────┐                           │
│                    │Orchestration   │                           │
│                    │Agent (조율)    │                           │
│                    └────────────────┘                           │
└─────────────────────────────────────────────────────────────────┘
                    │
                    ▼
결과: {"male": 75.2, "female": 72.8}
```

---

## 🏗️ 시스템 아키텍처

### 4개의 에이전트

| 에이전트 | 역할 | 문서 |
|---------|------|------|
| **IndexingAgent** | 데이터 파일을 분석하여 PostgreSQL/Neo4j에 인덱싱 | [→ 아키텍처](IndexingAgent_ARCHITECTURE.md) |
| **ExtractionAgent** | 자연어 쿼리를 Execution Plan으로 변환 | [→ 아키텍처](ExtractionAgent_ARCHITECTURE.md) |
| **AnalysisAgent** | LLM 기반 코드 생성/실행으로 데이터 분석 | [→ 아키텍처](AnalysisAgent_ARCHITECTURE.md) |
| **OrchestrationAgent** | 위 에이전트들을 조율하는 경량 레이어 | [→ 아키텍처](OrchestrationAgent_ARCHITECTURE.md) |

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
   │ (쿼리 이해/매핑)  │     │ (어떤 데이터, 어디서) │
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
                            │ (코드 생성 → 실행)    │
                            └──────────┬────────────┘
                                       │
                                       ▼
                            ┌───────────────────────┐
                            │ 분석 결과             │
                            └───────────────────────┘
```

---

## 🚀 빠른 시작

### 1. 서비스 시작

```bash
# PostgreSQL + Neo4j 실행
cd IndexingAgent
./run_postgres_neo4j.sh
```

### 2. 데이터 인덱싱 (최초 1회)

```bash
python test_full_pipeline_results.py
```

### 3. 분석 실행

```python
from OrchestrationAgent.src import Orchestrator

orchestrator = Orchestrator()
result = orchestrator.run("위암 환자의 심박수 평균을 구해줘")

if result.status == "success":
    print("결과:", result.result)
    print("생성된 코드:", result.generated_code)
```

---

## 📁 프로젝트 구조

```
MedicalAIMaster/
├── IndexingAgent/          # 데이터 인덱싱 에이전트
├── ExtractionAgent/        # 쿼리 해석 에이전트
├── AnalysisAgent/          # 코드 생성/실행 에이전트
├── OrchestrationAgent/     # 오케스트레이션 레이어
├── shared/                 # 공유 모듈
│   ├── data/              # DataContext
│   ├── database/          # DB 연결
│   ├── llm/               # LLM 클라이언트
│   └── processors/        # 데이터 처리기
├── docs/                   # 문서 (이 폴더)
└── venv/                   # Python 가상환경
```

---

## 🔗 문서 목록

### 아키텍처 문서
- [IndexingAgent 아키텍처](IndexingAgent_ARCHITECTURE.md)
- [ExtractionAgent 아키텍처](ExtractionAgent_ARCHITECTURE.md)
- [AnalysisAgent 아키텍처](AnalysisAgent_ARCHITECTURE.md)
- [OrchestrationAgent 아키텍처](OrchestrationAgent_ARCHITECTURE.md)
- [논문 작성 전략](PAPER_STRATEGY.md)
- [Hybrid Privacy Architecture 전략](HYBRID_PRIVACY_ARCHITECTURE.md)

### 각 에이전트의 상세 문서
각 에이전트 폴더 내의 `ARCHITECTURE.md`에서 더 상세한 내용을 확인할 수 있습니다:
- `IndexingAgent/ARCHITECTURE.md` - 전체 워크플로우, DB 스키마, 노드 상세
- `ExtractionAgent/ARCHITECTURE.md` - 6-Phase 파이프라인, Entity 스키마
- `OrchestrationAgent/ARCHITECTURE.md` - API 명세, 사용 예시

---

## ⚙️ 환경 설정

### 필수 환경 변수

```bash
# .env
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...  # (선택)

# Database
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

### Python 의존성

```bash
cd MedicalAIMaster
python -m venv venv
source venv/bin/activate
pip install -r IndexingAgent/requirements.txt
pip install -r ExtractionAgent/requirements.txt
pip install -r AnalysisAgent/requirements.txt
pip install -r OrchestrationAgent/requirements.txt
```

---

## 🧪 테스트

```bash
# End-to-End 테스트
python OrchestrationAgent/test_e2e_hr_mean.py --mode full --max-cases 50

# 개별 에이전트 테스트
python IndexingAgent/test_full_pipeline_results.py
python ExtractionAgent/test_pipeline.py
```

---

## 📊 지원 데이터 형식

| 형식 | 파일 확장자 | 설명 |
|------|------------|------|
| Tabular | `.csv`, `.xlsx`, `.parquet` | 정형 데이터 |
| Signal | `.vital`, `.edf` | 생체신호 데이터 |

---

## 🔒 보안

- **Sandbox 실행**: 코드는 격리된 환경에서 실행
- **금지 패턴**: `eval`, `exec`, `os.system`, 파일 I/O 등 차단
- **변수 검증**: 사용 가능한 변수만 참조 가능

---

## 📝 라이선스

Private - Internal Use Only
