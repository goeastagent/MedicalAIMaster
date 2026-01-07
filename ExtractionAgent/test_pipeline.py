#!/usr/bin/env python3
"""
VitalExtractionAgent - Full Pipeline Test (Debug Mode)
=======================================================

전체 파이프라인 테스트 스크립트 (디버깅 출력 포함)

Pipeline:
    [100] QueryUnderstandingNode
        ↓
    [200] ParameterResolverNode
        ↓
    [300] PlanBuilderNode

Usage:
    cd ExtractionAgent
    python test_pipeline.py              # 기본 실행
    python test_pipeline.py --verbose    # 상세 출력
    python test_pipeline.py --json       # JSON 전체 출력
"""

import sys
import json
import time
import argparse
from pathlib import Path

# 프로젝트 루트 경로 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(Path(__file__).parent))


# 테스트 쿼리 정의
TEST_QUERIES = [
    {
        "name": "한국어 복합 쿼리",
        "query": "위암 환자의 수술 중 심박수와 혈압 데이터를 추출해줘",
        "expected": {
            "intent": "data_retrieval",
            "min_parameters": 2,
            "temporal_type": "procedure_window"
        }
    },
    {
        "name": "영어 필터 쿼리",
        "query": "Extract SpO2 data for patients diagnosed with gastric cancer",
        "expected": {
            "intent": "data_retrieval",
            "min_parameters": 1,
            "temporal_type": "full_record"
        }
    },
    {
        "name": "시간 필터 쿼리",
        "query": "2020년 1월부터 2023년 12월까지 수술받은 환자들의 치료 중 체온과 심박수 데이터를 추출해줘",
        "expected": {
            "intent": "data_retrieval",
            "min_parameters": 2,  # 체온, 심박수
            "temporal_type": "treatment_window"
        }
    }
]


def print_header(text: str, char: str = "=", width: int = 80):
    """헤더 출력"""
    line = char * width
    print(f"\n{line}")
    print(f"  {text}")
    print(f"{line}\n")


def print_subheader(text: str, char: str = "-", width: int = 70):
    """서브 헤더 출력"""
    line = char * width
    print(f"\n{line}")
    print(f"  {text}")
    print(f"{line}")


def print_json_block(data: dict, title: str = None, indent: int = 2):
    """JSON 블록 출력"""
    if title:
        print(f"\n📦 {title}:")
    print(json.dumps(data, indent=indent, ensure_ascii=False, default=str))


def print_node_result_detail(result: dict, node_name: str):
    """개별 노드 결과 상세 출력"""
    
    if node_name == "query_understanding":
        print_subheader("🔍 [100] QueryUnderstandingNode 결과", "─")
        
        # Schema Context 요약
        schema_ctx = result.get("schema_context", {})
        print("\n📊 Schema Context:")
        print(f"   • Cohort Sources: {len(schema_ctx.get('cohort_sources', []))}")
        for cs in schema_ctx.get('cohort_sources', []):
            print(f"      - {cs.get('file_name')} (entity: {cs.get('entity_identifier')})")
        
        print(f"   • Signal Groups: {len(schema_ctx.get('signal_groups', []))}")
        for sg in schema_ctx.get('signal_groups', []):
            print(f"      - {sg.get('group_name')} (pattern: {sg.get('file_pattern')})")
        
        print(f"   • Parameter Categories: {len(schema_ctx.get('parameters', {}))}")
        for cat, params in schema_ctx.get('parameters', {}).items():
            print(f"      - {cat}: {len(params)} params")
        
        print(f"   • Relationships: {len(schema_ctx.get('relationships', []))}")
        for rel in schema_ctx.get('relationships', []):
            from_str = f"{rel.get('from_table')}.{rel.get('from_column')}"
            to_str = f"{rel.get('to_table')}.{rel.get('to_column')}"
            cardinality = rel.get('cardinality', 'N/A')
            print(f"      - {from_str} → {to_str} ({cardinality})")
        
        # Intent
        print(f"\n🎯 Intent: {result.get('intent', 'N/A')}")
        
        # Requested Parameters
        print("\n📋 Requested Parameters:")
        for i, param in enumerate(result.get('requested_parameters', []), 1):
            print(f"   [{i}] term: \"{param.get('term')}\"")
            print(f"       normalized: \"{param.get('normalized')}\"")
            print(f"       candidates: {param.get('candidates', [])}")
        
        # Cohort Filters
        print("\n🔍 Cohort Filters:")
        filters = result.get('cohort_filters', [])
        if filters:
            for f in filters:
                print(f"   • {f.get('column')} {f.get('operator')} \"{f.get('value')}\"")
        else:
            print("   (없음)")
        
        # Temporal Context
        temporal = result.get('temporal_context', {})
        print("\n⏰ Temporal Context:")
        print(f"   • type: {temporal.get('type', 'N/A')}")
        print(f"   • margin_seconds: {temporal.get('margin_seconds', 0)}")
        if temporal.get('start_column'):
            print(f"   • start_column: {temporal.get('start_column')}")
            print(f"   • end_column: {temporal.get('end_column')}")
        
        # Node result metadata
        node_result = result.get('query_understanding_result', {})
        if node_result:
            print("\n📝 Node Metadata:")
            print(f"   • status: {node_result.get('status')}")
            print(f"   • context_loaded: {node_result.get('context_loaded')}")
            if node_result.get('llm_reasoning'):
                reasoning = node_result.get('llm_reasoning', '')
                print(f"   • llm_reasoning:")
                # 긴 텍스트를 80자씩 줄바꿈해서 출력
                for i in range(0, len(reasoning), 80):
                    print(f"     {reasoning[i:i+80]}")
    
    elif node_name == "parameter_resolver":
        print_subheader("🔗 [200] ParameterResolverNode 결과", "─")
        
        # Resolved Parameters
        print("\n✅ Resolved Parameters:")
        for idx, param in enumerate(result.get('resolved_parameters', []), 1):
            print(f"\n   {'='*60}")
            print(f"   [{idx}] term: \"{param.get('term')}\"")
            print(f"   {'='*60}")
            
            # Search info
            search_candidates = param.get('search_candidates', [])
            print(f"\n       🔍 Search:")
            print(f"          candidates: {search_candidates}")
            
            # DB Matches (중요!)
            db_matches = param.get('db_matches', [])
            print(f"\n       📊 DB Matches ({len(db_matches)}):")
            if db_matches:
                for j, match in enumerate(db_matches, 1):
                    print(f"          [{j}] param_key: {match.get('param_key')}")
                    print(f"              semantic_name: {match.get('semantic_name')}")
                    print(f"              unit: {match.get('unit')}")
                    print(f"              concept_category: {match.get('concept_category')}")
            else:
                print("          (없음)")
            
            # Resolution Result
            print(f"\n       🎯 Resolution Result:")
            print(f"          resolution_mode: {param.get('resolution_mode')}")
            print(f"          confidence: {param.get('confidence', 0):.2f}")
            print(f"          semantic_name: {param.get('semantic_name')}")
            print(f"          unit: {param.get('unit')}")
            print(f"          concept_category: {param.get('concept_category')}")
            
            # Selected param_keys
            param_keys = param.get('param_keys', [])
            print(f"\n       ✅ Selected param_keys ({len(param_keys)}):")
            for key in param_keys:
                # 이 key가 db_matches의 어떤 항목과 매칭되는지 표시
                match_info = next((m for m in db_matches if m.get('param_key') == key), None)
                if match_info:
                    print(f"          • {key} → {match_info.get('semantic_name')} ({match_info.get('unit')})")
                else:
                    print(f"          • {key}")
            
            # Reasoning
            if param.get('reasoning'):
                reasoning = param.get('reasoning', '')
                print(f"\n       💭 LLM Reasoning:")
                for i in range(0, len(reasoning), 70):
                    print(f"          {reasoning[i:i+70]}")
        
        # Ambiguities
        ambiguities = result.get('ambiguities', [])
        print(f"\n❓ Ambiguities: {len(ambiguities)}")
        if ambiguities:
            for a in ambiguities:
                print(f"   • term: \"{a.get('term')}\"")
                print(f"     question: {a.get('question')}")
                print(f"     candidates: {a.get('candidates', [])}")
        
        print(f"\n⚠️ Has Ambiguity: {result.get('has_ambiguity', False)}")
        
        # Node result metadata
        node_result = result.get('parameter_resolver_result', {})
        if node_result:
            print("\n📝 Node Metadata:")
            print(f"   • status: {node_result.get('status')}")
            print(f"   • resolved_count: {node_result.get('resolved_count')}")
            print(f"   • ambiguity_count: {node_result.get('ambiguity_count')}")
    
    elif node_name == "plan_builder":
        print_subheader("📦 [300] PlanBuilderNode 결과", "─")
        
        # Execution Plan
        plan = result.get('execution_plan', {})
        exec_plan = plan.get('execution_plan', {})
        
        print(f"\n{'='*70}")
        print(f"   📋 EXECUTION PLAN OVERVIEW")
        print(f"{'='*70}")
        print(f"   Version: {plan.get('version', '?')}")
        print(f"   Generated at: {plan.get('generated_at')}")
        print(f"   Agent: {plan.get('agent')}")
        print(f"   Original Query: {plan.get('original_query', 'N/A')}")
        
        # Cohort Source 상세
        cohort = exec_plan.get('cohort_source', {})
        print(f"\n{'─'*70}")
        print(f"   🏥 COHORT SOURCE (환자/케이스 데이터)")
        print(f"{'─'*70}")
        if cohort:
            print(f"   file_id: {cohort.get('file_id')}")
            print(f"   file_name: {cohort.get('file_name')}")
            print(f"   entity_identifier: {cohort.get('entity_identifier')}")
            print(f"   row_represents: {cohort.get('row_represents')}")
            
            filters = cohort.get('filters', [])
            print(f"\n   Filters ({len(filters)}):")
            if filters:
                for idx, f in enumerate(filters, 1):
                    print(f"      [{idx}] {f.get('column')} {f.get('operator')} \"{f.get('value')}\"")
                    if f.get('validated'):
                        print(f"          validated: {f.get('validated')}")
            else:
                print(f"      (없음 - 전체 데이터 사용)")
        else:
            print(f"   ⚠️ Cohort source not configured")
        
        # Signal Source 상세
        signal = exec_plan.get('signal_source', {})
        print(f"\n{'─'*70}")
        print(f"   📈 SIGNAL SOURCE (시계열 신호 데이터)")
        print(f"{'─'*70}")
        if signal:
            print(f"   group_id: {signal.get('group_id')}")
            print(f"   group_name: {signal.get('group_name')}")
            print(f"   file_pattern: {signal.get('file_pattern')}")
            
            # Parameters 상세
            params = signal.get('parameters', [])
            print(f"\n   Parameters ({len(params)}):")
            for idx, p in enumerate(params, 1):
                print(f"\n      [{idx}] term: \"{p.get('term')}\"")
                print(f"          resolution_mode: {p.get('resolution_mode')}")
                print(f"          semantic_name: {p.get('semantic_name')}")
                print(f"          unit: {p.get('unit')}")
                print(f"          confidence: {p.get('confidence', 'N/A')}")
                
                param_keys = p.get('param_keys', [])
                print(f"          param_keys ({len(param_keys)}):")
                for key in param_keys:
                    print(f"             • {key}")
            
            # Temporal Alignment 상세
            temporal = signal.get('temporal_alignment', {})
            print(f"\n   Temporal Alignment:")
            print(f"      type: {temporal.get('type')}")
            print(f"      margin_seconds: {temporal.get('margin_seconds')}")
            if temporal.get('start_column'):
                print(f"      start_column: {temporal.get('start_column')}")
                print(f"      end_column: {temporal.get('end_column')}")
            
            # Temporal type 설명
            temporal_type = temporal.get('type', '')
            if temporal_type == 'full_record':
                print(f"      📝 (전체 기록 - 시간 필터 없음)")
            elif temporal_type == 'procedure_window':
                print(f"      📝 (시술/수술 시간 구간 내 데이터만)")
            elif temporal_type == 'treatment_window':
                print(f"      📝 (치료 시간 구간 내 데이터만)")
        else:
            print(f"   ⚠️ Signal source not configured")
        
        # Join Specification 상세
        join = exec_plan.get('join_specification', {})
        print(f"\n{'─'*70}")
        print(f"   🔗 JOIN SPECIFICATION (데이터 연결)")
        print(f"{'─'*70}")
        if join:
            print(f"   type: {join.get('type')}")
            print(f"   cohort_key: {join.get('cohort_key')}")
            print(f"   signal_key: {join.get('signal_key')}")
            print(f"   cardinality: {join.get('cardinality')}")
            
            # Join 설명
            cohort_key = join.get('cohort_key', '')
            signal_key = join.get('signal_key', '')
            cardinality = join.get('cardinality', '')
            print(f"\n   📝 JOIN 설명:")
            print(f"      {cohort.get('file_name', 'cohort')}.{cohort_key}")
            print(f"         ↓ {join.get('type', 'inner')} join ({cardinality})")
            print(f"      {signal.get('group_name', 'signal')}.{signal_key}")
        else:
            print(f"   ⚠️ Join specification not configured")
        
        # Validation 상세
        validation = result.get('validation', {})
        print(f"\n{'─'*70}")
        print(f"   ✓ VALIDATION (검증 결과)")
        print(f"{'─'*70}")
        is_valid = validation.get('is_valid', False)
        confidence = validation.get('confidence', 0)
        
        status_icon = "✅" if is_valid else "❌"
        conf_bar = "█" * int(confidence * 10) + "░" * (10 - int(confidence * 10))
        
        print(f"   is_valid: {status_icon} {is_valid}")
        print(f"   confidence: [{conf_bar}] {confidence:.2f}")
        print(f"   validated_at: {validation.get('validated_at')}")
        
        warnings = validation.get('warnings', [])
        if warnings:
            print(f"\n   Warnings ({len(warnings)}):")
            for w in warnings:
                print(f"      ⚠️ {w}")
        else:
            print(f"\n   Warnings: (없음)")
        
        # Full JSON 출력
        print(f"\n{'─'*70}")
        print(f"   📄 FULL EXECUTION PLAN JSON")
        print(f"{'─'*70}")
        print(json.dumps(plan, indent=2, ensure_ascii=False, default=str))
        
        # Node result metadata
        node_result = result.get('plan_builder_result', {})
        if node_result:
            print("\n📝 Node Metadata:")
            print(f"   • status: {node_result.get('status')}")
            print(f"   • confidence: {node_result.get('confidence')}")
            print(f"   • warning_count: {node_result.get('warning_count')}")


def print_logs(result: dict):
    """로그 출력"""
    logs = result.get('logs', [])
    if logs:
        print_subheader(f"📝 Pipeline Logs ({len(logs)} entries)", "─")
        for log in logs:
            print(f"   {log}")


def run_test(workflow, query_info: dict, verbose: bool = False, show_json: bool = False) -> tuple:
    """단일 테스트 실행"""
    query = query_info["query"]
    expected = query_info["expected"]
    
    print(f"\n📝 Query: {query}")
    print(f"⏳ Running pipeline...\n")
    
    start_time = time.time()
    
    try:
        # 초기 상태
        initial_state = {
            "user_query": query,
            "logs": []
        }
        
        # 파이프라인 실행
        result = workflow.invoke(initial_state)
        
        elapsed = time.time() - start_time
        print(f"\n✅ Completed in {elapsed:.2f}s")
        
        # 상세 출력 모드
        if verbose:
            print_node_result_detail(result, "query_understanding")
            print_node_result_detail(result, "parameter_resolver")
            print_node_result_detail(result, "plan_builder")
            # print_logs(result)  # 중복 출력 방지 - 노드에서 이미 실시간 로그 출력됨
        
        # JSON 전체 출력 모드
        if show_json:
            print_subheader("📄 Full Result JSON", "─")
            # 민감 정보 제외한 복사본
            result_copy = {k: v for k, v in result.items() if k != 'schema_context'}
            print(json.dumps(result_copy, indent=2, ensure_ascii=False, default=str))
        
        # 검증
        checks = validate_result(result, expected)
        
        # 검증 결과 출력
        print_subheader("✓ Validation Checks", "─")
        print(f"   Intent Match: {'✅' if checks['intent_match'] else '❌'} (expected: {expected.get('intent')}, got: {result.get('intent')})")
        print(f"   Min Params Met: {'✅' if checks['min_params_met'] else '❌'} (expected: >={expected.get('min_parameters')}, got: {len(result.get('resolved_parameters', []))})")
        print(f"   Temporal Match: {'✅' if checks['temporal_match'] else '❌'} (expected: {expected.get('temporal_type')}, got: {result.get('temporal_context', {}).get('type')})")
        print(f"   Plan Valid: {'✅' if checks['is_valid'] else '❌'} (confidence: {result.get('validation', {}).get('confidence', 0):.2f})")
        
        return True, result, checks, elapsed
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"❌ Failed after {elapsed:.2f}s: {e}")
        import traceback
        traceback.print_exc()
        return False, None, {}, elapsed


def validate_result(result: dict, expected: dict) -> dict:
    """결과 검증"""
    checks = {
        "intent_match": False,
        "min_params_met": False,
        "temporal_match": False,
        "is_valid": False
    }
    
    checks["intent_match"] = result.get("intent") == expected.get("intent")
    
    resolved = result.get("resolved_parameters", [])
    checks["min_params_met"] = len(resolved) >= expected.get("min_parameters", 1)
    
    temporal = result.get("temporal_context", {})
    checks["temporal_match"] = temporal.get("type") == expected.get("temporal_type")
    
    validation = result.get("validation", {})
    checks["is_valid"] = validation.get("is_valid", False)
    
    return checks


def main():
    """메인 실행"""
    # 인자 파싱
    parser = argparse.ArgumentParser(description='VitalExtractionAgent Pipeline Test')
    parser.add_argument('--verbose', '-v', action='store_true', help='상세 출력 모드')
    parser.add_argument('--json', '-j', action='store_true', help='JSON 전체 출력')
    parser.add_argument('--query', '-q', type=int, help='특정 쿼리만 테스트 (1 or 2)')
    args = parser.parse_args()
    
    # 기본값: verbose 모드
    verbose = args.verbose if args.verbose else True  # 기본으로 상세 출력
    show_json = args.json
    
    print_header("VitalExtractionAgent - Full Pipeline Test (Debug Mode)", "=", 80)
    
    if verbose:
        print("🔧 Mode: VERBOSE (상세 출력)")
    if show_json:
        print("🔧 Mode: JSON (전체 JSON 출력)")
    
    # 파이프라인 빌드
    print("\n🔧 Building pipeline...")
    
    try:
        from src.agents.graph import build_agent
        workflow = build_agent()
    except Exception as e:
        print(f"❌ Failed to build pipeline: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # 테스트할 쿼리 선택
    queries_to_test = TEST_QUERIES
    if args.query:
        if 1 <= args.query <= len(TEST_QUERIES):
            queries_to_test = [TEST_QUERIES[args.query - 1]]
        else:
            print(f"❌ Invalid query number: {args.query}")
            return False
    
    # 테스트 실행
    results = []
    total_time = 0
    
    for i, query_info in enumerate(queries_to_test, 1):
        print_header(f"Test {i}/{len(queries_to_test)}: {query_info['name']}", "═", 80)
        
        success, result, checks, elapsed = run_test(
            workflow, 
            query_info, 
            verbose=verbose, 
            show_json=show_json
        )
        total_time += elapsed
        
        results.append({
            "name": query_info["name"],
            "success": success,
            "checks": checks,
            "elapsed": elapsed,
            "result": result
        })
    
    # 최종 요약
    print_header("TEST SUMMARY", "═", 80)
    
    passed = 0
    for r in results:
        name = r["name"]
        success = r["success"]
        checks = r["checks"]
        elapsed = r["elapsed"]
        
        if success:
            all_passed = all(checks.values())
            status = "✅ PASS" if all_passed else "⚠️ PARTIAL"
            if all_passed:
                passed += 1
        else:
            status = "❌ FAIL"
        
        print(f"  {status} | {name} | {elapsed:.2f}s")
        if success:
            for check_name, check_value in checks.items():
                icon = "✓" if check_value else "✗"
                print(f"         | {icon} {check_name}")
        print()
    
    # 최종 결과
    print("─" * 80)
    print(f"  Total: {passed}/{len(results)} tests passed")
    print(f"  Total time: {total_time:.2f}s")
    if len(results) > 0:
        print(f"  Avg time per query: {total_time/len(results):.2f}s")
    print("─" * 80)
    
    if passed == len(results):
        print("\n🎉 All tests passed! VitalExtractionAgent is ready.")
    else:
        print("\n⚠️ Some tests need attention. Review results above.")
    
    return passed == len(results)


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
