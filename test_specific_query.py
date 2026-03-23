import logging
from ExtractionAgent.src.facade import ExtractionFacade

logging.basicConfig(level=logging.DEBUG)

def main():
    facade = ExtractionFacade()
    q = "How did the numbers fluctuate in the middle part of the operation?"
    print(f"\n--- Testing Query: {q} ---")
    result = facade.extract_with_state(q)
    print(f"has_ambiguity: {result.has_ambiguity}")
    print(f"ambiguities: {result.ambiguities}")

if __name__ == "__main__":
    main()
