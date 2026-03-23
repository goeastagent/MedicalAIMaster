import json
from ExtractionAgent.src.facade import ExtractionFacade

facade = ExtractionFacade()

queries = [
    "What is the intraoperative synovial fluid pressure?",
    "Please analyze the inspiratory CO2 data for trends.",
    "Can you provide the end-tidal CO2 levels during the last hour of surgery?",
    "I need the cerebral blood flow velocity metrics for patient Y.",
    "I'd like to see the real-time electrolyte balance levels for the patient.",
    "Can you provide the cardiac output using esophageal Doppler for this patient?",
    "Can you retrieve the real-time bladder pressure data during surgery?",
    "Can you show me the brain wave conduction during the surgery?",
    "What are the trends in inspiratory CO2 for patient 12?",
    "I want to see the breathing gas CO2 from the procedure."
]

for q in queries:
    print(f"\n\n=== Query: {q} ===")
    res = facade.extract_with_state(q)
    print(f"Success: {res.success}")
    print(f"Ambiguities: {res.ambiguities}")
    print(f"Error: {res.error_message}")
    print(f"Validation: {res.validation}")
    for p in res.resolved_parameters:
        print(f"  Param: {p.get('term')} -> mode: {p.get('resolution_mode')}, keys: {p.get('param_keys')}, conf: {p.get('confidence')}")
