#!/usr/bin/env python3
"""
LLM Log Viewer

LLM 호출 로그를 보기 쉽게 출력하는 뷰어입니다.

사용법:
    # 최신 세션의 모든 로그 보기
    python view_llm_logs.py
    
    # 특정 세션 지정
    python view_llm_logs.py --session session_20260101_123456
    
    # 특정 호출만 보기
    python view_llm_logs.py --call 3
    
    # 요약만 보기 (프롬프트/응답 생략)
    python view_llm_logs.py --summary
    
    # 프롬프트만 보기
    python view_llm_logs.py --call 3 --prompt-only
    
    # 응답만 보기
    python view_llm_logs.py --call 3 --response-only
"""

import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any


# 색상 코드 (터미널 출력용)
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'


def colorize(text: str, color: str) -> str:
    """텍스트에 색상 적용"""
    return f"{color}{text}{Colors.END}"


def print_separator(char: str = "─", length: int = 80, color: str = Colors.DIM):
    """구분선 출력"""
    print(colorize(char * length, color))


def print_header(text: str):
    """헤더 출력"""
    print()
    print_separator("═", 80, Colors.CYAN)
    print(colorize(f"  {text}", Colors.BOLD + Colors.CYAN))
    print_separator("═", 80, Colors.CYAN)


def print_subheader(text: str):
    """서브헤더 출력"""
    print()
    print(colorize(f"▶ {text}", Colors.BOLD + Colors.YELLOW))
    print_separator("─", 60, Colors.DIM)


def format_prompt(prompt: str, max_lines: int = 50) -> str:
    """프롬프트 포맷팅"""
    lines = prompt.split('\n')
    if len(lines) > max_lines:
        return '\n'.join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} more lines)"
    return prompt


def format_response(response: Any) -> str:
    """응답 포맷팅 (JSON이면 pretty print)"""
    if isinstance(response, dict):
        return json.dumps(response, ensure_ascii=False, indent=2)
    elif isinstance(response, list):
        return json.dumps(response, ensure_ascii=False, indent=2)
    return str(response)


def find_latest_session(log_dir: Path) -> Optional[Path]:
    """가장 최근 세션 디렉토리 찾기"""
    sessions = sorted(log_dir.glob("session_*"), reverse=True)
    return sessions[0] if sessions else None


def list_sessions(log_dir: Path) -> List[Path]:
    """모든 세션 목록"""
    return sorted(log_dir.glob("session_*"), reverse=True)


def load_log_file(filepath: Path) -> Dict[str, Any]:
    """로그 파일 로드"""
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def print_log_summary(log: Dict[str, Any], show_preview: bool = True):
    """단일 로그 요약 출력"""
    call_id = log.get('call_id', '?')
    method = log.get('method', '?')
    model = log.get('model', '?')
    duration = log.get('duration_seconds', 0)
    timestamp = log.get('timestamp', '')
    
    # 시간 포맷
    try:
        dt = datetime.fromisoformat(timestamp)
        time_str = dt.strftime("%H:%M:%S")
    except:
        time_str = timestamp[:8] if timestamp else "?"
    
    # 프롬프트 미리보기
    prompt = log.get('input', {}).get('prompt', '')
    prompt_preview = prompt[:60].replace('\n', ' ') + "..." if len(prompt) > 60 else prompt.replace('\n', ' ')
    prompt_lines = len(prompt.split('\n'))
    prompt_chars = len(prompt)
    
    # 응답 미리보기
    response = log.get('output', {}).get('response', '')
    if isinstance(response, dict):
        response_preview = json.dumps(response, ensure_ascii=False)[:60] + "..."
        response_chars = len(json.dumps(response, ensure_ascii=False))
    else:
        response_preview = str(response)[:60].replace('\n', ' ') + "..."
        response_chars = len(str(response))
    
    # 에러 여부
    error = log.get('error')
    status = colorize("✗ ERROR", Colors.RED) if error else colorize("✓", Colors.GREEN)
    
    # 출력
    print(f"\n{colorize(f'[Call #{call_id:03d}]', Colors.BOLD + Colors.BLUE)} {time_str} | {method} | {model} | {duration:.2f}s {status}")
    
    if show_preview:
        print(f"  {colorize('Prompt:', Colors.DIM)} ({prompt_lines} lines, {prompt_chars:,} chars)")
        print(f"    {colorize(prompt_preview, Colors.DIM)}")
        print(f"  {colorize('Response:', Colors.DIM)} ({response_chars:,} chars)")
        print(f"    {colorize(response_preview, Colors.DIM)}")
    
    if error:
        print(f"  {colorize('Error:', Colors.RED)} {error}")


def print_log_detail(log: Dict[str, Any], prompt_only: bool = False, response_only: bool = False):
    """단일 로그 상세 출력"""
    call_id = log.get('call_id', '?')
    method = log.get('method', '?')
    model = log.get('model', '?')
    duration = log.get('duration_seconds', 0)
    timestamp = log.get('timestamp', '')
    max_tokens = log.get('input', {}).get('max_tokens')
    error = log.get('error')
    
    print_header(f"LLM Call #{call_id:03d} - {method}")
    
    # 메타정보
    print(f"\n{colorize('Timestamp:', Colors.BOLD)}  {timestamp}")
    print(f"{colorize('Model:', Colors.BOLD)}      {model}")
    print(f"{colorize('Duration:', Colors.BOLD)}   {duration:.3f} seconds")
    if max_tokens:
        print(f"{colorize('Max Tokens:', Colors.BOLD)} {max_tokens}")
    if error:
        print(f"{colorize('Error:', Colors.BOLD + Colors.RED)}     {error}")
    
    # 프롬프트
    if not response_only:
        prompt = log.get('input', {}).get('prompt', '')
        print_subheader(f"INPUT PROMPT ({len(prompt):,} chars, {len(prompt.split(chr(10)))} lines)")
        print(format_prompt(prompt))
    
    # 응답
    if not prompt_only:
        response = log.get('output', {}).get('response', '')
        response_str = format_response(response)
        print_subheader(f"OUTPUT RESPONSE ({len(response_str):,} chars)")
        print(response_str)
    
    print()
    print_separator("═", 80, Colors.CYAN)


def print_session_summary(session_dir: Path, logs: List[Dict[str, Any]]):
    """세션 요약 통계"""
    print_header(f"Session: {session_dir.name}")
    
    total_calls = len(logs)
    total_duration = sum(log.get('duration_seconds', 0) for log in logs)
    total_prompt_chars = sum(len(log.get('input', {}).get('prompt', '')) for log in logs)
    total_response_chars = sum(
        len(json.dumps(log.get('output', {}).get('response', ''), ensure_ascii=False) 
            if isinstance(log.get('output', {}).get('response'), (dict, list)) 
            else str(log.get('output', {}).get('response', '')))
        for log in logs
    )
    errors = sum(1 for log in logs if log.get('error'))
    
    # 메서드별 통계
    methods = {}
    for log in logs:
        method = log.get('method', 'unknown')
        methods[method] = methods.get(method, 0) + 1
    
    print(f"\n{colorize('📊 Statistics:', Colors.BOLD)}")
    print(f"   Total Calls:      {total_calls}")
    print(f"   Total Duration:   {total_duration:.2f} seconds ({total_duration/60:.1f} min)")
    print(f"   Avg Duration:     {total_duration/total_calls:.2f}s" if total_calls > 0 else "")
    print(f"   Total Prompt:     {total_prompt_chars:,} chars")
    print(f"   Total Response:   {total_response_chars:,} chars")
    print(f"   Errors:           {errors}")
    print(f"\n{colorize('📋 By Method:', Colors.BOLD)}")
    for method, count in methods.items():
        print(f"   {method}: {count}")


def main():
    parser = argparse.ArgumentParser(
        description="LLM Log Viewer - LLM 호출 로그를 보기 쉽게 출력",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python view_llm_logs.py                     # 최신 세션 요약
  python view_llm_logs.py --list              # 모든 세션 목록
  python view_llm_logs.py --call 3            # 3번째 호출 상세 보기
  python view_llm_logs.py --call 3 --prompt-only   # 프롬프트만
  python view_llm_logs.py --call 3 --response-only # 응답만
  python view_llm_logs.py --all               # 모든 호출 상세 보기
  python view_llm_logs.py --summary           # 요약만 (미리보기 없음)
        """
    )
    
    parser.add_argument('--log-dir', type=str, default='./data/llm_logs',
                        help='로그 디렉토리 경로 (기본: ./data/llm_logs)')
    parser.add_argument('--session', type=str, default=None,
                        help='특정 세션 지정 (예: session_20260101_123456)')
    parser.add_argument('--list', action='store_true',
                        help='모든 세션 목록 출력')
    parser.add_argument('--call', type=int, default=None,
                        help='특정 호출 번호 상세 보기')
    parser.add_argument('--all', action='store_true',
                        help='모든 호출 상세 보기')
    parser.add_argument('--summary', action='store_true',
                        help='요약만 보기 (프롬프트/응답 미리보기 생략)')
    parser.add_argument('--prompt-only', action='store_true',
                        help='프롬프트만 보기 (--call과 함께 사용)')
    parser.add_argument('--response-only', action='store_true',
                        help='응답만 보기 (--call과 함께 사용)')
    parser.add_argument('--no-color', action='store_true',
                        help='색상 출력 비활성화')
    
    args = parser.parse_args()
    
    # 색상 비활성화
    if args.no_color:
        for attr in dir(Colors):
            if not attr.startswith('_'):
                setattr(Colors, attr, '')
    
    log_dir = Path(args.log_dir)
    
    if not log_dir.exists():
        print(f"❌ Log directory not found: {log_dir}")
        print(f"   Run enable_llm_logging() first to create logs.")
        sys.exit(1)
    
    # 세션 목록 출력
    if args.list:
        sessions = list_sessions(log_dir)
        print_header("LLM Log Sessions")
        if not sessions:
            print("\n  No sessions found.")
        else:
            for session in sessions:
                log_files = sorted(session.glob("*.json"))
                total_calls = len(log_files)
                
                # 첫번째/마지막 로그에서 시간 정보
                if log_files:
                    first_log = load_log_file(log_files[0])
                    last_log = load_log_file(log_files[-1])
                    start_time = first_log.get('timestamp', '')[:19]
                    end_time = last_log.get('timestamp', '')[:19]
                    print(f"\n  📁 {session.name}")
                    print(f"     Calls: {total_calls}")
                    print(f"     Time: {start_time} ~ {end_time}")
                else:
                    print(f"\n  📁 {session.name} (empty)")
        return
    
    # 세션 디렉토리 결정
    if args.session:
        session_dir = log_dir / args.session
        if not session_dir.exists():
            # session_ 접두사 없이 입력한 경우
            session_dir = log_dir / f"session_{args.session}"
        if not session_dir.exists():
            print(f"❌ Session not found: {args.session}")
            sys.exit(1)
    else:
        session_dir = find_latest_session(log_dir)
        if not session_dir:
            print(f"❌ No sessions found in {log_dir}")
            sys.exit(1)
    
    # 로그 파일 로드
    log_files = sorted(session_dir.glob("*.json"))
    if not log_files:
        print(f"❌ No log files in session: {session_dir.name}")
        sys.exit(1)
    
    logs = [load_log_file(f) for f in log_files]
    
    # 특정 호출 보기
    if args.call is not None:
        matching_logs = [log for log in logs if log.get('call_id') == args.call]
        if not matching_logs:
            print(f"❌ Call #{args.call} not found in session")
            sys.exit(1)
        print_log_detail(matching_logs[0], args.prompt_only, args.response_only)
        return
    
    # 모든 호출 상세 보기
    if args.all:
        print_session_summary(session_dir, logs)
        for log in logs:
            print_log_detail(log, args.prompt_only, args.response_only)
        return
    
    # 기본: 세션 요약 + 각 호출 요약
    print_session_summary(session_dir, logs)
    print_subheader("Call List")
    for log in logs:
        print_log_summary(log, show_preview=not args.summary)


if __name__ == "__main__":
    main()

