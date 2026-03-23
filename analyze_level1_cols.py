import pandas as pd
file_path = '/Users/goeastagent/products/MedicalAIMaster/Evaluation/Level1/output/level1_eval_20260323_145816.xlsx'
detail_df = pd.read_excel(file_path, sheet_name='Detail')
print(detail_df.columns.tolist())
