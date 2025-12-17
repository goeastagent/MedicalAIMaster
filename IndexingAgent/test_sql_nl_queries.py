#!/usr/bin/env python3
"""
자연어 → SQL 변환 예시 및 실행 스모크 테스트 스크립트.

설정:
- PostgreSQL 접속 정보는 `.env`의 POSTGRES_* 값 사용 (없으면 기본값).
- 최대한 많은 테이블을 조인하는 복잡한 예시 3개를 포함.

주의:
- 실제 스키마 컬럼명이 다르면 실행이 건너뛰어질 수 있음.
- 필요한 컬럼 존재 여부를 information_schema로 확인하고 부족하면 경고만 출력.
"""

import os
from typing import Dict, List

import psycopg2
from dotenv import load_dotenv

# .env 로드
load_dotenv()


def connect():
    conn = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "medical_data"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", ""),
    )
    conn.autocommit = False
    return conn


def table_has_columns(cur, table: str, cols: List[str]) -> bool:
    placeholders = ",".join(["%s"] * len(cols))
    cur.execute(
        f"""
        SELECT COUNT(*) = %s
        FROM (
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
              AND column_name IN ({placeholders})
        ) t;
        """,
        [len(cols), table, *cols],
    )
    return cur.fetchone()[0]


def run_queries():
    queries = [
        {
            "natural": "지난 24시간 동안 동일 환자(subject_id)에 대해 병동 바이탈, 일반 바이탈, 최근 랩(젖산/칼륨), 투약(바소프레서), 진단 코드까지 한 번에 묶어서 타임라인으로 보여줘.",
            "required": {
                "vitals": ["subject_id", "chart_time"],
                "ward_vitals": ["subject_id", "chart_time"],
                "labs": ["subject_id", "chart_time", "item_name"],
                "medications": ["subject_id", "chart_time", "drug_name"],
                "diagnosis": ["subject_id", "icd10_cm"],
            },
            "sql": """
WITH anchor AS (
    SELECT subject_id, chart_time
    FROM vitals
    WHERE chart_time >= NOW() - INTERVAL '1 day'
),
merged AS (
    SELECT
        a.subject_id,
        a.chart_time AS vital_time,
        v.item_name       AS vital_item,
        v.value           AS vital_value,
        w.item_name       AS ward_item,
        w.value           AS ward_value,
        l.item_name       AS lab_item,
        l.value           AS lab_value,
        m.drug_name,
        m.dose,
        d.icd10_cm
    FROM anchor a
    LEFT JOIN vitals v
        ON v.subject_id = a.subject_id
       AND v.chart_time = a.chart_time
    LEFT JOIN ward_vitals w
        ON w.subject_id = a.subject_id
       AND ABS(EXTRACT(EPOCH FROM (w.chart_time - a.chart_time))) <= 3600
    LEFT JOIN labs l
        ON l.subject_id = a.subject_id
       AND ABS(EXTRACT(EPOCH FROM (l.chart_time - a.chart_time))) <= 3600
       AND l.item_name ILIKE ANY (ARRAY['%lactate%', '%k%'])
    LEFT JOIN medications m
        ON m.subject_id = a.subject_id
       AND ABS(EXTRACT(EPOCH FROM (m.chart_time - a.chart_time))) <= 3600
       AND m.drug_name ILIKE ANY (ARRAY['%norepinephrine%', '%epinephrine%', '%vasopressin%'])
    LEFT JOIN diagnosis d
        ON d.subject_id = a.subject_id
)
SELECT *
FROM merged
ORDER BY subject_id, vital_time DESC
LIMIT 50;
""",
        },
        {
            "natural": "수술 케이스별(op_id)로 최근 7일간 수술 정보 + 시술 직전/직후 2시간 내 바이탈, 시술 당일 투약/검사 결과, 진단 코드까지 모두 조인해서 보고 싶다.",
            "required": {
                "operations": ["op_id", "subject_id", "chart_time"],
                "vitals": ["subject_id", "chart_time"],
                "labs": ["subject_id", "chart_time", "item_name"],
                "medications": ["subject_id", "chart_time", "drug_name"],
                "diagnosis": ["subject_id", "icd10_cm"],
            },
            "sql": """
WITH recent_ops AS (
    SELECT *
    FROM operations
    WHERE chart_time >= NOW() - INTERVAL '7 day'
),
ctx AS (
    SELECT
        o.op_id,
        o.subject_id,
        o.chart_time AS op_time,
        v.chart_time AS vit_time,
        v.item_name  AS vit_item,
        v.value      AS vit_value,
        l.chart_time AS lab_time,
        l.item_name  AS lab_item,
        l.value      AS lab_value,
        m.chart_time AS med_time,
        m.drug_name,
        m.dose,
        d.icd10_cm
    FROM recent_ops o
    LEFT JOIN vitals v
        ON v.subject_id = o.subject_id
       AND ABS(EXTRACT(EPOCH FROM (v.chart_time - o.chart_time))) <= 7200
    LEFT JOIN labs l
        ON l.subject_id = o.subject_id
       AND l.chart_time::date = o.chart_time::date
    LEFT JOIN medications m
        ON m.subject_id = o.subject_id
       AND m.chart_time::date = o.chart_time::date
    LEFT JOIN diagnosis d
        ON d.subject_id = o.subject_id
)
SELECT *
FROM ctx
ORDER BY op_id, vit_time DESC NULLS LAST
LIMIT 50;
""",
        },
        {
            "natural": "중환자/병동 전환 패턴: 최근 48시간 이내 ward_vitals와 일반 vitals를 모두 가진 환자들 중, 동일 subject_id에서 고위험 약물(바소프레서) 투약과 젖산 상승(lactate) 검사가 같이 보이는 시점을 찾아라.",
            "required": {
                "ward_vitals": ["subject_id", "chart_time"],
                "vitals": ["subject_id", "chart_time"],
                "medications": ["subject_id", "chart_time", "drug_name"],
                "labs": ["subject_id", "chart_time", "item_name"],
            },
            "sql": """
WITH dual_ward AS (
    SELECT DISTINCT subject_id
    FROM ward_vitals
    WHERE chart_time >= NOW() - INTERVAL '48 hour'
    INTERSECT
    SELECT DISTINCT subject_id
    FROM vitals
    WHERE chart_time >= NOW() - INTERVAL '48 hour'
),
events AS (
    SELECT
        d.subject_id,
        v.chart_time AS vit_time,
        w.chart_time AS ward_time,
        m.chart_time AS med_time,
        l.chart_time AS lab_time,
        m.drug_name,
        l.item_name  AS lab_item,
        l.value      AS lab_value
    FROM dual_ward d
    JOIN vitals v
      ON v.subject_id = d.subject_id
     AND v.chart_time >= NOW() - INTERVAL '48 hour'
    JOIN ward_vitals w
      ON w.subject_id = d.subject_id
     AND ABS(EXTRACT(EPOCH FROM (w.chart_time - v.chart_time))) <= 7200
    JOIN medications m
      ON m.subject_id = d.subject_id
     AND m.drug_name ILIKE ANY (ARRAY['%norepinephrine%', '%vasopressin%', '%epinephrine%'])
     AND ABS(EXTRACT(EPOCH FROM (m.chart_time - v.chart_time))) <= 7200
    JOIN labs l
      ON l.subject_id = d.subject_id
     AND l.item_name ILIKE '%lactate%'
     AND ABS(EXTRACT(EPOCH FROM (l.chart_time - v.chart_time))) <= 7200
)
SELECT *
FROM events
ORDER BY subject_id, vit_time DESC
LIMIT 50;
""",
        },
    ]

    with connect() as conn:
        cur = conn.cursor()
        print("\n✅ PostgreSQL 연결 성공")
        for i, q in enumerate(queries, 1):
            print("\n" + "=" * 80)
            print(f"[{i}] 자연어: {q['natural']}")
            print("-" * 80)
            print(q["sql"].strip())

            # 컬럼 존재 여부 확인
            missing = []
            for tbl, cols in q["required"].items():
                if not table_has_columns(cur, tbl, cols):
                    missing.append(f"{tbl} (missing: {', '.join(cols)})")
            if missing:
                print(f"⚠️  스키마에 필요한 컬럼이 없어 실행을 건너뜁니다: {', '.join(missing)}")
                continue

            try:
                cur.execute(q["sql"])
                rows = cur.fetchall()
                if not rows:
                    print("⚠️  결과 없음")
                else:
                    print(f"🔹 결과 상위 {min(len(rows), 5)}건:")
                    for r in rows[:5]:
                        print("   ", r)
            except Exception as e:
                print(f"❌ 실행 실패: {e}")
                conn.rollback()
            else:
                conn.rollback()  # 읽기만 했으므로 롤백


if __name__ == "__main__":
    run_queries()

