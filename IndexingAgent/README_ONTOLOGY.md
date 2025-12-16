# Ontology Builder 사용 가이드

**버전:** Phase 0-1 구현 완료  
**작성일:** 2025-12-16

---

## 🎯 구현 완료 사항

### ✅ Phase 0: 기반 구조
- [x] `src/agents/state.py` - OntologyContext, Relationship, EntityHierarchy 추가
- [x] `src/utils/llm_cache.py` - LLM 캐싱 시스템
- [x] `src/utils/ontology_manager.py` - 온톨로지 저장/로드
- [x] `src/agents/nodes.py` - ontology_builder_node 구현
- [x] `src/agents/graph.py` - 워크플로우 연결

---

## 🚀 주요 기능

### 1. **자동 메타데이터 감지**
```python
clinical_parameters.csv  → 자동 감지 → 용어 사전 추가 → 인덱싱 스킵
lab_data.csv            → 일반 데이터 → 분석 계속
```

### 2. **Rule Prepares, LLM Decides 패턴**
```python
# Rule: 데이터 전처리
unique_vals = df[col].unique()[:20]
null_ratio = df[col].isna().sum() / len(df)

# LLM: 판단
llm.ask(f"unique_vals={unique_vals}, null_ratio={null_ratio}, PK인가?")
```

### 3. **Negative Evidence (데이터 품질 체크)**
```python
# 99% unique인데 1% 중복 → 데이터 오류 감지
"uniqueness=0.99 BUT 1% duplicates - possible data error"
```

### 4. **LLM 캐싱 (비용 절감)**
```python
# 동일 파일 재실행 시
첫 실행: LLM 호출 6회 ($0.18)
재실행: 캐시 사용 ($0.00) ✅
```

---

## 📋 사용 방법

### 1. 환경 설정

```bash
# 가상환경 활성화
cd /Users/goeastagent/products/MedicalAIMaster
source venv/bin/activate

# 패키지 설치
cd IndexingAgent
pip install -r requirements.txt

# .env 파일 설정
echo "LLM_PROVIDER=openai" > .env
echo "OPENAI_API_KEY=your-key-here" >> .env
```

### 2. 테스트 실행

```bash
# 모든 CSV 파일 자동 처리
python test_agent_with_interrupt.py
```

**실행 예시:**
```
📁 Found 5 CSV files:
   - clinical_data.csv
   - clinical_parameters.csv
   - lab_data.csv
   - lab_parameters.csv
   - track_names.csv

################################################################################
# File 1/5: clinical_data.csv
################################################################################

📂 [LOADER NODE] 시작 - clinical_data.csv
✅ [LOADER NODE] 완료
   - Processor: tabular
   - Columns: 74개

📚 [ONTOLOGY BUILDER NODE] 시작
🔧 [Rule] 데이터 전처리 중...
   - 파일명 파싱: ['clinical', 'data']
   - Base Name: clinical
   - 컬럼 수: 74개

🧠 [LLM] 메타데이터 여부 판단 중...
   - 판단: 일반 데이터
   - 확신도: 92%
   
📊 [Data] 일반 데이터 파일로 확정

... (분석 계속)
```

---

## 📊 작동 흐름

```
파일 입력
   ↓
[LOADER] 파일 읽기
   ↓
[ONTOLOGY BUILDER] ← 새로 추가!
   ├─ Rule: 파일명 파싱, 통계 계산
   ├─ LLM: 메타데이터 여부 판단
   ├─ (메타데이터) → 용어 추가 → END
   └─ (일반 데이터) → 분석 계속
      ↓
[ANALYZER] 의미 분석
   ↓
[INDEXER] DB 저장
```

---

## 🔍 확인 사항

### 자동 메타데이터 감지 확인

**성공 케이스:**
```bash
# 메타데이터 파일들이 자동으로 스킵되어야 함
✅ clinical_parameters.csv → 메타데이터 감지 → 용어 73개 추가 → 인덱싱 스킵
✅ lab_parameters.csv → 메타데이터 감지 → 용어 33개 추가 → 인덱싱 스킵
✅ track_names.csv → 메타데이터 감지 → 용어 196개 추가 → 인덱싱 스킵
```

**일반 데이터:**
```bash
# 일반 데이터는 분석이 계속되어야 함
✅ clinical_data.csv → 일반 데이터 → 분석 계속 → 인덱싱
✅ lab_data.csv → 일반 데이터 → 분석 계속 → 인덱싱
```

### 캐시 확인

```bash
# 두 번째 실행 시
python test_agent_with_interrupt.py

# 출력에서 확인
✅ [Cache Hit] 캐시 사용 (총 5회 절약)
```

### 온톨로지 저장 확인

```bash
# 온톨로지 파일 생성 확인
ls -lh data/processed/ontology_db.json

# 내용 확인
cat data/processed/ontology_db.json | head -30
```

---

## 🐛 트러블슈팅

### 문제 1: "온톨로지가 저장되지 않음"
**원인:** 디렉토리 권한  
**해결:** `mkdir -p data/processed`

### 문제 2: "캐시가 작동하지 않음"
**원인:** 캐시 디렉토리 없음  
**해결:** `mkdir -p data/cache/llm`

### 문제 3: "메타데이터 파일이 계속 분석됨"
**원인:** LLM confidence < 0.75  
**해결:** Human Review에서 "메타데이터" 입력

### 문제 4: "LLM API 오류"
**원인:** API 키 미설정 또는 잘못됨  
**해결:** `.env` 파일 확인, `OPENAI_API_KEY` 설정

---

## 📈 다음 단계 (Phase 2-3)

Phase 0-1이 잘 작동하면:

- [ ] Phase 2: 관계 추론 (`_infer_relationships_with_llm`)
- [ ] Phase 3: 계층 구조 자동 생성
- [ ] Phase 4: JOIN 쿼리 자동 생성

---

## 📚 관련 문서

- `docs/ontology_builder_implementation_plan.md` - 전체 구현 계획
- `docs/ontology_and_multilevel_anchor_analysis.md` - 문제 분석
- `technical_spec.md` - 프로젝트 전체 스펙

---

**상태:** Phase 0-1 구현 완료 ✅  
**테스트 준비:** 완료  
**다음:** 실제 데이터로 테스트 실행

