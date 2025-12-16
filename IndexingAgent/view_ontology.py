#!/usr/bin/env python3
# view_ontology.py
"""
온톨로지 DB 확인 스크립트

저장된 온톨로지를 읽어서 내용을 출력합니다.
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from utils.ontology_manager import get_ontology_manager


def main():
    """온톨로지 내용 확인"""
    print("\n" + "="*80)
    print("📚 Ontology Database Viewer")
    print("="*80)
    
    # 온톨로지 로드
    manager = get_ontology_manager()
    ontology = manager.load()
    
    if not ontology or not ontology.get("definitions"):
        print("\n⚠️  온톨로지가 비어있습니다.")
        print("먼저 test_agent_with_interrupt.py를 실행하세요.")
        return
    
    # 요약 출력
    print(manager.export_summary())
    
    # 상세 내용
    print("\n" + "="*80)
    print("📖 Definitions (용어 사전)")
    print("="*80)
    
    definitions = ontology.get("definitions", {})
    for i, (key, val) in enumerate(sorted(definitions.items())[:10]):
        print(f"\n{i+1}. {key}")
        print(f"   {val}")
    
    if len(definitions) > 10:
        print(f"\n... and {len(definitions) - 10} more definitions")
    
    # 파일 태그
    print("\n" + "="*80)
    print("🏷️  File Tags")
    print("="*80)
    
    file_tags = ontology.get("file_tags", {})
    for file_path, tag_info in file_tags.items():
        filename = os.path.basename(file_path)
        file_type = tag_info.get("type", "unknown")
        confidence = tag_info.get("confidence", 0.0)
        
        icon = "📖" if file_type == "metadata" else "📊"
        print(f"{icon} {filename}")
        print(f"   - Type: {file_type}")
        print(f"   - Confidence: {confidence:.1%}")
        print(f"   - Detected: {tag_info.get('detected_at', 'N/A')[:19]}")
    
    # 관계
    relationships = ontology.get("relationships", [])
    if relationships:
        print("\n" + "="*80)
        print("🔗 Relationships")
        print("="*80)
        
        for rel in relationships:
            print(f"\n{rel['source_table']}.{rel['source_column']}")
            print(f"  → {rel['target_table']}.{rel['target_column']}")
            print(f"  Type: {rel['relation_type']}, Confidence: {rel.get('confidence', 0):.1%}")
    
    # 계층
    hierarchy = ontology.get("hierarchy", [])
    if hierarchy:
        print("\n" + "="*80)
        print("🏗️  Hierarchy")
        print("="*80)
        
        for h in sorted(hierarchy, key=lambda x: x['level']):
            print(f"\nLevel {h['level']}: {h['entity_name']}")
            print(f"  - Anchor: {h['anchor_column']}")
            print(f"  - Mapping Table: {h.get('mapping_table', 'N/A')}")
            print(f"  - Confidence: {h.get('confidence', 0):.1%}")
    
    # 메타데이터
    metadata_info = ontology.get("metadata", {})
    print("\n" + "="*80)
    print("📊 Statistics")
    print("="*80)
    print(f"  Created: {ontology.get('created_at', 'N/A')[:19]}")
    print(f"  Last Updated: {ontology.get('last_updated', 'N/A')[:19]}")
    print(f"  Total Tables: {metadata_info.get('total_tables', 0)}")
    print(f"  Total Definitions: {metadata_info.get('total_definitions', 0)}")
    print(f"  Total Relationships: {metadata_info.get('total_relationships', 0)}")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()

