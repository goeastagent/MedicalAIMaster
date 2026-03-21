# Embedding 기반 파라미터 검색 개선안

> **Status:** 설계 완료 / 구현 대기  
> **대상 모듈:** `ExtractionAgent/src/agents/nodes/parameter_resolver/node.py`  
> **관련 평가:** Level 1 Evaluation (`Evaluation/Level1/test_level1_dataset.py`)

---

## 1. 현재 문제점

### 1.1 현재 구조: ILIKE 키워드 검색

ParameterResolverNode는 다음과 같은 **3단계 간접 매칭** 파이프라인으로 동작한다:

```
사용자 쿼리
  → [QueryUnderstanding] LLM이 candidates 키워드 생성
    → [ParameterResolver] ILIKE '%keyword%' DB 검색
      → [LLM Resolution] 후보 중 최종 선택
```

`_search_parameters` 메서드의 핵심 SQL:

```sql
SELECT DISTINCT ON (param_key)
       param_id, param_key, semantic_name, unit, concept_category
FROM parameter
WHERE (param_key ILIKE '%keyword1%' OR semantic_name ILIKE '%keyword1%')
   OR (param_key ILIKE '%keyword2%' OR semantic_name ILIKE '%keyword2%')
   AND concept_category IN ('Medication')  -- Option B 카테고리 필터
ORDER BY param_key
LIMIT {search_limit}
```

### 1.2 ILIKE 검색의 한계

ILIKE는 **문자열 부분 일치**만 수행하므로 다음 경우에 실패한다:

| 실패 유형 | 쿼리 표현 | DB semantic_name | ILIKE 결과 | 원인 |
|---|---|---|---|---|
| **구두점 불일치** | `effect site concentration` | `Effect-site Concentration` | **0건** | 하이픈(`-`) 유무 차이 |
| **동의어 불일치** | `amount of propofol` | `Propofol (20 mg/mL) Infused Volume` | **0건** | `amount` ≠ `volume` |
| **축약어 불일치** | `blood pressure` | `SBP (Systolic Blood Pressure)` | **0건** | param_key `Solar8000/NIBP_SBP`에 blood pressure 없음 |
| **임상 개념 불일치** | `consciousness level` | `BIS (Bispectral Index)` | **0건** | 완전히 다른 용어 |

### 1.3 Level 1 평가에서 확인된 실제 실패 케이스

| Case ID | 쿼리 | 정답 param_key | VitalAgent 결과 | 원인 분석 |
|---|---|---|---|---|
| **L1-013** | "propofol effect-site concentration during anesthesia maintenance" | `Orchestra/PPF20_CE` | 빈 결과 또는 오매칭 | candidates에서 `effect-site` → `effect site`로 변환 시 DB 매칭 실패 |
| **L1-079** | "When BIS drops below 40... propofol concentration" | `Orchestra/PPF20_CE` | `Orchestra/PPF20_RATE` 등 | `propofol`로만 매칭 → 6개 후보 중 LLM이 잘못 선택 |
| **L1-094** | "When awareness levels drop too low... amount of propofol" | `Orchestra/PPF20_CE` | 오매칭 | `amount`가 `Volume`과 연결되지 않음 |

DB 검증 결과:

```
Search "propofol"                → 6건 (PPF20_CE, PPF20_CP, PPF20_CT, PPF20_RATE, PPF20_VOL, intraop_ppf)
Search "effect-site"             → 3건 (PPF20_CE, RFTN20_CE, RFTN50_CE)
Search "effect site concentration" → 0건 ← 하이픈 없으면 실패
```

### 1.4 비교: Claude Baseline은 왜 성공하는가

Claude는 **파라미터 리스트 전체**를 프롬프트로 받아 **1단계 직접 매칭**을 수행한다:

```
사용자 쿼리 + 전체 파라미터 리스트 → LLM이 직접 매칭
```

| 항목 | VitalAgent (현재) | Claude Baseline |
|---|---|---|
| 매칭 방식 | 3단계 간접 (키워드→DB→LLM) | 1단계 직접 (쿼리+리스트→LLM) |
| 정보 손실 | 각 단계에서 발생 가능 | 없음 (전체 정보 한번에 제공) |
| 하이픈/동의어 | ILIKE 실패 | LLM이 의미적으로 해석 |
| Level 1 F1 | 0.80~0.85 | 0.93~0.95 |

---

## 2. 해결 방안: Embedding 기반 의미 검색

### 2.1 핵심 아이디어

ILIKE의 **문자열 일치** 대신, **벡터 유사도**로 검색하여 의미적으로 유사한 파라미터를 찾는다:

```
"propofol effect site concentration"
  → embedding → [0.12, -0.34, 0.56, ...]

"Propofol (20 mg/mL) Effect-site Concentration"
  → embedding → [0.11, -0.33, 0.55, ...]

cosine_similarity = 0.97  ← 높은 유사도로 매칭 성공
```

### 2.2 Embedding이 해결하는 실패 유형

| 실패 유형 | 쿼리 표현 | DB 표현 | Embedding 유사도 (예상) |
|---|---|---|---|
| 구두점 불일치 | `effect site concentration` | `Effect-site Concentration` | **~0.96** |
| 동의어 | `amount of propofol` | `Propofol Infused Volume` | **~0.82** |
| 축약어 | `blood pressure` | `SBP (Systolic Blood Pressure)` | **~0.88** |
| 임상 개념 | `consciousness level` | `BIS (Bispectral Index)` | **~0.75** |

---

## 3. 인프라 현황 (구현 준비 상태)

### 3.1 이미 갖춰진 요소

| 항목 | 상태 | 세부 |
|---|---|---|
| **pgvector** | ✅ 설치됨 | PostgreSQL extension v0.8.1 |
| **OpenAI Embedding API** | ✅ 사용 중 | `text-embedding-3-small` (Level1 Stage4 dedup에서 활용) |
| **파라미터 수** | ✅ 적음 | **259개** distinct param_key |
| **parameter 테이블** | ✅ 텍스트 풍부 | `semantic_name`, `description`, `concept_category`, `unit` |

### 3.2 비용 추정

| 항목 | 비용/시간 |
|---|---|
| 사전 임베딩 계산 (259개) | **< $0.001** (1회성) |
| 런타임 쿼리 임베딩 | **~$0.00001/건**, ~100ms |
| 인메모리 방식 (사전 로드) | **$0** (런타임), **< 1ms/건** |

---

## 4. 구현 설계

### 4.1 아키텍처: Hybrid Search (ILIKE + Embedding)

기존 ILIKE 검색을 제거하지 않고, embedding 결과와 **합산**하여 안정성을 확보한다:

```
requested_parameter.term
        │
        ├──→ [ILIKE 검색]    → db_matches_keyword  (기존 로직 유지)
        │
        └──→ [Embedding 검색] → db_matches_semantic (신규)
                │
                ▼
        ┌───────────────────────┐
        │  Merge & Rank         │
        │  (중복 제거 + 점수화)  │
        └───────────────────────┘
                │
                ▼
          db_matches (통합)
                │
                ▼
        [기존 LLM Resolution 로직]
```

### 4.2 사전 준비: 파라미터 임베딩 생성

#### 4.2.1 임베딩 텍스트 구성

각 파라미터를 다음 형식으로 문자열화하여 임베딩한다:

```python
def build_embedding_text(param: dict) -> str:
    """파라미터 정보를 임베딩용 텍스트로 변환"""
    parts = []
    
    if param.get("param_key"):
        parts.append(f"Key: {param['param_key']}")
    
    if param.get("semantic_name"):
        parts.append(f"Name: {param['semantic_name']}")
    
    if param.get("concept_category"):
        parts.append(f"Category: {param['concept_category']}")
    
    if param.get("unit"):
        parts.append(f"Unit: {param['unit']}")
    
    if param.get("description"):
        parts.append(f"Description: {param['description']}")
    
    return " | ".join(parts)
```

예시 결과:

```
"Key: Orchestra/PPF20_CE | Name: Propofol (20 mg/mL) Effect-site Concentration | Category: Medication | Unit: mcg/mL"
```

#### 4.2.2 임베딩 저장

**Option A: pgvector (DB 레벨)**

```sql
-- 컬럼 추가
ALTER TABLE parameter ADD COLUMN IF NOT EXISTS 
    name_embedding vector(1536);

-- 인덱스 생성 (259개 → IVFFlat 충분)
CREATE INDEX IF NOT EXISTS idx_parameter_embedding 
    ON parameter USING ivfflat (name_embedding vector_cosine_ops)
    WITH (lists = 10);
```

**Option B: 인메모리 캐시 (더 간단, 권장)**

```python
import numpy as np
from openai import OpenAI

class ParameterEmbeddingCache:
    """259개 파라미터 임베딩을 메모리에 캐시"""
    
    def __init__(self, model: str = "text-embedding-3-small"):
        self.model = model
        self.client = OpenAI()
        self.param_keys: list[str] = []
        self.param_info: list[dict] = []
        self.embeddings: np.ndarray | None = None  # shape: (N, 1536)
    
    def load_from_db(self, db_manager):
        """DB에서 파라미터 로드 후 임베딩 계산"""
        conn = db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT ON (param_key)
                   param_key, semantic_name, unit, 
                   concept_category, description
            FROM parameter
            ORDER BY param_key, param_id
        """)
        rows = cursor.fetchall()
        conn.commit()
        
        self.param_keys = []
        self.param_info = []
        texts = []
        
        for row in rows:
            param_key, sem_name, unit, category, desc = row
            info = {
                "param_key": param_key,
                "semantic_name": sem_name,
                "unit": unit,
                "concept_category": category,
                "description": desc,
            }
            self.param_keys.append(param_key)
            self.param_info.append(info)
            texts.append(build_embedding_text(info))
        
        # Batch embedding (259개 → 1회 API 호출)
        resp = self.client.embeddings.create(model=self.model, input=texts)
        vecs = [np.array(d.embedding, dtype=np.float32) for d in resp.data]
        self.embeddings = np.stack(vecs)
        
        # L2 정규화
        norms = np.linalg.norm(self.embeddings, axis=1, keepdims=True)
        self.embeddings = self.embeddings / np.clip(norms, 1e-10, None)
    
    def search(self, query: str, top_k: int = 5, 
               threshold: float = 0.5) -> list[dict]:
        """쿼리와 가장 유사한 파라미터 반환"""
        resp = self.client.embeddings.create(
            model=self.model, input=query
        )
        q_vec = np.array(resp.data[0].embedding, dtype=np.float32)
        q_vec = q_vec / np.linalg.norm(q_vec)
        
        # Cosine similarity (정규화된 벡터 → dot product)
        similarities = self.embeddings @ q_vec
        
        top_indices = np.argsort(similarities)[::-1][:top_k]
        
        results = []
        for idx in top_indices:
            sim = float(similarities[idx])
            if sim < threshold:
                break
            results.append({
                **self.param_info[idx],
                "similarity": sim,
            })
        
        return results
```

### 4.3 ParameterResolverNode 변경

#### 4.3.1 초기화

```python
class ParameterResolverNode(BaseNode):
    def __init__(self):
        super().__init__()
        self.config = ExtractionConfig().parameter_resolver
        self.db = get_db_manager()
        self.llm_client = get_llm_client()
        
        # [NEW] Embedding 캐시 초기화
        self._embedding_cache = None
    
    def _get_embedding_cache(self) -> ParameterEmbeddingCache:
        """Lazy initialization — 첫 호출 시 1회만 로드"""
        if self._embedding_cache is None:
            self._embedding_cache = ParameterEmbeddingCache()
            self._embedding_cache.load_from_db(self.db)
            self.log(f"📦 Loaded {len(self._embedding_cache.param_keys)} parameter embeddings")
        return self._embedding_cache
```

#### 4.3.2 execute() 변경

```python
def execute(self, state: ExtractionState) -> Dict[str, Any]:
    # ... (기존 로직 동일) ...
    
    for param in requested_parameters:
        term = param.get("term", "")
        candidates = param.get("candidates", [])
        expected_categories = param.get("expected_categories", [])
        
        # Step 1: 기존 ILIKE 검색 (유지)
        db_matches_keyword = self._search_parameters(
            candidates, expected_categories, schema_context
        )
        
        # Step 2: [NEW] Embedding 검색
        db_matches_semantic = self._search_by_embedding(
            term, expected_categories, top_k=5
        )
        
        # Step 3: [NEW] 결과 합산
        db_matches = self._merge_results(
            db_matches_keyword, db_matches_semantic
        )
        
        # Step 4: 기존 분기 로직 (동일)
        if len(db_matches) == 0:
            resolved = self._create_no_match_result(...)
        elif len(db_matches) <= 3:
            resolved = self._create_all_sources_result(...)
        else:
            resolved = self._resolve_with_llm(...)
```

#### 4.3.3 신규 메서드

```python
def _search_by_embedding(
    self, 
    term: str, 
    expected_categories: list[str],
    top_k: int = 5,
    threshold: float = 0.6
) -> list[dict]:
    """Embedding 유사도 기반 파라미터 검색"""
    cache = self._get_embedding_cache()
    results = cache.search(term, top_k=top_k, threshold=threshold)
    
    # 카테고리 필터 적용 (Option B와 동일)
    if expected_categories:
        filtered = [
            r for r in results 
            if r.get("concept_category") in expected_categories
        ]
        if filtered:
            results = filtered
    
    # DB 형식에 맞게 변환 (기존 ILIKE 결과와 동일한 스키마)
    return self._fetch_full_param_info([r["param_key"] for r in results])

def _merge_results(
    self, 
    keyword_results: list[dict], 
    semantic_results: list[dict]
) -> list[dict]:
    """ILIKE 결과와 Embedding 결과 합산 (중복 제거)"""
    seen_keys = set()
    merged = []
    
    # ILIKE 결과 우선 (정확한 매칭)
    for r in keyword_results:
        key = r.get("param_key")
        if key not in seen_keys:
            seen_keys.add(key)
            r["match_source"] = "keyword"
            merged.append(r)
    
    # Embedding 결과 추가 (ILIKE에서 빠진 것만)
    for r in semantic_results:
        key = r.get("param_key")
        if key not in seen_keys:
            seen_keys.add(key)
            r["match_source"] = "embedding"
            merged.append(r)
    
    return merged

def _fetch_full_param_info(self, param_keys: list[str]) -> list[dict]:
    """param_key 목록으로 DB에서 전체 정보 조회"""
    if not param_keys:
        return []
    
    conn = self.db.get_connection()
    cursor = conn.cursor()
    
    placeholders = ", ".join(["%s"] * len(param_keys))
    cursor.execute(f"""
        SELECT DISTINCT ON (param_key)
               param_id, param_key, semantic_name, unit,
               concept_category, file_id, group_id
        FROM parameter
        WHERE param_key IN ({placeholders})
        ORDER BY param_key, param_id
    """, param_keys)
    
    rows = cursor.fetchall()
    conn.commit()
    
    return [
        {
            "param_id": r[0], "param_key": r[1],
            "semantic_name": r[2], "unit": r[3],
            "concept_category": r[4],
            "file_id": str(r[5]) if r[5] else None,
            "group_id": str(r[6]) if r[6] else None,
        }
        for r in rows
    ]
```

---

## 5. 설정 및 튜닝 포인트

### 5.1 ExtractionConfig 확장

```python
# ExtractionAgent/src/config.py

class ParameterResolverConfig:
    search_limit: int = 20
    
    # [NEW] Embedding 검색 설정
    embedding_enabled: bool = True
    embedding_model: str = "text-embedding-3-small"
    embedding_top_k: int = 5
    embedding_threshold: float = 0.6   # 이 값 이하의 유사도는 무시
```

### 5.2 Threshold 튜닝 가이드

| threshold | 특성 | 적합한 경우 |
|---|---|---|
| **0.5** | 느슨한 매칭, recall 높음 | 많은 후보를 LLM에게 넘겨 판단시킬 때 |
| **0.6** | 균형 (권장 시작점) | 일반적인 파라미터 검색 |
| **0.7** | 엄격한 매칭, precision 높음 | 오탐 최소화가 중요할 때 |
| **0.8+** | 매우 엄격 | 거의 정확한 매칭만 허용 |

Level 1 데이터셋으로 최적 threshold를 실험적으로 결정할 것을 권장한다.

---

## 6. 캐시 전략

### 6.1 임베딩 파일 캐시 (재시작 시 API 재호출 방지)

```python
CACHE_PATH = "ExtractionAgent/data/parameter_embeddings.npz"

def save_cache(self, path: str = CACHE_PATH):
    np.savez(path, 
             embeddings=self.embeddings,
             param_keys=self.param_keys)

def load_cache(self, path: str = CACHE_PATH) -> bool:
    if os.path.exists(path):
        data = np.load(path, allow_pickle=True)
        self.embeddings = data["embeddings"]
        self.param_keys = list(data["param_keys"])
        return True
    return False
```

### 6.2 캐시 무효화 조건

다음 상황에서 임베딩을 재계산해야 한다:

- IndexingAgent가 새 파라미터를 등록한 경우
- `semantic_name`이나 `description`이 수정된 경우
- 임베딩 모델이 변경된 경우

무효화 감지 방법: `parameter` 테이블의 `MAX(updated_at)`과 캐시 파일 수정 시간을 비교한다.

---

## 7. 테스트 및 검증 계획

### 7.1 단위 테스트

```python
def test_embedding_search_propofol():
    """L1-013 재현: 하이픈 불일치 케이스"""
    cache = ParameterEmbeddingCache()
    cache.load_from_db(db)
    
    results = cache.search("propofol effect site concentration", top_k=3)
    param_keys = [r["param_key"] for r in results]
    
    assert "Orchestra/PPF20_CE" in param_keys
    assert results[0]["param_key"] == "Orchestra/PPF20_CE"  # 1위여야 함

def test_embedding_search_blood_pressure():
    """동의어 매칭 검증"""
    results = cache.search("blood pressure", top_k=3)
    param_keys = [r["param_key"] for r in results]
    
    assert any("NIBP" in k or "ABP" in k for k in param_keys)

def test_embedding_search_consciousness():
    """임상 개념 매칭 검증"""
    results = cache.search("consciousness level", top_k=3)
    param_keys = [r["param_key"] for r in results]
    
    assert "BIS/BIS" in param_keys
```

### 7.2 Level 1 통합 평가

embedding 적용 전후 Level 1 평가 스크립트로 성능 변화를 비교한다:

```bash
# Before (현재)
python Evaluation/Level1/test_level1_dataset.py --scenarios vitalagent-extraction

# After (embedding 적용 후)
python Evaluation/Level1/test_level1_dataset.py --scenarios vitalagent-extraction
```

**기대 개선 효과:**

| 지표 | Before (현재) | After (예상) | 개선 |
|---|---|---|---|
| Parameter Recall | 0.85 | **0.93+** | +8%p |
| Parameter Precision | 0.78 | **0.85+** | +7%p |
| F1 Score | 0.80 | **0.89+** | +9%p |
| Behavior Match | 0.70 | **0.78+** | +8%p |

---

## 8. 리스크 및 고려사항

| 리스크 | 영향 | 완화 방안 |
|---|---|---|
| OpenAI API 의존성 추가 | 오프라인 환경에서 사용 불가 | 로컬 임베딩 모델 대체 가능 (e.g., `all-MiniLM-L6-v2`) |
| 임베딩 모델 업데이트 시 일관성 | 모델 버전 변경 시 캐시 무효화 | 모델명을 캐시 키에 포함 |
| 의학 도메인 특화 부족 | 일반 임베딩 모델은 의학 용어 유사도가 낮을 수 있음 | threshold 조정 + 의학 용어 사전 기반 텍스트 보강 |
| ILIKE와의 결과 충돌 | 같은 term에 대해 다른 결과 가능 | Hybrid merge 전략으로 양쪽 결과 합산 |

---

## 9. 향후 확장

1. **Neo4j 그래프 + Embedding 결합**: 온톨로지 관계(RELATED_TO)와 embedding 유사도를 가중 합산하여 더 정교한 검색
2. **Query-level Embedding**: `term` 단위가 아닌 `전체 쿼리` 임베딩으로 문맥 기반 검색
3. **Fine-tuned Embedding**: 의료 도메인 파라미터 매칭에 특화된 임베딩 모델 학습
4. **로컬 임베딩 모델**: `sentence-transformers/all-MiniLM-L6-v2` 등으로 OpenAI 의존성 제거
