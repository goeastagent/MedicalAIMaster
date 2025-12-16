# Phase 3 사용 가이드

**작성일:** 2025-12-17  
**최종 업데이트:** 2025-12-17  
**상태:** Phase 3 (PostgreSQL + VectorDB) 구현 완료

---

## 🎯 Phase 3 목표 달성

### Part A: PostgreSQL DB 구축 ✅
- PostgreSQL 데이터베이스 생성
- FK 제약조건 자동 생성
- 인덱스 자동 생성 (Level 1-2)
- **Chunk Processing** (대용량 안전 처리)

### Part B: VectorDB 구축 ✅
- ChromaDB 기반 시맨틱 검색
- **계층적 임베딩** (Table + Column + Relationship)
- **임베딩 모델 설정 통합** (config.py)
- Hybrid Search 지원
- Context Assembly

---

## 📁 새로 추가된 파일

### 모듈
```
src/
├── database/              # 🆕 Part A (PostgreSQL 전용)
│   ├── __init__.py
│   ├── connection.py      # DB 연결 관리 (psycopg2 + SQLAlchemy)
│   └── schema_generator.py  # DDL 생성 (FK, 인덱스)
│
├── knowledge/             # 🆕 Part B
│   ├── __init__.py
│   └── vector_store.py    # VectorDB 관리 (ChromaDB)
│
└── config.py              # 🆕 LLM + Embedding 설정 통합
```

### 스크립트
```
IndexingAgent/
├── build_vector_db.py         # 🆕 VectorDB 구축
├── test_vector_search.py      # 🆕 대화형 검색
├── view_database.py           # 🆕 PostgreSQL DB 조회
└── run_with_postgres.sh       # 🆕 PostgreSQL 서버 관리
```

### 수정된 파일
```
src/agents/nodes.py
├── index_data_node()           # PostgreSQL + Chunk Processing
└── _check_indirect_link_via_ontology()  # 간접 연결 로직
```

---

## 🚀 사용 방법

### 전체 프로세스 (처음부터)

```bash
cd /Users/goeastagent/products/MedicalAIMaster/IndexingAgent

# 0. PostgreSQL 서버 시작 (별도 터미널)
./run_with_postgres.sh
# → Ctrl-C로 종료 (자동으로 서버도 종료됨)

# 1. 온톨로지 구축 + DB 저장 (Phase 0-3)
python test_agent_with_interrupt.py
# → data/processed/ontology_db.json 생성
# → PostgreSQL에 테이블 생성

# 2. VectorDB 구축 (Phase 3-B)
python build_vector_db.py
# → data/processed/vector_db/ 생성

# 3. 시맨틱 검색 테스트
python test_vector_search.py
```

---

## 📊 Part A: PostgreSQL DB 구축

### 1. PostgreSQL 서버 시작

```bash
./run_with_postgres.sh
```

**출력:**
```
================================================================================
🐘 PostgreSQL 서버 시작
================================================================================
📂 데이터 디렉토리: /Users/.../data/postgres_data
⏳ 서버 시작 중...
✅ PostgreSQL 서버가 실행 중입니다 (PID: 12345)

📋 연결 정보:
   Host: localhost
   Port: 5432
   Database: medical_data
   User: postgres

🔧 유용한 명령어:
   psql -h localhost -U postgres -d medical_data
   \dt                # 테이블 목록
   \d table_name      # 테이블 스키마

⚠️  서버를 종료하려면 Ctrl+C를 누르세요
================================================================================
```

### 2. 온톨로지 + DB 구축

```bash
# 다른 터미널에서
python test_agent_with_interrupt.py
```

**자동으로 수행됨:**
1. 온톨로지 로드 (357개 용어, 4개 관계)
2. 각 데이터 파일 처리
3. **PostgreSQL에 실제 저장** (Chunk Processing 포함)

---

### 3. 결과 확인

```bash
# 1. view_database.py로 확인 (권장)
python view_database.py

# 2. psql로 직접 확인
psql -h localhost -U postgres -d medical_data

# 테이블 목록
\dt

# 예상 출력:
#              List of relations
#  Schema |       Name        | Type  |  Owner   
# --------+-------------------+-------+----------
#  public | clinical_data_table | table | postgres
#  public | lab_data_table      | table | postgres

# 행 개수 확인
SELECT COUNT(*) FROM clinical_data_table;
# → 6,388

SELECT COUNT(*) FROM lab_data_table;
# → 928,450

# 테이블 스키마 확인
\d clinical_data_table

# 인덱스 확인
\di
```

---

### 4. 대용량 처리 확인

**lab_data.csv (928,450행, ~145MB):**

```
실행 로그:
📥 [Data] 데이터 적재 중...
   - 파일 크기: 145.2MB
   - 대용량 파일 - Chunk Processing 적용
      • Chunk 1: 100,000행 적재 (누적: 100,000행)
      • Chunk 2: 100,000행 적재 (누적: 200,000행)
      • Chunk 3: 100,000행 적재 (누적: 300,000행)
      ...
      • Chunk 10: 28,450행 적재 (누적: 928,450행)

✅ [Verify] 검증 중...
   - 행 개수 일치: 928,450행 ✅
```

✅ **메모리 초과 없이 안전하게 처리됨!**

---

## 📚 Part B: VectorDB 구축

### 실행

```bash
python build_vector_db.py
```

**인터랙티브 프로세스:**
```
================================================================================
🚀 VectorDB 구축 시작
================================================================================

📚 [Step 1] 온톨로지 로드 중...
✅ 온톨로지 로드 완료
   - 용어: 357개
   - 관계: 4개
   - 계층: 7개

🔧 [Step 2] VectorDB 초기화 중...

📋 [Config] 현재 설정:
   - Provider: openai
   - OpenAI Model: text-embedding-3-large
   - Local Model: all-MiniLM-L6-v2

임베딩 모델 선택:
  1. OpenAI (text-embedding-3-large)
  2. Local (all-MiniLM-L6-v2)
  Enter. Config 기본값 사용 (openai)

선택 (1, 2, Enter): 1  ← 사용자 입력

✅ OpenAI 모델 사용 (text-embedding-3-large)
✅ VectorDB 초기화 완료
   - 임베딩 Provider: openai
   - 모델: text-embedding-3-large

📝 [Step 3] 임베딩 생성 중...
   - Table Summary 임베딩...
      • 2개 테이블
   - Column Definition 임베딩...
      • 310개 컬럼
   - Relationship 임베딩...
      • 1개 관계

💾 [VectorDB] 임베딩 저장 중...
✅ VectorDB 구축 완료: 313개 임베딩
   - Table: 2개
   - Column: 310개
   - Relationship: 1개

💡 [확장성] 향후 최적화 가능:
   - 임베딩 모델 교체 (OpenAI → Local)
   - Re-ranking 추가
   - Hybrid Search 고도화

🧪 [테스트] 시맨틱 검색 테스트...

📍 Query: '혈압 관련 데이터' (filter: all)
   1. [column_definition] Column: preop_htn...
   2. [column_definition] Column: Solar8000/NIBP_DBP...
   3. [column_definition] Column: Solar8000/ART_DBP...

✅ 모든 작업 완료!
```

---

### 대화형 검색 테스트

```bash
python test_vector_search.py
```

**사용 예시:**
```
🔍 검색어: 혈압
   1. [column] preop_htn: Preoperative hypertension...
   2. [column] Solar8000/NIBP_DBP: Non-invasive diastolic...
   3. [column] Solar8000/ART_DBP: Diastolic arterial pressure...

🔍 검색어: table:환자
   1. [table] clinical_data - Hub Table, Level 2...

🔍 검색어: rel:lab
   1. [relationship] lab_data.caseid → clinical_data.caseid (N:1)

🔍 검색어: 수술 중 사용한 약물
   1. [column] intraop_mdz: Midazolam | Unit=mg
   2. [column] intraop_ftn: Fentanyl | Unit=mcg
   3. [column] intraop_rocu: Rocuronium | Unit=mg

🔧 Context Assembly 실행? (y/n): y

📦 Assembled Context:
   - Primary Results: 3개
   - Related Tables: ['clinical_data']
   - JOIN Paths: []

💡 이 컨텍스트를 LLM에게 전달하여 SQL 생성 가능
```

---

## 🔍 검증 체크리스트

### Part A: PostgreSQL DB

- [ ] PostgreSQL 서버 실행 중 (`./run_with_postgres.sh`)
- [ ] 테이블 2개 생성 (clinical_data_table, lab_data_table)
- [ ] clinical_data: 6,388행 확인
- [ ] lab_data: 928,450행 확인
- [ ] Chunk Processing 로그 확인 (10개 chunk)
- [ ] 인덱스 확인 (caseid, subjectid)

### Part B: VectorDB

- [ ] `vector_db/` 디렉토리 생성됨
- [ ] 313개 임베딩 생성 (Table 2 + Column 310 + Rel 1)
- [ ] Table-level 검색 작동 ("환자 정보 테이블")
- [ ] Column-level 검색 작동 ("혈압")
- [ ] Relationship 검색 작동 ("lab 연결")
- [ ] Context Assembly 작동

---

## 💡 핵심 기능

### 1. **Chunk Processing (대용량 안전)**
```
lab_data (145MB, 928K행)
→ 10만 행씩 10개 Chunk로 분할
→ 메모리 사용량 일정 유지
→ 안전하게 적재 ✅
```

### 2. **FK 자동 생성 (온톨로지 활용)**
```python
relationships: [
  {source: "lab_data", target: "clinical_data", column: "caseid"}
]

→ FOREIGN KEY (caseid) REFERENCES clinical_data_table(caseid)
```

### 3. **인덱스 자동 생성 (성능 최적화)**
```python
hierarchy: [
  {level: 1, anchor: "subjectid"},
  {level: 2, anchor: "caseid"}
]

→ CREATE INDEX idx_..._caseid
→ CREATE INDEX idx_..._subjectid
```

### 4. **임베딩 설정 통합 (config.py)**
```python
class EmbeddingConfig:
    PROVIDER = "openai"
    OPENAI_MODEL = "text-embedding-3-large"  # 최고 성능
    LOCAL_MODEL = "all-MiniLM-L6-v2"         # 무료 대안
```

### 5. **계층적 임베딩 (검색 품질)**
```
Table (2개): "clinical_data는 Hub Table..."
Column (310개): "alb: Albumin | Chemistry..."
Relationship (1개): "lab_data → clinical_data..."

→ 313개 임베딩으로 다양한 질문 대응
```

---

## 🐛 트러블슈팅

### 문제: "PostgreSQL 연결 실패"
```bash
# PostgreSQL 서버 실행 확인
./run_with_postgres.sh

# 또는 Homebrew로 설치된 경우
brew services start postgresql@14
```

### 문제: "ChromaDB 설치 안 됨"
```bash
pip install chromadb
```

### 문제: "OpenAI API 키 없음"
```bash
# .env 파일에 추가
echo "OPENAI_API_KEY=sk-your-key" >> .env
```

### 문제: "메모리 부족"
```python
# nodes.py 수정
chunk_size = 50000  # 10만 → 5만으로 줄이기
```

### 문제: "임베딩 생성 느림"
```bash
# Local 모델 사용
python build_vector_db.py
# → 2 선택 (Local)
```

---

## 📈 성능 정보

### DB 구축
| 테이블 | 행 수 | 소요 시간 |
|--------|-------|-----------|
| clinical_data | 6,388 | ~1초 |
| lab_data | 928,450 | ~30초 (Chunk) |
| **총계** | 934,838 | **~2분** |

### VectorDB 구축
| 모델 | 소요 시간 | 비용 |
|------|-----------|------|
| OpenAI (text-embedding-3-large) | ~1분 | ~$0.05 |
| Local (all-MiniLM-L6-v2) | ~3분 | 무료 |

### 검색 속도
| 모델 | 쿼리당 지연 |
|------|-------------|
| OpenAI | ~100ms |
| Local | ~50ms |

---

## 🎉 Phase 3 완료 후 달성

### 1. PostgreSQL 데이터베이스
```sql
-- 928,450개 lab 결과 쿼리 가능
SELECT * FROM lab_data_table 
WHERE caseid = 1;

-- FK로 JOIN 가능
SELECT l.*, c.subjectid
FROM lab_data_table l
JOIN clinical_data_table c ON l.caseid = c.caseid
WHERE c.subjectid = 5955;
```

### 2. 시맨틱 검색
```python
# 자연어로 데이터 탐색
search("수술 중 사용한 약물")
→ [intraop_mdz, intraop_ftn, intraop_rocu]

search("환자 식별하는 컬럼")
→ [subjectid, caseid]
```

### 3. Hybrid 시스템
- **PostgreSQL**: 정확한 쿼리, JOIN
- **VectorDB**: 자연어 탐색, 의미 검색
- 두 시스템 조합 → 강력한 데이터 탐색

---

## 🔜 다음 단계 (선택)

### Phase 4: 고급 기능
- Schema Merge (컬럼 추가/삭제 감지)
- Re-ranking (검색 후 LLM 재정렬)
- Text-to-SQL (LangChain SQL Agent 통합)
- 다중 데이터셋 지원

### 또는: 현재 기능 활용
- 실제 의료 데이터 분석
- 온톨로지 기반 데이터 탐색
- 자연어 쿼리 인터페이스 구축

---

**상태:** Phase 3 구현 완료 ✅  
**다음:** 실제 데이터 분석 또는 Phase 4 진행
