#!/usr/bin/env python3
# test_llm_client.py
"""
LLM Client 테스트 코드
환자 데이터에서 Anchor 컬럼(환자 ID)을 찾는 예시
"""

import sys
import os

# src 디렉토리를 Python 경로에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from utils.llm_client import get_llm_client


def test_find_anchor_column():
    """
    데이터 요약을 보고 환자 ID 컬럼을 찾는 테스트
    """
    print("=" * 60)
    print("LLM Client 테스트: Anchor 컬럼 찾기")
    print("=" * 60)
    
    # 1. 클라이언트 생성 (config에 따라 자동 결정)
    print("\n[Step 1] LLM 클라이언트 생성 중...")
    try:
        llm = get_llm_client()
        print(f"✓ 클라이언트 생성 완료: {llm.__class__.__name__}")
    except Exception as e:
        print(f"✗ 클라이언트 생성 실패: {e}")
        return
    
    # 2. 프롬프트 작성 (Anchor 찾기 예시)
    print("\n[Step 2] 프롬프트 작성 및 전송...")
    prompt = """
다음 데이터 요약을 보고 환자 ID 컬럼을 찾아서 JSON으로 답해줘:

데이터 요약:
- 컬럼명: 'pid', 샘플 값: ['P001', 'P002', 'P003']
- 컬럼명: 'age', 샘플 값: [45, 67, 32]
- 컬럼명: 'gender', 샘플 값: ['M', 'F', 'M']
- 컬럼명: 'admission_date', 샘플 값: ['2023-01-15', '2023-02-20', '2023-03-10']
- 컬럼명: 'diagnosis', 샘플 값: ['Hypertension', 'Diabetes', 'Asthma']

위 컬럼들 중 환자를 고유하게 식별하는 Anchor 컬럼을 찾아서 다음 형식으로 답변:
{
    "found_anchor": true 또는 false,
    "column_name": "컬럼명",
    "confidence": "high/medium/low",
    "reasoning": "이 컬럼을 선택한 이유"
}
"""
    
    # 3. 결과 받기 (항상 Python Dictionary 형태)
    print("LLM에 질의 중...")
    try:
        result = llm.ask_json(prompt)
        print(f"✓ 응답 수신 완료")
    except Exception as e:
        print(f"✗ LLM 질의 실패: {e}")
        return
    
    # 4. 결과 출력
    print("\n[Step 3] 결과 분석")
    print("-" * 60)
    if "error" in result:
        print(f"✗ 에러 발생: {result.get('error')}")
        if "raw_text" in result:
            print(f"원본 응답:\n{result['raw_text']}")
    else:
        print(f"✓ Anchor 발견 여부: {result.get('found_anchor', 'N/A')}")
        print(f"✓ 컬럼명: {result.get('column_name', 'N/A')}")
        print(f"✓ 신뢰도: {result.get('confidence', 'N/A')}")
        print(f"✓ 이유: {result.get('reasoning', 'N/A')}")
    
    print("\n전체 응답 (JSON):")
    import json
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("=" * 60)


def test_simple_query():
    """
    간단한 텍스트 질의 테스트
    """
    print("\n" + "=" * 60)
    print("LLM Client 테스트: 간단한 질의")
    print("=" * 60)
    
    try:
        llm = get_llm_client()
        print(f"\n사용 중인 클라이언트: {llm.__class__.__name__}")
        
        prompt = "Hello! Please respond with a simple greeting."
        print(f"\n질의: {prompt}")
        
        response = llm.ask_text(prompt)
        print(f"\n응답:\n{response}")
        print("=" * 60)
    except Exception as e:
        print(f"✗ 테스트 실패: {e}")


if __name__ == "__main__":
    print("\n🚀 LLM Client 테스트 시작\n")
    
    # 테스트 1: Anchor 컬럼 찾기 (JSON 응답)
    test_find_anchor_column()
    
    # 테스트 2: 간단한 텍스트 질의
    # test_simple_query()
    
    print("\n✅ 테스트 완료\n")

