import json

input_path = 'testdata/case3_low_dataset.json'

with open(input_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

for item in data:
    item['format'] = 'list'

with open(input_path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"Updated {input_path} with format='list'")
