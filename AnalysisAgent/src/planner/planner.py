# AnalysisAgent/src/planner/planner.py
"""
Analysis Planner

Creates analysis execution plans using LLM.

Usage:
    from AnalysisAgent.src.planner import AnalysisPlanner
    from AnalysisAgent.src.context import ContextBuilder, AnalysisContext
    from shared.llm import get_llm_client
    
    # Build context
    builder = ContextBuilder()
    context = builder.build_from_dataframes({"df": signal_df})
    
    # Create planner
    llm = get_llm_client()
    planner = AnalysisPlanner(llm_client=llm)
    
    # Create plan
    result = planner.plan("Calculate mean of HR", context)
    
    if result.success:
        print(result.plan.describe())
"""

import logging
import json
import re
import time
from typing import Dict, List, Any, Optional, TYPE_CHECKING

from ..models.plan import PlanStep, AnalysisPlan, PlanningResult
from .prompts import build_planning_prompt
from ..context.schema import AnalysisContext

if TYPE_CHECKING:
    from shared.llm.client import LLMClient

logger = logging.getLogger(__name__)


class AnalysisPlanner:
    """LLM 기반 분석 계획 수립기"""
    
    def __init__(
        self,
        llm_client: Optional["LLMClient"] = None,
        max_tokens: int = 2000,
        temperature: float = 0.0,
        max_retries: int = 2,
    ):
        """
        Args:
            llm_client: LLM 클라이언트 (None이면 lazy init)
            max_tokens: 최대 응답 토큰 수
            temperature: LLM 온도 (0.0 = deterministic)
            max_retries: 파싱 실패 시 최대 재시도 횟수
        """
        self._llm_client = llm_client
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_retries = max_retries
    
    def _get_llm_client(self) -> "LLMClient":
        """Lazy LLM client initialization"""
        if self._llm_client is None:
            from shared.llm import get_llm_client
            self._llm_client = get_llm_client()
        return self._llm_client
    
    def plan(
        self,
        query: str,
        context: AnalysisContext,
        additional_context: Optional[str] = None,
    ) -> PlanningResult:
        """
        분석 계획 수립
        
        Args:
            query: 사용자 분석 쿼리 (예: "HR의 평균을 구해줘")
            context: AnalysisContext (데이터 스키마, Tool 목록 등)
            additional_context: 추가 컨텍스트 (선택)
        
        Returns:
            PlanningResult (success=True이면 plan 포함)
        """
        logger.info(f"📝 Planning analysis for: '{query}'")
        start_time = time.time()
        
        # 프롬프트 생성
        system_prompt, user_prompt = build_planning_prompt(
            query=query,
            context=context,
            additional_context=additional_context,
        )
        
        logger.debug(f"   System prompt: {len(system_prompt)} chars")
        logger.debug(f"   User prompt: {len(user_prompt)} chars")
        
        # LLM 호출 및 파싱 (재시도 포함)
        last_error = None
        raw_response = None
        
        for attempt in range(self.max_retries + 1):
            try:
                # LLM 호출
                llm = self._get_llm_client()
                
                full_prompt = f"{system_prompt}\n\n{user_prompt}"
                raw_response = llm.ask_text(full_prompt, max_tokens=self.max_tokens)
                
                logger.debug(f"   LLM response ({attempt + 1}): {len(raw_response)} chars")
                
                # JSON 파싱
                plan_dict = self._parse_response(raw_response)
                
                # AnalysisPlan 객체 생성
                plan = self._build_plan(query, plan_dict)
                
                # 계획 검증
                validation_errors = plan.validate()
                if validation_errors:
                    raise ValueError(f"Plan validation failed: {validation_errors}")
                
                # 성공
                planning_time = (time.time() - start_time) * 1000
                plan.planning_time_ms = planning_time
                
                logger.info(f"✅ Plan created: {plan.step_count} steps, "
                           f"complexity={plan.estimated_complexity}, "
                           f"confidence={plan.confidence:.0%}")
                
                return PlanningResult.from_plan(plan)
            
            except json.JSONDecodeError as e:
                last_error = f"JSON parsing error: {e}"
                logger.warning(f"   Attempt {attempt + 1} failed: {last_error}")
            
            except KeyError as e:
                last_error = f"Missing required field: {e}"
                logger.warning(f"   Attempt {attempt + 1} failed: {last_error}")
            
            except ValueError as e:
                last_error = str(e)
                logger.warning(f"   Attempt {attempt + 1} failed: {last_error}")
            
            except Exception as e:
                last_error = f"Unexpected error: {e}"
                logger.error(f"   Attempt {attempt + 1} failed: {last_error}")
        
        # 모든 재시도 실패
        logger.error(f"❌ Planning failed after {self.max_retries + 1} attempts: {last_error}")
        return PlanningResult.from_error(last_error, raw_response)
    
    def _parse_response(self, response: str) -> Dict[str, Any]:
        """LLM 응답에서 JSON 파싱"""
        # JSON 블록 추출 시도
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 코드 블록 없으면 전체를 JSON으로 시도
            json_str = response.strip()
            
            # 혹시 다른 마크다운 코드 블록이 있다면
            json_match = re.search(r'```\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
        
        # 앞뒤 불필요한 텍스트 제거
        # JSON 객체 시작/끝 찾기
        start_idx = json_str.find('{')
        end_idx = json_str.rfind('}')
        
        if start_idx == -1 or end_idx == -1:
            raise json.JSONDecodeError("No JSON object found", json_str, 0)
        
        json_str = json_str[start_idx:end_idx + 1]
        
        return json.loads(json_str)
    
    def _build_plan(self, query: str, plan_dict: Dict[str, Any]) -> AnalysisPlan:
        """딕셔너리에서 AnalysisPlan 객체 생성"""
        
        # PlanStep 객체들 생성
        steps = []
        for i, step_dict in enumerate(plan_dict.get("steps", [])):
            step = PlanStep(
                id=step_dict.get("id", f"step_{i + 1}"),
                order=step_dict.get("order", i),
                action=step_dict.get("action", "unknown"),
                description=step_dict.get("description", ""),
                execution_mode=step_dict.get("execution_mode", "code"),
                tool_name=step_dict.get("tool_name"),
                inputs=step_dict.get("inputs", []),
                input_columns=step_dict.get("input_columns", []),
                parameters=step_dict.get("parameters", {}),
                output_key=step_dict.get("output_key", f"step_{i + 1}_result"),
                expected_output_type=step_dict.get("expected_output_type", "any"),
                code_hint=step_dict.get("code_hint"),
                depends_on=step_dict.get("depends_on", []),
            )
            steps.append(step)
        
        # execution_mode 결정
        has_tool = any(s.execution_mode == "tool" for s in steps)
        has_code = any(s.execution_mode == "code" for s in steps)
        
        if has_tool and has_code:
            execution_mode = "hybrid"
        elif has_tool:
            execution_mode = "tool_only"
        else:
            execution_mode = "code_only"
        
        # AnalysisPlan 생성
        plan = AnalysisPlan(
            query=query,
            analysis_type=plan_dict.get("analysis_type", "general"),
            steps=steps,
            expected_output=plan_dict.get("expected_output", {}),
            execution_mode=execution_mode,
            estimated_complexity=plan_dict.get("estimated_complexity", "simple"),
            confidence=plan_dict.get("confidence", 0.8),
            reasoning=plan_dict.get("reasoning"),
            warnings=plan_dict.get("warnings", []),
        )
        
        return plan
    
    def plan_simple(
        self,
        query: str,
        context: AnalysisContext,
    ) -> PlanningResult:
        """
        Fast planning for simple queries (minimizes LLM calls)
        
        For simple statistical queries, creates plan using rule-based approach.
        Falls back to plan() for complex queries.
        
        Args:
            query: User query
            context: AnalysisContext
        
        Returns:
            PlanningResult
        """
        # Detect simple query patterns
        simple_patterns = self._detect_simple_patterns(query, context)
        
        if simple_patterns:
            logger.info(f"📝 Using rule-based planning for simple query")
            return self._create_simple_plan(query, simple_patterns, context)
        
        # Complex queries use LLM-based planning
        return self.plan(query, context)
    
    def _detect_simple_patterns(
        self,
        query: str,
        context: AnalysisContext,
    ) -> Optional[Dict[str, Any]]:
        """Detect simple query patterns"""
        query_lower = query.lower()
        
        # 컬럼 이름 추출
        all_columns = []
        for schema in context.data_schemas.values():
            all_columns.extend(schema.column_names)
        
        mentioned_columns = [
            col for col in all_columns
            if col.lower() in query_lower or col in query
        ]
        
        # 평균 쿼리
        if any(kw in query_lower for kw in ["평균", "mean", "average"]):
            if mentioned_columns:
                return {
                    "type": "mean",
                    "columns": mentioned_columns,
                }
        
        # 상관관계 쿼리
        if any(kw in query_lower for kw in ["상관", "correlation", "corr"]):
            if len(mentioned_columns) >= 2:
                return {
                    "type": "correlation",
                    "columns": mentioned_columns[:2],
                }
        
        # 표준편차 쿼리
        if any(kw in query_lower for kw in ["표준편차", "std", "standard deviation"]):
            if mentioned_columns:
                return {
                    "type": "std",
                    "columns": mentioned_columns,
                }
        
        return None
    
    def _create_simple_plan(
        self,
        query: str,
        patterns: Dict[str, Any],
        context: AnalysisContext,
    ) -> PlanningResult:
        """Create simple plan using rule-based approach"""
        pattern_type = patterns["type"]
        columns = patterns["columns"]
        
        # DataFrame variable name (default: df)
        df_var = "df"
        for name, schema in context.data_schemas.items():
            if any(col in schema.column_names for col in columns):
                df_var = name
                break
        
        if pattern_type == "mean":
            col = columns[0]
            step = PlanStep(
                id="step_1",
                order=0,
                action="compute_mean",
                description=f"Calculate mean of {col}",
                execution_mode="code",
                inputs=[df_var],
                input_columns=[col],
                output_key="mean_result",
                expected_output_type="numeric",
                code_hint=f"result = {df_var}['{col}'].mean()",
            )
            expected_output = {
                "type": "numeric",
                "description": f"Mean value of {col}",
            }
        
        elif pattern_type == "std":
            col = columns[0]
            step = PlanStep(
                id="step_1",
                order=0,
                action="compute_std",
                description=f"Calculate standard deviation of {col}",
                execution_mode="code",
                inputs=[df_var],
                input_columns=[col],
                output_key="std_result",
                expected_output_type="numeric",
                code_hint=f"result = {df_var}['{col}'].std()",
            )
            expected_output = {
                "type": "numeric",
                "description": f"Standard deviation of {col}",
            }
        
        elif pattern_type == "correlation":
            col1, col2 = columns[:2]
            step = PlanStep(
                id="step_1",
                order=0,
                action="compute_correlation",
                description=f"Calculate correlation between {col1} and {col2}",
                execution_mode="code",
                inputs=[df_var],
                input_columns=[col1, col2],
                output_key="correlation_result",
                expected_output_type="dict",
                code_hint=f"from scipy import stats; r = stats.pearsonr({df_var}['{col1}'].dropna(), {df_var}['{col2}'].dropna()); result = {{'correlation': r.statistic, 'pvalue': r.pvalue}}",
            )
            expected_output = {
                "type": "dict",
                "schema": {"correlation": "float", "pvalue": "float"},
                "description": "Correlation coefficient and p-value",
            }
        
        else:
            # fallback: LLM-based planning
            return self.plan(query, context)
        
        plan = AnalysisPlan(
            query=query,
            analysis_type=pattern_type,
            steps=[step],
            expected_output=expected_output,
            execution_mode="code_only",
            estimated_complexity="simple",
            confidence=0.95,
            reasoning=f"Rule-based simple plan ({pattern_type})",
        )
        
        logger.info(f"✅ Simple plan created: {plan.step_count} step, type={pattern_type}")
        
        return PlanningResult.from_plan(plan)
