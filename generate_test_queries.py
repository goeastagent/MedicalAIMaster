#!/usr/bin/env python3
"""
생체신호 분석 테스트 질의 생성 스크립트
ChatGPT를 사용하여 페르소나별 테스트 질의를 생성합니다.
"""

import json
from datetime import datetime
from openai import OpenAI

# ============================================
# 설정
# ============================================
API_KEY = "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"
MODEL = "gpt-5.2-2025-12-11"

# ============================================
# 페르소나 정의
# ============================================
EXPERTISE_LEVELS = {
    "상급자": "해당 분야에서 10년 이상의 경험을 가진 전문가",
    "중급자": "해당 분야에서 3-5년의 경험을 가진 실무자",
    "하급자": "해당 분야 초보자 또는 비전문가"
}

ROLES = {
    "임상의": "환자를 직접 진료하는 의사",
    "데이터_사이언티스트": "의료 데이터를 분석하는 전문가",
    "환자": "자신의 건강 데이터를 이해하고 싶어하는 일반인"
}

# 페르소나당 생성할 질의 개수
QUERIES_PER_PERSONA = 3

# ============================================
# 시스템 프롬프트
# ============================================
SYSTEM_PROMPT = """당신은 생체신호 분석 시스템의 테스트 데이터를 만드는 전문가입니다.

주어진 페르소나(전문성 수준 + 역할)에 맞는 질의를 생성해주세요.
생체신호 분석 시스템에 물어볼 만한 현실적인 질문을 만들어주세요.

생체신호 종류: ECG, 혈압(ABP), 심박수(HR), SpO2, 호흡수, HRV, EEG, EMG, 체온 등
분석 가능한 것: 패턴 감지, 이상 탐지, 추세 분석, 통계 요약, 시각화, 예측 등

응답은 반드시 아래 JSON 형식으로만 출력하세요:
{
    "queries": [
        "질의1",
        "질의2",
        "질의3"
    ]
}"""


def create_user_prompt(expertise: str, expertise_desc: str, role: str, role_desc: str, count: int) -> str:
    """사용자 프롬프트 생성"""
    return f"""다음 페르소나가 생체신호 분석 시스템에 물어볼 만한 질의를 {count}개 생성해주세요.

페르소나:
- 전문성 수준: {expertise} ({expertise_desc})
- 역할: {role} ({role_desc})

해당 페르소나의 지식 수준과 관심사에 맞는 현실적인 질문을 만들어주세요."""


def call_chatgpt(client: OpenAI, expertise: str, role: str) -> list:
    """ChatGPT API 호출"""
    user_prompt = create_user_prompt(
        expertise=expertise,
        expertise_desc=EXPERTISE_LEVELS[expertise],
        role=role,
        role_desc=ROLES[role],
        count=QUERIES_PER_PERSONA
    )
    
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.9,
        response_format={"type": "json_object"}
    )
    
    result = json.loads(response.choices[0].message.content)
    return result.get("queries", [])


def main():
    """메인 실행 함수"""
    client = OpenAI(api_key=API_KEY)
    results = []
    query_id = 0
    
    total_personas = len(EXPERTISE_LEVELS) * len(ROLES)
    count = 0
    
    for expertise in EXPERTISE_LEVELS:
        for role in ROLES:
            count += 1
            print(f"[{count}/{total_personas}] 생성 중: {expertise} {role}...")
            
            try:
                queries = call_chatgpt(client, expertise, role)
                
                for query in queries:
                    query_id += 1
                    results.append({
                        "id": query_id,
                        "query": query,
                        "persona": {
                            "expertise_level": expertise,
                            "role": role
                        }
                    })
                    
            except Exception as e:
                print(f"  에러 발생: {e}")
    
    # JSON 파일로 저장
    output_file = f"test_queries_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "model": MODEL,
            "total_count": len(results),
            "results": results
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\n완료! {output_file}에 {len(results)}개의 테스트 질의가 저장되었습니다.")


if __name__ == "__main__":
    main()
