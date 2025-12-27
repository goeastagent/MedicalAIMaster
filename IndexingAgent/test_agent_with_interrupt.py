#!/usr/bin/env python3
# test_agent_with_interrupt.py
"""
LangGraph 3-Phase Workflow 테스트

⭐ 3-Phase Architecture:
   Phase 0: 데이터 카탈로그 (Data Catalog)
            - phase0_catalog: 규칙 기반 메타데이터 추출 및 DB 저장 (LLM 없음)
   
   Phase 1: 전체 파일 분류 (Classification)
            - batch_classifier: 모든 파일 분류
            - classification_review: 불확실한 파일 Human 확인 (interrupt() 사용)
   
   Phase 2: 순차 처리 (Processing)
            - process_metadata: 메타데이터 먼저 처리 (온톨로지 구축)
            - process_data_batch: 데이터 파일 처리
              └─ loader → analyzer → human_review → indexer → advance

⭐ Human-in-the-Loop:
   각 노드 내부에서 interrupt()를 호출하여 사용자 입력을 받습니다.
   - interrupt() 호출 시 질문과 컨텍스트를 함께 전달
   - Command(resume=...) 로 응답 전달
   - 대화 히스토리는 자동으로 파일에 저장됨
"""

import sys
import os
import glob
import json
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.agents.graph import build_agent, build_batch_agent
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command


# ============================================================================
# Test 1: 새로운 2-Phase Batch Workflow
# ============================================================================

def test_batch_workflow(file_paths: list, dataset_id: str = None):
    """
    [NEW] 3-Phase Batch Workflow 테스트
    
    Phase 0: 규칙 기반 메타데이터 추출 및 DB 카탈로그 저장
    Phase 1: 파일 분류 (메타데이터/데이터)
    Phase 2: 메타데이터 → 데이터 순서로 처리
    """
    print("\n" + "🌐"*40)
    print("🌐 3-Phase Batch Workflow Test")
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
    
    # 초기 상태 (3-Phase용)
    initial_state = {
        # 3-Phase Workflow 필드
        "input_files": file_paths,
        "phase0_result": None,  # Phase 0에서 채워짐
        "phase0_file_ids": [],  # Phase 0에서 채워짐 (UUID 문자열 리스트)
        "classification_result": None,
        "processing_progress": {
            "phase": "phase0",  # Phase 0부터 시작
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
        
        # =====================================================================
        # 새로운 interrupt() 기반 Human-in-the-Loop 처리
        # =====================================================================
        # 각 노드가 내부에서 interrupt()를 호출하면:
        # 1. stream()이 interrupt 이벤트를 반환
        # 2. 외부에서 사용자 입력을 받음
        # 3. Command(resume=응답)으로 재실행
        # =====================================================================
        
        while True:
            # 스트림 실행
            events = list(agent.stream(initial_state, thread_config, stream_mode="values"))
            
            for event in events:
                # 로그 출력
                if "logs" in event and event["logs"]:
                    last_log = event["logs"][-1]
                    if not final_state or last_log not in final_state.get("logs", []):
                        print(f"📝 {last_log}")
                final_state = event
            
            # Interrupt 확인 (agent.get_state()로 확인)
            current_state = agent.get_state(thread_config)
            
            # interrupt가 없으면 종료
            if not current_state.tasks or not any(
                hasattr(task, 'interrupts') and task.interrupts 
                for task in current_state.tasks
            ):
                break
            
            # Interrupt 처리
            for task in current_state.tasks:
                if hasattr(task, 'interrupts') and task.interrupts:
                    for interrupt_data in task.interrupts:
                        # interrupt()에서 전달한 데이터 추출
                        interrupt_value = interrupt_data.value if hasattr(interrupt_data, 'value') else interrupt_data
                        
                        review_type = interrupt_value.get("type", "general") if isinstance(interrupt_value, dict) else "general"
                        question = interrupt_value.get("question", "확인이 필요합니다") if isinstance(interrupt_value, dict) else str(interrupt_value)
                        instructions = interrupt_value.get("instructions", {}) if isinstance(interrupt_value, dict) else {}
                        
                        # UI 표시
                        print("\n")
                        print("█" * 80)
                        print("█" + " " * 30 + "⚠️  사용자 확인 필요" + " " * 29 + "█")
                        print("█" * 80)
                        print()
                        print(question)
                        
                        # 리뷰 타입별 안내
                        print("\n" + "─" * 80)
                        if review_type == "classification_review":
                            print("💡 [파일 분류 확인]")
                            print("   - 모두 맞으면: 확인 또는 ok")
                            print("   - 수정: 1:데이터, 2:메타데이터 (번호:분류)")
                            print("   - 제외: 1:제외 또는 1:skip")
                        elif review_type == "anchor_review":
                            print("💡 [데이터 분석 확인]")
                            print("   - 컬럼명 입력: 해당 컬럼을 Anchor로 지정")
                            print("   - 'skip' 입력: 이 파일 건너뛰기")
                            print("   - Enter만 입력: AI 추천 승인")
                        else:
                            print("💡 [일반 확인]")
                            if instructions:
                                for key, val in instructions.items():
                                    print(f"   - {key}: {val}")
                        print("─" * 80)
                        
                        # 사용자 입력
                        user_input = input("\n>>> 입력: ").strip()
                        
                        # 기본값 처리
                        if not user_input:
                            if review_type == "classification_review":
                                user_input = "확인"
                                print("   (기본값 '확인' 사용)")
                            else:
                                user_input = "ok"
                                print("   (기본값 'ok' 사용)")
                        
                        print(f"\n✅ 입력받음: '{user_input}'")
                        print("\n🔄 피드백 반영하여 재실행...\n")
                        
                        # Command(resume=...)로 응답 전달하여 재실행
                        # initial_state를 Command로 교체
                        initial_state = Command(resume=user_input)
        
        # 결과 요약
        _print_batch_summary(final_state, shared_ontology, ontology_mgr, dataset_id)
        
    except KeyboardInterrupt:
        print("\n\n⚠️ 사용자에 의해 중단됨")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


def _print_batch_summary(final_state: dict, shared_ontology: dict, ontology_mgr, dataset_id: str):
    """Batch 처리 결과 요약 출력"""
    
    print("\n\n" + "="*80)
    print("📊 3-Phase Workflow 결과 요약")
    print("="*80)
    
    phase0_result = final_state.get("phase0_result", {})
    classification_result = final_state.get("classification_result", {})
    processing_progress = final_state.get("processing_progress", {})
    
    # =========================================================================
    # Phase 0: Data Catalog 결과
    # =========================================================================
    file_ids = final_state.get("phase0_file_ids", [])
    print(f"\n📦 [Phase 0] Data Catalog 결과:")
    print(f"   - 전체 파일: {phase0_result.get('total_files', 0)}개")
    print(f"   - 처리 완료: {phase0_result.get('processed_files', 0)}개")
    print(f"   - 스킵 (변경없음): {phase0_result.get('skipped_files', 0)}개")
    print(f"   - 실패: {phase0_result.get('failed_files', 0)}개")
    print(f"   - 성공률: {phase0_result.get('success_rate', 'N/A')}")
    print(f"   - File IDs: {len(file_ids)}개")
    
    # =========================================================================
    # Phase 1: Classification 결과
    # =========================================================================
    print(f"\n📋 [Phase 1] 분류 결과:")
    print(f"   - 메타데이터: {len(classification_result.get('metadata_files', []))}개")
    for f in classification_result.get("metadata_files", []):
        clf = classification_result.get("classifications", {}).get(f, {})
        confirmed = "✓ Human" if clf.get("human_confirmed") else "AI"
        print(f"      📖 [{confirmed}] {os.path.basename(f)}")
    
    print(f"   - 데이터: {len(classification_result.get('data_files', []))}개")
    for f in classification_result.get("data_files", []):
        clf = classification_result.get("classifications", {}).get(f, {})
        confirmed = "✓ Human" if clf.get("human_confirmed") else "AI"
        print(f"      📊 [{confirmed}] {os.path.basename(f)}")
    
    # =========================================================================
    # Phase 2: Processing 결과
    # =========================================================================
    print(f"\n🔄 [Phase 2] 처리 결과:")
    print(f"   - Phase: {processing_progress.get('phase')}")
    
    # 메타데이터 처리
    metadata_processed = processing_progress.get('metadata_processed', [])
    skipped_metadata = processing_progress.get('skipped_metadata_files', [])
    print(f"   - 메타데이터 처리: {len(metadata_processed)}개")
    for f in metadata_processed:
        print(f"      ✅ {os.path.basename(f)}")
    if skipped_metadata:
        print(f"   - 메타데이터 스킵: {len(skipped_metadata)}개")
        for skip in skipped_metadata:
            print(f"      ⏭️ {skip.get('filename', 'unknown')}: {skip.get('reason', '')}")
    
    # 데이터 처리
    data_processed = processing_progress.get('data_processed', [])
    skipped_data = processing_progress.get('skipped_data_files', [])
    print(f"   - 데이터 처리: {len(data_processed)}개")
    for f in data_processed:
        print(f"      ✅ {os.path.basename(f)}")
    if skipped_data:
        print(f"   - 데이터 스킵: {len(skipped_data)}개")
        for skip in skipped_data:
            print(f"      ⏭️ {skip.get('filename', 'unknown')}: {skip.get('reason', '')}")
    
    # =========================================================================
    # Ontology 정보
    # =========================================================================
    ontology = final_state.get("ontology_context", shared_ontology)
    print(f"\n📚 [Ontology] 최종 상태:")
    print(f"   - 용어 수: {len(ontology.get('definitions', {}))}개")
    print(f"   - 관계: {len(ontology.get('relationships', []))}개")
    print(f"   - 계층: {len(ontology.get('hierarchy', []))}개")
    print(f"   - 컬럼 계층: {len(ontology.get('column_hierarchy', []))}개")
    print(f"   - 태그된 파일: {len(ontology.get('file_tags', {}))}개")
    print(f"   - 컬럼 메타데이터: {len(ontology.get('column_metadata', {}))}개")
    
    # 온톨로지 상세 요약
    print(ontology_mgr.export_summary())
    
    # =========================================================================
    # 대화 히스토리 요약
    # =========================================================================
    conversation_history = final_state.get("conversation_history", {})
    turns = conversation_history.get("turns", [])
    if turns:
        print(f"\n💬 [Conversation] 대화 히스토리:")
        print(f"   - Session ID: {conversation_history.get('session_id')}")
        print(f"   - Total Turns: {len(turns)}개")
        print(f"   - Classification Decisions: {len(conversation_history.get('classification_decisions', []))}개")
        print(f"   - Anchor Decisions: {len(conversation_history.get('anchor_decisions', []))}개")
    
    print("\n" + "="*80)
    print("✅ 3-Phase Workflow 완료!")
    print("="*80)


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    """메인 함수 - 3-Phase Batch Workflow"""
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
