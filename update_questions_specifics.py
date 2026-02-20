import json

input_path = 'testdata/case3_low_dataset.json'

with open(input_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

for item in data:
    q_id = item['id']
    q = item['question']
    
    # 1. SBP/DBP -> 동맥혈압(ART) 명시
    if q_id in [15, 16, 17, 18]:
        if "수축기 혈압(SBP)" in q:
            item['question'] = q.replace("수축기 혈압(SBP)", "동맥혈압(ART) 수축기 혈압(SBP)")
    
    elif q_id == 19:
        if "이완기 혈압(DBP)" in q:
            item['question'] = q.replace("이완기 혈압(DBP)", "동맥혈압(ART) 이완기 혈압(DBP)")
            
    elif q_id in [23, 24]:
        if "DBP 값" in q:
            item['question'] = q.replace("DBP 값", "동맥혈압(ART) 이완기 혈압(DBP) 값")
            
    # 2. EtCO2 -> Solar8000 명시
    elif q_id in [20, 21]:
        if "호기말 이산화탄소(EtCO2)" in q:
            item['question'] = q.replace("호기말 이산화탄소(EtCO2)", "Solar8000 장비의 호기말 이산화탄소(EtCO2)")
            
    # 3. HRV -> SDNN 방식 명시
    elif q_id == 22:
        if "HRV(심박변이도)" in q:
            item['question'] = q.replace("HRV(심박변이도)", "HRV(심박변이도, SDNN 방식)")

with open(input_path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"Updated questions with specific data sources in {input_path}")
