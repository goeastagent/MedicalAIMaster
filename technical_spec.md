# Medical AI Data Auto-Indexing Agent Specification

## 1. 개요 (Overview)
본 프로젝트는 멀티모달(Multi-modal) 의료 데이터를 자동으로 분석하여 **의미 기반 인덱싱(Semantic Indexing)**을 수행하는 지능형 에이전트 시스템입니다.  
단순한 파일 저장을 넘어, LLM을 활용해 데이터의 **문맥(Context)**을 파악하고, 불확실한 경우 **연구자에게 질의(Human-in-the-loop)**하여 고품질의 데이터 카탈로그와 DB 스키마를 동적으로 생성합니다.

## 2. 핵심 목표 (Core Objectives)
1.  **Automated Reasoning:** 컬럼명이나 메타데이터가 불친절해도 데이터 내용(Sample)을 보고 의미를 추론.
2.  **Ambiguity Resolution:** 환자 식별자(Anchor) 등 핵심 정보가 모호할 때 사람에게 물어보고 학습.
3.  **Dynamic Structuring:** 정형(CSV), 생체신호(EDF/WFDB) 등 다양한 포맷을 통일된 DB 스키마로 변환.
4.  **Extensibility:** 영상(DICOM), 유전체(VCF) 등으로 확장이 용이한 플러그인 아키텍처.

## 3. 시스템 아키텍처 (Architecture)

### 3.1 디렉토리 구조 (Directory Structure)
```text
src/
├── agents/             # [Brain] LangGraph 기반 워크플로우 제어
│   ├── graph.py        # 노드 연결 및 상태 머신 정의
│   ├── nodes.py        # 각 단계별 실행 로직 (Load -> Analyze -> Index)
│   └── state.py        # 에이전트 상태(State) 및 데이터 규약 정의
│
├── processors/         # [Sensors] 데이터 모달리티별 처리기 (Interface 기반)
│   ├── base.py         # 공통 규약 (LLM 문맥 생성 로직 포함)
│   ├── tabular.py      # 정형/시계열 데이터 처리 (CSV, Parquet)
│   └── signal.py       # 생체신호 데이터 처리 (EDF, WFDB)
│
├── utils/              # [Tools] 공통 유틸리티
│   └── llm_client.py   # LLM Factory (OpenAI, Claude, Gemini 지원)
│
└── config.py           # 환경 설정 관리