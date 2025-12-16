# Phase 2 구현 완료 가이드

**작성일:** 2025-12-17  
**상태:** Phase 2 구현 완료 - 관계 추론 기능 추가

---

## 🎯 Phase 2 목표

**Multi-level Anchor 문제 해결을 위한 관계 추론 구현**

### Before (Phase 0-1)
```
clinical_data → subjectid (Master Anchor)
lab_data → subjectid 없음 → MISSING → Human Review ❌
```

### After (Phase 2)
```
clinical_data → subjectid (Master Anchor)
lab_data → caseid 발견
       → LLM: "caseid는 clinical_data.caseid와 FK 관계"
       → 관계 자동 추론 ✅
       → Multi-level 이해: Patient > Case
```

---

## ✅ 구현 완료 기능

### 1. **공통 컬럼 찾기 (Rule)**
```python
_find_common_columns(current_cols, existing_tables)
→ ["caseid"] ← clinical_data와 lab_data 공통
```

### 2. **파일명 힌트 추출 (Rule + LLM)**
```python
_extract_filename_hints("lab_data.csv")
→ {
    "entity_type": "Laboratory",
    "scope": "measurement",
    "suggested_level": 4,
    "related_file_patterns": ["lab_parameters"]
}
```

### 3. **관계 추론 (LLM)**
```python
_infer_relationships_with_llm(...)
→ {
    "relationships": [{
        "source_table": "lab_data",
        "target_table": "clinical_data",
        "source_column": "caseid",
        "target_column": "caseid",
        "relation_type": "N:1"
    }],
    "hierarchy": [
        {"level": 1, "entity_name": "Patient", "anchor_column": "subjectid"},
        {"level": 2, "entity_name": "Case", "anchor_column": "caseid"}
    ]
}
```

### 4. **온톨로지 확장**
- 컬럼 정보 저장 (file_tags에 columns 추가)
- 관계 자동 병합 (중복 제거)
- 계층 자동 업데이트

---

## 🚀 테스트 방법

### 방법 1: 자동 스크립트 (권장)

```bash
# 실행 권한 부여
chmod +x test_phase2.sh

# 실행
./test_phase2.sh
```

**자동으로 수행:**
1. 캐시 클리어
2. 온톨로지 클리어
3. 테스트 실행
4. 결과 확인
5. 온톨로지 상세 출력

---

### 방법 2: 수동 실행

```bash
# 1. 클리어 (깨끗한 상태)
rm -rf data/cache/llm/*
rm -rf data/processed/ontology_db.json

# 2. 실행
python test_agent_with_interrupt.py

# 3. 결과 확인
python view_ontology.py
```

---

## 📊 예상 결과

### 온톨로지 파일 내용

```json
{
  "definitions": { ... 310개 용어 ... },
  
  "relationships": [  // [NEW] 관계 추가됨!
    {
      "source_table": "lab_data",
      "target_table": "clinical_data",
      "source_column": "caseid",
      "target_column": "caseid",
      "relation_type": "N:1",
      "confidence": 0.92,
      "description": "Lab results belong to a surgical case",
      "llm_inferred": true
    }
  ],
  
  "hierarchy": [  // [NEW] 계층 추가됨!
    {
      "level": 1,
      "entity_name": "Patient",
      "anchor_column": "subjectid",
      "mapping_table": "clinical_data",
      "confidence": 0.9
    },
    {
      "level": 2,
      "entity_name": "Case",
      "anchor_column": "caseid",
      "mapping_table": null,
      "confidence": 0.95
    }
  ],
  
  "file_tags": { ... 5개 파일 + 컬럼 정보 ... }
}
```

---

## 🔍 확인 사항

### 1. **관계 추론 로그**

```
[ONTOLOGY BUILDER] 관계 추론 시작...
   - 기존 데이터 파일: 1개
   - 관계 1개 발견
      • lab_data.caseid → clinical_data.caseid (N:1, conf: 92%)
   - 계층 정보 업데이트
      • L1: Patient (subjectid)
      • L2: Case (caseid)
```

### 2. **Multi-level Anchor 해결**

**Before:**
```
lab_data 처리 시:
→ subjectid 못 찾음
→ MISSING
→ Human Review
```

**After:**
```
lab_data 처리 시:
→ caseid 발견
→ clinical_data.caseid와 FK 관계 인식
→ 자동으로 처리 ✅
→ 계층: Patient > Case 이해
```

### 3. **파일명 힌트 로그**

```
_extract_filename_hints("lab_data.csv")
→ entity_type: "Laboratory"
→ suggested_level: 4
→ related_patterns: ["lab_parameters"]
```

---

## 📈 Phase 2 목표 달성 기준

| 항목 | 목표 | 확인 방법 |
|------|------|----------|
| FK 자동 발견 | lab_data ↔ clinical_data | relationships 배열 확인 |
| 관계 타입 정확도 | N:1 판단 | relation_type 확인 |
| 계층 자동 생성 | Patient > Case | hierarchy 배열 확인 |
| Confidence | >0.85 | 각 관계의 confidence 확인 |
| Multi-level Anchor 이해 | caseid ≠ subjectid 인식 | Human Review 없이 처리 |

---

## 🐛 트러블슈팅

### 문제: "관계가 추론되지 않음"

**원인:**
- 첫 파일 처리 시에는 기존 테이블 없음
- 두 번째 파일부터 관계 추론 시작

**해결:**
- 최소 2개 데이터 파일 필요
- clinical_data (첫 번째) + lab_data (두 번째)

### 문제: "계층이 생성되지 않음"

**원인:**
- LLM이 계층을 추론하지 못함
- Confidence < 0.8

**해결:**
- LLM 프롬프트 확인
- 온톨로지 definitions 활용 (caseid, subjectid 설명 참조)

---

## 🎉 Phase 2 완료 후 달성 효과

### 달성 1: **Multi-level Anchor 자동 인식**
```
clinical_data: caseid(PK), subjectid
lab_data: caseid(FK) → clinical_data

계층:
L1: Patient (subjectid) - 한 환자가 여러 케이스
L2: Case (caseid) - 각 수술 케이스
```

### 달성 2: **자동 JOIN 경로 파악**
```
"환자 5955의 lab 결과"
→ lab_data JOIN clinical_data ON caseid
   WHERE subjectid = 5955
```

### 달성 3: **Human Review 감소**
```
Before: lab_data 처리 시 Human Review 필요
After: 자동으로 관계 파악
```

---

## 📝 다음 단계

### Phase 2 완료 후:
- [ ] Phase 3: 계층 구조 활용 (JOIN 쿼리 자동 생성)
- [ ] Phase 4: Vector Indexing, Semantic Search

### 또는:
- [ ] 현재 기능으로 실제 데이터 분석 시작
- [ ] 온톨로지 기반 데이터 탐색

---

**준비 완료!** 🚀  
**실행:** `./test_phase2.sh` 또는 `python test_agent_with_interrupt.py`

