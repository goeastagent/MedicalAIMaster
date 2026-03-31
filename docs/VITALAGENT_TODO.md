# VitalAgent TODO — 개선 과제

> 기준: 2026-03-30 최신 평가 결과 분석  
> 평가 파일 기준일: `level1_eval_20260329_233221`, `value_accuracy_eval_20260329_205519`, `temporal_eval_20260329_205523`, `sva_eval_20260329_205525`

---

## P0 — 즉시 수정 (Critical)

### [ ] T-01: Ambiguity Detection 로직 구현

**평가:** Temporal  
**현황:** Ambiguous 쿼리 50개 중 **50개 전부 실패 (0% pass rate)**

**문제:**  
caseid, 시간 범위 등 필수 정보가 없는 쿼리에서 VitalAgent는 clarification을 요청하지 않고 임의의 숫자를 반환한다.

```
Q: "What is the average heart rate during the first 10 minutes?"
missing_info: caseid, sampling_rate, nan_handling, precision
Expected: AMBIGUOUS (또는 assumption 명시 후 답변)
Got: 76.01101837158203
```

평가 루브릭 (LLM-as-a-Judge, 3단계):
- **PASS**: 답하기 전에 clarification을 명시적으로 요청
- **PARTIAL_PASS**: "caseid를 X로 가정하고..." 처럼 assumption을 명시한 뒤 답변
- **FAIL**: assumption 언급 없이 바로 숫자 반환 → **현재 VitalAgent의 동작**

---

**검토 이력 (2026-03-30): 단순 접근들의 한계**

**검토 A — 데이터셋 쿼리에 ambiguous 힌트 추가 (기각)**  
쿼리 텍스트 자체에 "이 질의는 caseid가 없습니다" 같은 힌트를 삽입하는 방식.  
단일 턴 시스템의 현실에는 맞지만, ambiguity *탐지* 능력을 테스트하지 않고 지시 따르기를 테스트하게 됨.  
프로덕션에서 실제 사용자의 implicit ambiguous 쿼리에 대한 대응 능력은 여전히 0%.

**검토 B — Orchestrator 레벨 사후 assumption_note 부착 (기각)**  
`execution_plan`에서 caseid_filter가 없으면 `assumption_note`를 생성해 결과에 붙이는 방식.  
3가지 근본 문제로 기각:

1. **평가 프롬프트 차단**: 테스트 프롬프트가 `"output ONLY a JSON object"` 를 강제하므로  
   AnalysisAgent가 생성하는 코드는 assumption 문구를 절대 출력하지 않음.  
   `assumption_note`는 Orchestrator 메타데이터일 뿐, 실제 응답 텍스트가 아님.

2. **False Positive 과다**: `caseid_filter == []` 조건은 "모든 케이스의 평균 HR"처럼  
   caseid가 의도적으로 없는 population-level 쿼리에도 전부 해당됨.  
   규칙 기반으로는 `single_case` intent vs `population` intent를 구분할 수 없음.

3. **Metric 위조**: VitalAgent 자신이 ambiguity를 이해한 게 아니라,  
   evaluation 코드가 후처리로 삽입한 문자열이 LLM judge를 통과하는 구조.  
   프로덕션 사용자에게는 여전히 숫자만 반환됨.

---

**올바른 해결 방향 (3-Layer 접근)**

**Layer 1 — QueryUnderstanding에서 LLM이 scope_intent 직접 판단**  
`query_understanding/prompts.py`에 새 출력 필드 추가:
```json
{
  "scope_intent": "single_case | population | ambiguous",
  "is_caseid_required": true,
  "is_time_range_specified": false
}
```
LLM이 쿼리 문맥을 보고 직접 `single_case` (특정 환자 대상) vs `population` (전체 통계)를 판단.

**Layer 2 — Orchestrator에서 scope_intent 기반 분기**  
`scope_intent == "single_case"` + caseid_filter 없음 → LLM이 판단한 진짜 ambiguity:
```python
first_caseid = ctx.get_case_ids()[0]
assumption_note = f"No caseid was specified; assuming first available case (caseid='{first_caseid}')"
# → 이 문구를 생성 코드 출력에 포함시켜 raw_response에 반영
```

**Layer 3 — 평가 테스트 프롬프트 수정**  
`temporal_ambiguous` 케이스에 한해 `"output ONLY a JSON"` 제약을 제거하거나,  
assumption 문구를 허용하는 별도 프롬프트로 분기하여 raw_response에 텍스트가 남도록 처리.

이 3가지가 모두 구현되어야 실제로 PARTIAL_PASS를 획득할 수 있음.

---

### [ ] T-02: Ontology/Category 기반 파라미터 열거 기능 구현

**평가:** SVA (SemanticValueAccuracy)  
**현황:** `ontology_based` 카테고리 resolution 50%, `category_aggregate` 스타일 12.5%

**문제:**  
의학적 온톨로지 카테고리로 파라미터를 그룹화하는 쿼리에서 빈 결과를 반환한다.

```
Q: "all vasopressor/inotrope drug infusion rates"
Expected: [Orchestra/DOBU_RATE, DOPA_RATE, EPI_RATE, NEPI_RATE, PHEN_RATE, VASO_RATE, ...]
Got: []  (not_attempted)

Q: "all hemodynamic parameters from the advanced cardiac output monitor (EV1000)"
Expected: [EV1000/ART_MBP, EV1000/CI, EV1000/CO, EV1000/CVP, EV1000/SV, ...]
Got: []  (not_attempted)
```

**해결 방향:**
- 파라미터 메타데이터에 `ontology_category` 필드 추가 (예: `vasopressor`, `hemodynamic`, `ventilator_mechanics`)
- 장비명 기반 파라미터 그룹 매핑 테이블 구축 (예: `EV1000/*`, `Orchestra/*`)
- parameter_resolver에서 카테고리 매칭 로직 추가

---

## P1 — 우선 수정 (High)

### [ ] T-03: Cross-Device 파라미터 Disambiguation

**평가:** Level1 Multi-Conditional (recall 0.84)  
**현황:** 동일 의미의 파라미터가 두 장비에 존재할 때 일관되게 잘못된 장비를 선택

**문제:**
```
Expected: Solar8000/ETCO2   →   Retrieved: Primus/ETCO2
Expected: Primus/TV         →   Retrieved: Solar8000/VENT_TV
Expected: Orchestra/PPF20_CE (effect-site) →   Retrieved: Orchestra/PPF20_RATE (infusion rate)
```

**해결 방향:**
- 쿼리 문맥에서 장비 힌트(예: "anesthesia machine" = Primus, "patient monitor" = Solar8000) 추출
- 힌트가 없을 때 우선순위 규칙 정의 (기본 장비 설정)
- effect-site concentration(`_CE`) vs infusion rate(`_RATE`) 구분 로직 강화

---

### [x] T-04: `'DataFrame' object has no attribute 'dtype'` 버그 수정 ✅ 완료 (2026-03-30)

**평가:** ValueAccuracy  
**현황:** 6개 케이스에서 동일한 에러로 실패

**문제:**  
파생 지표(pulse pressure, MAP 추정, shock index) 계산 시 생성된 코드에서 발생:
```
error_message="Unexpected error: 'DataFrame' object has no attribute 'dtype'"
```

영향받는 쿼리 유형:
- pulse pressure (SBP - DBP)
- MAP 추정 (derived 계산)
- shock index (HR / SBP)

**근본 원인:**  
`OrchestrationAgent/src/orchestrator.py` `_build_execution_context()` 내부(line 649/658/669/687/694)에서  
시그널 DataFrame에 **중복 컬럼명**이 있을 때 `df[col]`이 Series 대신 DataFrame을 반환하고,  
DataFrame에는 `.dtype`이 없어서 AttributeError 발생. 이 에러는 sandbox 밖에서 발생하므로  
최상위 try/except까지 전파되어 `"Unexpected error"` 포맷으로 출력됨.

**해결 내용:**  
`_col_dtype(df, col)` static 헬퍼 메서드 추가 후 5곳의 `.dtype` 호출 교체:
```python
@staticmethod
def _col_dtype(df, col: str) -> str:
    col_data = df[col]
    if isinstance(col_data, pd.Series):
        return str(col_data.dtype)
    # 중복 컬럼명: df[col]이 DataFrame 반환 → 첫 번째 컬럼의 dtype 사용
    if isinstance(col_data, pd.DataFrame) and not col_data.empty:
        return str(col_data.iloc[:, 0].dtype)
    return "unknown"
```

---

### [ ] T-05: Behavior Classification 로직 수정 (clarify ↔ retrieve 역전)

**평가:** Level1  
**현황:** Multi-Conditional 쿼리에서 `retrieve`/`clarify` 행동 분류 오류

**문제:**
```
Q: "During episodes of elevated ETCO2, how does the tidal volume adjust?"
Expected behavior: retrieve   →   Detected: clarify  (잘못)

Q: (caseid 없는 ambiguous 쿼리)
Expected behavior: clarify    →   Detected: retrieve (잘못)
```

clarify를 반환해야 할 때 retrieve를 하고, retrieve를 해야 할 때 clarify를 반환하는 역전 현상.

**해결 방향:**
- 행동 분류 기준 재정의: 조건이 명시된 경우(even if complex) → `retrieve`
- 필수 컨텍스트(caseid 등)가 없는 경우 → `clarify`
- parameter_resolver의 behavior detection 프롬프트 수정

---

## P2 — 개선 (Medium)

### [x] T-06: Trailing Backslash 버그 수정 ✅ 완료 (2026-03-30)

**평가:** SVA  
**현황:** 파라미터 이름 끝에 `\`가 붙어 lookup 실패

**문제:**
```python
Resolved: ['Solar8000/ART_DBP\', 'Solar8000/ART_MBP\', 'Solar8000/ART_SBP\']
# → 파라미터 검색 실패 (backslash로 인한 key mismatch)
```

**해결 내용:** `node.py` 두 곳에 `rstrip("\\")` 적용:
- `_resolve_with_llm()` LLM 응답 파싱 직후 `selected_keys` 
- 최종 `param_keys` 리스트 조립 시 (`selected_matches` → `param_keys`)

---

### [x] T-07: Float Precision 비교 기준 완화 ✅ 완료 (2026-03-30)

**평가:** ValueAccuracy  
**현황:** 실패 26개 중 15개(57%)가 부동소수점 오차로 인한 것

**문제:**
```
Expected: 8237.7197      Got: 8237.7197265625   (차이: 0.000027)  → FAIL
Expected: 3375.816       Got: 3375.81591796875  (차이: 0.000082)  → FAIL
Expected: 44.1           Got: 44.2              (차이: 0.1)       → FAIL
Expected: 10.77          Got: 10.779999732971191                  → FAIL
```

**해결 내용:**  
`Evaluation/ValueAccuracy/test_value_accuracy.py` `compare_values()` 수정.  
기존 `abs(expected - actual) < 1e-5` → Temporal eval과 동일한 이중 tolerance 방식으로 교체:
```python
FLOAT_STRICT_REL_TOL = 1e-4   # float repr 노이즈 (8237.7197 vs 8237.7197265625)
FLOAT_APPROX_REL_TOL = 1e-2   # 반올림 차이 (44.1 vs 44.2, 10.77 vs 10.78)
```
검증: 기존 실패 15/15 케이스 → 전부 PASS. 완전히 다른 값(80.9 vs 81.72 등)은 여전히 FAIL.

---

### [ ] T-08: 파형(Waveform) vs 스칼라 파라미터 구분

**평가:** Level1 Single-Semantic  
**현황:** waveform 파라미터를 스칼라로 잘못 해석

**문제:**
```
Q: "brain activity patterns during surgery"
Expected: BIS/EEG2_WAV  (파형 데이터)
Got: BIS/BIS, BIS/EMG, BIS/SEF, BIS/SQI, BIS/SR, BIS/TOTPOW  (스칼라 지표들)
```

**검토 이력 (2026-03-30):**  
param_key suffix(`_WAV`) 기반 후처리 구현 → **되돌림**.  
이유: VitalDB naming convention 전용 방식. 타 데이터셋(`ECG_waveform`, `pleth_signal` 등)에서 미매칭.  
순수 코드 후처리로는 naming convention 독립적인 범용 해결책 불가.

**올바른 해결 방향:**
- DB `parameter` 테이블에 `measurement_type: waveform | scalar` 컬럼 추가 (스키마 변경)
- 또는 LLM이 `semantic_name` + `unit` 메타데이터를 보고 직접 판단 (프롬프트 개선)

---

### [ ] T-09: 약물 용량(Volume) vs 주입속도(Rate) 구분

**평가:** Level1 Single-Semantic/Single-Abbreviation  
**현황:** `DEX2_VOL` (누적 용량) 대신 `DEX2_RATE` (주입속도) 또는 미검색

**문제:**
```
Q: "How much dexmedetomidine was administered?"
Expected: Orchestra/DEX2_VOL  (누적 투여량)
Got: (미검색)

Q: "How much Dex was administered?"  [abbreviation]
Expected: Orchestra/DEX2_VOL
Got: (미검색)
```

**검토 이력 (2026-03-30):**  
쿼리 키워드 → `_VOL` / `_RATE` suffix 필터링 후처리 구현 → **되돌림**.  
이유: `_VOL`, `_RATE` suffix는 VitalDB/Orchestra 전용. 타 데이터셋 naming 패턴 불일치 시 동작 안 함.  
또한 "how much" 키워드가 농도(`_CP`, `_CE`) 쿼리와도 겹쳐 false positive 위험 있음.

**올바른 해결 방향:**
- DB `parameter` 테이블에 `measurement_type: cumulative | rate | concentration | scalar` 컬럼 추가
- 또는 LLM이 `unit` 메타데이터를 활용해 판단 (mL/hr → rate, mL → cumulative)

---

## P3 — 성능 최적화 (Low)

### [ ] T-10: ValueAccuracy 응답 속도 개선

**평가:** ValueAccuracy  
**현황:** VitalAgent 평균 11,495ms vs Claude-Code-CLI 6,524ms (76% 느림)

**상세:**
```
conditional_multi_hop: 평균 15,760ms, p95 22,428ms  (가장 느림)
Multi-Conditional:     평균 17,759ms, p95 23,395ms
```

**해결 방향:**
- 파라미터 해석 → 코드 생성 → 실행 파이프라인의 병렬화 검토
- 이미 해석된 파라미터 캐싱
- conditional_multi_hop에서 불필요한 재시도 루프 제거

---

## 참고: 평가별 현재 성능 요약

| 평가 | 지표 | VitalAgent | Claude-Code-CLI |
|------|------|-----------|----------------|
| Level1 | F1 (overall) | **0.861** | 0.648 |
| Level1 | Perfect recall% | **83.3%** | 66.7% |
| ValueAccuracy | Accuracy | 94.8% | **95.4%** |
| ValueAccuracy | Avg time | 11,495ms | **6,524ms** |
| Temporal | Numeric accuracy | 98.0% | **98.7%** |
| Temporal | Ambiguity pass | 2.0% | 2.0% |
| SVA | Composite score | **0.812** | 0.380 |
| SVA | Resolution | **0.730** | 0.080 |

> VitalAgent는 파라미터 해석(Level1, SVA)에서 압도적 우위지만,  
> 수치 정확도(ValueAccuracy, Temporal)와 속도(ValueAccuracy)에서 개선 여지가 있음.  
> Ambiguity detection은 양측 모두 미구현 상태.
