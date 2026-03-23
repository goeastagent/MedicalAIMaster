import os
import json
import vitaldb
from pathlib import Path

def extract_metadata():
    project_root = Path(__file__).resolve().parent.parent.parent
    vital_dir = project_root / "IndexingAgent" / "data" / "raw" / "Open_VitalDB_1.0.0" / "vital_files"
    
    if not vital_dir.exists():
        print(f"Error: Vital directory not found at {vital_dir}")
        return

    metadata = {}
    
    # We only care about 0001, 0002, 0009 as per previous constraints
    target_cases = ["0001", "0002", "0009"]
    
    for caseid in target_cases:
        file_path = vital_dir / f"{caseid}.vital"
        if file_path.exists():
            print(f"Processing {caseid}.vital...")
            vf = vitaldb.VitalFile(str(file_path))
            
            # Use SNUADC/ECG_II as a reference track to get the length in seconds at 1Hz
            # If not present, we can just get the first available track
            tracks = vf.get_track_names()
            if not tracks:
                continue
                
            ref_track = 'SNUADC/ECG_II' if 'SNUADC/ECG_II' in tracks else tracks[0]
            
            # Extract at 1Hz to get duration in seconds
            vals = vf.to_numpy([ref_track], 1)
            duration_sec = len(vals)
            
            metadata[caseid] = {
                "duration_sec": duration_sec,
                "tracks": tracks
            }
            print(f"  - Duration: {duration_sec} seconds")
            print(f"  - Tracks count: {len(tracks)}")
        else:
            print(f"Warning: {caseid}.vital not found.")

    output_path = Path(__file__).resolve().parent / "vital_metadata.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=4)
        
    print(f"\nMetadata successfully saved to {output_path}")

if __name__ == "__main__":
    extract_metadata()
