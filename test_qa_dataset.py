#!/usr/bin/env python
"""
QA Dataset 테스트 스크립트
==========================

vitaldb_low_qa_pairs.json 파일을 읽고,
각 question을 OrchestrationAgent에 넣어서 결과를 얻고,
answer와 비교하여 점수를 매깁니다.

결과는 xlsx 파일로 저장되고, 최종 요약 점수가 출력됩니다.
"""

import sys
import json
import logging
import re
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Tuple

import pandas as pd

# 프로젝트 루트 추가
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from OrchestrationAgent.src.orchestrator import Orchestrator


def setup_logging(level: str = "INFO"):
    """로깅 설정"""
    log_level = getattr(logging, level.upper(), logging.INFO)
    
    log_format = "%(asctime)s | %(name)-30s | %(levelname)-8s | %(message)s"
    date_format = "%H:%M:%S"
    
    logging.basicConfig(
        level=log_level,
        format=log_format,
        datefmt=date_format,
        handlers=[logging.StreamHandler()]
    )
    
    # 외부 라이브러리 로그 줄이기
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def load_qa_pairs(json_path: str) -> List[Dict[str, Any]]:
    """QA 데이터셋 로드"""
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_columns_from_code(generated_code: str) -> List[str]:
    """
    생성된 코드에서 실제 사용된 컬럼 추출
    
    Args:
        generated_code: LLM이 생성한 Python 코드
    
    Returns:
        사용된 컬럼명 리스트
    """
    if not generated_code:
        return []
    
    columns = set()
    
    # 패턴 1: df['컬럼명'] 또는 df["컬럼명"]
    pattern1 = r"df\[[\'\"]([^\'\"]+)[\'\"]\]"
    columns.update(re.findall(pattern1, generated_code))
    
    # 패턴 2: signals[...]['컬럼명'] 형태
    pattern2 = r"signals\[[^\]]+\]\[[\'\"]([^\'\"]+)[\'\"]\]"
    columns.update(re.findall(pattern2, generated_code))
    
    # 패턴 3: ['컬럼명'] 형태에서 실제 VitalDB 컬럼 패턴만 추출
    # (Solar8000/HR, Primus/ETCO2 등 슬래시가 포함된 형태)
    pattern3 = r"\[[\'\"]([A-Za-z0-9_]+/[A-Za-z0-9_]+)[\'\"]\]"
    columns.update(re.findall(pattern3, generated_code))
    
    # Time, EVENT 등 기본 컬럼도 포함
    if "'Time'" in generated_code or '"Time"' in generated_code:
        columns.add("Time")
    
    return sorted(list(columns))


def compare_values(expected: Any, actual: Any, format_type: str) -> Tuple[bool, str]:
    """
    기대값과 실제값 비교
    
    Args:
        expected: 기대값 (float 또는 dict)
        actual: 실제값
        format_type: "float" 또는 "dict"
    
    Returns:
        (is_correct, reason)
    """
    if actual is None:
        return False, "실제값이 None"
    
    if format_type == "float":
        # float 비교: 완전히 동일해야 함
        try:
            actual_float = float(actual)
            expected_float = float(expected)
            
            if actual_float == expected_float:
                return True, "정확히 일치"
            else:
                diff = abs(actual_float - expected_float)
                return False, f"불일치 (차이: {diff:.6f})"
        except (TypeError, ValueError) as e:
            return False, f"float 변환 실패: {e}"
    
    elif format_type == "dict":
        # dict 비교: 모든 키가 일치하고 값도 정확히 일치해야 함
        if not isinstance(actual, dict):
            return False, f"실제값이 dict가 아님: {type(actual)}"
        
        expected_keys = set(expected.keys())
        actual_keys = set(actual.keys())
        
        if expected_keys != actual_keys:
            missing = expected_keys - actual_keys
            extra = actual_keys - expected_keys
            return False, f"키 불일치 (누락: {missing}, 추가: {extra})"
        
        mismatches = []
        for key in expected_keys:
            exp_val = float(expected[key])
            try:
                act_val = float(actual[key])
                if exp_val != act_val:
                    mismatches.append(f"{key}: {exp_val} != {act_val}")
            except (TypeError, ValueError):
                mismatches.append(f"{key}: 변환 실패")
        
        if mismatches:
            return False, f"값 불일치: {', '.join(mismatches)}"
        
        return True, "모든 키와 값 일치"
    
    else:
        return False, f"알 수 없는 format: {format_type}"


def run_qa_test(
    qa_pairs: List[Dict[str, Any]],
    orchestrator: Orchestrator,
    verbose: bool = True
) -> List[Dict[str, Any]]:
    """
    QA 테스트 실행
    
    Args:
        qa_pairs: QA 데이터셋
        orchestrator: Orchestrator 인스턴스
        verbose: 상세 출력 여부
    
    Returns:
        테스트 결과 리스트
    """
    results = []
    total = len(qa_pairs)
    
    for idx, qa in enumerate(qa_pairs, 1):
        question = qa["question"]
        # corrected_answer 사용 (없으면 기존 answer 사용)
        expected_answer = qa.get("corrected_answer", qa["answer"])
        format_type = qa["format"]
        expected_param = qa.get("parameter", "N/A")
        
        print(f"\n{'='*60}")
        print(f"[{idx}/{total}] 테스트 중...")
        print(f"질문: {question[:80]}{'...' if len(question) > 80 else ''}")
        print(f"기대값: {expected_answer} (정답컬럼: {expected_param})")
        print(f"형식: {format_type}")
        print("-" * 60)
        
        # Orchestrator 실행
        try:
            result = orchestrator.run(question)
            
            if result.status == "success":
                actual_answer = result.result
                generated_code = result.generated_code
                execution_time = result.execution_time_ms
                error_message = None
                
                # param_keys 추출 (Parameter Resolver가 매핑한 컬럼)
                mapped_param_keys = []
                if result.data_summary and isinstance(result.data_summary, dict):
                    mapped_param_keys = result.data_summary.get("param_keys", [])
                
                # 생성된 코드에서 실제 사용된 컬럼 추출
                code_used_columns = extract_columns_from_code(generated_code)
                
                # 두 소스 병합 (중복 제거)
                used_param_keys = sorted(list(set(mapped_param_keys + code_used_columns)))
                
                # 값 비교
                is_correct, reason = compare_values(expected_answer, actual_answer, format_type)
                
            else:
                actual_answer = None
                generated_code = result.generated_code
                execution_time = result.execution_time_ms
                error_message = result.error_message
                is_correct = False
                reason = f"실행 실패: {error_message}"
                
                # 실패 시에도 컬럼 추출 시도
                mapped_param_keys = []
                if result.data_summary and isinstance(result.data_summary, dict):
                    mapped_param_keys = result.data_summary.get("param_keys", [])
                code_used_columns = extract_columns_from_code(generated_code)
                used_param_keys = sorted(list(set(mapped_param_keys + code_used_columns)))
                
        except Exception as e:
            actual_answer = None
            generated_code = None
            execution_time = None
            error_message = str(e)
            is_correct = False
            reason = f"예외 발생: {e}"
            used_param_keys = []
        
        # 컬럼 일치 여부 확인
        param_match = expected_param in used_param_keys if used_param_keys and expected_param != "N/A" else None
        
        # 결과 저장
        test_result = {
            "번호": idx,
            "질문": question,
            "기대값": str(expected_answer),
            "실제값": str(actual_answer) if actual_answer is not None else "N/A",
            "형식": format_type,
            "정답여부": "O" if is_correct else "X",
            "점수": 1 if is_correct else 0,
            "사유": reason,
            "정답컬럼": expected_param,
            "사용컬럼": ", ".join(used_param_keys) if used_param_keys else "N/A",
            "컬럼일치": "O" if param_match else ("X" if param_match is False else "N/A"),
            "실행시간(ms)": execution_time,
            "에러메시지": error_message if error_message else "",
            "생성코드": generated_code if generated_code else ""
        }
        results.append(test_result)
        
        # 출력
        status_emoji = "✅" if is_correct else "❌"
        param_emoji = "✅" if param_match else ("❌" if param_match is False else "⚠️")
        print(f"실제값: {actual_answer}")
        print(f"정답컬럼: {expected_param} | 사용컬럼: {', '.join(used_param_keys) if used_param_keys else 'N/A'} {param_emoji}")
        print(f"결과: {status_emoji} {reason}")
        if execution_time:
            print(f"실행시간: {execution_time:.1f}ms")
    
    return results


def save_results_to_xlsx(
    results: List[Dict[str, Any]],
    output_path: str
):
    """
    결과를 xlsx 파일로 저장 (상세 결과 + 요약)
    
    Args:
        results: 테스트 결과 리스트
        output_path: 출력 파일 경로
    """
    # 상세 결과 DataFrame
    df_details = pd.DataFrame(results)
    
    # 요약 계산
    total_count = len(results)
    correct_count = sum(1 for r in results if r["점수"] == 1)
    incorrect_count = total_count - correct_count
    accuracy = (correct_count / total_count * 100) if total_count > 0 else 0
    
    avg_time = pd.Series([r["실행시간(ms)"] for r in results if r["실행시간(ms)"]]).mean()
    
    # 형식별 정확도
    float_results = [r for r in results if r["형식"] == "float"]
    dict_results = [r for r in results if r["형식"] == "dict"]
    
    float_correct = sum(1 for r in float_results if r["점수"] == 1)
    dict_correct = sum(1 for r in dict_results if r["점수"] == 1)
    
    # 요약 DataFrame
    summary_data = {
        "항목": [
            "총 문항 수",
            "정답 수",
            "오답 수",
            "정확도 (%)",
            "평균 실행시간 (ms)",
            "",
            "Float 문항 수",
            "Float 정답 수",
            "Float 정확도 (%)",
            "",
            "Dict 문항 수",
            "Dict 정답 수",
            "Dict 정확도 (%)",
        ],
        "값": [
            total_count,
            correct_count,
            incorrect_count,
            f"{accuracy:.2f}",
            f"{avg_time:.2f}" if pd.notna(avg_time) else "N/A",
            "",
            len(float_results),
            float_correct,
            f"{(float_correct/len(float_results)*100):.2f}" if float_results else "N/A",
            "",
            len(dict_results),
            dict_correct,
            f"{(dict_correct/len(dict_results)*100):.2f}" if dict_results else "N/A",
        ]
    }
    df_summary = pd.DataFrame(summary_data)
    
    # xlsx 저장 (여러 시트)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df_summary.to_excel(writer, sheet_name="요약", index=False)
        df_details.to_excel(writer, sheet_name="상세결과", index=False)
    
    print(f"\n📁 결과 저장: {output_path}")


def print_summary(results: List[Dict[str, Any]]):
    """최종 요약 출력"""
    total_count = len(results)
    correct_count = sum(1 for r in results if r["점수"] == 1)
    accuracy = (correct_count / total_count * 100) if total_count > 0 else 0
    
    print("\n" + "=" * 60)
    print("📊 최종 요약")
    print("=" * 60)
    print(f"총 문항 수: {total_count}")
    print(f"정답 수: {correct_count}")
    print(f"오답 수: {total_count - correct_count}")
    print(f"정확도: {accuracy:.2f}%")
    print("=" * 60)
    
    # 오답 목록 출력
    incorrect = [r for r in results if r["점수"] == 0]
    if incorrect:
        print("\n❌ 오답 목록:")
        for r in incorrect:
            print(f"  [{r['번호']}] {r['질문'][:50]}...")
            print(f"       사유: {r['사유']}")


def clear_all_caches():
    """캐시 관련 안내 (인스턴스 레벨 캐시로 변경됨)"""
    # 캐시가 이제 인스턴스 레벨이므로 수동 초기화 불필요
    # 각 DataContext 인스턴스가 독립된 캐시를 가짐
    print("ℹ️  캐시: 인스턴스 레벨 (각 DataContext 독립)")


def main():
    """메인 함수"""
    import argparse
    
    parser = argparse.ArgumentParser(description="QA Dataset 테스트")
    parser.add_argument(
        "--input", "-i",
        default="testdata/vitaldb_low_qa_pairs.json",
        help="입력 QA 데이터셋 경로 (default: testdata/vitaldb_low_qa_pairs.json)"
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="출력 xlsx 파일 경로 (default: testdata/qa_test_results_YYYYMMDD_HHMMSS.xlsx)"
    )
    parser.add_argument(
        "--log-level", "-l",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="로그 레벨 (default: INFO)"
    )
    args = parser.parse_args()
    
    # 캐시 초기화 (테스트 시작 전)
    clear_all_caches()
    
    # 로깅 설정
    setup_logging(args.log_level)
    
    # LLM 로깅 활성화 (생성된 코드, 프롬프트, 응답 저장)
    from shared.llm import enable_llm_logging
    log_session_dir = enable_llm_logging("./data/llm_logs")
    logging.info(f"📝 LLM Logs: {log_session_dir}")
    
    # 입력 파일 경로
    input_path = Path(project_root) / args.input
    if not input_path.exists():
        print(f"❌ 입력 파일을 찾을 수 없습니다: {input_path}")
        sys.exit(1)
    
    # 출력 파일 경로
    if args.output:
        output_path = args.output
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path(project_root) / f"testdata/qa_test_results_{timestamp}.xlsx"
    
    print("=" * 60)
    print("🧪 QA Dataset 테스트 시작")
    print("=" * 60)
    print(f"입력 파일: {input_path}")
    print(f"출력 파일: {output_path}")
    print("=" * 60)
    
    # QA 데이터 로드
    qa_pairs = load_qa_pairs(str(input_path))
    print(f"\n📚 {len(qa_pairs)}개의 QA 쌍 로드 완료")
    
    # Orchestrator 생성
    orchestrator = Orchestrator()
    
    # 테스트 실행
    results = run_qa_test(qa_pairs, orchestrator)
    
    # 결과 저장
    save_results_to_xlsx(results, str(output_path))
    
    # 최종 요약 출력
    print_summary(results)


if __name__ == "__main__":
    main()
