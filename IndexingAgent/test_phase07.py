#!/usr/bin/env python
"""
Phase 0.7 테스트: File Classification

파일을 metadata/data로 분류하는 기능을 테스트합니다.

Usage:
    python test_phase07.py [--reset]

Options:
    --reset: DB 테이블 초기화 후 실행
"""

import os
import sys

# 프로젝트 루트를 PYTHONPATH에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.agents.graph import build_phase07_agent
from src.database.schema_catalog import init_catalog_schema


def get_test_files():
    """테스트용 파일 목록 반환 (Open_VitalDB만 사용)"""
    base_path = os.path.join(os.path.dirname(__file__), "data/raw/Open_VitalDB_1.0.0")
    
    files = [
        os.path.join(base_path, "clinical_parameters.csv"),
        os.path.join(base_path, "clinical_data.csv"),
        os.path.join(base_path, "lab_parameters.csv"),
        os.path.join(base_path, "lab_data.csv"),
        os.path.join(base_path, "track_names.csv"),
    ]
    
    # 존재하는 파일만 필터링
    existing_files = [f for f in files if os.path.exists(f)]
    
    if not existing_files:
        print("❌ No Open_VitalDB test files found!")
        print(f"   Expected path: {base_path}")
    
    return existing_files


def main(reset: bool = False):
    """Phase 0.7 테스트 실행"""
    print("=" * 70)
    print("🧪 Phase 0.7 Test: File Classification")
    print("=" * 70)
    
    # 1. DB 스키마 초기화
    print("\n📦 Initializing database schema...")
    init_catalog_schema(reset=reset)
    
    # 2. 테스트 파일 확인
    test_files = get_test_files()
    if not test_files:
        print("❌ No test files found!")
        return
    
    print(f"\n📂 Test files ({len(test_files)}):")
    for f in test_files:
        print(f"   - {os.path.basename(f)}")
    
    # 3. 워크플로우 빌드 및 실행
    print("\n🚀 Building Phase 0.7 workflow...")
    agent = build_phase07_agent()
    
    # 초기 상태
    initial_state = {
        "current_dataset_id": "test_dataset",
        "input_files": test_files,
        "data_catalog": {},
        "logs": [],
        # Phase 0 결과 (빈 상태로 시작)
        "phase0_result": None,
        "phase0_file_ids": [],
        # Phase 0.5 결과
        "phase05_result": None,
        "unique_columns": [],
        "unique_files": [],
        "column_batches": [],
        "file_batches": [],
        # Phase 0.7 결과
        "phase07_result": None,
        "metadata_files": [],
        "data_files": [],
    }
    
    print("\n🔄 Running workflow...")
    print("-" * 70)
    
    # 워크플로우 실행
    result = agent.invoke(initial_state)
    
    print("-" * 70)
    
    # 4. 결과 출력
    print("\n📊 Results:")
    
    phase07_result = result.get("phase07_result", {})
    metadata_files = result.get("metadata_files", [])
    data_files = result.get("data_files", [])
    
    print(f"\n   📋 Metadata files ({len(metadata_files)}):")
    for f in metadata_files:
        print(f"      - {os.path.basename(f)}")
    
    print(f"\n   📊 Data files ({len(data_files)}):")
    for f in data_files:
        print(f"      - {os.path.basename(f)}")
    
    if phase07_result.get("classifications"):
        print(f"\n   📝 Classification details:")
        for fname, details in phase07_result.get("classifications", {}).items():
            is_meta = "📋 metadata" if details.get("is_metadata") else "📊 data"
            conf = details.get("confidence", 0)
            print(f"      {fname}: {is_meta} (conf={conf:.2f})")
    
    # 5. 로그 출력
    print("\n📜 Logs:")
    for log in result.get("logs", []):
        print(f"   {log}")
    
    print("\n" + "=" * 70)
    print("✅ Phase 0.7 Test Complete!")
    print("=" * 70)
    
    return result


if __name__ == "__main__":
    reset = "--reset" in sys.argv
    main(reset=reset)

