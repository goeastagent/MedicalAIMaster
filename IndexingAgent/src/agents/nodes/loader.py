# src/agents/nodes/loader.py
"""
Loader Node - 파일 로드 및 메타데이터 추출
"""

import os
from typing import Dict, Any

from src.agents.state import AgentState
from src.agents.nodes.common import processors


def load_data_node(state: AgentState) -> Dict[str, Any]:
    """
    [Node 1] Load file and extract basic metadata
    
    에러 발생 시 skip_indexing=True를 설정하여 해당 파일을 스킵합니다.
    스킵된 파일은 advance 노드에서 기록됩니다.
    """
    file_path = state["file_path"]
    filename = os.path.basename(file_path)
    
    print("\n" + "="*80)
    print(f"📂 [LOADER NODE] Starting - {filename}")
    print("="*80)
    
    # 1. Find appropriate Processor
    selected_processor = next((p for p in processors if p.can_handle(file_path)), None)
    
    if not selected_processor:
        print(f"   ⚠️ Processor 없음 - 파일 스킵")
        print("="*80)
        return {
            "logs": [f"⚠️ [Loader] Unsupported format, skipping: {filename}"],
            "error_message": f"No processor available for {filename}",
            "skip_indexing": True,  # NEW: 이 파일 스킵
            "skip_reason": "unsupported_format"
        }

    # 2. Extract metadata (Entity identification is also performed here)
    try:
        raw_metadata = selected_processor.extract_metadata(file_path)
        processor_type = raw_metadata.get("processor_type", "unknown")
        
        # Check if Processor failed to find or was uncertain about Entity Identifier
        entity_info = raw_metadata.get("entity_info", raw_metadata.get("anchor_info", {}))
        identification_status = entity_info.get("status", "MISSING")

        log_message = f"✅ [Loader] {processor_type.upper()} analysis complete. Identification Status: {identification_status}"

        print(f"\n✅ [LOADER NODE] Complete")
        print(f"   - Processor: {processor_type}")
        print(f"   - Columns: {len(raw_metadata.get('columns', []))}")
        print(f"   - Identification Status: {identification_status}")
        print("="*80)

        return {
            "file_type": processor_type,
            "raw_metadata": raw_metadata,
            "skip_indexing": False,  # 명시적으로 False 설정
            "logs": [log_message]
        }
    except Exception as e:
        print(f"\n❌ [LOADER NODE] Error: {str(e)}")
        print(f"   ⚠️ 파일 스킵됨")
        print("="*80)
        return {
            "logs": [f"❌ [Loader] Error, skipping: {filename} - {str(e)}"],
            "error_message": str(e),
            "skip_indexing": True,  # NEW: 에러 발생 시 스킵
            "skip_reason": "load_error"
        }

