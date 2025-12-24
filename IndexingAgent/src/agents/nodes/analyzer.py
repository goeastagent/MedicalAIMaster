# src/agents/nodes/analyzer.py
"""
Analyzer Node - 시맨틱 분석 및 온톨로지 빌드
"""

import os
from datetime import datetime
from typing import Dict, Any

from src.agents.state import AgentState
from src.agents.nodes.common import (
    llm_client, llm_cache, ontology_manager,
    create_empty_conversation_history, format_history_for_prompt
)
from src.agents.helpers.llm_helpers import (
    analyze_columns_with_llm,
    analyze_intra_table_hierarchy,
    compare_with_global_context,
    should_request_human_review,
    ask_llm_is_metadata,
)
from src.agents.helpers.feedback_parser import (
    parse_human_feedback_to_column,
    generate_natural_human_question,
)
from src.agents.helpers.metadata_helpers import (
    build_metadata_detection_context,
    parse_metadata_content,
    infer_relationships_with_llm,
)
from src.config import HumanReviewConfig


def analyze_semantics_node(state: AgentState) -> Dict[str, Any]:
    """
    [Node 2] Semantic Analysis (Semantic Reasoning)
    Core brain that finalizes schema based on Processor results
    """
    print("\n" + "="*80)
    print("🧠 [ANALYZER NODE] Starting - Semantic Analysis")
    print("="*80)
    
    metadata = state["raw_metadata"]
    local_anchor_info = metadata.get("anchor_info", {})
    human_feedback = state.get("human_feedback")
    
    # Get Global Context
    project_context = state.get("project_context", {
        "master_anchor_name": None, 
        "known_aliases": [], 
        "example_id_values": []
    })
    
    # 대화 히스토리
    dataset_id = state.get("current_dataset_id", "unknown")
    conversation_history = state.get("conversation_history")
    if not conversation_history:
        conversation_history = create_empty_conversation_history(dataset_id)
    
    history_context = format_history_for_prompt(conversation_history, max_turns=5)
    if history_context:
        print(f"   📚 대화 히스토리 컨텍스트 로드됨 ({len(conversation_history.get('turns', []))}개 턴)")
    
    finalized_anchor = state.get("finalized_anchor")
    retry_count = state.get("retry_count", 0)
    
    # Prevent infinite loop
    if retry_count >= HumanReviewConfig.MAX_RETRY_COUNT:
        log_msg = f"⚠️ [Analyzer] Retry count exceeded ({retry_count}). Forcing local Anchor."
        
        finalized_anchor = {
            "status": "CONFIRMED",
            "column_name": local_anchor_info.get("target_column", "unknown"),
            "is_time_series": local_anchor_info.get("is_time_series", False),
            "reasoning": f"Forced confirmation after {retry_count} retries",
            "mapped_to_master": project_context.get("master_anchor_name")
        }
        
        return {
            "finalized_anchor": finalized_anchor,
            "finalized_schema": [],
            "project_context": project_context,
            "needs_human_review": False,
            "human_feedback": None,
            "retry_count": retry_count,
            "logs": [log_msg, "⚠️ [Analyzer] Schema analysis skipped (retry exceeded)"]
        }

    # --- Process user feedback ---
    if human_feedback:
        log_msg = f"🗣️ [Feedback] User feedback received: '{human_feedback}'"
        
        file_path = state.get("file_path", "")
        if file_path:
            filename = os.path.basename(file_path)
            llm_cache.invalidate_for_file(filename)
        
        parsed_column = parse_human_feedback_to_column(
            feedback=human_feedback,
            available_columns=metadata.get("columns", []),
            master_anchor=project_context.get("master_anchor_name"),
            file_path=state.get("file_path", "")
        )
        
        if parsed_column.get("action") == "skip":
            return {
                "finalized_anchor": None,
                "finalized_schema": [],
                "project_context": project_context,
                "needs_human_review": False,
                "human_feedback": None,
                "skip_indexing": True,
                "logs": [log_msg, "⏭️ [Analyzer] File skipped by user request"]
            }
        
        if parsed_column.get("action") == "use_filename_as_id":
            caseid_value = parsed_column.get("caseid_value")
            reasoning = parsed_column.get("reasoning", "Using filename as identifier")
            
            print(f"   → Using filename as ID: caseid={caseid_value}")
            
            if "anchor_info" not in metadata:
                metadata["anchor_info"] = {}
            
            metadata["anchor_info"]["status"] = "FOUND"
            metadata["anchor_info"]["target_column"] = "caseid"
            metadata["anchor_info"]["caseid_value"] = caseid_value
            metadata["anchor_info"]["is_time_series"] = True
            metadata["anchor_info"]["needs_human_confirmation"] = False
            
            finalized_anchor = {
                "status": "CONFIRMED",
                "column_name": "caseid",
                "caseid_value": caseid_value,
                "is_time_series": metadata.get("is_time_series", True),
                "reasoning": reasoning,
                "mapped_to_master": project_context.get("master_anchor_name")
            }
        
        determined_column = parsed_column.get("column_name", human_feedback.strip())
        reasoning = parsed_column.get("reasoning", "User manually confirmed.")
        
        print(f"   → Parsing result: '{determined_column}'")
        
        finalized_anchor = {
            "status": "CONFIRMED",
            "column_name": determined_column,
            "is_time_series": local_anchor_info.get("is_time_series", False),
            "reasoning": reasoning,
            "mapped_to_master": project_context.get("master_anchor_name") 
        }
        
        if "anchor_info" in metadata:
            metadata["anchor_info"]["needs_human_confirmation"] = False
            metadata["anchor_info"]["status"] = "CONFIRMED"
    
    # --- When Anchor is not yet finalized -> Check Global Context ---
    if not finalized_anchor:
        file_type = state.get("file_type", "tabular")
        
        # Signal 파일 특별 처리
        if file_type == "signal" and local_anchor_info.get("id_value"):
            id_column = local_anchor_info.get("target_column", "file_id")
            id_value = local_anchor_info.get("id_value")
            confidence = local_anchor_info.get("confidence", 0.5)
            needs_confirmation = local_anchor_info.get("needs_human_confirmation", False)
            
            print(f"\n📡 [Signal File] LLM-inferred ID: {id_column}={id_value} (confidence: {confidence:.0%})")
            
            if needs_confirmation and confidence < HumanReviewConfig.SIGNAL_FILE_CONFIDENCE_THRESHOLD:
                question = generate_natural_human_question(
                    file_path=state.get("file_path", ""),
                    context={
                        "reasoning": local_anchor_info.get("reasoning", ""),
                        "candidates": f"{id_column}={id_value}",
                        "columns": [],
                        "message": f"LLM inferred ID with {confidence:.0%} confidence."
                    },
                    issue_type="anchor_uncertain",
                    conversation_history=conversation_history
                )
                
                return {
                    "needs_human_review": True,
                    "review_type": "anchor",
                    "human_question": question,
                    "conversation_history": conversation_history,
                    "logs": [f"⚠️ [Analyzer] Signal file ID uncertain ({confidence:.0%})."]
                }
            
            finalized_anchor = {
                "status": "CONFIRMED",
                "column_name": id_column,
                "id_value": id_value,
                "is_time_series": True,
                "reasoning": local_anchor_info.get("reasoning", "LLM inferred ID"),
                "confidence": confidence,
                "mapped_to_master": project_context.get("master_anchor_name")
            }
        
        # Case 1: Project already has agreed Anchor (Leader)
        elif project_context.get("master_anchor_name"):
            master_name = project_context["master_anchor_name"]
            
            # ontology_context 전달하여 FK 추론 활성화
            ontology_context = state.get("ontology_context")
            
            comparison = compare_with_global_context(
                local_metadata=metadata,
                local_anchor_info=local_anchor_info,
                project_context=project_context,
                ontology_context=ontology_context
            )
            
            comparison_status = comparison.get("status", "UNKNOWN")
            print(f"\n[DEBUG] Global Anchor comparison result: {comparison_status}")
            
            if comparison["status"] == "MATCH":
                target_col = comparison["target_column"]
                finalized_anchor = {
                    "status": "CONFIRMED",
                    "column_name": target_col,
                    "is_time_series": local_anchor_info.get("is_time_series", False),
                    "reasoning": f"Matched with global master anchor '{master_name}'",
                    "mapped_to_master": master_name
                }
            
            elif comparison["status"] == "INDIRECT_LINK":
                via_col = comparison["target_column"]
                via_table = comparison.get("via_table", "unknown")
                
                finalized_anchor = {
                    "status": "INDIRECT_LINK",
                    "column_name": via_col,
                    "is_time_series": local_anchor_info.get("is_time_series", False),
                    "reasoning": comparison.get("message"),
                    "mapped_to_master": master_name,
                    "via_table": via_table,
                    "link_type": "indirect"
                }
                
                print(f"\n✅ [INDIRECT_LINK] Auto-confirmed indirect link!")
            
            elif comparison["status"] == "FK_LINK":
                # NEW: FK 관계를 통한 자동 연결
                fk_col = comparison["target_column"]
                via_table = comparison.get("via_table", "unknown")
                via_column = comparison.get("via_column", fk_col)
                fk_path = comparison.get("fk_path", [])
                confidence = comparison.get("confidence", 0.7)
                
                finalized_anchor = {
                    "status": "FK_LINK",
                    "column_name": fk_col,
                    "is_time_series": local_anchor_info.get("is_time_series", False),
                    "reasoning": comparison.get("message"),
                    "mapped_to_master": master_name,
                    "via_table": via_table,
                    "via_column": via_column,
                    "fk_path": fk_path,
                    "link_type": "fk",
                    "confidence": confidence
                }
                
                print(f"\n✅ [FK_LINK] Auto-confirmed FK relationship!")
                print(f"   - FK Path: {' → '.join(fk_path)}")
                print(f"   - Confidence: {confidence:.0%}")
                
                # FK 관계를 온톨로지에 저장
                if ontology_context is not None:
                    current_table = os.path.basename(state.get("file_path", "")).replace(".csv", "").replace(".CSV", "")
                    new_relationship = {
                        "source_table": current_table,
                        "target_table": via_table,
                        "source_column": fk_col,
                        "target_column": via_column,
                        "relation_type": comparison.get("relation_type", "N:1"),
                        "confidence": confidence,
                        "llm_inferred": True,
                        "description": f"FK inferred: {current_table}.{fk_col} → {via_table}.{via_column}"
                    }
                    
                    if "relationships" not in ontology_context:
                        ontology_context["relationships"] = []
                    
                    # 중복 체크
                    existing_keys = {
                        (r.get("source_table"), r.get("target_table"), 
                         r.get("source_column"), r.get("target_column"))
                        for r in ontology_context.get("relationships", [])
                    }
                    new_key = (current_table, via_table, fk_col, via_column)
                    
                    if new_key not in existing_keys:
                        ontology_context["relationships"].append(new_relationship)
                        print(f"   - FK relationship saved to ontology")
            
            else:
                msg = comparison.get("message", "Anchor mismatch occurred")
                
                natural_question = generate_natural_human_question(
                    file_path=state.get("file_path", ""),
                    context={
                        "master_anchor": master_name,
                        "candidates": local_anchor_info.get("target_column"),
                        "reasoning": msg,
                        "columns": metadata.get("columns", [])
                    },
                    issue_type="anchor_conflict",
                    conversation_history=conversation_history
                )
                
                return {
                    "needs_human_review": True,
                    "review_type": "anchor",
                    "human_question": natural_question,
                    "conversation_history": conversation_history,
                    "retry_count": retry_count,
                    "logs": [f"⚠️ [Analyzer] Global Anchor mismatch ({comparison_status})."]
                }

        # Case 2: This is the first file (no Global Context)
        else:
            processor_confidence = local_anchor_info.get(
                "confidence", 
                0.5 if local_anchor_info.get("needs_human_confirmation") else 0.9
            )
            
            review_decision = should_request_human_review(
                file_path=state.get("file_path", ""),
                issue_type="anchor_detection",
                context={
                    "processor_msg": local_anchor_info.get("msg"),
                    "candidates": local_anchor_info.get("target_column"),
                    "columns": metadata.get("columns", []),
                    "processor_needs_confirmation": local_anchor_info.get("needs_human_confirmation", False)
                },
                rule_based_confidence=processor_confidence
            )
            
            if review_decision["needs_review"]:
                question = generate_natural_human_question(
                    file_path=state.get("file_path", ""),
                    context={
                        "reasoning": local_anchor_info.get("msg"),
                        "candidates": local_anchor_info.get("target_column", "None"),
                        "columns": metadata.get("columns", [])
                    },
                    issue_type="anchor_uncertain",
                    conversation_history=conversation_history
                )
                
                return {
                    "needs_human_review": True,
                    "review_type": "anchor",
                    "human_question": question,
                    "conversation_history": conversation_history,
                    "logs": [f"⚠️ [Analyzer] Anchor uncertain (first file). {review_decision['reason']}"]
                }
            
            finalized_anchor = {
                "status": "CONFIRMED",
                "column_name": local_anchor_info.get("target_column"),
                "is_time_series": local_anchor_info.get("is_time_series"),
                "reasoning": local_anchor_info.get("reasoning"),
                "mapped_to_master": None
            }

    # --- Update Global Context ---
    if finalized_anchor and not project_context.get("master_anchor_name"):
        project_context["master_anchor_name"] = finalized_anchor["column_name"]
        project_context["known_aliases"].append(finalized_anchor["column_name"])
        print(f"👑 [Project Context] New Master Anchor set: '{finalized_anchor['column_name']}'")

    # --- [NEW] user_feedback을 LLM에 전달하여 분석 품질 향상 ---
    human_feedback = state.get("human_feedback")
    dataset_id = state.get("current_dataset_id", "unknown")
    
    if human_feedback:
        print(f"   📝 [User Feedback] Passing to LLM: '{human_feedback[:50]}...'")
    
    # --- Detailed schema analysis (with user_feedback) ---
    schema_analysis = analyze_columns_with_llm(
        columns=metadata.get("columns", []),
        sample_data=metadata.get("column_details", {}),
        anchor_context=finalized_anchor,
        user_feedback=human_feedback  # NEW: LLM에 user_feedback 전달
    )
    
    # --- [NEW] Build analysis_context for traceability ---
    enrichments = []
    
    for schema_item in schema_analysis:
        col_name = schema_item.get("original_name")
        if col_name:
            # analysis_context 생성: 분석 근거 (user_feedback 포함)
            # NOTE: user_feedback 원본은 별도 저장하지 않음 (중복 방지)
            context_parts = []
            if human_feedback:
                context_parts.append(f"user_feedback: '{human_feedback}'")
            if schema_item.get("full_name"):
                context_parts.append(f"full_name: '{schema_item.get('full_name')}'")
            if schema_item.get("semantic_type"):
                context_parts.append(f"semantic_type: '{schema_item.get('semantic_type')}'")
            
            analysis_context = "; ".join(context_parts) if context_parts else None
            
            # PostgreSQL에 analysis_context만 저장 (user_feedback 중복 제거)
            schema_item["analysis_context"] = analysis_context
            
            # enriched_definition: LLM이 분석한 풍부한 설명
            enriched_def = schema_item.get("description_kr") or schema_item.get("description", "")
            
            # Neo4j enrichment 준비
            enrichments.append({
                "name": col_name,
                "enriched_definition": enriched_def,
                "analysis_context": analysis_context
            })
    
    if human_feedback:
        print(f"   ✅ [User Feedback] Applied to LLM analysis & stored in analysis_context")
    
    # 배치로 Neo4j Concept 업데이트
    if enrichments:
        from src.utils.ontology_manager import get_ontology_manager
        ontology_mgr = get_ontology_manager()
        ontology_mgr.enrich_concepts_batch(enrichments, dataset_id=dataset_id)

    # --- Intra-table Hierarchy Analysis ---
    file_path = state.get("file_path", "")
    table_name = os.path.basename(file_path).replace(".csv", "").replace(".CSV", "")
    
    # human_feedback는 위에서 이미 가져옴 (line 383)
    
    print(f"\n🔗 [Hierarchy] Analyzing intra-table hierarchy for {table_name}...")
    hierarchy_info = analyze_intra_table_hierarchy(
        columns=metadata.get("columns", []),
        sample_data=metadata.get("column_details", {}),
        table_name=table_name,
        user_feedback=human_feedback  # NEW: 사용자 피드백 전달
    )
    
    # hierarchy가 발견되면 저장
    intra_table_hierarchy = None
    if hierarchy_info:
        intra_table_hierarchy = hierarchy_info
        
        # 1. PostgreSQL column_metadata에 parent_column/cardinality 추가
        # (schema_analysis의 child_column에 정보 추가)
        child_col = hierarchy_info.get("child_column")
        parent_col = hierarchy_info.get("parent_column")
        cardinality = hierarchy_info.get("cardinality", "N:1")
        
        for schema_item in schema_analysis:
            if schema_item.get("original_name") == child_col:
                schema_item["parent_column"] = parent_col
                schema_item["cardinality"] = cardinality
                schema_item["hierarchy_type"] = hierarchy_info.get("hierarchy_type", "unknown")
                print(f"   ✅ [PostgreSQL] {child_col} metadata updated with parent_column={parent_col}")
                break
        
        # 2. Neo4j에 CHILD_OF 관계 저장 (ontology_context에 추가)
        ontology_context = state.get("ontology_context")
        if ontology_context is not None:
            if "column_hierarchy" not in ontology_context:
                ontology_context["column_hierarchy"] = []
            
            new_hierarchy = {
                "table_name": table_name,
                "child_column": child_col,
                "parent_column": parent_col,
                "cardinality": cardinality,
                "hierarchy_type": hierarchy_info.get("hierarchy_type", "unknown"),
                "reasoning": hierarchy_info.get("reasoning", ""),
                "dataset_id": state.get("current_dataset_id", "unknown")
            }
            
            # 중복 체크
            existing_keys = {
                (h.get("table_name"), h.get("child_column"), h.get("parent_column"))
                for h in ontology_context.get("column_hierarchy", [])
            }
            new_key = (table_name, child_col, parent_col)
            
            if new_key not in existing_keys:
                ontology_context["column_hierarchy"].append(new_hierarchy)
                print(f"   ✅ [Neo4j] CHILD_OF relationship added: {child_col} → {parent_col}")

    print(f"\n✅ [ANALYZER NODE] Complete")
    print(f"   - Anchor: {finalized_anchor.get('column_name', 'N/A')}")
    print(f"   - Anchor Status: {finalized_anchor.get('status', 'N/A')}")
    if finalized_anchor.get('status') == 'FK_LINK':
        print(f"   - FK Path: {finalized_anchor.get('fk_path', [])}")
    print(f"   - Schema Columns: {len(schema_analysis)}")
    if intra_table_hierarchy:
        print(f"   - Hierarchy: {intra_table_hierarchy['child_column']} → {intra_table_hierarchy['parent_column']} ({intra_table_hierarchy['cardinality']})")
    print("="*80)

    # ontology_context가 수정되었을 수 있으므로 함께 반환
    result = {
        "finalized_anchor": finalized_anchor,
        "finalized_schema": schema_analysis,
        "project_context": project_context,
        "raw_metadata": metadata,
        "needs_human_review": False,
        "human_feedback": None, 
        "logs": ["🧠 [Analyzer] Complete schema and ontology analysis."]
    }
    
    # FK_LINK의 경우 ontology_context 업데이트 반환
    if finalized_anchor.get('status') == 'FK_LINK':
        ontology_context = state.get("ontology_context")
        if ontology_context:
            result["ontology_context"] = ontology_context
    
    return result


def ontology_builder_node(state: AgentState) -> Dict[str, Any]:
    """
    [Node] 온톨로지 구축 - Rule Prepares, LLM Decides
    
    파일이 메타데이터인지 판단하고, 메타데이터면 파싱하여 온톨로지에 추가
    """
    print("\n" + "="*80)
    print("📚 [ONTOLOGY BUILDER NODE] 시작")
    print("="*80)
    
    file_path = state["file_path"]
    metadata = state["raw_metadata"]
    
    dataset_id = state.get("current_dataset_id", "unknown")
    conversation_history = state.get("conversation_history")
    if not conversation_history:
        conversation_history = create_empty_conversation_history(dataset_id)
    
    ontology = state.get("ontology_context")
    
    if not ontology or not ontology.get("definitions"):
        print(f"   - 온톨로지 로드 시도...")
        ontology = ontology_manager.load()
    
    if not ontology:
        ontology = {
            "definitions": {},
            "relationships": [],
            "hierarchy": [],
            "file_tags": {}
        }
    
    # === Step 1: Rule Prepares ===
    print("\n🔧 [Rule] 데이터 전처리 중...")
    context = build_metadata_detection_context(file_path, metadata)
    
    print(f"   - 파일명 파싱: {context.get('name_parts')}")
    print(f"   - 컬럼 수: {context.get('num_columns')}개")
    
    # === Step 2: LLM Decides ===
    print("\n🧠 [LLM] 메타데이터 여부 판단 중...")
    
    meta_result = ask_llm_is_metadata(context)
    
    confidence = meta_result.get("confidence", 0.0)
    is_metadata = meta_result.get("is_metadata", False)
    
    print(f"   - 판단: {'메타데이터' if is_metadata else '일반 데이터'}")
    print(f"   - 확신도: {confidence:.2%}")
    
    # === Step 3: Confidence Check ===
    review_decision = should_request_human_review(
        file_path=file_path,
        issue_type="metadata_classification",
        context={
            "is_metadata": is_metadata,
            "reasoning": meta_result.get("reasoning"),
            "columns": context.get("columns", []),
            "indicators": meta_result.get("indicators", {})
        },
        rule_based_confidence=confidence
    )
    
    if review_decision["needs_review"]:
        print(f"\n⚠️  [Low Confidence] Human Review 요청")
        
        specific_question = generate_natural_human_question(
            file_path=file_path,
            context={
                "reasoning": meta_result.get("reasoning"),
                "message": f"Confidence {confidence:.1%}",
                "columns": context.get("columns", [])
            },
            issue_type="metadata_uncertain",
            conversation_history=conversation_history
        )
        
        return {
            "needs_human_review": True,
            "review_type": "classification",
            "human_question": specific_question,
            "ontology_context": ontology,
            "conversation_history": conversation_history,
            "logs": [f"⚠️ [Ontology] 메타데이터 판단 불확실 ({confidence:.2%})."]
        }
    
    # === Step 4: Branching ===
    
    # [Branch A] 메타데이터 파일
    if is_metadata:
        print(f"\n📖 [Metadata] 메타데이터 파일로 확정")
        
        ontology["file_tags"][file_path] = {
            "type": "metadata",
            "role": "dictionary",
            "confidence": confidence,
            "detected_at": datetime.now().isoformat()
        }
        
        print(f"   - 메타데이터 파싱 중...")
        new_definitions = parse_metadata_content(file_path)
        ontology["definitions"].update(new_definitions)
        
        print(f"   - 용어 {len(new_definitions)}개 추가")
        
        ontology_manager.save(ontology)
        
        return {
            "ontology_context": ontology,
            "skip_indexing": True,
            "logs": [f"📚 [Ontology] 메타데이터 등록: {len(new_definitions)}개 용어 추가"]
        }
    
    # [Branch B] 일반 데이터 파일
    else:
        print(f"\n📊 [Data] 일반 데이터 파일로 확정")
        
        columns = metadata.get("columns", [])
        
        ontology["file_tags"][file_path] = {
            "type": "transactional_data",
            "confidence": confidence,
            "detected_at": datetime.now().isoformat(),
            "columns": columns
        }
        
        # 관계 추론
        existing_data_files = [
            fp for fp, tag in ontology.get("file_tags", {}).items()
            if tag.get("type") == "transactional_data" and fp != file_path
        ]
        
        if existing_data_files:
            print(f"\n🔗 [Relationship] 관계 추론 시작...")
            print(f"   - 기존 데이터 파일: {len(existing_data_files)}개")
            
            table_name = os.path.basename(file_path).replace(".csv", "_table").replace(".", "_")
            
            relationship_result = infer_relationships_with_llm(
                current_table_name=table_name,
                current_cols=columns,
                ontology_context=ontology,
                current_metadata=metadata
            )
            
            new_relationships = relationship_result.get("relationships", [])
            if new_relationships:
                print(f"   - 관계 {len(new_relationships)}개 발견")
                
                existing_rels = ontology.get("relationships", [])
                existing_keys = {
                    (r["source_table"], r["target_table"], r["source_column"], r["target_column"])
                    for r in existing_rels
                }
                
                for new_rel in new_relationships:
                    key = (new_rel["source_table"], new_rel["target_table"], 
                           new_rel["source_column"], new_rel["target_column"])
                    if key not in existing_keys:
                        ontology["relationships"].append(new_rel)
        
        ontology_manager.save(ontology)
        
        return {
            "ontology_context": ontology,
            "skip_indexing": False,
            "logs": ["🔍 [Ontology] 일반 데이터 확인. 관계 추론 완료."]
        }

