"""경량 Orchestrator - ExtractionAgent + DataContext + CodeGen 연결

책임:
- ExtractionAgent 호출하여 Execution Plan 획득
- DataContext로 데이터 로드
- AnalysisAgent(CodeGen)로 분석 코드 생성 및 실행
- 결과 통합 및 반환
"""

import time
import logging
from typing import Dict, Any, Optional, Tuple

from .models import OrchestrationResult, DataSummary
from .config import OrchestratorConfig, DEFAULT_CONFIG

logger = logging.getLogger("OrchestrationAgent.orchestrator")


class Orchestrator:
    """
    ExtractionAgent와 AnalysisAgent(CodeGen)를 연결하는 오케스트레이터
    
    사용법:
        orchestrator = Orchestrator()
        result = orchestrator.run("위암 환자의 심박수 평균을 구해줘")
        
        if result.status == "success":
            print(result.result)
            print(result.generated_code)
    
    실행 모드:
        1. run(query) - 전체 파이프라인 (Extraction → DataLoad → Analysis)
        2. run_with_plan(query, plan) - Plan 있을 때 (DataLoad → Analysis)
        3. run_analysis_only(query, data) - 데이터 있을 때 (Analysis만)
    """
    
    def __init__(self, config: Optional[OrchestratorConfig] = None):
        """
        Args:
            config: 오케스트레이터 설정 (None이면 기본값 사용)
        """
        self.config = config or DEFAULT_CONFIG
        
        # Lazy initialization
        self._extraction_agent = None
        self._data_context = None
        self._code_generator = None
        self._sandbox = None
        self._llm_client = None
    
    # =========================================================================
    # Public API
    # =========================================================================
    
    def run(
        self, 
        query: str,
        max_retries: Optional[int] = None,
        timeout_seconds: Optional[int] = None
    ) -> OrchestrationResult:
        """
        질의 실행 - 전체 파이프라인
        
        Args:
            query: 자연어 질의
            max_retries: 코드 생성 재시도 횟수 (None이면 config 값)
            timeout_seconds: 실행 타임아웃 (None이면 config 값)
        
        Returns:
            OrchestrationResult
        
        Example:
            result = orchestrator.run("위암 환자의 심박수 평균을 성별로 비교해줘")
        """
        start_time = time.time()
        
        max_retries = max_retries if max_retries is not None else self.config.max_retries
        timeout = timeout_seconds if timeout_seconds is not None else self.config.timeout_seconds
        
        logger.info(f"🚀 Starting pipeline for query: '{query[:50]}{'...' if len(query) > 50 else ''}'")
        
        try:
            # Step 1: Extraction - 실행 계획 생성
            logger.info("📝 Step 1/3: Running ExtractionAgent...")
            extraction_result = self._run_extraction(query)
            
            if not extraction_result.get("execution_plan"):
                logger.error("❌ Extraction failed: No execution plan generated")
                return OrchestrationResult(
                    status="error",
                    error_message="Extraction failed: No execution plan generated",
                    error_stage="extraction",
                    extraction_plan=extraction_result,
                    execution_time_ms=(time.time() - start_time) * 1000
                )
            
            execution_plan = extraction_result["execution_plan"]
            extraction_confidence = extraction_result.get("confidence", 0.0)
            ambiguities = extraction_result.get("ambiguities", [])
            logger.info(f"✅ Extraction complete (confidence: {extraction_confidence:.2f})")
            logger.debug(f"   Plan: {execution_plan}")
            
            # Step 2: Data Load - 데이터 로드
            logger.info("📦 Step 2/3: Loading data via DataContext...")
            runtime_data, data_summary = self._load_data(execution_plan)
            
            if not runtime_data:
                logger.error("❌ Data loading failed: No data available")
                return OrchestrationResult(
                    status="error",
                    error_message="Data loading failed: No data available",
                    error_stage="data_load",
                    extraction_plan=execution_plan,
                    extraction_confidence=extraction_confidence,
                    execution_time_ms=(time.time() - start_time) * 1000
                )
            
            signals_count = len(runtime_data.get("signals", {}))
            total_rows = sum(len(df) for df in runtime_data.get("signals", {}).values())
            cohort_shape = runtime_data.get("cohort", {}).shape if hasattr(runtime_data.get("cohort", {}), "shape") else "N/A"
            logger.info(f"✅ Data loaded (signals: {signals_count} cases, {total_rows} rows, cohort: {cohort_shape})")
            
            # Step 3: Analysis - 코드 생성 및 실행
            logger.info("🧮 Step 3/3: Running AnalysisAgent (CodeGen)...")
            analysis_result = self._run_analysis(
                query=query,
                runtime_data=runtime_data,
                data_summary=data_summary,
                max_retries=max_retries,
                timeout=timeout
            )
            
            execution_time = (time.time() - start_time) * 1000
            
            if analysis_result["success"]:
                logger.info(f"✅ Analysis complete ({execution_time:.1f}ms, retries: {analysis_result.get('retry_count', 0)})")
            else:
                logger.error(f"❌ Analysis failed: {analysis_result.get('error')}")
            
            return OrchestrationResult(
                status="success" if analysis_result["success"] else "error",
                result=analysis_result.get("result"),
                generated_code=analysis_result.get("code"),
                error_message=analysis_result.get("error"),
                error_stage="analysis" if not analysis_result["success"] else None,
                execution_time_ms=execution_time,
                data_summary=data_summary,
                extraction_plan=execution_plan,
                extraction_confidence=extraction_confidence,
                ambiguities=ambiguities,
                retry_count=analysis_result.get("retry_count", 0)
            )
        
        except Exception as e:
            logger.exception(f"❌ Unexpected error: {e}")
            return OrchestrationResult(
                status="error",
                error_message=f"Unexpected error: {str(e)}",
                execution_time_ms=(time.time() - start_time) * 1000
            )
    
    def run_with_plan(
        self,
        query: str,
        execution_plan: Dict[str, Any],
        max_retries: Optional[int] = None
    ) -> OrchestrationResult:
        """
        이미 있는 Execution Plan으로 분석 실행 (ExtractionAgent 스킵)
        
        Args:
            query: 분석 질의
            execution_plan: 미리 생성된 실행 계획
            max_retries: 재시도 횟수
        
        Returns:
            OrchestrationResult
        """
        start_time = time.time()
        max_retries = max_retries if max_retries is not None else self.config.max_retries
        
        try:
            # Data Load
            runtime_data, data_summary = self._load_data(execution_plan)
            
            if not runtime_data:
                return OrchestrationResult(
                    status="error",
                    error_message="Data loading failed",
                    error_stage="data_load",
                    execution_time_ms=(time.time() - start_time) * 1000
                )
            
            # Analysis
            analysis_result = self._run_analysis(
                query=query,
                runtime_data=runtime_data,
                data_summary=data_summary,
                max_retries=max_retries
            )
            
            return OrchestrationResult(
                status="success" if analysis_result["success"] else "error",
                result=analysis_result.get("result"),
                generated_code=analysis_result.get("code"),
                error_message=analysis_result.get("error"),
                error_stage="analysis" if not analysis_result["success"] else None,
                execution_time_ms=(time.time() - start_time) * 1000,
                data_summary=data_summary,
                extraction_plan=execution_plan,
                retry_count=analysis_result.get("retry_count", 0)
            )
        
        except Exception as e:
            return OrchestrationResult(
                status="error",
                error_message=f"Unexpected error: {str(e)}",
                execution_time_ms=(time.time() - start_time) * 1000
            )
    
    def run_analysis_only(
        self,
        query: str,
        runtime_data: Dict[str, Any],
        max_retries: Optional[int] = None
    ) -> OrchestrationResult:
        """
        데이터가 이미 있을 때 분석만 실행 (Extraction + DataLoad 스킵)
        
        Args:
            query: 분석 질의
            runtime_data: 이미 로드된 데이터 {"df": ..., "cohort": ...}
            max_retries: 재시도 횟수
        
        Returns:
            OrchestrationResult
        
        Example:
            runtime_data = {
                "df": signals_df,
                "cohort": cohort_df,
                "case_ids": ["1", "2", "3"],
                "param_keys": ["HR", "SpO2"]
            }
            result = orchestrator.run_analysis_only("HR 평균 구해줘", runtime_data)
        """
        start_time = time.time()
        max_retries = max_retries if max_retries is not None else self.config.max_retries
        
        logger.info(f"🧮 Running analysis only for: '{query[:50]}{'...' if len(query) > 50 else ''}'")
        
        # 데이터 요약 생성
        data_summary = self._create_data_summary(runtime_data)
        logger.debug(f"   Data summary: {data_summary}")
        
        # Analysis
        analysis_result = self._run_analysis(
            query=query,
            runtime_data=runtime_data,
            data_summary=data_summary,
            max_retries=max_retries
        )
        
        execution_time = (time.time() - start_time) * 1000
        
        if analysis_result["success"]:
            logger.info(f"✅ Analysis complete ({execution_time:.1f}ms, retries: {analysis_result.get('retry_count', 0)})")
        else:
            logger.error(f"❌ Analysis failed: {analysis_result.get('error')}")
        
        return OrchestrationResult(
            status="success" if analysis_result["success"] else "error",
            result=analysis_result.get("result"),
            generated_code=analysis_result.get("code"),
            error_message=analysis_result.get("error"),
            error_stage="analysis" if not analysis_result["success"] else None,
            execution_time_ms=execution_time,
            data_summary=data_summary,
            retry_count=analysis_result.get("retry_count", 0)
        )
    
    # =========================================================================
    # Step 1: Extraction
    # =========================================================================
    
    def _run_extraction(self, query: str) -> Dict[str, Any]:
        """ExtractionAgent 호출하여 Execution Plan 생성"""
        
        if self._extraction_agent is None:
            self._extraction_agent = self._create_extraction_agent()
        
        # ExtractionAgent 실행
        result = self._extraction_agent.invoke({"user_query": query})
        
        # 결과에서 plan 추출
        return {
            "execution_plan": result.get("validated_plan") or result.get("execution_plan"),
            "confidence": result.get("overall_confidence", 0.0),
            "ambiguities": result.get("ambiguities", []),
            "intent": result.get("intent")
        }
    
    def _create_extraction_agent(self):
        """ExtractionAgent 인스턴스 생성"""
        import sys
        from pathlib import Path
        
        # ExtractionAgent를 sys.path 앞에 추가 (src.agents import 위해)
        extraction_path = str(Path(__file__).parent.parent.parent / "ExtractionAgent")
        if extraction_path not in sys.path:
            sys.path.insert(0, extraction_path)
        
        # src.agents로 import (ExtractionAgent 내부 import 경로와 일치)
        from src.agents.graph import build_agent
        return build_agent()
    
    # =========================================================================
    # Step 2: Data Load
    # =========================================================================
    
    def _load_data(
        self, 
        execution_plan: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """DataContext로 데이터 로드 (케이스별 Dict 형태)
        
        Returns:
            (runtime_data, data_summary)
            
        runtime_data 구조:
            - signals: Dict[caseid, DataFrame] - 케이스별 시계열 데이터
            - cohort: DataFrame - 전체 메타데이터
            - case_ids: List[str] - 로드된 케이스 ID
            - total_cases: int - 전체 케이스 수
            - _access_guide: str - LLM용 동적 데이터 접근 가이드
        """
        from shared.data.context import DataContext
        
        ctx = DataContext()
        ctx.load_from_plan(execution_plan, preload_cohort=self.config.preload_cohort)
        
        # runtime_data 구성
        runtime_data = {}
        
        # Cohort (전체)
        cohort = ctx.get_cohort()
        if cohort is not None and not cohort.empty:
            runtime_data["cohort"] = cohort
        
        # Signals - Dict[caseid, DataFrame] 형태로!
        max_cases = self.config.max_signal_cases if self.config.max_signal_cases > 0 else None
        signals_dict = ctx.get_signals_dict(max_cases=max_cases)
        if signals_dict:
            runtime_data["signals"] = signals_dict
        
        # 메타데이터
        runtime_data["case_ids"] = list(signals_dict.keys()) if signals_dict else []
        runtime_data["total_cases"] = len(ctx.get_case_ids())
        runtime_data["param_keys"] = ctx.get_available_parameters()
        
        # 동적 접근 가이드 생성 (LLM 프롬프트용)
        access_guide = ctx.generate_access_guide(signals_dict, cohort)
        runtime_data["_access_guide"] = access_guide
        
        # 요약 생성
        data_summary = {
            "signals_count": len(signals_dict) if signals_dict else 0,
            "total_cases": runtime_data["total_cases"],
            "cohort_shape": cohort.shape if cohort is not None and not cohort.empty else None,
            "param_keys": runtime_data["param_keys"],
            "loaded_case_ids": runtime_data["case_ids"][:10],  # 샘플
        }
        
        # DataContext 저장 (재사용 가능)
        self._data_context = ctx
        
        return runtime_data, data_summary
    
    def _create_data_summary(self, runtime_data: Dict[str, Any]) -> Dict[str, Any]:
        """runtime_data에서 요약 생성"""
        summary = {}
        
        if "signals" in runtime_data:
            signals_dict = runtime_data["signals"]
            if signals_dict:
                sample_cid = list(signals_dict.keys())[0]
                sample_df = signals_dict[sample_cid]
                summary["signals"] = {
                    "case_count": len(signals_dict),
                    "total_rows": sum(len(df) for df in signals_dict.values()),
                    "sample_shape": sample_df.shape,
                    "columns": list(sample_df.columns)
                }
        
        if "cohort" in runtime_data:
            cohort = runtime_data["cohort"]
            summary["cohort"] = {
                "shape": cohort.shape,
                "columns": list(cohort.columns)
            }
        
        summary["case_count"] = len(runtime_data.get("case_ids", []))
        summary["total_cases"] = runtime_data.get("total_cases", 0)
        summary["param_keys"] = runtime_data.get("param_keys", [])
        
        return summary
    
    # =========================================================================
    # Step 3: Analysis (CodeGen)
    # =========================================================================
    
    def _run_analysis(
        self,
        query: str,
        runtime_data: Dict[str, Any],
        data_summary: Dict[str, Any],
        max_retries: int = 2,
        timeout: int = 30
    ) -> Dict[str, Any]:
        """CodeGenerator로 분석 코드 생성 및 실행
        
        Returns:
            {"success": bool, "result": Any, "code": str, "error": str, "retry_count": int}
        """
        # 컴포넌트 초기화
        if self._code_generator is None:
            self._init_code_gen_components(timeout)
        
        # 동적 접근 가이드 추출 (LLM 프롬프트용)
        access_guide = runtime_data.pop("_access_guide", None)
        
        # ExecutionContext 생성
        exec_context = self._build_execution_context(runtime_data, data_summary)
        
        # CodeRequest 생성 (동적 가이드 포함)
        request = self._build_code_request(query, exec_context, data_summary, access_guide)
        
        # 생성 + 실행 (with retry)
        last_error = None
        generated_code = None
        
        for attempt in range(max_retries + 1):
            # 첫 시도 또는 재시도
            if attempt == 0:
                gen_result = self._code_generator.generate(request)
            else:
                gen_result = self._code_generator.generate_with_fix(
                    request, 
                    generated_code, 
                    last_error
                )
            
            generated_code = gen_result.code
            
            # 검증 실패
            if not gen_result.is_valid:
                last_error = f"Validation failed: {gen_result.validation_errors}"
                continue
            
            # 실행
            exec_result = self._sandbox.execute(gen_result.code, runtime_data)
            
            if exec_result.success:
                return {
                    "success": True,
                    "result": exec_result.result,
                    "code": gen_result.code,
                    "retry_count": attempt
                }
            
            last_error = exec_result.error
        
        # 모든 재시도 실패
        return {
            "success": False,
            "error": last_error,
            "code": generated_code,
            "retry_count": max_retries + 1
        }
    
    def _init_code_gen_components(self, timeout: int = 30):
        """CodeGenerator와 Sandbox 초기화"""
        from AnalysisAgent.src.code_gen import CodeGenerator, SandboxExecutor
        from shared.llm import get_llm_client
        
        if self._llm_client is None:
            self._llm_client = get_llm_client()
        
        self._code_generator = CodeGenerator(llm_client=self._llm_client)
        self._sandbox = SandboxExecutor(timeout_seconds=timeout)
    
    def _build_execution_context(
        self, 
        runtime_data: Dict[str, Any],
        data_summary: Dict[str, Any]
    ):
        """CodeGen용 ExecutionContext 생성"""
        from AnalysisAgent.src.models import ExecutionContext
        
        # 사용 가능한 변수 설명
        available_variables = {}
        
        # signals: Dict[caseid, DataFrame]
        if "signals" in runtime_data and runtime_data["signals"]:
            signals_dict = runtime_data["signals"]
            case_count = len(signals_dict)
            sample_cid = list(signals_dict.keys())[0]
            sample_df = signals_dict[sample_cid]
            cols = list(sample_df.columns)[:10]
            cols_str = str(cols) + ("..." if len(sample_df.columns) > 10 else "")
            available_variables["signals"] = (
                f"Dict[caseid, DataFrame] - 케이스별 시계열 데이터, "
                f"{case_count} cases, columns: {cols_str}"
            )
        
        if "cohort" in runtime_data:
            cohort = runtime_data["cohort"]
            cols = list(cohort.columns)[:10]
            cols_str = str(cols) + ("..." if len(cohort.columns) > 10 else "")
            available_variables["cohort"] = (
                f"pandas DataFrame - Cohort 메타데이터, "
                f"shape: {cohort.shape}, columns: {cols_str}"
            )
        
        case_ids = runtime_data.get("case_ids", [])
        available_variables["case_ids"] = f"List[str] - {len(case_ids)}개 로드된 케이스 ID"
        
        total_cases = runtime_data.get("total_cases", len(case_ids))
        available_variables["total_cases"] = f"int - 전체 케이스 수: {total_cases}"
        
        param_keys = runtime_data.get("param_keys", [])
        available_variables["param_keys"] = f"List[str] - 파라미터 키: {param_keys}"
        
        # 샘플 데이터 (LLM 참고용)
        sample_data = {}
        if "signals" in runtime_data and runtime_data["signals"]:
            signals_dict = runtime_data["signals"]
            sample_cid = list(signals_dict.keys())[0]
            sample_df = signals_dict[sample_cid].head(3)
            sample_data["signals_sample"] = {
                "caseid": sample_cid,
                "data": sample_df.round(4).to_dict(orient="records")
            }
        
        if "cohort" in runtime_data and not runtime_data["cohort"].empty:
            sample_cohort = runtime_data["cohort"].head(3)
            sample_data["cohort_head"] = sample_cohort.to_dict(orient="records")
        
        return ExecutionContext(
            available_variables=available_variables,
            sample_data=sample_data if sample_data else None
        )
    
    def _build_code_request(
        self, 
        query: str,
        exec_context,
        data_summary: Dict[str, Any],
        access_guide: Optional[str] = None
    ):
        """CodeRequest 생성"""
        from AnalysisAgent.src.models import CodeRequest
        
        # 동적 접근 가이드 + 기존 힌트 결합
        hints_parts = []
        
        # 1. 동적 데이터 접근 가이드 (우선)
        if access_guide:
            hints_parts.append(access_guide)
        
        # 2. 질의 기반 추가 힌트
        if self.config.generate_hints:
            additional_hints = self._generate_hints(query, data_summary)
            if additional_hints:
                hints_parts.append("\n## Additional Hints\n" + additional_hints)
        
        hints = "\n".join(hints_parts) if hints_parts else None
        
        return CodeRequest(
            task_description=query,
            expected_output="Assign final result to `result` variable. Can be number, dict, or list.",
            execution_context=exec_context,
            hints=hints,
            constraints=[
                "Handle NaN with dropna() or fillna()",
                "Must assign final result to `result` variable",
                "For case-level statistics: compute per-case first, then aggregate",
                "Use signals[caseid] to access individual case DataFrame"
            ]
        )
    
    def _generate_hints(self, query: str, data_summary: Dict[str, Any]) -> Optional[str]:
        """질의 기반 추가 힌트 생성 (동적 가이드 보완용)"""
        hints = []
        query_lower = query.lower()
        
        # 키워드 기반 힌트 (signals Dict 기반)
        if "평균" in query_lower or "mean" in query_lower:
            hints.append("Mean calculation (per-case recommended):")
            hints.append("  case_means = {cid: df['col'].mean() for cid, df in signals.items()}")
            hints.append("  result = np.mean(list(case_means.values()))")
        
        if "비교" in query_lower or "그룹" in query_lower or "성별" in query_lower:
            hints.append("Group comparison: use cohort to filter cases by group")
            hints.append("  male_cases = cohort[cohort['sex'] == 'M']['caseid'].astype(str).tolist()")
            hints.append("  male_signals = {cid: signals[cid] for cid in male_cases if cid in signals}")
        
        if "상관" in query_lower or "correlation" in query_lower:
            hints.append("Correlation (per-case, then aggregate):")
            hints.append("  from scipy import stats")
            hints.append("  def case_corr(df):")
            hints.append("      clean = df[['col1', 'col2']].dropna()")
            hints.append("      if len(clean) < 3: return np.nan")
            hints.append("      r = stats.pearsonr(clean['col1'], clean['col2'])")
            hints.append("      return r.statistic  # Use .statistic, NOT tuple unpacking!")
            hints.append("  case_corrs = {cid: case_corr(df) for cid, df in signals.items()}")
            hints.append("  result = np.nanmean(list(case_corrs.values()))")
        
        if "분포" in query_lower or "distribution" in query_lower:
            hints.append("Distribution: compute per-case, then combine")
        
        # 데이터 구조 힌트
        param_keys = data_summary.get("param_keys", [])
        if param_keys:
            hints.append(f"Available signal parameters: {param_keys[:5]}")
        
        return "\n".join(hints) if hints else None
    
    # =========================================================================
    # Utility
    # =========================================================================
    
    def get_data_context(self):
        """현재 DataContext 반환 (데이터 재사용용)"""
        return self._data_context
    
    def clear_cache(self):
        """캐시 정리"""
        from shared.data.context import DataContext
        DataContext.clear_cache()
        self._data_context = None
    
    def reset(self):
        """모든 컴포넌트 리셋"""
        self._extraction_agent = None
        self._data_context = None
        self._code_generator = None
        self._sandbox = None
        self._llm_client = None

