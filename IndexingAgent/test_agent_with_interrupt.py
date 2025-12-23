#!/usr/bin/env python3
# test_agent_with_interrupt.py
"""
LangGraph의 공식 Interrupt 메커니즘을 사용한 Human-in-the-Loop 테스트
여러 CSV 파일을 순차적으로 처리하며 Global Context를 유지합니다.

⭐ 2-Pass 처리 방식:
   Pass 1: 모든 파일을 사전 분류 (메타데이터 vs 데이터)
   Pass 2: 메타데이터 먼저 처리 → 데이터 파일 처리
"""

import sys
import os
import glob
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from agents.graph import build_agent
from langgraph.checkpoint.memory import MemorySaver


# ============================================================================
# Pass 1: 사전 분류 (Pre-classification)
# ============================================================================

def preclassify_files(file_paths: list) -> dict:
    """
    [Pass 1] 모든 파일을 빠르게 스캔하여 메타데이터/데이터로 분류
    
    Returns:
        {
            "metadata_files": [...],  # 메타데이터 파일 경로 리스트
            "data_files": [...],      # 데이터 파일 경로 리스트
            "classification": {...}   # 파일별 분류 결과
        }
    """
    from src.processors.tabular import TabularProcessor
    from src.utils.llm_client import get_llm_client
    from src.utils.llm_cache import get_llm_cache
    
    print("\n" + "="*80)
    print("🔍 [Pass 1] 파일 사전 분류 (Pre-classification)")
    print("="*80)
    print(f"   총 {len(file_paths)}개 파일을 분류합니다...\n")
    
    llm_client = get_llm_client()
    llm_cache = get_llm_cache()
    processor = TabularProcessor(llm_client)
    
    metadata_files = []
    data_files = []
    classification = {}
    
    for idx, file_path in enumerate(file_paths, 1):
        filename = os.path.basename(file_path)
        print(f"   [{idx}/{len(file_paths)}] {filename}...", end=" ")
        
        try:
            # 1. 기초 메타데이터 추출 (빠른 스캔)
            if not processor.can_handle(file_path):
                print("⚠️ 지원하지 않는 형식")
                data_files.append(file_path)
                classification[file_path] = {"is_metadata": False, "reason": "Unsupported format"}
                continue
            
            raw_metadata = processor.extract_metadata(file_path)
            
            # 2. 분류용 컨텍스트 생성 (간소화)
            context = _build_classification_context(file_path, raw_metadata)
            
            # 3. LLM에게 분류 요청 (캐시 활용)
            result = _classify_file_with_llm(context, llm_cache, llm_client)
            
            is_metadata = result.get("is_metadata", False)
            confidence = result.get("confidence", 0.0)
            
            classification[file_path] = {
                "is_metadata": is_metadata,
                "confidence": confidence,
                "reason": result.get("reasoning", "N/A")
            }
            
            if is_metadata:
                metadata_files.append(file_path)
                print(f"📖 메타데이터 ({confidence:.0%})")
            else:
                data_files.append(file_path)
                print(f"📊 데이터 ({confidence:.0%})")
                
        except Exception as e:
            print(f"❌ 오류: {e}")
            data_files.append(file_path)  # 실패 시 데이터로 가정
            classification[file_path] = {"is_metadata": False, "reason": f"Error: {str(e)}"}
    
    print("\n" + "-"*80)
    print(f"📖 메타데이터 파일: {len(metadata_files)}개")
    for f in metadata_files:
        print(f"   • {os.path.basename(f)}")
    print(f"📊 데이터 파일: {len(data_files)}개")
    for f in data_files:
        print(f"   • {os.path.basename(f)}")
    print("="*80)
    
    return {
        "metadata_files": metadata_files,
        "data_files": data_files,
        "classification": classification
    }


def _build_classification_context(file_path: str, raw_metadata: dict) -> dict:
    """분류용 컨텍스트 생성 (간소화 버전)"""
    import pandas as pd
    
    filename = os.path.basename(file_path)
    name_parts = filename.replace(".csv", "").replace("_", " ").replace("-", " ").split()
    base_name = filename.rsplit(".", 1)[0]
    extension = filename.rsplit(".", 1)[-1] if "." in filename else ""
    
    columns = raw_metadata.get("columns", [])
    
    # 샘플 데이터 (처음 5행만)
    sample_data = []
    try:
        df = pd.read_csv(file_path, nrows=5)
        for col in columns[:5]:  # 처음 5개 컬럼만
            if col in df.columns:
                samples = df[col].dropna().head(3).tolist()
                sample_data.append({
                    "column": col,
                    "samples": [str(s)[:100] for s in samples],
                    "avg_text_length": sum(len(str(s)) for s in samples) / max(len(samples), 1)
                })
    except:
        pass
    
    return {
        "filename": filename,
        "name_parts": name_parts,
        "base_name": base_name,
        "extension": extension,
        "num_columns": len(columns),
        "columns": columns,
        "sample_data": sample_data
    }


def _classify_file_with_llm(context: dict, llm_cache, llm_client) -> dict:
    """LLM으로 파일 분류 (캐시 활용)"""
    
    # 캐시 확인
    cached = llm_cache.get("file_preclassification", context)
    if cached:
        return cached
    
    prompt = f"""
You are a Data Classification Expert. Quickly classify this file.

[FILE INFO]
Filename: {context['filename']}
Name Parts: {context['name_parts']}
Columns ({context['num_columns']}): {context['columns'][:10]}...
Sample Data: {json.dumps(context['sample_data'][:3], ensure_ascii=False)}

[CLASSIFICATION]
- METADATA: Describes other data (codebook, parameter list, dictionary)
  * Usually has columns like: [Name, Description, Unit, Type]
  * Content is explanatory text, not measurements

- DATA: Actual records/measurements
  * Contains patient records, lab results, events
  * Values are data points, not descriptions

[OUTPUT - JSON ONLY]
{{
    "is_metadata": true or false,
    "confidence": 0.0 to 1.0,
    "reasoning": "Brief reason"
}}
"""
    
    try:
        result = llm_client.ask_json(prompt)
        llm_cache.set("file_preclassification", context, result)
        return result
    except Exception as e:
        return {"is_metadata": False, "confidence": 0.5, "reasoning": f"LLM error: {str(e)}"}


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
                print("   - 'unknown' 입력: AI가 자동 결정하도록 위임")
                print("─" * 80)
                
                # 사용자 입력
                user_feedback = input("\n>>> 입력: ").strip()
                
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
                    print("   - Enter만 입력: 자동 처리 (3번 재시도 후 강제 진행)")
                    print("─" * 80)
                    
                    # 사용자 입력
                    user_feedback = input("\n>>> 입력: ").strip()
                    
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
    """메인 함수 - 2-Pass 처리 방식"""
    from pathlib import Path
    
    data_dir = Path(__file__).parent / "data" / "raw"
    
    # CSV 파일 (INSPIRE 데이터셋)
    inspire_files = sorted(glob.glob(str(data_dir / "INSPIRE_130K_1.3/*.csv")))
    
    # VitalDB CSV 파일
    vital_csv_files = sorted(glob.glob(str(data_dir / "Open_VitalDB_1.0.0/*.csv")))
    
    # VitalDB 파일 (신호 데이터)
    vital_signal_files = sorted(glob.glob(str(data_dir / "Open_VitalDB_1.0.0/vital_files/*.vital")))
    
    # 요청에 의해 Open_VitalDB_1.0.0 CSV 파일만 indexing하도록 설정
    all_files = vital_csv_files

    if not all_files:
        print(f"❌ 파일을 찾을 수 없습니다: {data_dir}")
        return
    
    print(f"\n📁 Found {len(all_files)} files:")
    print(f"   📊 INSPIRE CSV: {len(inspire_files)}개")
    print(f"   📊 VitalDB CSV: {len(vital_csv_files)}개")
    for f in vital_csv_files:
        print(f"      - {os.path.basename(f)}")
    print(f"   📈 VitalDB Signal: {len(vital_signal_files)}개")
    
    # ⭐ [Pass 1] 사전 분류 - 메타데이터 vs 데이터 구분
    classification_result = preclassify_files(all_files)
    
    metadata_files = classification_result["metadata_files"]
    data_files = classification_result["data_files"]
    
    # ⭐ [Pass 2] 메타데이터 먼저 → 데이터 나중에 처리
    ordered_files = metadata_files + data_files
    
    print(f"\n📋 처리 순서 (메타데이터 우선):")
    for i, f in enumerate(ordered_files, 1):
        file_type = "📖 메타데이터" if f in metadata_files else "📊 데이터"
        print(f"   {i}. {file_type}: {os.path.basename(f)}")
    
    # [TEST] 속도 향상을 위해 데이터 로드 제한 설정 (1000행)
    # os.environ["TEST_ROW_LIMIT"] = "1000"
    # print("\n⚠️  [TEST MODE] 데이터 로드 제한 설정됨 (TEST_ROW_LIMIT=1000)")
    
    # Pass 2 실행
    test_multiple_files_with_interrupt(ordered_files)
    
    # 캐시 통계 출력 (전역 캐시 import)
    from src.utils.llm_cache import get_llm_cache
    cache = get_llm_cache()
    cache.print_stats()
    
    # ⭐ [Pass 3] VectorDB 임베딩 자동 생성
    print("\n" + "="*80)
    print("🔢 [VectorDB] 임베딩 생성 시작...")
    print("="*80)
    
    try:
        from src.knowledge.vector_store import VectorStore
        from src.utils.ontology_manager import get_ontology_manager
        
        # 온톨로지 로드
        ontology_mgr = get_ontology_manager()
        ontology = ontology_mgr.load()
        
        if ontology and (ontology.get("definitions") or ontology.get("column_metadata")):
            # VectorStore 초기화 및 임베딩 생성
            vector_store = VectorStore()
            vector_store.initialize()
            vector_store.build_index(ontology)
            
            # 통계 출력
            stats = vector_store.get_stats()
            print(f"\n✅ [VectorDB] 임베딩 생성 완료")
            print(f"   - Provider: {stats.get('provider')}")
            print(f"   - Dimensions: {stats.get('dimensions')}")
            print(f"   - Total Embeddings: {stats.get('total', 0)}개")
        else:
            print("⚠️  [VectorDB] 임베딩할 데이터 없음 (온톨로지 비어있음)")
    except Exception as e:
        print(f"⚠️  [VectorDB] 임베딩 생성 실패: {e}")
        print("   (pgvector 미설치 시: brew install pgvector)")
    
    print("\n" + "="*80)
    print("✅ 모든 작업 완료!")
    print("="*80)


if __name__ == "__main__":
    main()

