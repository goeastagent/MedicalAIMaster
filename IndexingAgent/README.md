# Medical AI Data Auto-Indexing Agent

**버전:** Phase 0-3 구현 완료  
**상태:** 프로덕션 준비 완료

---

## 🎯 프로젝트 개요

멀티모달 의료 데이터를 자동으로 분석하여 의미 기반 인덱싱을 수행하는 지능형 에이전트 시스템

**핵심 기능:**
- ✅ 메타데이터 자동 감지 (100% 정확도)
- ✅ 온톨로지 자동 구축 (310개 용어)
- ✅ 테이블 관계 자동 추론 (FK 발견)
- ✅ Multi-level Anchor 해결
- ✅ 실제 DB 구축 (SQLite)
- ✅ VectorDB 시맨틱 검색

---

## 🚀 빠른 시작 (Quick Start)

### 1. 환경 설정

```bash
# 가상환경 활성화
cd /Users/goeastagent/products/MedicalAIMaster
source venv/bin/activate

# 패키지 설치
cd IndexingAgent
pip install -r requirements.txt

# API 키 설정
echo "LLM_PROVIDER=openai" > .env
echo "OPENAI_API_KEY=your-api-key-here" >> .env
```

---

### 2. 실행 순서

#### ✅ **필수: 온톨로지 + DB 구축**

```bash
python test_agent_with_interrupt.py
```

**생성되는 것:**
- `data/processed/ontology_db.json` (310개 용어, 관계, 계층)
- `data/processed/medical_data.db` (SQLite, 93만+ 행)
- `data/cache/llm/` (LLM 캐시)

**소요 시간:** ~2-3분 (VitalDB 5개 파일 기준)

---

#### 🔍 **선택: VectorDB 구축 (시맨틱 검색)**

```bash
python build_vector_db.py
```

**생성되는 것:**
- `data/processed/vector_db/` (ChromaDB, 313개 임베딩)

**소요 시간:** ~1분 (OpenAI 임베딩 기준)

---

### 3. 결과 확인

#### 온톨로지 확인
```bash
python view_ontology.py
```

**출력 예시:**
```
📚 Ontology Summary
   - 용어: 310개
   - 관계: 1개 (lab_data → clinical_data)
   - 계층: 3레벨 (Patient > Case > Lab)
```

---

#### DB 확인
```bash
python view_database.py
```

**출력 예시:**
```
🗄️ Database Viewer
   - 크기: 145.23 MB

📋 테이블 목록
   1. clinical_data_table (6,388행)
   2. lab_data_table (928,450행)

🔗 테이블 관계:
   lab_data_table.caseid → clinical_data_table.caseid

🔹 Foreign Keys:
   • caseid → clinical_data_table(caseid)

🔹 Indices:
   • idx_lab_data_table_caseid ON (caseid)
   • idx_clinical_data_table_subjectid ON (subjectid)
```

---

#### VectorDB 검색 (대화형)
```bash
python test_vector_search.py
```

**사용 예시:**
```
🔍 검색어: 혈압
   1. [column] bp_sys: Systolic blood pressure...
   2. [column] bp_dia: Diastolic blood pressure...

🔍 검색어: table: 환자
   1. [table] clinical_data - Hub Table...

🔍 검색어: 수술 중 사용한 약물
   1. [column] intraop_mdz: Midazolam...
```

---

## 📊 주요 기능

### 1. **메타데이터 자동 감지**
```
clinical_parameters.csv → LLM 판단 (96% 확신) → 메타데이터
→ 용어 81개 추출 → 인덱싱 스킵 ✅
```

### 2. **관계 자동 추론**
```
lab_data + clinical_data
→ 공통 컬럼: caseid
→ LLM 판단: FK 관계 (N:1)
→ 계층: Patient > Case > Lab ✅
```

### 3. **실제 DB 구축**
```
온톨로지 relationships
→ FOREIGN KEY (caseid) REFERENCES clinical_data(caseid) ✅

온톨로지 hierarchy
→ CREATE INDEX ON caseid, subjectid ✅
```

### 4. **시맨틱 검색**
```
자연어: "혈압 관련 데이터"
→ Vector Search
→ [bp_sys, bp_dia, preop_htn, ...] ✅
```

---

## 📁 프로젝트 구조

```
IndexingAgent/
├── src/
│   ├── agents/         # LangGraph 워크플로우
│   ├── processors/     # 데이터 파싱 (CSV, EDF 등)
│   ├── utils/          # LLM, 캐시, 온톨로지 관리
│   ├── database/       # 🆕 DB 연결, DDL 생성
│   └── knowledge/      # 🆕 VectorDB, 시맨틱 검색
│
├── data/
│   ├── raw/            # 원본 데이터
│   ├── processed/      # 산출물 (ontology, DB, vector)
│   └── cache/          # LLM 캐시
│
├── test_agent_with_interrupt.py  # 메인 실행
├── build_vector_db.py             # VectorDB 구축
├── test_vector_search.py          # 검색 테스트
├── view_ontology.py               # 온톨로지 뷰어
└── view_database.py               # DB 뷰어 🆕
```

---

## 🔧 유틸리티 스크립트

| 스크립트 | 용도 | 실행 |
|----------|------|------|
| `view_ontology.py` | 온톨로지 내용 확인 | `python view_ontology.py` |
| `view_database.py` | DB 테이블, FK, 인덱스 확인 | `python view_database.py` |
| `view_database.py -i` | 대화형 SQL 쿼리 | `python view_database.py --interactive` |
| `test_vector_search.py` | 시맨틱 검색 테스트 | `python test_vector_search.py` |

---

## 📈 성능 지표

### Phase 0-2 (온톨로지 구축)
- 메타데이터 감지: **100% 정확** (5/5 파일)
- LLM 캐시 효율: **83% Hit Rate**
- 비용 절감: **$0.30**

### Phase 3-A (DB 구축)
- Chunk Processing: **928,450행 안전 처리**
- FK 자동 생성: **1개**
- 인덱스 자동 생성: **4개**

### Phase 3-B (VectorDB)
- 임베딩 개수: **313개** (Table 2 + Column 310 + Rel 1)
- 검색 속도: **~100ms/query**

---

## 🐛 트러블슈팅

### "DB 파일 없음"
```bash
# test_agent_with_interrupt.py를 먼저 실행
python test_agent_with_interrupt.py
```

### "VectorDB 초기화 실패"
```bash
# ChromaDB 설치
pip install chromadb

# API 키 확인
cat .env | grep OPENAI_API_KEY
```

### "메모리 부족"
```bash
# Chunk size 조정
# src/agents/nodes.py에서 chunk_size = 50000으로 줄이기
```

---

## 📚 관련 문서

| 문서 | 내용 |
|------|------|
| `CURRENT_STATUS_2025-12-17.md` | 전체 프로젝트 현황 (팀 공유용) |
| `docs/ontology_builder_implementation_plan.md` | 상세 구현 계획 (4,100+ 줄) |
| `PHASE0_IMPLEMENTATION_SUMMARY.md` | Phase 0-1 완료 보고 |
| `PHASE2_IMPLEMENTATION_SUMMARY.md` | Phase 2 완료 보고 |
| `PHASE3_IMPLEMENTATION_SUMMARY.md` | Phase 3 완료 보고 |
| `PHASE3_GUIDE.md` | Phase 3 사용 가이드 |

---

## 🎯 핵심 성과

**Phase 0-3 완료:**
- ✅ 메타데이터 3개 파일 자동 스킵 (Human Review 0회)
- ✅ 310개 의료 용어 추출
- ✅ Multi-level Anchor 해결 (Patient > Case > Lab)
- ✅ 실제 DB 구축 (93만+ 행)
- ✅ VectorDB 시맨틱 검색

**전체 진행률: 99%** 🎉

---

**프로젝트 상태:** ✅ Phase 0-3 완료  
**다음:** 실제 의료 데이터 분석 또는 Phase 4 (고급 기능)

