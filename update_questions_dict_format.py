import json

input_path = 'testdata/case3_low_dataset.json'

with open(input_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

for item in data:
    q_id = item['id']
    if q_id == 19:
        item['question'] = "Case ID 1, 2, 9번 환자들의 이완기 혈압(DBP)의 평균값, 최댓값, 최솟값, 중간값을 각각 구해주세요. (0 이하 노이즈 제외) 각 환자의 결과는 딕셔너리({'mean': ..., 'max': ..., 'min': ..., 'median': ...}) 형태로 반환하고, 전체 결과는 순서대로 리스트로 알려주세요."
    elif q_id == 21:
        item['question'] = "Case ID 1, 2, 9번 환자의 호기말 이산화탄소(EtCO2)의 최댓값, 최솟값, 중간값은 순서대로 리스트로 알려주세요. 각 환자의 결과는 딕셔너리({'max': ..., 'min': ..., 'median': ...}) 형태로 반환해주세요."

with open(input_path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"Updated questions 19 and 21 in {input_path}")
