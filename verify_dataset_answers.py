import json
import concurrent.futures
import numpy as np
import pandas as pd
import vitaldb
import sys

# Define all the tool functions from the dataset
# I will define them exactly as they appear in the JSON to ensure fidelity

def fetch_max_hr(case_id):
    try:
        vals = vitaldb.load_case(case_id, ['Solar8000/HR'], 1)
        if vals is None or len(vals) == 0: return None
        return float(np.nanmax(vals[:, 0]))
    except: return None

def fetch_min_hr(case_id):
    try:
        vals = vitaldb.load_case(case_id, ['Solar8000/HR'], 1)
        if vals is None or len(vals) == 0: return None
        return float(np.nanmin(vals[:, 0]))
    except: return None

def fetch_median_hr(case_id):
    try:
        vals = vitaldb.load_case(case_id, ['Solar8000/HR'], 1)
        if vals is None or len(vals) == 0: return None
        val = np.nanmedian(vals[:, 0])
        return round(float(val), 2)
    except: return None

def fetch_mean_abp(case_id):
    try:
        # ABP Mean = Solar8000/ART_MBP 트랙 사용
        vals = vitaldb.load_case(case_id, ['Solar8000/ART_MBP'], 1)
        if vals is None or len(vals) == 0: return None
        val = np.nanmean(vals[:, 0])
        return round(float(val), 2)
    except: return None

def fetch_max_abp(case_id):
    try:
        # ABP Max = Solar8000/ART_SBP (수축기) 트랙 사용
        vals = vitaldb.load_case(case_id, ['Solar8000/ART_SBP'], 1)
        if vals is None or len(vals) == 0: return None
        val = np.nanmax(vals[:, 0])
        return round(float(val), 2)
    except: return None

def fetch_min_abp_filtered(case_id):
    try:
        # ABP Min = Solar8000/ART_DBP (이완기) 트랙 사용
        vals = vitaldb.load_case(case_id, ['Solar8000/ART_DBP'], 1)
        if vals is None or len(vals) == 0: return None
        
        data = vals[:, 0]
        # 0보다 큰 값만 추출 (0이하 노이즈 제거)
        valid_data = data[data > 0]
        
        if len(valid_data) > 0:
            return round(float(np.min(valid_data)), 2)
        else:
            return None
    except: return None

def fetch_median_abp(case_id):
    try:
        # ABP의 중심 경향(Median) = Solar8000/ART_MBP 사용
        vals = vitaldb.load_case(case_id, ['Solar8000/ART_MBP'], 1)
        if vals is None or len(vals) == 0: return None
        
        # 결측치 제외 중간값 계산
        val = np.nanmedian(vals[:, 0])
        return round(float(val), 2)
    except: return None

def fetch_mean_spo2(case_id):
    try:
        # SpO2 트랙 로드 (Solar8000/PLETH_SPO2)
        vals = vitaldb.load_case(case_id, ['Solar8000/PLETH_SPO2'], 1)
        if vals is None or len(vals) == 0: return None
        
        # NaN 제외하고 평균 계산
        val = np.nanmean(vals[:, 0])
        return round(float(val), 2)
    except: return None

def fetch_min_spo2(case_id):
    try:
        # SpO2 트랙 로드
        vals = vitaldb.load_case(case_id, ['Solar8000/PLETH_SPO2'], 1)
        if vals is None or len(vals) == 0: return None
        
        # 필터링 없이 순수 최솟값 계산 (np.nanmin)
        val = np.nanmin(vals[:, 0])
        return round(float(val), 2)
    except: return None

def fetch_median_spo2(case_id):
    try:
        # SpO2 트랙 로드
        vals = vitaldb.load_case(case_id, ['Solar8000/PLETH_SPO2'], 1)
        if vals is None or len(vals) == 0: return None
        
        # 중간값(Median) 계산 - 이상치에 강함
        val = np.nanmedian(vals[:, 0])
        return round(float(val), 2)
    except: return None

def fetch_mean_bis(case_id):
    try:
        vals = vitaldb.load_case(case_id, ['BIS/BIS'], 1)
        if vals is None or len(vals) == 0: return None
        bis_data = vals[:, 0]
        # 0을 포함하여 평균 계산 (NaN만 제거)
        valid_bis = bis_data[~np.isnan(bis_data)]
        if len(valid_bis) == 0: return None
        return round(float(np.mean(valid_bis)), 2)
    except: return None

def fetch_min_bis(case_id):
    try:
        vals = vitaldb.load_case(case_id, ['BIS/BIS'], 1)
        if vals is None or len(vals) == 0: return None
        bis_data = vals[:, 0]
        # 0을 포함하여 최솟값 계산
        val = np.nanmin(bis_data)
        if np.isnan(val): return None
        return round(float(val), 2)
    except: return None

def fetch_median_bis(case_id):
    try:
        vals = vitaldb.load_case(case_id, ['BIS/BIS'], 1)
        if vals is None or len(vals) == 0: return None
        # 0을 포함하여 중간값 계산
        val = np.nanmedian(vals[:, 0])
        if np.isnan(val): return None
        return round(float(val), 2)
    except: return None

def get_op_duration_batch(target_ids=[1, 2, 9]):
    df_cases = pd.read_csv('https://api.vitaldb.net/cases')
    df_selected = df_cases[df_cases['caseid'].isin(target_ids)].copy()
    # Ensure order matches target_ids
    df_selected = df_selected.set_index('caseid').reindex(target_ids).reset_index()
    
    # 수술 종료(opend) - 수술 시작(opstart)을 60으로 나누어 분 단위 계산
    df_selected['duration_min'] = (df_selected['opend'] - df_selected['opstart']) / 60
    return [round(d, 1) if pd.notnull(d) else None for d in df_selected['duration_min']]

def fetch_sbp_mean_filtered(case_id):
    try:
        # SBP = 'Solar8000/ART_SBP' 트랙
        vals = vitaldb.load_case(case_id, ['Solar8000/ART_SBP'], 1)
        if vals is None or len(vals) == 0: return None
        
        sbp_data = vals[:, 0]
        # 0 이하 노이즈 및 NaN 제외
        valid_sbp = sbp_data[(sbp_data > 0) & (~np.isnan(sbp_data))]
        
        if len(valid_sbp) == 0: return None
        return round(float(np.mean(valid_sbp)), 2)
    except: return None

def fetch_sbp_max(case_id):
    try:
        # SBP = 'Solar8000/ART_SBP' 트랙
        vals = vitaldb.load_case(case_id, ['Solar8000/ART_SBP'], 1)
        if vals is None or len(vals) == 0: return None
        
        sbp_data = vals[:, 0]
        # 모든 값이 NaN인 경우 제외
        if np.all(np.isnan(sbp_data)): return None
            
        # 최댓값은 노이즈(0)보다 크므로 별도 필터 없이 nanmax 사용
        return round(float(np.nanmax(sbp_data)), 2)
    except: return None

def fetch_sbp_min_filtered(case_id):
    try:
        # SBP = 'Solar8000/ART_SBP' 트랙
        vals = vitaldb.load_case(case_id, ['Solar8000/ART_SBP'], 1)
        if vals is None or len(vals) == 0: return None
        
        sbp_data = vals[:, 0]
        # 0 이하 및 NaN 제외
        valid_sbp = sbp_data[(sbp_data > 0) & (~np.isnan(sbp_data))]
        
        if len(valid_sbp) == 0: return None
        return round(float(np.min(valid_sbp)), 2)
    except: return None

def fetch_sbp_median_filtered(case_id):
    try:
        # SBP = 'Solar8000/ART_SBP' 트랙
        vals = vitaldb.load_case(case_id, ['Solar8000/ART_SBP'], 1)
        if vals is None or len(vals) == 0: return None
        
        sbp_data = vals[:, 0]
        # 0 이하 및 NaN 제외
        valid_sbp = sbp_data[(sbp_data > 0) & (~np.isnan(sbp_data))]
        
        if len(valid_sbp) == 0: return None
        return round(float(np.median(valid_sbp)), 2)
    except: return None

def fetch_dbp_stats(case_id):
    try:
        # DBP = 'Solar8000/ART_DBP'
        vals = vitaldb.load_case(case_id, ['Solar8000/ART_DBP'], 1)
        if vals is None or len(vals) == 0: 
            return None
        
        dbp_data = vals[:, 0]
        # 0 이하 및 NaN 제외
        valid_dbp = dbp_data[(dbp_data > 0) & (~np.isnan(dbp_data))]
        
        if len(valid_dbp) == 0: 
            return None
            
        return {
            "mean": round(float(np.mean(valid_dbp)), 2),
            "max": round(float(np.max(valid_dbp)), 2),
            "min": round(float(np.min(valid_dbp)), 2),
            "median": round(float(np.median(valid_dbp)), 2)
        }
    except: 
        return None

def fetch_etco2_mean(case_id):
    try:
        # EtCO2 = 'Solar8000/ETCO2'
        vals = vitaldb.load_case(case_id, ['Solar8000/ETCO2'], 1)
        if vals is None or len(vals) == 0: return None
        
        etco2_data = vals[:, 0]
        # 0 이하 및 NaN 제외
        valid_etco2 = etco2_data[(etco2_data > 0) & (~np.isnan(etco2_data))]
        
        if len(valid_etco2) == 0: return None
        return round(float(np.mean(valid_etco2)), 2)
    except: return None

def fetch_etco2_stats(case_id):
    try:
        # EtCO2 = 'Solar8000/ETCO2'
        vals = vitaldb.load_case(case_id, ['Solar8000/ETCO2'], 1)
        if vals is None or len(vals) == 0: return None
        
        etco2_data = vals[:, 0]
        # 통상적인 분석을 위해 0 이하 노이즈 제거 (Min 값이 0이 되지 않도록)
        valid_etco2 = etco2_data[(etco2_data > 0) & (~np.isnan(etco2_data))]
        
        if len(valid_etco2) == 0: return None
        
        return {
            "max": round(float(np.max(valid_etco2)), 2),
            "min": round(float(np.min(valid_etco2)), 2),
            "median": round(float(np.median(valid_etco2)), 2)
        }
    except: return None

def fetch_hrv_sdnn(case_id):
    try:
        # HRV usually requires ECG analysis (R-R intervals). 
        # For a simple API check without downloading waveforms, we approximate using the HR track.
        # We calculate SDNN (Standard Deviation of NN intervals) from the 1-second HR data.
        # This is an approximation.
        vals = vitaldb.load_case(case_id, ['Solar8000/HR'], 1)
        if vals is None or len(vals) == 0: return None
        
        hr_data = vals[:, 0]
        # Filter valid HR (excluding 0 and NaN)
        valid_hr = hr_data[(hr_data > 0) & (~np.isnan(hr_data))]
        
        if len(valid_hr) < 2: return None
        
        # Convert BPM to RR intervals (ms)
        rr_intervals = 60000 / valid_hr
        
        # Calculate SDNN (Standard Deviation of RR intervals)
        sdnn = np.std(rr_intervals)
        
        return round(float(sdnn), 2)
    except: return None

def fetch_dbp_over_90_duration(case_id):
    try:
        # 지속 시간을 계산하려면 연속 데이터인 'Solar8000/ART_DBP' (1초 간격)가 적합
        vals = vitaldb.load_case(case_id, ['Solar8000/ART_DBP'], 1)
        if vals is None or len(vals) == 0: return None
        
        dbp_data = vals[:, 0]
        # NaN 제외
        valid_dbp = dbp_data[~np.isnan(dbp_data)]
        
        if len(valid_dbp) == 0: return 0.0
        
        # 90 이상인 데이터 포인트 개수 (1초 간격이므로 개수 = 초)
        count_seconds = np.sum(valid_dbp >= 90)
        
        # 분(minute) 단위로 변환
        duration_min = round(count_seconds / 60.0, 2)
        
        return duration_min
    except: return None

def fetch_dbp_under_50_duration(case_id):
    try:
        # Load DBP track
        vals = vitaldb.load_case(case_id, ['Solar8000/ART_DBP'], 1)
        if vals is None or len(vals) == 0: return None
        
        dbp_data = vals[:, 0]
        # 중요: 0보다 크고 50 이하인 값만 필터링 (0은 노이즈로 간주하고 제외)
        valid_dbp = dbp_data[(dbp_data > 0) & (~np.isnan(dbp_data))]
        
        if len(valid_dbp) == 0: return 0.0
        
        # 50 이하인 샘플 개수 (1초 간격)
        count_seconds = np.sum(valid_dbp <= 50)
        
        # 분 단위 변환
        duration_min = round(count_seconds / 60.0, 2)
        
        return duration_min
    except: return None

# Mapping from ID to function
func_map = {
    1: fetch_max_hr,
    2: fetch_min_hr,
    3: fetch_median_hr,
    4: fetch_mean_abp,
    5: fetch_max_abp,
    6: fetch_min_abp_filtered,
    7: fetch_median_abp,
    8: fetch_mean_spo2,
    9: fetch_min_spo2,
    10: fetch_median_spo2,
    11: fetch_mean_bis,
    12: fetch_min_bis,
    13: fetch_median_bis,
    # 14 is special (pandas)
    15: fetch_sbp_mean_filtered,
    16: fetch_sbp_max,
    17: fetch_sbp_min_filtered,
    18: fetch_sbp_median_filtered,
    19: fetch_dbp_stats,
    20: fetch_etco2_mean,
    21: fetch_etco2_stats,
    22: fetch_hrv_sdnn,
    23: fetch_dbp_over_90_duration,
    24: fetch_dbp_under_50_duration
}

def verify_answers():
    input_path = 'testdata/case3_low_dataset.json'
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    target_ids = [1, 2, 9]
    
    print(f"Verifying answers for cases {target_ids}...\n")
    
    for item in data:
        q_id = item['id']
        expected_answer_str = item['answer']
        
        # Parse expected answer
        try:
            expected_answer = json.loads(expected_answer_str.replace("'", '"').replace("None", "null"))
        except:
            # Fallback for simple list string
            try:
                import ast
                expected_answer = ast.literal_eval(expected_answer_str)
            except:
                print(f"[{q_id}] Failed to parse expected answer: {expected_answer_str}")
                continue

        print(f"[{q_id}] Verifying...")
        
        calculated_result = []
        
        if q_id == 14:
            # Special case for op duration
            try:
                calculated_result = get_op_duration_batch(target_ids)
            except Exception as e:
                print(f"  Error calculating: {e}")
                continue
        elif q_id in func_map:
            func = func_map[q_id]
            for cid in target_ids:
                try:
                    res = func(cid)
                    calculated_result.append(res)
                except Exception as e:
                    print(f"  Error for case {cid}: {e}")
                    calculated_result.append(None)
        else:
            print(f"  No function mapped for ID {q_id}")
            continue
            
        # Compare
        is_match = True
        if str(expected_answer) != str(calculated_result):
            # Try float comparison with tolerance
            try:
                # If list of dicts
                if isinstance(expected_answer[0], dict):
                     if str(expected_answer) != str(calculated_result):
                         is_match = False
                else:
                    # List of values
                    for exp, calc in zip(expected_answer, calculated_result):
                        if exp is None and calc is None: continue
                        if exp is None or calc is None: 
                            is_match = False; break
                        
                        if abs(float(exp) - float(calc)) > 0.01: # 0.01 tolerance
                             is_match = False; break
            except:
                is_match = False
        
        if is_match:
            print(f"  ✅ Match! {calculated_result}")
        else:
            print(f"  ❌ Mismatch!")
            print(f"     Expected: {expected_answer}")
            print(f"     Calculated: {calculated_result}")

if __name__ == "__main__":
    verify_answers()
