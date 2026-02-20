import json

input_path = 'testdata/case3_low_dataset.json'

with open(input_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

for item in data:
    q_id = item['id']
    q = item['question']
    
    # ID 5: ABP Max -> SBP Max clarification
    if q_id == 5:
        item['question'] = "Case ID 1, 2, 9번 환자들의 ABP(동맥혈압) 중 수축기 혈압(SBP)의 최댓값을 각각 구해주세요. 순서대로 리스트로 알려주세요."

    # ID 15: SBP Mean - Stronger filtering instruction
    elif q_id == 15:
        item['question'] = "Case ID 1, 2, 9번 환자들의 동맥혈압(ART) 수축기 혈압(SBP) 평균값을 구해주세요. (반드시 0 이하 값은 노이즈로 간주하여 제외할 것) 순서대로 리스트로 알려주세요."

    # ID 19: DBP Stats - None return and filtering
    elif q_id == 19:
        item['question'] = "Case ID 1, 2, 9번 환자들의 동맥혈압(ART) 이완기 혈압(DBP)의 평균값, 최댓값, 최솟값, 중간값을 각각 구해주세요. (반드시 0 이하 값은 노이즈로 간주하여 제외할 것) 각 환자의 결과는 딕셔너리({'mean': ..., 'max': ..., 'min': ..., 'median': ...}) 형태로 반환하고, 유효한 데이터가 없으면 딕셔너리 대신 None을 반환하세요. 전체 결과는 순서대로 리스트로 알려주세요."

    # ID 20: EtCO2 Mean - Filtering
    elif q_id == 20:
        item['question'] = "Case ID 1, 2, 9번 환자의 Solar8000 장비의 호기말 이산화탄소(EtCO2)의 평균값은 순서대로 리스트로 알려주세요. (반드시 0 이하 값은 노이즈로 간주하여 제외할 것)"

    # ID 21: EtCO2 Stats - Filtering
    elif q_id == 21:
        item['question'] = "Case ID 1, 2, 9번 환자의 Solar8000 장비의 호기말 이산화탄소(EtCO2)의 최댓값, 최솟값, 중간값은 순서대로 리스트로 알려주세요. (반드시 0 이하 값은 노이즈로 간주하여 제외할 것) 각 환자의 결과는 딕셔너리({'max': ..., 'min': ..., 'median': ...}) 형태로 반환해주세요."

    # ID 22: HRV - SDNN specific instruction
    elif q_id == 22:
        item['question'] = "Case ID 1, 2, 9 환자의 HRV(심박변이도)를 구해주세요. 1초 간격의 심박수(HR) 데이터를 이용하여 RR 간격을 추정하고, 이를 통해 SDNN(Standard Deviation of NN intervals) 값을 계산하세요. (0 이하 및 NaN 제외) 순서대로 리스트로 알려주세요."

    # ID 23: DBP High Duration - Filtering
    elif q_id == 23:
        item['question'] = "Case ID 1, 2, 9번 환자의 90mmHg이상의 동맥혈압(ART) 이완기 혈압(DBP) 값이 몇 분간 지속되었는지 알려줘 (0 이하 값은 노이즈로 제외하고 계산) 순서대로 리스트로 알려주세요."

    # ID 24: DBP Low Duration - Filtering (Critical)
    elif q_id == 24:
        item['question'] = "Case ID 1, 2, 9이 50mmHg 이하의 동맥혈압(ART) 이완기 혈압(DBP) 값이 몇 분간 지속되었는지 알려줘 (반드시 0 이하 값은 노이즈로 간주하여 제외하고, 0초과 50이하인 경우만 계산) 순서대로 리스트로 알려주세요."

with open(input_path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"Updated questions with strict filtering rules in {input_path}")
