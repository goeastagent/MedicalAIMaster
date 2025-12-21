#!/usr/bin/env python3
"""
ExtractionAgent 사용 예시 - 단순 버전

단일 테이블 쿼리부터 시작하여 점진적으로 복잡한 쿼리로 확장합니다.
"""

import sys
import os

# 프로젝트 루트를 path에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

# 프로젝트 루트의 .env 로드 시도
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(project_root, '.env'))
load_dotenv()  # 현재 폴더도 시도

from ExtractionAgent.src.extraction_agent import ExtractionAgent


def example_1_simple_select():
    """
    예시 1: 가장 단순한 SELECT
    - 단일 테이블
    - 조건 없음
    - 상위 10개만
    """
    print("\n" + "=" * 80)
    print("📌 예시 1: 단순 SELECT (operations 테이블)")
    print("=" * 80)
    
    agent = ExtractionAgent()
    
    # 매우 단순한 쿼리
    query = "operations 테이블에서 환자 10명의 기본 정보(나이, 성별, 체중)를 보여줘"
    
    result = agent.extract(
        query=query,
        max_tables=5,
        result_limit=10
    )
    
    if result["success"]:
        print(f"\n✅ 성공! {result['row_count']}행 반환")
        if result["data"] is not None and len(result["data"]) > 0:
            print("\n📊 결과 미리보기:")
            print(result["data"].head())
    else:
        print(f"\n❌ 실패: {result['error']}")


def example_2_simple_filter():
    """
    예시 2: 단순 WHERE 조건
    - 단일 테이블
    - 간단한 필터
    """
    print("\n" + "=" * 80)
    print("📌 예시 2: 단순 필터 (labs 테이블)")
    print("=" * 80)
    
    agent = ExtractionAgent()
    
    # 단순 조건 쿼리
    query = "labs 테이블에서 어떤 검사 항목들이 있는지 item_name 목록을 중복 없이 보여줘"
    
    result = agent.extract(
        query=query,
        max_tables=5,
        result_limit=50
    )
    
    if result["success"]:
        print(f"\n✅ 성공! {result['row_count']}행 반환")
        if result["data"] is not None and len(result["data"]) > 0:
            print("\n📊 검사 항목 목록:")
            print(result["data"])
    else:
        print(f"\n❌ 실패: {result['error']}")


def example_3_count_query():
    """
    예시 3: COUNT 쿼리
    - 단일 테이블
    - 집계 함수
    """
    print("\n" + "=" * 80)
    print("📌 예시 3: COUNT 쿼리 (medications 테이블)")
    print("=" * 80)
    
    agent = ExtractionAgent()
    
    query = "medications 테이블에서 총 몇 개의 투약 기록이 있는지 세어줘"
    
    result = agent.extract(
        query=query,
        max_tables=5,
        result_limit=10
    )
    
    if result["success"]:
        print(f"\n✅ 성공!")
        if result["data"] is not None and len(result["data"]) > 0:
            print(f"📊 결과: {result['data'].iloc[0, 0]} 건")
    else:
        print(f"\n❌ 실패: {result['error']}")


def example_4_group_by():
    """
    예시 4: GROUP BY 쿼리
    - 단일 테이블
    - 그룹화 + 집계
    """
    print("\n" + "=" * 80)
    print("📌 예시 4: GROUP BY (diagnosis 테이블)")
    print("=" * 80)
    
    agent = ExtractionAgent()
    
    query = "diagnosis 테이블에서 각 진단코드(icd10_cm)별로 몇 건씩 있는지 집계해서 보여줘"
    
    result = agent.extract(
        query=query,
        max_tables=5,
        result_limit=20
    )
    
    if result["success"]:
        print(f"\n✅ 성공! {result['row_count']}행 반환")
        if result["data"] is not None and len(result["data"]) > 0:
            print("\n📊 진단코드별 건수:")
            print(result["data"])
    else:
        print(f"\n❌ 실패: {result['error']}")


def example_5_preview_only():
    """
    예시 5: SQL 미리보기만 (실행 X)
    - SQL 생성만 확인
    """
    print("\n" + "=" * 80)
    print("📌 예시 5: SQL 미리보기 (실행하지 않음)")
    print("=" * 80)
    
    agent = ExtractionAgent()
    
    query = "vitals 테이블에서 subject_id가 100인 환자의 모든 바이탈 기록을 시간순으로 보여줘"
    
    result = agent.preview_sql(query)
    
    if result.get("sql"):
        print(f"\n🔍 생성된 SQL:")
        print("-" * 60)
        print(result["sql"])
        print("-" * 60)
        print(f"\n💡 설명: {result['explanation']}")
        print(f"📊 확신도: {result['confidence']:.0%}")
        print(f"📋 사용 테이블: {', '.join(result['tables_used'])}")
    else:
        print(f"\n❌ 실패: {result.get('error')}")


def example_6_specific_patient():
    """
    예시 6: 특정 환자 조회
    - 단일 테이블
    - WHERE 조건
    """
    print("\n" + "=" * 80)
    print("📌 예시 6: 특정 환자 조회 (ward_vitals 테이블)")
    print("=" * 80)
    
    agent = ExtractionAgent()
    
    # 먼저 어떤 subject_id가 있는지 확인하는 쿼리
    query = "ward_vitals 테이블에서 상위 5명의 환자(subject_id)와 그들의 바이탈 기록 수를 보여줘"
    
    result = agent.extract(
        query=query,
        max_tables=5,
        result_limit=5
    )
    
    if result["success"]:
        print(f"\n✅ 성공! {result['row_count']}행 반환")
        if result["data"] is not None and len(result["data"]) > 0:
            print("\n📊 환자별 기록 수:")
            print(result["data"])
    else:
        print(f"\n❌ 실패: {result['error']}")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("🚀 ExtractionAgent 단순 예시 테스트")
    print("=" * 80)
    print("\n현재 DB에 있는 테이블들:")
    print("  - operations_table: 수술 정보")
    print("  - labs_table: 검사 결과")
    print("  - medications_table: 투약 정보")
    print("  - diagnosis_table: 진단 코드")
    print("  - vitals_table: OR 내 바이탈")
    print("  - ward_vitals_table: 병동 바이탈")
    
    # 실행할 예시 선택
    print("\n" + "-" * 40)
    print("실행할 예시 번호를 입력하세요 (1-6, 또는 'all'):")
    print("  1: 단순 SELECT")
    print("  2: 검사 항목 목록")
    print("  3: COUNT 쿼리")
    print("  4: GROUP BY")
    print("  5: SQL 미리보기만")
    print("  6: 특정 환자 조회")
    print("  all: 모든 예시 실행")
    print("-" * 40)
    
    choice = input("선택 >>> ").strip().lower()
    
    try:
        if choice == '1':
            example_1_simple_select()
        elif choice == '2':
            example_2_simple_filter()
        elif choice == '3':
            example_3_count_query()
        elif choice == '4':
            example_4_group_by()
        elif choice == '5':
            example_5_preview_only()
        elif choice == '6':
            example_6_specific_patient()
        elif choice == 'all':
            example_1_simple_select()
            example_2_simple_filter()
            example_3_count_query()
            example_4_group_by()
            example_5_preview_only()
            example_6_specific_patient()
        else:
            print("잘못된 입력입니다. 1-6 또는 'all'을 입력하세요.")
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
