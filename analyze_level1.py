import pandas as pd

file_path = '/Users/goeastagent/products/MedicalAIMaster/Evaluation/Level1/output/level1_eval_20260323_145816.xlsx'
detail_df = pd.read_excel(file_path, sheet_name='Detail')
va_df = detail_df[detail_df['scenario'] == 'VitalAgent-Extraction']
print(va_df[va_df['case_id'] == 'L1-ADV-001'][['case_id', 'detected_behavior', 'error']].to_string())
