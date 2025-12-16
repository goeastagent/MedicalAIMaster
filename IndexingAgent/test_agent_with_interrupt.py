#!/usr/bin/env python3
# test_agent_with_interrupt.py
"""
LangGraph의 공식 Interrupt 메커니즘을 사용한 Human-in-the-Loop 테스트
여러 CSV 파일을 순차적으로 처리하며 Global Context를 유지합니다.
"""

import sys
import os
import glob

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from agents.graph import build_agent
from langgraph.checkpoint.memory import MemorySaver


def test_with_interrupt(file_path: str):
    """
    LangGraph Interrupt 기능을 사용한 Human Feedback 테스트
    """
    print("="*80)
    print("🚀 LangGraph Interrupt 방식 테스트")
    print("="*80)
    
    # 1. Checkpointer 생성 (State 저장/복원용)
    memory = MemorySaver()
    
    # 2. Agent 빌드 (checkpointer 전달)
    agent = build_agent(checkpointer=memory)
    
    # 3. 초기 상태 및 설정
    initial_state = {
        "file_path": file_path,
        "file_type": None,
        "raw_metadata": {},
        "finalized_anchor": None,
        "finalized_schema": [],
        "needs_human_review": False,
        "human_question": "",
        "human_feedback": None,
        "logs": [],
        "retry_count": 0,
        "error_message": None,
        "project_context": {
            "master_anchor_name": None,
            "known_aliases": [],
            "example_id_values": []
        }
    }
    
    # Thread ID (같은 세션을 추적하기 위함)
    thread_config = {"configurable": {"thread_id": "test-session-1"}}
    
    print(f"\n📁 파일: {os.path.basename(file_path)}")
    print(f"🧵 Thread ID: {thread_config['configurable']['thread_id']}\n")
    
    # 4. 실행 (Interrupt 발생 시 멈춤)
    try:
        print("▶️  에이전트 실행 중...\n")
        
        # stream()으로 단계별 실행 확인
        for event in agent.stream(initial_state, thread_config, stream_mode="values"):
            # 각 노드 실행 후 state 출력
            if "logs" in event and event["logs"]:
                print(f"📝 {event['logs'][-1]}")
            
            # needs_human_review 체크
            if event.get("needs_human_review"):
                print("\n" + "🛑"*40)
                print("⚠️  HUMAN REVIEW REQUIRED - Workflow Interrupted")
                print("🛑"*40)
                
                question = event.get("human_question", "확인 필요")
                print(f"\n질문:\n{question}\n")
                
                # 사용자 입력
                user_feedback = input(">>> Anchor 컬럼명 입력: ").strip()
                
                if not user_feedback:
                    print("⚠️  입력 없음. 'unknown' 사용")
                    user_feedback = "unknown"
                
                print(f"\n✅ 입력받음: '{user_feedback}'")
                
                # 5. State 업데이트 후 재실행 (같은 thread_id 사용)
                print("\n🔄 피드백 반영하여 재실행...\n")
                
                # None으로 업데이트하면 이전 state 유지하면서 특정 필드만 변경
                update_state = {
                    "human_feedback": user_feedback,
                    "needs_human_review": False
                }
                
                # 재실행 (update 후)
                for event2 in agent.stream(update_state, thread_config, stream_mode="values"):
                    if "logs" in event2 and event2["logs"]:
                        last_log = event2["logs"][-1]
                        if last_log not in event.get("logs", []):
                            print(f"📝 {last_log}")
        
        print("\n" + "="*80)
        print("✅ WORKFLOW COMPLETED")
        print("="*80)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


def test_multiple_files_with_interrupt(file_paths: list):
    """
    여러 CSV 파일을 순차적으로 처리 (Global Context 유지)
    """
    print("\n" + "🌐"*40)
    print("🌐 MULTI-FILE PROCESSING with Global Context")
    print("🌐"*40)
    
    # Ontology Manager 초기화 및 기존 온톨로지 로드
    from src.utils.ontology_manager import get_ontology_manager
    ontology_mgr = get_ontology_manager()
    
    print("\n📚 [Ontology] 기존 온톨로지 확인 중...")
    shared_ontology = ontology_mgr.load()
    
    # Checkpointer 생성 (모든 파일이 공유)
    memory = MemorySaver()
    agent = build_agent(checkpointer=memory)
    
    # 공유 Project Context
    shared_context = {
        "master_anchor_name": None,
        "known_aliases": [],
        "example_id_values": []
    }
    
    results = []
    
    for idx, file_path in enumerate(file_paths, 1):
        print(f"\n\n{'#'*80}")
        print(f"# File {idx}/{len(file_paths)}: {os.path.basename(file_path)}")
        print(f"{'#'*80}")
        
        # Thread ID (각 파일마다 다른 세션)
        thread_config = {"configurable": {"thread_id": f"file-{idx}"}}
        
        # 초기 상태 (이전 파일의 Context 전달)
        initial_state = {
            "file_path": file_path,
            "file_type": None,
            "raw_metadata": {},
            "finalized_anchor": None,
            "finalized_schema": [],
            "needs_human_review": False,
            "human_question": "",
            "human_feedback": None,
            "logs": [],
            "retry_count": 0,
            "error_message": None,
            "project_context": shared_context.copy(),
            # [NEW] 공유 Ontology Context (누적됨)
            "ontology_context": shared_ontology.copy(),
            "skip_indexing": False
        }
        
        try:
            print(f"\n▶️  에이전트 실행 중...\n")
            
            # 실행
            final_state = None
            for event in agent.stream(initial_state, thread_config, stream_mode="values"):
                # 로그 출력 (중복 방지)
                if "logs" in event and event["logs"]:
                    last_log = event["logs"][-1]
                    if not final_state or last_log not in final_state.get("logs", []):
                        print(f"📝 {last_log}")
                
                final_state = event
                
                # Human Review 필요 시
                if event.get("needs_human_review"):
                    print("\n" + "🛑"*40)
                    print("⚠️  HUMAN REVIEW REQUIRED")
                    print("🛑"*40)
                    
                    question = event.get("human_question", "확인 필요")
                    print(f"\n질문:\n{question}\n")
                    
                    # 사용자 입력
                    user_feedback = input(">>> Anchor 컬럼명 입력 (Enter=skip): ").strip()
                    
                    if not user_feedback:
                        print("⚠️  입력 없음. 자동 처리 (3번 재시도 후 강제 진행)")
                        continue  # 자동 모드
                    
                    print(f"\n✅ 입력받음: '{user_feedback}'")
                    
                    # State 업데이트 후 재실행
                    print("\n🔄 피드백 반영하여 재실행...\n")
                    update_state = {
                        "human_feedback": user_feedback,
                        "needs_human_review": False
                    }
                    
                    # 재실행
                    for event2 in agent.stream(update_state, thread_config, stream_mode="values"):
                        if "logs" in event2 and event2["logs"]:
                            last_log = event2["logs"][-1]
                            if last_log not in event.get("logs", []):
                                print(f"📝 {last_log}")
                        final_state = event2
            
            # 성공
            if final_state:
                # Context 업데이트 (다음 파일을 위해)
                shared_context = final_state.get('project_context', shared_context)
                shared_ontology = final_state.get('ontology_context', shared_ontology)
                
                results.append({
                    'file': file_path,
                    'success': True,
                    'anchor': final_state.get('finalized_anchor'),
                    'was_metadata': final_state.get('skip_indexing', False)
                })
                
                print(f"\n✅ 파일 처리 완료: {os.path.basename(file_path)}")
                print(f"🔄 Global Context 업데이트:")
                print(f"   - Master Anchor: {shared_context.get('master_anchor_name')}")
                print(f"   - Known Aliases: {shared_context.get('known_aliases')}")
                print(f"🔄 Ontology Context:")
                print(f"   - 용어 수: {len(shared_ontology.get('definitions', {}))}개")
                print(f"   - 파일 태그: {len(shared_ontology.get('file_tags', {}))}개")
            else:
                results.append({'file': file_path, 'success': False})
                
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()
            results.append({'file': file_path, 'success': False})
    
    # 최종 요약
    print("\n\n" + "="*80)
    print("📊 FINAL SUMMARY - All Files")
    print("="*80)
    print(f"\n✅ Successfully processed: {sum(1 for r in results if r['success'])}/{len(results)} files")
    
    # 메타데이터 vs 데이터 분리
    metadata_files = [r for r in results if r.get('was_metadata')]
    data_files = [r for r in results if not r.get('was_metadata')]
    
    print(f"\n📖 Metadata Files: {len(metadata_files)}개")
    for r in metadata_files:
        print(f"   • {os.path.basename(r['file'])} → 온톨로지 추가됨")
    
    print(f"\n📊 Data Files: {len(data_files)}개")
    for r in data_files:
        print(f"   • {os.path.basename(r['file'])}")
        if r.get('anchor'):
            anchor = r['anchor']
            print(f"      → Anchor: {anchor.get('column_name')} (mapped: {anchor.get('mapped_to_master', 'N/A')})")
    
    print(f"\n🌐 Final Global Context:")
    print(f"   - Master Anchor: {shared_context.get('master_anchor_name')}")
    print(f"   - Known Aliases: {shared_context.get('known_aliases')}")
    
    print(f"\n📚 Ontology Context:")
    print(f"   - 총 용어: {len(shared_ontology.get('definitions', {}))}개")
    print(f"   - 관계: {len(shared_ontology.get('relationships', []))}개")
    print(f"   - 계층: {len(shared_ontology.get('hierarchy', []))}개")
    print(f"   - 태그된 파일: {len(shared_ontology.get('file_tags', {}))}개")
    
    # 온톨로지 요약 출력
    print(ontology_mgr.export_summary())


def main():
    """메인 함수"""
    from pathlib import Path
    
    data_dir = Path(__file__).parent / "data" / "raw" / "INSPIRE_130K_1.3"
    
    # raw 디렉토리의 모든 CSV 파일 찾기
    csv_files = sorted(glob.glob(str(data_dir / "*.csv")))
    
    if not csv_files:
        print(f"❌ CSV 파일을 찾을 수 없습니다: {data_dir}")
        return
    
    print(f"\n📁 Found {len(csv_files)} CSV files:")
    for f in csv_files:
        print(f"   - {os.path.basename(f)}")
    
    # 모든 CSV 파일 처리
    test_multiple_files_with_interrupt(csv_files)
    
    # 캐시 통계 출력 (전역 캐시 import)
    from src.utils.llm_cache import get_llm_cache
    cache = get_llm_cache()
    cache.print_stats()


if __name__ == "__main__":
    main()

