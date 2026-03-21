# Future Work: Autonomous Data Agent Architecture

## 1. 개요 및 핵심 목표
현재 MedicalAIMaster(VitalAgent)는 대용량 의료 데이터를 안정적으로 처리하기 위한 **"사전 구축(Pre-built) 중심의 파이프라인"**으로 훌륭하게 설계되어 있습니다. 
하지만 궁극적인 지향점인 **"폴더만 지정하면 알아서 파일에 접근하고 파악하여 분석을 진행하는 자율형 데이터 분석가(Autonomous Data Analyst)"**로 진화하기 위해서는 아키텍처의 패러다임 전환이 필요합니다.

이 문서는 현재의 폭포수(Waterfall) 파이프라인 구조를 **"도구 기반의 순환(Loop) 구조"**로 개편하기 위한 심층적인 업그레이드 방향과 로드맵을 정의합니다.

---

## 2. 현재 아키텍처의 한계점 진단

1. **동적 대응 부족**: 파일이 폴더에 새로 추가되었을 때, `IndexingAgent`의 사전 DB 인덱싱이 완료되지 않으면 에이전트가 해당 파일을 인지하거나 분석할 수 없습니다.
2. **시야의 단절 (Blind Coding)**: `ExtractionAgent`와 `AnalysisAgent`가 실제 파일의 원본 데이터를 열어보지 못하고, DB에 요약된 메타데이터에만 의존하여 코드를 생성합니다. 이로 인해 실제 데이터의 결측치(NaN)나 예상치 못한 스키마 변형에 유연하게 대처하지 못하고 런타임 에러가 발생할 확률이 높습니다.
3. **단방향 실행 (One-shot Generation)**: 코드를 한 번에 생성하고 끝내는 방식이므로, 실제 데이터 분석가처럼 데이터를 "탐색(EDA)"하며 점진적으로 인사이트를 도출해 나가는 과정이 불가능합니다.

---

## 3. 추천 아키텍처: 자율 탐색형 데이터 에이전트 (Autonomous Data Agent)

새로운 아키텍처는 다음 3가지 핵심 계층(Layer)으로 구성됩니다.

### 계층 1: 동적 작업 공간 (Dynamic Workspace & File System Tools)
DB에 전적으로 의존하는 대신, 에이전트가 폴더(File System) 자체를 자신의 작업 공간으로 인식하고 직접 탐색할 수 있는 도구를 제공합니다.
* **제공 도구(Tools)**:
  * `list_files(directory_path)`: 폴더 내 파일 목록, 용량, 확장자 확인
  * `peek_file(file_path, n_rows=5)`: 파일의 처음 몇 줄을 읽어 실제 데이터 구조 파악
  * `search_files(keyword)`: 특정 키워드가 포함된 파일명이나 헤더 검색
* **역할 변화**: 기존 `IndexingAgent`는 파이프라인의 필수 선행 단계가 아닌, 대용량 폴더 분석 시 에이전트가 스스로 호출하는 **백그라운드 요약 도구**로 역할이 변경됩니다.

### 계층 2: 상태 유지형 코드 실행기 (Stateful Code Interpreter / REPL)
코드를 한 번에 생성하고 끝내는 것이 아니라, Jupyter Notebook처럼 **상태(메모리, 변수)가 유지되는 환경**에서 에이전트가 코드를 반복 실행하며 데이터를 만져볼 수 있게 합니다.
* **작동 방식**:
  1. 데이터를 로드하는 코드 실행 (`df = pd.read_csv(...)`)
  2. 실행 결과(스키마, 샘플 데이터)를 관찰
  3. 관찰 결과를 바탕으로 전처리 및 분석 코드 작성 및 실행
  4. 에러 발생 시 스스로 원인을 파악하고 코드를 수정하여 재실행 (Self-Correction)

### 계층 3: 오케스트레이터의 ReAct (Reasoning + Acting) 루프 전환
현재의 단방향 `OrchestrationAgent`를 LangGraph의 `AgentExecutor` 패턴 등을 활용하여 **ReAct 프레임워크 기반의 메인 브레인**으로 격상시킵니다.
* 에이전트가 사용자 질의를 받으면 스스로 **[생각 -> 도구 선택 -> 실행 -> 결과 관찰 -> 다시 생각]**의 과정을 정답이 도출될 때까지 무한히 반복합니다.

---

## 4. 실제 작동 시나리오 예시

**사용자 질의:** *"data 폴더에 있는 파일들을 보고, 수술 중 심박수가 가장 불안정했던 환자를 찾아서 이유를 분석해줘."*

1. **탐색 (Discovery)**: `list_files("data/")` 도구를 호출하여 `.vital` 파일들과 `clinical_info.csv`를 발견.
2. **스키마 파악 (Peeking)**: `execute_python_code` 도구를 통해 첫 번째 `.vital` 파일의 트랙 목록을 출력하여 데이터 구조 확인.
3. **반복 분석 (Iterative Analysis)**: 
   * 모든 환자의 심박수 분산을 계산하는 코드를 작성 및 실행.
   * 특정 파일에서 데이터 누락으로 에러 발생 시, 스스로 예외 처리 코드를 추가하여 재실행.
4. **교차 분석 (Cross-referencing)**: 도출된 환자 ID를 바탕으로 `clinical_info.csv`를 조회하여 임상적 원인(예: 과다 출혈) 파악.
5. **최종 답변 생성**: 분석 결과, 근거 데이터, 사용된 코드를 종합하여 사용자에게 최종 리포트 제공.

---

## 5. 단계별 업그레이드 로드맵

### Phase 1 (단기): AnalysisAgent에 REPL 도입
* `AnalysisAgent`가 코드를 한 번만 생성하는 대신, 파이썬 REPL(예: `jupyter_client` 또는 내장 `exec` 환경)을 통해 코드를 실행하고, 그 결과를 다시 LLM이 읽어들여 코드를 수정할 수 있는 **반복 루프(Loop)** 구현.

### Phase 2 (중기): ExtractionAgent의 Tool 변환 및 파일 시스템 도구 추가
* `ExtractionAgent`를 필수 파이프라인 단계에서 메인 에이전트가 필요할 때 호출하는 `search_database_tool`로 변경.
* 메인 에이전트에게 `list_directory_tool`, `read_file_header_tool` 등 파일 시스템 직접 접근 도구 제공.

### Phase 3 (장기): LangGraph 기반의 완전 자율 에이전트 구축
* 메인 `OrchestrationAgent`를 LangGraph의 순환 그래프(Cyclic Graph)로 재설계.
* 에이전트가 스스로 목표를 설정하고, 도구를 선택하며, 에러를 수정해 나가는 완전한 자율형(Autonomous) 에이전트 완성.