#!/usr/bin/env python3
"""
Phase 1 Human Review 테스트

LLM response와 Human feedback이 어떻게 교환되는지 확인하는 테스트입니다.

실행:
    cd IndexingAgent
    python test_phase1_review.py
"""

import os
import sys
import json
from datetime import datetime
from typing import Dict, Any

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import Phase1Config
from src.database.connection import get_db_manager
from src.database.schema_catalog import init_catalog_schema


# =============================================================================
# 유틸리티: 예쁜 출력
# =============================================================================

def print_separator(title: str = "", char: str = "=", width: int = 80):
    """구분선 출력"""
    if title:
        padding = (width - len(title) - 2) // 2
        print(f"\n{char * padding} {title} {char * padding}")
    else:
        print(char * width)


def print_json(data: Dict[str, Any], title: str = ""):
    """JSON을 예쁘게 출력"""
    if title:
        print(f"\n📦 {title}:")
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def print_mappings(mappings: list, title: str = "LLM Mappings"):
    """매핑 결과 출력"""
    print(f"\n📊 {title} ({len(mappings)} items):")
    for i, m in enumerate(mappings[:10], 1):  # 처음 10개만
        if 'original' in m:
            # Column mapping
            print(f"   {i}. {m.get('original', '?'):30} → {m.get('semantic', '?'):25} "
                  f"[{m.get('concept', '?'):15}] conf={m.get('confidence', 0):.2f}")
        elif 'file_name' in m:
            # File mapping
            print(f"   {i}. {m.get('file_name', '?'):30} → {m.get('semantic_type', '?'):20} "
                  f"[{m.get('domain', '?'):15}] conf={m.get('confidence', 0):.2f}")
    if len(mappings) > 10:
        print(f"   ... and {len(mappings) - 10} more")


# =============================================================================
# Interactive Human Feedback 시뮬레이션
# =============================================================================

def get_interactive_feedback(review_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    사용자로부터 피드백을 받는 대화형 함수
    
    실제 운영에서는 Web UI나 CLI로 구현됩니다.
    """
    print_separator("🔍 HUMAN REVIEW REQUIRED", "!", 80)
    
    print(f"\n📋 Review Information:")
    print(f"   Type: {review_info.get('type', '?')}")
    print(f"   Batch: {review_info.get('batch_index', 0) + 1}")
    print(f"   Retry: {review_info.get('retry_count', 0)}/{review_info.get('max_retries', 3)}")
    print(f"   Avg Confidence: {review_info.get('avg_confidence', 0):.2f}")
    print(f"   Low Conf Count: {review_info.get('low_conf_count', 0)}")
    
    # Low confidence 항목들 출력
    low_items = review_info.get('low_conf_items', [])
    if low_items:
        print(f"\n⚠️ Low Confidence Items:")
        for item in low_items[:10]:
            print(f"      - {item}")
        if len(low_items) > 10:
            print(f"      ... and {len(low_items) - 10} more")
    
    # 현재 매핑 결과 출력
    current_mappings = review_info.get('current_mappings', [])
    if current_mappings:
        print_mappings(current_mappings, "Current LLM Analysis")
    
    print(f"\n💬 Message: {review_info.get('message', '')}")
    
    # 옵션 출력
    print("\n" + "-" * 60)
    print("📝 Available Actions:")
    print("   [1] accept  - Accept current results as-is")
    print("   [2] correct - Provide corrections and re-analyze")
    print("   [3] skip    - Skip this batch (don't save to DB)")
    print("-" * 60)
    
    # 사용자 입력
    while True:
        choice = input("\n🎯 Select action (1/2/3) or 'q' to quit: ").strip().lower()
        
        if choice == 'q':
            print("\n⛔ User requested quit")
            sys.exit(0)
        
        if choice == '1' or choice == 'accept':
            return {"action": "accept"}
        
        elif choice == '2' or choice == 'correct':
            # 수정 사항 입력
            print("\n✏️ Enter corrections (JSON format):")
            print("   Example for column:")
            print('   {"column_corrections": [{"original_name": "ane_type", "correct_semantic": "Anesthesia Type", "hint": "마취 유형"}]}')
            print("   Example for file:")
            print('   {"file_corrections": [{"file_name": "case.csv", "correct_semantic_type": "Clinical:Case"}]}')
            print("   Or just provide context:")
            print('   {"additional_context": "This is VitalDB anesthesia data", "domain_hints": ["Anesthesia", "Surgery"]}')
            
            try:
                correction_input = input("\n📝 Corrections (JSON): ").strip()
                if not correction_input:
                    # 빈 입력이면 기본 컨텍스트만 제공
                    return {
                        "action": "correct",
                        "additional_context": "Please improve the analysis",
                        "domain_hints": ["Medical"]
                    }
                
                corrections = json.loads(correction_input)
                corrections["action"] = "correct"
                return corrections
                
            except json.JSONDecodeError as e:
                print(f"❌ Invalid JSON: {e}")
                print("   Using default correction...")
                return {
                    "action": "correct",
                    "additional_context": correction_input,  # JSON이 아니면 텍스트로 사용
                    "domain_hints": []
                }
        
        elif choice == '3' or choice == 'skip':
            return {"action": "skip"}
        
        else:
            print("❌ Invalid choice. Please enter 1, 2, 3, or 'q'")


def get_auto_feedback(review_info: Dict[str, Any], mode: str = "accept") -> Dict[str, Any]:
    """
    자동 피드백 생성 (테스트용)
    
    Args:
        review_info: interrupt에서 전달된 리뷰 정보
        mode: "accept", "correct", "skip" 중 하나
    """
    print_separator("🤖 AUTO FEEDBACK (TEST MODE)", "~", 80)
    
    print(f"\n📋 Review Info:")
    print(f"   Type: {review_info.get('type', '?')}")
    print(f"   Avg Confidence: {review_info.get('avg_confidence', 0):.2f}")
    print(f"   Low Conf Items: {review_info.get('low_conf_items', [])[:5]}")
    
    # 현재 매핑 출력
    current_mappings = review_info.get('current_mappings', [])
    if current_mappings:
        print_mappings(current_mappings[:5], "Sample Mappings")
    
    if mode == "accept":
        feedback = {"action": "accept"}
        print(f"\n🤖 Auto Feedback: ACCEPT")
        
    elif mode == "correct":
        # 자동으로 피드백 생성
        feedback = {
            "action": "correct",
            "additional_context": "This is medical monitoring data from VitalDB surgical database",
            "domain_hints": ["Anesthesia", "Surgery", "Vital Signs"]
        }
        
        # Low confidence 항목에 대한 힌트 추가
        low_items = review_info.get('low_conf_items', [])[:3]
        if low_items and 'column' in review_info.get('type', ''):
            feedback["column_corrections"] = [
                {"original_name": item, "hint": f"Please analyze '{item}' more carefully"}
                for item in low_items
            ]
        
        print(f"\n🤖 Auto Feedback: CORRECT")
        print_json(feedback, "Generated Feedback")
        
    elif mode == "skip":
        feedback = {"action": "skip"}
        print(f"\n🤖 Auto Feedback: SKIP")
    
    else:
        feedback = {"action": "accept"}
        print(f"\n🤖 Auto Feedback: DEFAULT ACCEPT")
    
    return feedback


# =============================================================================
# Phase 1 테스트 (with Manual Review)
# =============================================================================

def test_phase1_with_review(interactive: bool = False, auto_mode: str = "accept"):
    """
    Phase 1 Human Review 테스트
    
    Args:
        interactive: True면 대화형, False면 자동
        auto_mode: 자동 모드일 때 action ("accept", "correct", "skip")
    """
    from langgraph.checkpoint.memory import MemorySaver
    from src.agents.graph import build_phase1_only_agent
    from src.agents.state import AgentState
    
    print_separator("Phase 1 Human Review Test", "=", 80)
    print(f"   Mode: {'Interactive' if interactive else f'Auto ({auto_mode})'}")
    print(f"   Confidence Threshold: {Phase1Config.CONFIDENCE_THRESHOLD}")
    print(f"   Max Review Retries: {Phase1Config.MAX_REVIEW_RETRIES}")
    print_separator()
    
    # DB 초기화 (테이블이 없으면 생성)
    print("\n🗄️ Initializing database...")
    db = get_db_manager()
    
    # 테이블 존재 여부 확인
    if not db.table_exists("file_catalog"):
        print("   📦 Creating tables (first run)...")
        init_catalog_schema(reset=True)
    else:
        print("   ✅ Tables already exist")
    
    # 테스트 데이터 디렉토리
    test_dir = os.path.join(os.path.dirname(__file__), "data/test_samples")
    if not os.path.exists(test_dir):
        print(f"❌ Test directory not found: {test_dir}")
        print("   Please run test_phase0.py first to populate the database")
        return
    
    # Agent 빌드
    print("\n🔧 Building agent...")
    checkpointer = MemorySaver()
    agent = build_phase1_only_agent(checkpointer=checkpointer)
    
    # 초기 상태
    initial_state = {
        "current_dataset_id": "test_review",
        "input_files": [],  # Phase 0에서 채워짐
        "phase0_result": None,
        "phase0_file_ids": [],
        "target_directory": test_dir,
        "logs": [],
    }
    
    config = {"configurable": {"thread_id": f"review_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"}}
    
    print("\n🚀 Starting Phase 0 → 0.5 → 1 workflow...")
    print_separator("EXECUTION LOG", "-", 80)
    
    # 실행 (interrupt가 발생하면 중단됨)
    iteration = 0
    max_iterations = 20  # 무한 루프 방지
    
    while iteration < max_iterations:
        iteration += 1
        print(f"\n{'='*60}")
        print(f"🔄 Iteration {iteration}")
        print(f"{'='*60}")
        
        # 그래프 실행/재개
        result = None
        for event in agent.stream(initial_state if iteration == 1 else None, config):
            # 이벤트 출력
            for node_name, node_output in event.items():
                if node_name == "__interrupt__":
                    # Interrupt 발생!
                    print_separator("⏸️ INTERRUPT DETECTED", "!", 80)
                    
                    # interrupt 정보 추출
                    interrupt_info = node_output
                    if isinstance(interrupt_info, tuple):
                        interrupt_info = interrupt_info[0]  # (value,) 형태일 수 있음
                    if hasattr(interrupt_info, 'value'):
                        interrupt_info = interrupt_info.value
                    
                    print_json(interrupt_info, "Interrupt Info")
                    
                    # 피드백 획득
                    if interactive:
                        feedback = get_interactive_feedback(interrupt_info)
                    else:
                        feedback = get_auto_feedback(interrupt_info, auto_mode)
                    
                    print_json(feedback, "Human Feedback")
                    
                    # 피드백으로 재개
                    print("\n▶️ Resuming with feedback...")
                    agent.update_state(config, {"phase1_human_feedback": feedback}, as_node="phase1_semantic")
                    
                else:
                    # 일반 노드 출력
                    print(f"\n📍 Node: {node_name}")
                    
                    if isinstance(node_output, dict):
                        # 주요 결과만 출력
                        if "phase0_result" in node_output:
                            result_summary = node_output["phase0_result"]
                            print(f"   Phase 0: {result_summary.get('files_processed', 0)} files processed")
                        
                        if "phase05_result" in node_output:
                            result_summary = node_output["phase05_result"]
                            print(f"   Phase 0.5: {result_summary.get('unique_columns_count', 0)} unique columns")
                            print(f"             {result_summary.get('unique_files_count', 0)} unique files")
                        
                        if "phase1_result" in node_output:
                            result_summary = node_output["phase1_result"]
                            print(f"   Phase 1: {result_summary.get('total_columns_analyzed', 0)} columns analyzed")
                            print(f"            {result_summary.get('total_files_analyzed', 0)} files analyzed")
                            print(f"            {result_summary.get('total_review_requests', 0)} review requests")
                            print(f"            {result_summary.get('total_reanalyzes', 0)} re-analyzes")
                        
                        if "column_semantic_mappings" in node_output:
                            mappings = node_output["column_semantic_mappings"]
                            print_mappings(mappings[:5], "Column Mappings (sample)")
                        
                        if "file_semantic_mappings" in node_output:
                            mappings = node_output["file_semantic_mappings"]
                            print_mappings(mappings[:5], "File Mappings (sample)")
                    
                    result = node_output
        
        # 실행 완료 확인
        state = agent.get_state(config)
        if state.next == ():  # 다음 노드가 없으면 완료
            print("\n✅ Workflow completed!")
            break
    
    if iteration >= max_iterations:
        print(f"\n⚠️ Max iterations ({max_iterations}) reached")
    
    # 최종 결과 출력
    print_separator("FINAL RESULTS", "=", 80)
    
    final_state = agent.get_state(config)
    if hasattr(final_state, 'values'):
        values = final_state.values
        
        if values.get("phase1_result"):
            print_json(values["phase1_result"], "Phase 1 Result")
        
        if values.get("phase1_all_batch_states"):
            batch_states = values["phase1_all_batch_states"]
            print(f"\n📊 Batch States Summary ({len(batch_states)} batches):")
            for bs in batch_states:
                status_emoji = {
                    "accepted": "✅",
                    "max_retries": "⚠️",
                    "skipped": "⏭️"
                }.get(bs.get("status", ""), "❓")
                print(f"   {status_emoji} Batch {bs.get('batch_index', 0)+1} [{bs.get('batch_type', '?')}]: "
                      f"status={bs.get('status', '?')}, "
                      f"conf={bs.get('avg_confidence', 0):.2f}, "
                      f"retries={bs.get('retry_count', 0)}")
    
    print_separator("TEST COMPLETE", "=", 80)


# =============================================================================
# DB 현황 확인
# =============================================================================

def show_db_status():
    """현재 DB 상태 출력"""
    print_separator("Database Status", "=", 80)
    
    db = get_db_manager()
    
    # 테이블 존재 확인
    if not db.table_exists("file_catalog"):
        print("\n⚠️ Tables not found. Run Phase 0 first.")
        return
    
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        # file_catalog 현황
        cursor.execute("SELECT COUNT(*) FROM file_catalog")
        file_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM file_catalog WHERE semantic_type IS NOT NULL")
        file_with_semantic = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM file_catalog WHERE llm_confidence >= %s", 
                       (Phase1Config.CONFIDENCE_THRESHOLD,))
        file_high_conf = cursor.fetchone()[0]
        
        print(f"\n📁 file_catalog:")
        print(f"   Total: {file_count}")
        print(f"   With semantic: {file_with_semantic}")
        print(f"   High confidence (>={Phase1Config.CONFIDENCE_THRESHOLD}): {file_high_conf}")
        
        # column_metadata 현황
        cursor.execute("SELECT COUNT(*) FROM column_metadata")
        col_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM column_metadata WHERE semantic_name IS NOT NULL")
        col_with_semantic = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM column_metadata WHERE llm_confidence >= %s",
                       (Phase1Config.CONFIDENCE_THRESHOLD,))
        col_high_conf = cursor.fetchone()[0]
        
        print(f"\n📊 column_metadata:")
        print(f"   Total: {col_count}")
        print(f"   With semantic: {col_with_semantic}")
        print(f"   High confidence (>={Phase1Config.CONFIDENCE_THRESHOLD}): {col_high_conf}")
        
        # 샘플 데이터 (높은 confidence)
        cursor.execute("""
            SELECT original_name, semantic_name, concept_category, llm_confidence
            FROM column_metadata
            WHERE semantic_name IS NOT NULL
            ORDER BY llm_confidence DESC NULLS LAST
            LIMIT 5
        """)
        rows = cursor.fetchall()
        
        if rows:
            print(f"\n📝 Sample column mappings (highest confidence):")
            for r in rows:
                conf = r[3] if r[3] else 0
                print(f"   {r[0]:30} → {r[1]:25} [{r[2] or '-':15}] conf={conf:.2f}")
        
        # 샘플 데이터 (낮은 confidence)
        cursor.execute("""
            SELECT original_name, semantic_name, concept_category, llm_confidence
            FROM column_metadata
            WHERE semantic_name IS NOT NULL AND llm_confidence < %s
            ORDER BY llm_confidence ASC NULLS LAST
            LIMIT 5
        """, (Phase1Config.CONFIDENCE_THRESHOLD,))
        rows = cursor.fetchall()
        
        if rows:
            print(f"\n⚠️ Sample column mappings (lowest confidence):")
            for r in rows:
                conf = r[3] if r[3] else 0
                print(f"   {r[0]:30} → {r[1]:25} [{r[2] or '-':15}] conf={conf:.2f}")
    
    except Exception as e:
        print(f"\n❌ Error reading DB: {e}")
    finally:
        cursor.close()


# =============================================================================
# Main
# =============================================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Phase 1 Human Review Test")
    parser.add_argument("--interactive", "-i", action="store_true",
                        help="Run in interactive mode (prompt for feedback)")
    parser.add_argument("--mode", "-m", choices=["accept", "correct", "skip"],
                        default="accept", help="Auto mode action (default: accept)")
    parser.add_argument("--status", "-s", action="store_true",
                        help="Show database status only")
    
    args = parser.parse_args()
    
    if args.status:
        show_db_status()
    else:
        test_phase1_with_review(interactive=args.interactive, auto_mode=args.mode)
        print("\n")
        show_db_status()


if __name__ == "__main__":
    main()

