import json
from ExtractionAgent.src.facade import ExtractionFacade

facade = ExtractionFacade()

q = "What are the intraoperative changes in cardiac electrical activity and heart rate?"
print(f"\n\n=== Query: {q} ===")
res = facade.extract_with_state(q)
for p in res.resolved_parameters:
    print(f"  Param: {p.get('term')} -> mode: {p.get('resolution_mode')}, keys: {p.get('param_keys')}, conf: {p.get('confidence')}")
    print(f"  Reasoning: {p.get('reasoning')}")
