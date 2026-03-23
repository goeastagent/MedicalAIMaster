import json
from ExtractionAgent.src.facade import ExtractionFacade

facade = ExtractionFacade()

q = "Determine the fraction of inspired oxygen administered throughout the surgery."
print(f"\n\n=== Query: {q} ===")
res = facade.extract_with_state(q)
for p in res.resolved_parameters:
    print(f"  Param: {p.get('term')} -> mode: {p.get('resolution_mode')}, keys: {p.get('param_keys')}, conf: {p.get('confidence')}")
    print(f"  Reasoning: {p.get('reasoning')}")
