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
    """
    file_path = state["file_path"]
    
    print("\n" + "="*80)
    print(f"📂 [LOADER NODE] Starting - {os.path.basename(file_path)}")
    print("="*80)
    
    # 1. Find appropriate Processor
    selected_processor = next((p for p in processors if p.can_handle(file_path)), None)
    
    if not selected_processor:
        return {
            "logs": [f"❌ Error: Unsupported file format ({file_path})"],
            "needs_human_review": True,
            "human_question": "Unsupported file format. How would you like to process this file?"
        }

    # 2. Extract metadata (Anchor detection is also performed here)
    try:
        raw_metadata = selected_processor.extract_metadata(file_path)
        processor_type = raw_metadata.get("processor_type", "unknown")
        
        # Check if Processor failed to find or was uncertain about Anchor
        anchor_info = raw_metadata.get("anchor_info", {})
        anchor_status = anchor_info.get("status", "MISSING")

        log_message = f"✅ [Loader] {processor_type.upper()} analysis complete. Anchor Status: {anchor_status}"

        print(f"\n✅ [LOADER NODE] Complete")
        print(f"   - Processor: {processor_type}")
        print(f"   - Columns: {len(raw_metadata.get('columns', []))}")
        print(f"   - Anchor Status: {anchor_status}")
        print("="*80)

        return {
            "file_type": processor_type,
            "raw_metadata": raw_metadata,
            "logs": [log_message]
        }
    except Exception as e:
        print(f"\n❌ [LOADER NODE] Error: {str(e)}")
        print("="*80)
        return {
            "logs": [f"❌ [Loader] Critical error: {str(e)}"],
            "error_message": str(e)
        }

