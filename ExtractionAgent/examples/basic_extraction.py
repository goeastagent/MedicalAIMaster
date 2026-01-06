#!/usr/bin/env python3
"""
VitalExtractionAgent - Basic Usage Example
===========================================

This example demonstrates how to use the VitalExtractionAgent
to extract medical vital sign data based on natural language queries.

Pipeline:
    [100] QueryUnderstandingNode → [200] ParameterResolverNode → [300] PlanBuilderNode

Usage:
    cd ExtractionAgent
    python examples/basic_extraction.py
    
    # Or with a custom query:
    python examples/basic_extraction.py "your query here"
"""

import sys
import json
from pathlib import Path

# Add project paths
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(Path(__file__).parent.parent))


def create_agent():
    """Create and return the VitalExtractionAgent workflow."""
    from src.agents.graph import build_agent
    return build_agent()


def extract_data(workflow, query: str, verbose: bool = True):
    """
    Execute the extraction pipeline with the given query.
    
    Args:
        workflow: Compiled LangGraph workflow
        query: Natural language query describing the data to extract
        verbose: Whether to print detailed output
    
    Returns:
        dict: The execution result containing the plan and validation
    """
    if verbose:
        print(f"\n{'='*60}")
        print(f"📝 Query: {query}")
        print(f"{'='*60}\n")
    
    # Prepare initial state
    initial_state = {
        "user_query": query,
        "logs": []
    }
    
    # Execute pipeline
    result = workflow.invoke(initial_state)
    
    if verbose:
        print_results(result)
    
    return result


def print_results(result: dict):
    """Print formatted results."""
    
    print("\n" + "="*60)
    print("📊 EXTRACTION RESULTS")
    print("="*60)
    
    # 1. Intent & Parameters
    print("\n🎯 Intent:", result.get("intent", "N/A"))
    
    print("\n📋 Requested Parameters:")
    for p in result.get("requested_parameters", []):
        print(f"   • {p.get('term', 'N/A')} → {p.get('normalized', 'N/A')}")
    
    print("\n✅ Resolved Parameters:")
    for r in result.get("resolved_parameters", []):
        keys = r.get('param_keys', [])
        mode = r.get('resolution_mode', 'N/A')
        conf = r.get('confidence', 0)
        print(f"   • {r.get('term', 'N/A')}")
        print(f"     Keys: {keys}")
        print(f"     Mode: {mode}, Confidence: {conf:.2f}")
    
    # 2. Filters
    print("\n🔍 Cohort Filters:")
    filters = result.get("cohort_filters", [])
    if filters:
        for f in filters:
            print(f"   • {f.get('column')} {f.get('operator')} {f.get('value')}")
    else:
        print("   (no filters)")
    
    # 3. Temporal Context
    temporal = result.get("temporal_context", {})
    print(f"\n⏱️ Temporal Context:")
    print(f"   Type: {temporal.get('type', 'N/A')}")
    print(f"   Margin: {temporal.get('margin_seconds', 0)} seconds")
    if temporal.get('start_column'):
        print(f"   Start: {temporal.get('start_column')}")
        print(f"   End: {temporal.get('end_column')}")
    
    # 4. Validation
    validation = result.get("validation", {})
    print(f"\n✓ Validation:")
    print(f"   Valid: {validation.get('is_valid', 'N/A')}")
    print(f"   Confidence: {validation.get('confidence', 0):.2f}")
    
    warnings = validation.get("warnings", [])
    if warnings:
        print(f"   Warnings ({len(warnings)}):")
        for w in warnings:
            print(f"      ⚠️ {w}")
    
    # 5. Ambiguities
    if result.get("has_ambiguity"):
        print(f"\n⚠️ Ambiguities (requires clarification):")
        for a in result.get("ambiguities", []):
            print(f"   • {a.get('term')}: {a.get('question')}")
    
    # 6. Execution Plan Summary
    plan = result.get("execution_plan", {})
    if plan:
        print(f"\n📋 Execution Plan Summary:")
        exec_plan = plan.get("execution_plan", {})
        
        # Cohort
        cohort = exec_plan.get("cohort_source", {})
        if cohort:
            print(f"   Cohort: {cohort.get('file_name', 'N/A')}")
            print(f"   Entity: {cohort.get('entity_identifier', 'N/A')}")
        
        # Signal
        signal = exec_plan.get("signal_source", {})
        if signal:
            print(f"   Signal Group: {signal.get('group_name', 'N/A')}")
            params = signal.get("parameters", [])
            print(f"   Parameters: {len(params)}")
        
        # Join
        join = exec_plan.get("join_specification", {})
        if join:
            print(f"   Join: {join.get('cohort_key')} ↔ {join.get('signal_key')}")


def save_plan(result: dict, output_path: str):
    """Save the execution plan to a JSON file."""
    plan = result.get("execution_plan", {})
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)
    
    print(f"\n💾 Plan saved to: {output_path}")


def interactive_mode(workflow):
    """Run in interactive mode, accepting queries from stdin."""
    print("\n" + "="*60)
    print("🔄 VitalExtractionAgent - Interactive Mode")
    print("="*60)
    print("Enter queries to extract data. Type 'quit' or 'exit' to stop.")
    print("Type 'save' after a query to save the plan to a file.\n")
    
    last_result = None
    
    while True:
        try:
            query = input("📝 Query: ").strip()
            
            if not query:
                continue
            
            if query.lower() in ('quit', 'exit', 'q'):
                print("👋 Goodbye!")
                break
            
            if query.lower() == 'save' and last_result:
                filename = input("   Filename (default: plan.json): ").strip() or "plan.json"
                save_plan(last_result, filename)
                continue
            
            last_result = extract_data(workflow, query)
            
        except KeyboardInterrupt:
            print("\n👋 Interrupted. Goodbye!")
            break
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()


def main():
    """Main entry point."""
    print("\n" + "="*60)
    print("🏥 VitalExtractionAgent")
    print("   Medical Data Extraction Pipeline")
    print("="*60)
    
    # Create agent
    print("\n🔧 Initializing agent...")
    workflow = create_agent()
    
    # Check for command line argument
    if len(sys.argv) > 1:
        if sys.argv[1] in ('-i', '--interactive'):
            interactive_mode(workflow)
        else:
            # Single query mode
            query = " ".join(sys.argv[1:])
            result = extract_data(workflow, query)
            
            # Optionally save
            if len(sys.argv) > 2 and sys.argv[-1].endswith('.json'):
                save_plan(result, sys.argv[-1])
    else:
        # Default example queries
        example_queries = [
            "위암 환자의 심박수 데이터를 추출해줘",
            # "Extract blood pressure during surgery for patients over 60",
            # "SpO2 and heart rate for gastric cancer patients",
        ]
        
        print("\n📚 Running example queries...\n")
        
        for query in example_queries:
            result = extract_data(workflow, query)
            print("\n" + "-"*60 + "\n")
        
        print("\n💡 Tip: Run with -i or --interactive for interactive mode")
        print("   Or provide a query: python examples/basic_extraction.py \"your query\"")


if __name__ == "__main__":
    main()

