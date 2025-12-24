#!/usr/bin/env python3
# test_agent_with_interrupt.py
"""
LangGraph 2-Phase Workflow 테스트

⭐ 2-Phase Architecture:
   Phase 1: 전체 파일 분류 (Classification)
            - batch_classifier: 모든 파일 분류
            - classification_review: 불확실한 파일 Human 확인
   
   Phase 2: 순차 처리 (Processing)
            - process_metadata: 메타데이터 먼저 처리 (온톨로지 구축)
            - process_data_batch: 데이터 파일 처리
              └─ loader → analyzer → human_review → indexer → advance
"""

import sys
import os
import glob
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from agents.graph import build_agent, build_batch_agent, build_single_agent
from langgraph.checkpoint.memory import MemorySaver


# ============================================================================
# Test 1: 새로운 2-Phase Batch Workflow
# ============================================================================

def test_batch_workflow(file_paths: list, dataset_id: str = None):
    """
    [NEW] 2-Phase Batch Workflow 테스트
    
    모든 파일을 한 번에 분류하고, 메타데이터 → 데이터 순서로 처리합니다.
    """
    print("\n" + "🌐"*40)
    print("🌐 2-Phase Batch Workflow Test")
    print("🌐"*40)
    
    # Dataset ID 감지
    from src.utils.dataset_detector import detect_dataset_from_path, get_dataset_source_path
    from src.utils.naming import extract_dataset_prefix
    
    if dataset_id is None and file_paths:
        dataset_id = detect_dataset_from_path(file_paths[0])
        if not dataset_id:
            dataset_id = "default_dataset"
    
    print(f"\n📁 [Dataset-First] Dataset ID: {dataset_id}")
    print(f"   Prefix: {extract_dataset_prefix(dataset_id)}")
    print(f"   Total Files: {len(file_paths)}개")
    
    # Ontology Manager 초기화
    from src.utils.ontology_manager import get_ontology_manager
    ontology_mgr = get_ontology_manager()
    
    print("\n📚 [Ontology] 기존 온톨로지 확인 중...")
    shared_ontology = ontology_mgr.load(dataset_id=dataset_id)
    shared_ontology["dataset_id"] = dataset_id
    
    # DataCatalog 생성
    from src.utils.dataset_detector import create_empty_data_catalog, create_dataset_info
    data_catalog = create_empty_data_catalog()
    
    if file_paths:
        source_path = get_dataset_source_path(file_paths[0])
        data_catalog["datasets"][dataset_id] = create_dataset_info(
            dataset_id=dataset_id,
            source_path=source_path
        )
    
    # Checkpointer & Agent 생성
    memory = MemorySaver()
    agent = build_batch_agent(checkpointer=memory)
    
    # 공유 Project Context
    shared_context = {
        "master_anchor_name": None,
        "known_aliases": [],
        "example_id_values": []
    }
    
    # [NEW] 대화 히스토리 초기화
    from datetime import datetime
    conversation_history = {
        "session_id": f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "dataset_id": dataset_id,
        "started_at": datetime.now().isoformat(),
        "turns": [],
        "classification_decisions": [],
        "anchor_decisions": [],
        "user_preferences": {}
    }
    
    # 초기 상태 (2-Phase용)
    initial_state = {
        # 2-Phase Workflow 필드
        "input_files": file_paths,
        "classification_result": None,
        "processing_progress": {
            "phase": "classification",
            "metadata_processed": [],
            "data_processed": [],
            "current_file": None,
            "current_file_index": 0,
            "total_files": len(file_paths)
        },
        # Dataset-First Architecture
        "current_dataset_id": dataset_id,
        "current_table_name": None,
        "data_catalog": data_catalog,
        # 기존 필드들
        "file_path": "",  # batch_classifier에서 설정됨
        "file_type": None,
        "raw_metadata": {},
        "finalized_anchor": None,
        "finalized_schema": [],
        "needs_human_review": False,
        "human_question": "",
        "human_feedback": None,
        "review_type": None,
        "conversation_history": conversation_history,  # [NEW] 대화 히스토리
        "logs": [],
        "retry_count": 0,
        "error_message": None,
        "project_context": shared_context.copy(),
        "ontology_context": shared_ontology.copy(),
        "skip_indexing": False
    }
    
    # Thread ID
    thread_config = {"configurable": {"thread_id": "batch-session-1"}}
    
    print(f"\n🧵 Thread ID: {thread_config['configurable']['thread_id']}")
    print(f"\n▶️  2-Phase Workflow 실행 중...\n")
    
    try:
        final_state = None
        
        for event in agent.stream(initial_state, thread_config, stream_mode="values"):
            # 로그 출력
            if "logs" in event and event["logs"]:
                last_log = event["logs"][-1]
                if not final_state or last_log not in final_state.get("logs", []):
                    print(f"📝 {last_log}")
            
            final_state = event
            
            # Human Review 필요 시
            if event.get("needs_human_review"):
                review_type = event.get("review_type", "general")
                
                print("\n")
                print("█" * 80)
                print("█" + " " * 30 + "⚠️  사용자 확인 필요" + " " * 29 + "█")
                print("█" * 80)
                
                question = event.get("human_question", "확인 필요")
                print(question)
                
                # 리뷰 타입별 안내
                print("\n" + "─" * 80)
                if review_type == "classification":
                    print("💡 [파일 분류 확인]")
                    print("   - 모두 맞으면: 확인 또는 ok")
                    print("   - 수정: 1:데이터, 2:메타데이터 (번호:분류)")
                    print("   - 제외: 1:제외 또는 1:skip")
                else:
                    print("💡 [데이터 분석 확인]")
                    print("   - 컬럼명 입력: 해당 컬럼을 Anchor로 지정")
                    print("   - 'skip' 입력: 이 파일 건너뛰기")
                    print("   - Enter만 입력: 자동 처리")
                print("─" * 80)
                
                # 사용자 입력
                user_feedback = input("\n>>> 입력: ").strip()
                
                if not user_feedback:
                    if review_type == "classification":
                        user_feedback = "확인"  # 기본값: 승인
                    else:
                        print("⚠️  입력 없음. 자동 처리...")
                        continue
                
                print(f"\n✅ 입력받음: '{user_feedback}'")
                print("\n🔄 피드백 반영하여 재실행...\n")
                
                # State 업데이트 후 재실행
                update_state = {
                    "human_feedback": user_feedback,
                    "needs_human_review": False
                }
                
                for event2 in agent.stream(update_state, thread_config, stream_mode="values"):
                    if "logs" in event2 and event2["logs"]:
                        last_log = event2["logs"][-1]
                        if last_log not in final_state.get("logs", []):
                            print(f"📝 {last_log}")
                    final_state = event2
        
        # 결과 요약
        _print_batch_summary(final_state, shared_ontology, ontology_mgr, dataset_id)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


def _print_batch_summary(final_state: dict, shared_ontology: dict, ontology_mgr, dataset_id: str):
    """Batch 처리 결과 요약 출력"""
    
    print("\n\n" + "="*80)
    print("📊 2-Phase Workflow 결과 요약")
    print("="*80)
    
    classification_result = final_state.get("classification_result", {})
    processing_progress = final_state.get("processing_progress", {})
    
    print(f"\n📋 [Phase 1] 분류 결과:")
    print(f"   - 메타데이터: {len(classification_result.get('metadata_files', []))}개")
    for f in classification_result.get("metadata_files", []):
        print(f"      📖 {os.path.basename(f)}")
    print(f"   - 데이터: {len(classification_result.get('data_files', []))}개")
    for f in classification_result.get("data_files", []):
        print(f"      📊 {os.path.basename(f)}")
    
    print(f"\n🔄 [Phase 2] 처리 결과:")
    print(f"   - Phase: {processing_progress.get('phase')}")
    print(f"   - 메타데이터 처리: {len(processing_progress.get('metadata_processed', []))}개")
    print(f"   - 데이터 처리: {len(processing_progress.get('data_processed', []))}개")
    
    # 온톨로지 정보
    ontology = final_state.get("ontology_context", shared_ontology)
    print(f"\n📚 [Ontology] 최종 상태:")
    print(f"   - 용어 수: {len(ontology.get('definitions', {}))}개")
    print(f"   - 관계: {len(ontology.get('relationships', []))}개")
    print(f"   - 계층: {len(ontology.get('hierarchy', []))}개")
    print(f"   - 태그된 파일: {len(ontology.get('file_tags', {}))}개")
    
    # 온톨로지 상세 요약
    print(ontology_mgr.export_summary())
    
    print("="*80)
    print("✅ 2-Phase Workflow 완료!")
    print("="*80)


# ============================================================================
# Test 2: Legacy 단일 파일 워크플로우 (호환성)
# ============================================================================

def test_single_file_workflow(file_path: str, dataset_id: str = None):
    """
    [Legacy] 단일 파일 워크플로우 테스트
    """
    print("\n" + "="*80)
    print("🚀 Single File Workflow Test")
    print("="*80)
    
    from src.utils.dataset_detector import detect_dataset_from_path
    
    if dataset_id is None:
        dataset_id = detect_dataset_from_path(file_path) or "default_dataset"
    
    memory = MemorySaver()
    agent = build_single_agent(checkpointer=memory)
    
    initial_state = {
        "current_dataset_id": dataset_id,
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
        },
        "ontology_context": {
            "definitions": {},
            "relationships": [],
            "hierarchy": [],
            "file_tags": {}
        },
        "skip_indexing": False
    }
    
    thread_config = {"configurable": {"thread_id": "single-file-1"}}
    
    print(f"\n📁 파일: {os.path.basename(file_path)}")
    print(f"📁 Dataset: {dataset_id}")
    
    try:
        for event in agent.stream(initial_state, thread_config, stream_mode="values"):
            if "logs" in event and event["logs"]:
                print(f"📝 {event['logs'][-1]}")
            
            if event.get("needs_human_review"):
                question = event.get("human_question", "확인 필요")
                print(f"\n⚠️ Human Review: {question}")
                
                user_feedback = input(">>> 입력: ").strip() or "unknown"
                
                update_state = {
                    "human_feedback": user_feedback,
                    "needs_human_review": False
                }
                
                for event2 in agent.stream(update_state, thread_config, stream_mode="values"):
                    if "logs" in event2 and event2["logs"]:
                        print(f"📝 {event2['logs'][-1]}")
        
        print("\n✅ Single File Workflow 완료!")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


# ============================================================================
# Test 3: Legacy 멀티 파일 순차 처리 (호환성)
# ============================================================================

def test_multiple_files_with_interrupt(file_paths: list, dataset_id: str = None):
    """
    [Legacy] 여러 CSV 파일을 순차적으로 처리 (Global Context 유지)
    
    이 함수는 기존 코드와의 호환성을 위해 유지됩니다.
    새로운 프로젝트에서는 test_batch_workflow()를 사용하세요.
    """
    print("\n" + "🌐"*40)
    print("🌐 LEGACY: Sequential Multi-File Processing")
    print("🌐 (Use test_batch_workflow() for 2-Phase processing)")
    print("🌐"*40)
    
    from src.utils.dataset_detector import detect_dataset_from_path, get_dataset_source_path
    from src.utils.naming import extract_dataset_prefix
    
    if dataset_id is None and file_paths:
        dataset_id = detect_dataset_from_path(file_paths[0])
        if not dataset_id:
            dataset_id = "default_dataset"
    
    print(f"\n📁 [Dataset-First] Dataset ID: {dataset_id}")
    print(f"   Prefix: {extract_dataset_prefix(dataset_id)}")
    
    from src.utils.ontology_manager import get_ontology_manager
    ontology_mgr = get_ontology_manager()
    
    print("\n📚 [Ontology] 기존 온톨로지 확인 중...")
    shared_ontology = ontology_mgr.load(dataset_id=dataset_id)
    shared_ontology["dataset_id"] = dataset_id
    
    memory = MemorySaver()
    agent = build_single_agent(checkpointer=memory)  # 단일 파일 워크플로우 사용
    
    shared_context = {
        "master_anchor_name": None,
        "known_aliases": [],
        "example_id_values": []
    }
    
    from src.utils.dataset_detector import create_empty_data_catalog, create_dataset_info
    data_catalog = create_empty_data_catalog()
    
    if file_paths:
        source_path = get_dataset_source_path(file_paths[0])
        data_catalog["datasets"][dataset_id] = create_dataset_info(
            dataset_id=dataset_id,
            source_path=source_path
        )
    
    # [NEW] 대화 히스토리 (세션 전체에서 공유)
    from datetime import datetime
    shared_conversation_history = {
        "session_id": f"legacy_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "dataset_id": dataset_id,
        "started_at": datetime.now().isoformat(),
        "turns": [],
        "classification_decisions": [],
        "anchor_decisions": [],
        "user_preferences": {}
    }
    
    results = []
    
    for idx, file_path in enumerate(file_paths, 1):
        print(f"\n\n{'#'*80}")
        print(f"# File {idx}/{len(file_paths)}: {os.path.basename(file_path)}")
        print(f"{'#'*80}")
        
        thread_config = {"configurable": {"thread_id": f"file-{idx}"}}
        
        initial_state = {
            "current_dataset_id": dataset_id,
            "current_table_name": None,
            "data_catalog": data_catalog,
            "file_path": file_path,
            "file_type": None,
            "raw_metadata": {},
            "finalized_anchor": None,
            "finalized_schema": [],
            "needs_human_review": False,
            "human_question": "",
            "human_feedback": None,
            "conversation_history": shared_conversation_history.copy(),  # [NEW]
            "logs": [],
            "retry_count": 0,
            "error_message": None,
            "project_context": shared_context.copy(),
            "ontology_context": shared_ontology.copy(),
            "skip_indexing": False
        }
        
        try:
            print(f"\n▶️  에이전트 실행 중...\n")
            
            final_state = None
            for event in agent.stream(initial_state, thread_config, stream_mode="values"):
                if "logs" in event and event["logs"]:
                    last_log = event["logs"][-1]
                    if not final_state or last_log not in final_state.get("logs", []):
                        print(f"📝 {last_log}")
                
                final_state = event
                
                if event.get("needs_human_review"):
                    print("\n")
                    print("█" * 80)
                    print("█" + " " * 30 + "⚠️  사용자 확인 필요" + " " * 29 + "█")
                    print("█" * 80)
                    
                    question = event.get("human_question", "확인 필요")
                    print(question)
                    
                    print("\n" + "─" * 80)
                    print("💡 입력 안내:")
                    print("   - 컬럼명 입력: 해당 컬럼을 Anchor로 지정")
                    print("   - 'skip' 입력: 이 파일 건너뛰기")
                    print("   - Enter만 입력: 자동 처리")
                    print("─" * 80)
                    
                    user_feedback = input("\n>>> 입력: ").strip()
                    
                    if not user_feedback:
                        print("⚠️  입력 없음. 자동 처리...")
                        continue
                    
                    print(f"\n✅ 입력받음: '{user_feedback}'")
                    print("\n🔄 피드백 반영하여 재실행...\n")
                    
                    update_state = {
                        "human_feedback": user_feedback,
                        "needs_human_review": False
                    }
                    
                    for event2 in agent.stream(update_state, thread_config, stream_mode="values"):
                        if "logs" in event2 and event2["logs"]:
                            last_log = event2["logs"][-1]
                            if last_log not in event.get("logs", []):
                                print(f"📝 {last_log}")
                        final_state = event2
            
            if final_state:
                shared_context = final_state.get('project_context', shared_context)
                shared_ontology = final_state.get('ontology_context', shared_ontology)
                # [NEW] 대화 히스토리 업데이트 (파일 간 공유)
                if final_state.get('conversation_history'):
                    shared_conversation_history = final_state.get('conversation_history')
                
                results.append({
                    'file': file_path,
                    'success': True,
                    'anchor': final_state.get('finalized_anchor'),
                    'was_metadata': final_state.get('skip_indexing', False)
                })
                
                print(f"\n✅ 파일 처리 완료: {os.path.basename(file_path)}")
                print(f"📚 대화 히스토리: {len(shared_conversation_history.get('turns', []))}개 턴")
                print(f"🔄 Global Context 업데이트:")
                print(f"   - Master Anchor: {shared_context.get('master_anchor_name')}")
                print(f"   - Known Aliases: {shared_context.get('known_aliases')}")
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
    
    print(ontology_mgr.export_summary())


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    """메인 함수 - 2-Phase Batch Workflow"""
    from pathlib import Path
    
    data_dir = Path(__file__).parent / "data" / "raw"
    
    # CSV 파일
    inspire_files = sorted(glob.glob(str(data_dir / "INSPIRE_130K_1.3/*.csv")))
    vital_csv_files = sorted(glob.glob(str(data_dir / "Open_VitalDB_1.0.0/*.csv")))
    vital_signal_files = sorted(glob.glob(str(data_dir / "Open_VitalDB_1.0.0/vital_files/*.vital")))
    
    # VitalDB 데이터만 처리 (CSV + Signal)
    all_files = vital_csv_files + vital_signal_files[:2]
    
    if not all_files:
        print(f"❌ 파일을 찾을 수 없습니다: {data_dir}")
        return
    
    print(f"\n📁 Found {len(all_files)} files:")
    print(f"   📊 VitalDB CSV: {len(vital_csv_files)}개")
    for f in vital_csv_files:
        print(f"      - {os.path.basename(f)}")
    print(f"   📈 VitalDB Signal: {len(vital_signal_files)}개")
    
    # Dataset ID 감지
    from src.utils.dataset_detector import detect_dataset_from_path
    dataset_id = None
    if all_files:
        dataset_id = detect_dataset_from_path(all_files[0])
    print(f"\n📁 [Dataset-First] Detected Dataset: {dataset_id}")
    
    # ⭐ 2-Phase Batch Workflow 실행
    test_batch_workflow(all_files, dataset_id=dataset_id)
    
    # 캐시 통계 출력
    from src.utils.llm_cache import get_llm_cache
    cache = get_llm_cache()
    cache.print_stats()
    
    # [DISABLED] VectorDB 임베딩 생성 - 시간이 오래 걸려서 비활성화
    # 필요 시 주석 해제하세요
    # print("\n" + "="*80)
    # print(f"🔢 [VectorDB] 임베딩 생성 시작... (dataset: {dataset_id})")
    # print("="*80)
    # 
    # try:
    #     from src.knowledge.vector_store import VectorStore
    #     from src.utils.ontology_manager import get_ontology_manager
    #     
    #     ontology_mgr = get_ontology_manager()
    #     ontology = ontology_mgr.load(dataset_id=dataset_id)
    #     
    #     if ontology and (ontology.get("definitions") or ontology.get("column_metadata")):
    #         vector_store = VectorStore()
    #         vector_store.initialize()
    #         vector_store.build_index(ontology, dataset_id=dataset_id)
    #         
    #         stats = vector_store.get_stats()
    #         print(f"\n✅ [VectorDB] 임베딩 생성 완료")
    #         print(f"   - Dataset: {dataset_id}")
    #         print(f"   - Provider: {stats.get('provider')}")
    #         print(f"   - Dimensions: {stats.get('dimensions')}")
    #         print(f"   - Total Embeddings: {stats.get('total', 0)}개")
    #     else:
    #         print("⚠️  [VectorDB] 임베딩할 데이터 없음 (온톨로지 비어있음)")
    # except Exception as e:
    #     print(f"⚠️  [VectorDB] 임베딩 생성 실패: {e}")
    #     print("   (pgvector 미설치 시: brew install pgvector)")
    
    print("\n" + "="*80)
    print("✅ 모든 작업 완료!")
    print("="*80)


if __name__ == "__main__":
    main()
