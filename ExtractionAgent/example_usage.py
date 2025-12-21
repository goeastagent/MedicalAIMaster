#!/usr/bin/env python3
"""
ExtractionAgent 사용 예시

자연어 질의를 SQL로 변환하고 데이터를 추출하는 예시입니다.
"""

import sys
import os

# IndexingAgent의 경로 추가 (환경변수 설정용)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../IndexingAgent'))

from dotenv import load_dotenv
load_dotenv()  # .env 파일 로드

from src.extraction_agent import ExtractionAgent


def example_basic():
    """기본 사용 예시"""
    print("\n" + "=" * 80)
    print("예시 1: 기본 사용")
    print("=" * 80)
    
    agent = ExtractionAgent(output_dir="output")
    
    query = "지난 24시간 동안 동일 환자(subject_id)에 대해 병동 바이탈, 일반 바이탈, 최근 랩(젖산/칼륨), 투약(바소프레서), 진단 코드까지 한 번에 묶어서 타임라인으로 보여줘."
    
    result = agent.extract(
        query=query,
        max_tables=20,
        result_limit=1000,
        auto_save=True,
        save_format="csv"
    )
    
    if result["success"]:
        print(f"\n✅ 성공!")
        print(f"   - 반환된 행 수: {result['row_count']:,}")
        print(f"   - 저장된 파일: {result['saved_files']}")
    else:
        print(f"\n❌ 실패: {result['error']}")


def example_preview_sql():
    """SQL 미리보기 예시"""
    print("\n" + "=" * 80)
    print("예시 2: SQL 미리보기 (실행하지 않음)")
    print("=" * 80)
    
    agent = ExtractionAgent()
    
    query = "수술 케이스별(op_id)로 최근 7일간 수술 정보 + 시술 직전/직후 2시간 내 바이탈, 시술 당일 투약/검사 결과, 진단 코드까지 모두 조인해서 보고 싶다."
    
    result = agent.preview_sql(query)
    
    if result.get("sql"):
        print(f"\n생성된 SQL:")
        print("-" * 80)
        print(result["sql"])
        print("-" * 80)
        print(f"\n설명: {result['explanation']}")
        print(f"확신도: {result['confidence']:.2%}")
        print(f"사용된 테이블: {', '.join(result['tables_used'])}")
    else:
        print(f"\n❌ 실패: {result.get('error')}")


def example_custom_format():
    """커스텀 형식으로 저장 예시"""
    print("\n" + "=" * 80)
    print("예시 3: 여러 형식으로 저장")
    print("=" * 80)
    
    agent = ExtractionAgent(output_dir="output")
    
    query = "중환자/병동 전환 패턴: 최근 48시간 이내 ward_vitals와 일반 vitals를 모두 가진 환자들 중, 동일 subject_id에서 고위험 약물(바소프레서) 투약과 젖산 상승(lactate) 검사가 같이 보이는 시점을 찾아라."
    
    result = agent.extract_and_save(
        query=query,
        filename="critical_patients",
        format="excel",  # Excel 형식으로 저장
        result_limit=5000
    )
    
    if result["success"]:
        print(f"\n✅ 성공!")
        print(f"   - 반환된 행 수: {result['row_count']:,}")
        print(f"   - 저장된 파일: {result['saved_files']}")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("ExtractionAgent 사용 예시")
    print("=" * 80)
    
    # 예시 실행
    try:
        example_basic()
        example_preview_sql()
        example_custom_format()
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()

