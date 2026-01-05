# TODO: Neo4j Ontology 개선 계획

> 생성일: 2026-01-05
> 관련 노드: `relationship_inference`

---

## ✅ 완료된 작업

### 1. Parameter 테이블 기반 Neo4j 동기화 (2026-01-05)

**문제점:**
- 기존 코드는 `column_metadata`와 `parameter` 테이블을 `LEFT JOIN`하여 데이터 조회
- `group_common` 타입 파라미터 (file_id=NULL, source_column_id=NULL)가 JOIN에서 제외됨
- 결과: Vital Signs, Identifiers 등의 ConceptCategory 노드가 Parameter와 연결되지 않음

**해결:**
- `_create_concept_category_nodes()`, `_create_parameter_nodes()`, `_create_contains_edges()` 메서드 수정
- `ParameterRepository.get_all_parameters_for_ontology()`를 통해 parameter 테이블에서 직접 조회
- `_sync_to_neo4j()`에서 한 번만 호출하여 성능 최적화

**수정된 파일:**
- `src/agents/nodes/relationship_inference/node.py`

---

## 📋 대기 중인 작업

### 2. `_create_has_column_edges` 검토 및 개선

**현재 상태:**
- `RowEntity → Parameter` (HAS_COLUMN) 엣지 생성
- 여전히 `tables['columns']`를 사용 (column_metadata 기반)

**문제점:**
- `group_common` 파라미터는 특정 파일이 아닌 **FileGroup**에 속함
- `file_id = NULL`이므로 특정 RowEntity와 연결할 수 없음

**검토 필요 사항:**
```
질문 1: group_common 파라미터를 RowEntity와 연결해야 하는가?
  - Option A: FileGroup 노드를 새로 만들어 연결
  - Option B: group_common 파라미터는 HAS_COLUMN 엣지 없이 ConceptCategory만 연결
  - Option C: 해당 그룹의 모든 RowEntity에 연결 (중복 허용)

질문 2: 현재 구조로 충분한가?
  - 현재: RowEntity --HAS_COLUMN--> Parameter (column_name 기반만)
  - group_common은 CONTAINS 엣지로만 연결됨
```

**예상 작업:**
1. `file_groups` 테이블 확인
2. FileGroup 노드 생성 여부 결정
3. `_create_has_column_edges()` 수정 또는 새 메서드 추가

**우선순위:** 중간
**예상 소요 시간:** 2-3시간

---

### 3. FileGroup 노드 추가 (선택적)

**배경:**
- `.vital` 파일 같은 signal 데이터는 file_group으로 묶여서 처리됨
- 공통 파라미터(`group_common`)는 개별 파일이 아닌 그룹 단위로 존재

**제안 스키마:**
```cypher
// 새 노드
(:FileGroup {
    group_id: "uuid",
    directory: "/path/to/files",
    file_count: 3,
    file_type: "vital"
})

// 새 관계
(:FileGroup)-[:CONTAINS_FILE]->(:RowEntity)
(:FileGroup)-[:HAS_COMMON_PARAM]->(:Parameter)
```

**장점:**
- signal 데이터의 구조를 정확히 반영
- group_common 파라미터의 소속을 명확히 표현
- 쿼리 시 그룹 단위 조회 가능

**단점:**
- 스키마 복잡도 증가
- 기존 쿼리 수정 필요

**우선순위:** 낮음 (필요시 구현)
**예상 소요 시간:** 4-5시간

---

### 4. Neo4j 스키마 문서화

**필요 작업:**
1. 현재 노드/엣지 스키마 정리
2. 각 노드의 속성(property) 명세
3. 엣지 의미 및 사용 예시
4. Cypher 쿼리 예시

**예시 문서 구조:**
```markdown
## Nodes
- RowEntity: 개별 테이블/파일 (file_name, entity_name, ...)
- ConceptCategory: 개념 그룹 (name)
- Parameter: 개별 파라미터 (key, name, unit, concept)

## Edges
- LINKS_TO: FK 관계 (source_column, target_column, cardinality)
- HAS_CONCEPT: RowEntity가 포함하는 개념 카테고리
- CONTAINS: ConceptCategory가 포함하는 Parameter
- HAS_COLUMN: RowEntity가 가진 컬럼(Parameter)
```

**우선순위:** 낮음
**예상 소요 시간:** 1-2시간

---

### 5. 파이프라인 재실행 및 검증

**테스트 항목:**

| 항목 | 검증 방법 |
|------|-----------|
| ConceptCategory 노드 생성 | `MATCH (c:ConceptCategory) RETURN c.name, count(*)` |
| Parameter 노드 생성 | `MATCH (p:Parameter) RETURN count(*)` |
| CONTAINS 엣지 연결 | `MATCH (c:ConceptCategory)-[:CONTAINS]->(p:Parameter) RETURN c.name, count(p)` |
| group_common 파라미터 포함 여부 | `MATCH (p:Parameter) WHERE p.key CONTAINS '/' RETURN p.key` |

**실행 순서:**
```bash
# 1. DB 초기화
python reset_all.py

# 2. 파이프라인 실행
python test_full_pipeline_results.py

# 3. Neo4j 확인 (DBeaver 또는 Neo4j Browser)
# bolt://localhost:7687
```

**우선순위:** 높음 (수정 후 바로 실행)
**예상 소요 시간:** 30분

---

## 📊 참고: 현재 Neo4j 온톨로지 구조

```
                    ┌─────────────────┐
                    │   RowEntity     │
                    │  (테이블/파일)   │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
        ┌─────────┐    ┌──────────┐   ┌─────────┐
        │LINKS_TO │    │HAS_CONCEPT│   │HAS_COLUMN│
        │ (FK 관계)│    │          │   │         │
        └────┬────┘    └─────┬────┘   └────┬────┘
             │               │              │
             ▼               ▼              │
      ┌──────────┐    ┌───────────────┐    │
      │RowEntity │    │ConceptCategory│    │
      │ (다른 것) │    │  (개념 그룹)   │    │
      └──────────┘    └───────┬───────┘    │
                              │            │
                              ▼            ▼
                        ┌──────────┐
                        │CONTAINS  │
                        └────┬─────┘
                             │
                             ▼
                      ┌───────────┐
                      │ Parameter │
                      │ (파라미터) │
                      └───────────┘
```

---

## 📁 관련 파일

| 파일 | 역할 |
|------|------|
| `src/agents/nodes/relationship_inference/node.py` | Neo4j 온톨로지 생성 로직 |
| `src/database/repositories/parameter_repository.py` | Parameter 테이블 조회 |
| `src/database/repositories/entity_repository.py` | Entity/Column 정보 조회 |
| `src/config.py` | Neo4j 설정 (NEO4J_ENABLED 등) |
| `ARCHITECTURE.md` | 전체 아키텍처 문서 |

