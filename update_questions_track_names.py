import json

input_path = 'testdata/case3_low_dataset.json'

with open(input_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

for item in data:
    q_id = item['id']
    q = item['question']
    
    # Q4: ABP Mean -> ART_MBP
    if q_id == 4:
        item['question'] = "Case ID 1, 2, 9번 환자들의 'Solar8000/ART_MBP' 트랙의 평균값을 각각 구해주세요. 순서대로 리스트로 알려주세요."

    # Q5: ABP Max -> ART_SBP (Explicitly forbid NIBP)
    elif q_id == 5:
        item['question'] = "Case ID 1, 2, 9번 환자들의 'Solar8000/ART_SBP' 트랙의 최댓값을 각각 구해주세요. (주의: 해당 트랙이 없으면 NIBP 등 다른 데이터를 찾지 말고 바로 None을 반환하세요.) 순서대로 리스트로 알려주세요."

    # Q6: ABP Min -> ART_DBP
    elif q_id == 6:
        item['question'] = "Case ID 1, 2, 9번 환자들의 'Solar8000/ART_DBP' 트랙의 최솟값(0이하 노이즈 제거)을 각각 구해주세요. 순서대로 리스트로 알려주세요."

    # Q7: ABP Median -> ART_MBP
    elif q_id == 7:
        item['question'] = "Case ID 1, 2, 9번 환자들의 'Solar8000/ART_MBP' 트랙의 중간값을 각각 구해주세요. 순서대로 리스트로 알려주세요."

    # Q15: SBP Mean -> ART_SBP
    elif q_id == 15:
        item['question'] = "Case ID 1, 2, 9번 환자들의 'Solar8000/ART_SBP' 트랙의 평균값을 구해주세요. (반드시 0 이하 값은 노이즈로 간주하여 제외할 것) 순서대로 리스트로 알려주세요."

    # Q16: SBP Max -> ART_SBP
    elif q_id == 16:
        item['question'] = "Case ID 1, 2, 9번 환자들의 'Solar8000/ART_SBP' 트랙의 최댓값을 각각 구해주세요. 순서대로 리스트로 알려주세요."

    # Q17: SBP Min -> ART_SBP
    elif q_id == 17:
        item['question'] = "Case ID 1, 2, 9번 환자들의 'Solar8000/ART_SBP' 트랙의 최솟값을 각각 구해주세요. (반드시 0 이하 값은 노이즈로 간주하여 제외할 것) 순서대로 리스트로 알려주세요."

    # Q18: SBP Median -> ART_SBP
    elif q_id == 18:
        item['question'] = "Case ID 1, 2, 9번 환자들의 'Solar8000/ART_SBP' 트랙의 중간값을 각각 구해주세요. (반드시 0 이하 값은 노이즈로 간주하여 제외할 것) 순서대로 리스트로 알려주세요."

    # Q19: DBP Stats -> ART_DBP
    elif q_id == 19:
        item['question'] = "Case ID 1, 2, 9번 환자들의 'Solar8000/ART_DBP' 트랙의 평균값, 최댓값, 최솟값, 중간값을 각각 구해주세요. (반드시 0 이하 값은 노이즈로 간주하여 제외할 것) 각 환자의 결과는 딕셔너리({'mean': ..., 'max': ..., 'min': ..., 'median': ...}) 형태로 반환하고, 해당 트랙 데이터가 없으면 딕셔너리 대신 None을 반환하세요. 전체 결과는 순서대로 리스트로 알려주세요."

    # Q20: EtCO2 Mean -> Solar8000/ETCO2
    elif q_id == 20:
        item['question'] = "Case ID 1, 2, 9번 환자의 'Solar8000/ETCO2' 트랙의 평균값은 순서대로 리스트로 알려주세요. (반드시 0 이하 값은 노이즈로 간주하여 제외할 것)"

    # Q21: EtCO2 Stats -> Solar8000/ETCO2
    elif q_id == 21:
        item['question'] = "Case ID 1, 2, 9번 환자의 'Solar8000/ETCO2' 트랙의 최댓값, 최솟값, 중간값은 순서대로 리스트로 알려주세요. (반드시 0 이하 값은 노이즈로 간주하여 제외할 것) 각 환자의 결과는 딕셔너리({'max': ..., 'min': ..., 'median': ...}) 형태로 반환해주세요."

    # Q23: DBP High Duration -> ART_DBP
    elif q_id == 23:
        item['question'] = "Case ID 1, 2, 9번 환자의 'Solar8000/ART_DBP' 트랙 값이 90mmHg 이상인 구간이 몇 분간 지속되었는지 알려줘 (주의: 해당 트랙이 없으면 0분이 아니라 None을 반환하세요. 0 이하 값은 노이즈로 제외하고 계산) 순서대로 리스트로 알려주세요."

    # Q24: DBP Low Duration -> ART_DBP
    elif q_id == 24:
        item['question'] = "Case ID 1, 2, 9번 환자의 'Solar8000/ART_DBP' 트랙 값이 50mmHg 이하인 구간이 몇 분간 지속되었는지 알려줘 (주의: 해당 트랙이 없으면 0분이 아니라 None을 반환하세요. 반드시 0 이하 값은 노이즈로 간주하여 제외하고, 0초과 50이하인 경우만 계산) 순서대로 리스트로 알려주세요."

with open(input_path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"Updated questions with explicit track names in {input_path}")
