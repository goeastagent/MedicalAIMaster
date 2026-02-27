#!/usr/bin/env python
"""
멀티모델 비교 테스트 스크립트
============================

여러 Ollama 모델 또는 Hugging Face 모델로 QA 테스트를 실행하고 결과를 비교합니다.
기본적으로 현재 설치된 모든 Ollama 모델을 자동으로 테스트합니다.

사용법:
    # 설치된 모든 Ollama 모델 비교 (기본)
    python compare_models.py
    
    # 특정 모델만 비교 (Ollama)
    python compare_models.py --models qwen2.5:7b llama3.1:8b

    # 다른 QA 데이터셋 사용
    python compare_models.py -i testdata/vitaldb_mid_qa_pairs.json

결과물:
    testdata/model_comparison/
    ├── comparison_summary_YYYYMMDD_HHMMSS.xlsx  # 전체 비교표
    ├── results_qwen2.5_7b_YYYYMMDD_HHMMSS.xlsx
    └── ...
"""

import os
import sys
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

import pandas as pd

# 프로젝트 루트 추가
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Ollama Provider 강제 설정 (다른 설정 오버라이드)
os.environ["LLM_PROVIDER"] = "ollama"

from shared.llm import (
    enable_llm_logging,
    switch_model,
    get_current_model_name,
    reset_llm_client
)
from test_qa_dataset import (
    load_qa_pairs,
    run_qa_test,
    setup_logging,
    save_results_to_xlsx
)
from OrchestrationAgent.src.orchestrator import Orchestrator


# ============================================================
# 테스트할 모델 목록
# ============================================================
# 기본값: None = 현재 설치된 모든 Ollama 모델을 자동으로 테스트
# 특정 모델만 테스트하려면 아래 주석을 해제하고 수정하세요.
MODELS_TO_TEST = None  # 설치된 모든 모델 자동 감지

# ============================================================
# 제외할 모델 목록 (이미 테스트 완료된 모델)
# ============================================================
MODELS_TO_EXCLUDE = [
    "codestral:22b",
    "qwen2.5-coder:14b",
    "gpt-oss:20b",
    "qwen2.5-coder:7b",
    "deepseek-coder-v2:16b",
    "starcoder2:7b",
]

# # === 전체 추천 모델 목록 (필요시 주석 해제) ===
# MODELS_TO_TEST = [
#     # === 코딩 특화 모델 ===
#     "qwen2.5-coder:7b",
#     "qwen2.5-coder:14b",
#     "codestral:22b",
#     "deepseek-coder-v2:16b",
#     "starcoder2:7b",
#     "codellama:7b",
#     
#     # === 범용 모델 ===
#     "qwen2.5:7b",
#     "qwen2.5:14b",
#     "qwen2.5:32b",
#     "llama3.1:8b",
#     "mistral:7b",
#     "mixtral:8x7b",
#     "gpt-oss:20b",
# ]


def check_ollama_available() -> bool:
    """Ollama 서버가 실행 중인지 확인"""
    import urllib.request
    import urllib.error
    
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return False


def get_installed_models() -> List[str]:
    """설치된 Ollama 모델 목록 조회"""
    import urllib.request
    import urllib.error
    
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            return [model["name"] for model in data.get("models", [])]
    except Exception:
        return []


def filter_available_models(models: List[str]) -> List[str]:
    """설치된 모델만 필터링하고, 제외 목록에 있는 모델은 스킵"""
    installed = get_installed_models()
    available = []
    unavailable = []
    excluded = []
    
    for model in models:
        # Hugging Face 모델 (슬래시 포함)은 설치 확인 없이 통과
        if "/" in model:
            available.append(model)
            continue

        # 제외 목록 체크
        if model in MODELS_TO_EXCLUDE or any(model in ex or ex in model for ex in MODELS_TO_EXCLUDE):
            excluded.append(model)
            continue
        
        # 모델명 매칭 (태그 포함/미포함 모두 체크)
        if model in installed or any(model in m or m in model for m in installed):
            available.append(model)
        else:
            unavailable.append(model)
    
    if excluded:
        print(f"\n⏭️  이미 테스트 완료된 모델 (스킵됨): {len(excluded)}개")
        for model in excluded:
            print(f"   - {model}")
    
    if unavailable:
        print(f"\n⚠️  설치되지 않은 Ollama 모델 (스킵됨):")
        for model in unavailable:
            print(f"   - {model}")
        print(f"   설치: ollama pull <모델명>")
    
    return available


def run_single_model_test(
    model: str,
    qa_pairs: List[Dict[str, Any]],
    output_dir: Path,
    timestamp: str
) -> Optional[Dict[str, Any]]:
    """
    단일 모델로 QA 테스트 실행
    
    Returns:
        성공 시 요약 정보 dict, 실패 시 None
    """
    print(f"\n{'='*60}")
    print(f"🔄 모델 테스트: {model}")
    print(f"{'='*60}")
    
    try:
        # 1. 모델 변경 (자동 감지: / 포함 시 HF, 아니면 Ollama)
        switch_model(model)
        current = get_current_model_name()
        print(f"   현재 모델: {current}")
        
        # 2. Orchestrator 생성 (매번 새로 생성하여 캐시 초기화)
        orchestrator = Orchestrator()
        
        # 3. QA 테스트 실행
        results = run_qa_test(qa_pairs, orchestrator, verbose=True)
        
        # 4. 개별 결과 저장
        model_safe_name = model.replace(":", "_").replace("/", "_")
        result_file = output_dir / f"results_{model_safe_name}_{timestamp}.xlsx"
        save_results_to_xlsx(results, str(result_file))
        
        # 5. 요약 계산
        total = len(results)
        correct = sum(1 for r in results if r["점수"] == 1)
        accuracy = (correct / total * 100) if total > 0 else 0
        failures = sum(1 for r in results if r["에러메시지"])
        
        summary = {
            "모델": model,
            "정확도(%)": round(accuracy, 2),
            "정답수": correct,
            "총문항": total,
            "실패수": failures,
            "결과파일": result_file.name
        }
        
        print(f"\n✅ {model}: 정확도 {accuracy:.1f}% ({correct}/{total})")
        
        return summary
        
    except Exception as e:
        print(f"\n❌ {model} 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        
        return {
            "모델": model,
            "정확도(%)": "ERROR",
            "정답수": 0,
            "총문항": len(qa_pairs),
            "실패수": len(qa_pairs),
            "결과파일": f"ERROR: {str(e)[:50]}"
        }


def run_model_comparison(
    qa_path: str,
    models: List[str],
    output_dir: str
) -> Dict[str, Any]:
    """
    여러 모델로 QA 테스트 실행 및 비교
    
    Args:
        qa_path: QA 데이터셋 경로
        models: 테스트할 모델 목록
        output_dir: 결과 저장 디렉토리
    
    Returns:
        비교 결과 dict
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # QA 데이터 로드
    qa_pairs = load_qa_pairs(qa_path)
    print(f"\n📚 {len(qa_pairs)}개의 QA 쌍 로드 완료")
    
    # 설치된 모델만 필터링
    available_models = filter_available_models(models)
    
    if not available_models:
        print("\n❌ 테스트 가능한 모델이 없습니다.")
        print("   ollama pull <모델명> 으로 모델을 설치해주세요.")
        return {"error": "No available models"}
    
    print(f"\n🤖 테스트할 모델: {len(available_models)}개")
    for i, model in enumerate(available_models, 1):
        print(f"   {i}. {model}")
    
    # 모델별 결과 수집
    summary_rows = []
    
    for idx, model in enumerate(available_models, 1):
        print(f"\n[{idx}/{len(available_models)}] ", end="")
        
        summary = run_single_model_test(
            model=model,
            qa_pairs=qa_pairs,
            output_dir=output_path,
            timestamp=timestamp
        )
        
        if summary:
            summary_rows.append(summary)
    
    # 비교 요약 저장
    if summary_rows:
        summary_df = pd.DataFrame(summary_rows)
        
        # 정확도 기준 정렬 (ERROR는 맨 뒤로)
        def sort_key(x):
            if isinstance(x, (int, float)):
                return (0, -x)  # 숫자는 내림차순
            return (1, 0)  # ERROR는 맨 뒤
        
        summary_df["_sort"] = summary_df["정확도(%)"].apply(sort_key)
        summary_df = summary_df.sort_values("_sort").drop(columns=["_sort"])
        
        summary_file = output_path / f"comparison_summary_{timestamp}.xlsx"
        summary_df.to_excel(summary_file, index=False)
        
        # 최종 결과 출력
        print_comparison_summary(summary_df)
        
        print(f"\n📁 결과 저장 위치: {output_path}")
        print(f"📊 비교 요약: {summary_file.name}")
        
        return {
            "summary": summary_df,
            "summary_file": str(summary_file),
            "output_dir": str(output_path)
        }
    
    return {"error": "No results"}


def print_comparison_summary(summary_df: pd.DataFrame):
    """비교 결과 콘솔 출력"""
    print("\n" + "=" * 70)
    print("📊 모델 비교 결과 (정확도 순)")
    print("=" * 70)
    print(f"{'모델':<28} | {'정확도':>10} | {'정답':>6} | {'실패':>6}")
    print("-" * 70)
    
    for _, row in summary_df.iterrows():
        acc = row['정확도(%)']
        acc_str = f"{acc:.1f}%" if isinstance(acc, (int, float)) else str(acc)
        correct_str = f"{row['정답수']}/{row['총문항']}"
        
        print(f"{row['모델']:<28} | {acc_str:>10} | {correct_str:>6} | {row['실패수']:>6}")
    
    print("=" * 70)
    
    # 베스트 모델 표시
    valid_rows = summary_df[summary_df['정확도(%)'].apply(lambda x: isinstance(x, (int, float)))]
    if not valid_rows.empty:
        best = valid_rows.iloc[0]
        print(f"\n🏆 최고 성능: {best['모델']} (정확도 {best['정확도(%)']}%)")


def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(
        description="멀티모델 비교 테스트",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python compare_models.py                           # 설치된 모든 Ollama 모델 비교 (기본)
  python compare_models.py --models qwen2.5:7b       # 특정 모델만
  python compare_models.py -i testdata/vitaldb_mid_qa_pairs.json  # 다른 데이터셋
        """
    )
    parser.add_argument(
        "--input", "-i",
        default="testdata/vitaldb_low_qa_pairs.json",
        help="QA 데이터셋 경로 (default: testdata/vitaldb_low_qa_pairs.json)"
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="testdata/model_comparison",
        help="결과 저장 디렉토리 (default: testdata/model_comparison)"
    )
    parser.add_argument(
        "--models", "-m",
        nargs="+",
        default=None,
        help="테스트할 모델 목록 (미지정시 설치된 모든 모델 자동 감지)"
    )
    parser.add_argument(
        "--log-level", "-l",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="WARNING",
        help="로그 레벨 (default: WARNING)"
    )
    parser.add_argument(
        "--no-llm-log",
        action="store_true",
        help="LLM 호출 로깅 비활성화"
    )
    parser.add_argument(
        "--ignore-ollama-check",
        action="store_true",
        help="Ollama 서버 실행 여부 확인 건너뛰기 (HF 모델만 테스트할 때 유용)"
    )
    args = parser.parse_args()
    
    # 로깅 설정
    setup_logging(args.log_level)
    
    # Ollama 서버 확인 (HF 모델만 테스트하는 경우 무시 가능)
    # 모델 목록에 HF 모델('/')이 포함되어 있으면 Ollama 체크를 강제하지 않음
    has_hf_model = args.models and any("/" in m for m in args.models)
    
    if not args.ignore_ollama_check and not has_hf_model:
        if not check_ollama_available():
            print("❌ Ollama 서버가 실행 중이지 않습니다.")
            print("   다른 터미널에서 'ollama serve' 를 실행해주세요.")
            print("   (Hugging Face 모델만 테스트하려면 --ignore-ollama-check 옵션 사용)")
            sys.exit(1)
    
    # LLM 로깅 설정
    if not args.no_llm_log:
        log_session_dir = enable_llm_logging("./data/llm_logs")
        logging.info(f"📝 LLM Logs: {log_session_dir}")
    
    # 입력 파일 확인
    input_path = Path(project_root) / args.input
    if not input_path.exists():
        print(f"❌ 입력 파일을 찾을 수 없습니다: {input_path}")
        sys.exit(1)
    
    # 모델 목록 결정
    if args.models:
        # CLI에서 지정한 모델
        models = args.models
        model_source = "CLI 지정"
    elif MODELS_TO_TEST:
        # 코드에서 지정한 모델
        models = MODELS_TO_TEST
        model_source = "사전 정의"
    else:
        # 설치된 모든 모델 자동 감지
        models = get_installed_models()
        model_source = "자동 감지 (설치된 모델)"
        if not models:
            print("❌ 설치된 Ollama 모델이 없습니다.")
            print("   ollama pull <모델명> 으로 모델을 설치해주세요.")
            sys.exit(1)
    
    # 제외 목록 적용
    # HF 모델은 제외 목록 로직을 타지 않도록 주의
    original_count = len(models)
    
    # HF 모델은 제외 로직에서 보호
    models = [
        m for m in models 
        if "/" in m or (m not in MODELS_TO_EXCLUDE and not any(m in ex or ex in m for ex in MODELS_TO_EXCLUDE))
    ]
    excluded_count = original_count - len(models)
    
    if excluded_count > 0:
        print(f"\n⏭️  이미 테스트 완료된 모델 제외: {excluded_count}개")
        for ex in MODELS_TO_EXCLUDE:
            print(f"   - {ex}")
    
    if not models:
        print("❌ 테스트할 모델이 없습니다. (모든 모델이 제외됨)")
        print("   MODELS_TO_EXCLUDE 목록을 확인해주세요.")
        sys.exit(1)
    
    print("=" * 60)
    print("🧪 멀티모델 비교 테스트")
    print("=" * 60)
    print(f"📚 QA 데이터: {args.input}")
    print(f"📁 출력 디렉토리: {args.output_dir}")
    print(f"🤖 모델 선택: {model_source}")
    print(f"🤖 대상 모델 수: {len(models)}개 (제외: {excluded_count}개)")
    print("=" * 60)
    
    # 비교 실행
    run_model_comparison(
        qa_path=str(input_path),
        models=models,
        output_dir=args.output_dir
    )
    
    print("\n🎉 테스트 완료!")


if __name__ == "__main__":
    main()
