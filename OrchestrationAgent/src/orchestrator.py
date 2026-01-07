"""경량 Orchestrator - ExtractionAgent + DataContext + CodeGen 연결

책임:
- ExtractionAgent 호출하여 Execution Plan 획득
- DataContext로 데이터 로드
- AnalysisAgent(CodeGen)로 분석 코드 생성 및 실행
- 결과 통합 및 반환
"""

import time
from typing import Dict, Any, Optional, Tuple

from .models import OrchestrationResult, DataSummary
from .config import OrchestratorConfig, DEFAULT_CONFIG


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
        
        try:
            # Step 1: Extraction - 실행 계획 생성
            extraction_result = self._run_extraction(query)
            
            if not extraction_result.get("execution_plan"):
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
            
            # Step 2: Data Load - 데이터 로드
            runtime_data, data_summary = self._load_data(execution_plan)
            
            if not runtime_data:
                return OrchestrationResult(
                    status="error",
                    error_message="Data loading failed: No data available",
                    error_stage="data_load",
                    extraction_plan=execution_plan,
                    extraction_confidence=extraction_confidence,
                    execution_time_ms=(time.time() - start_time) * 1000
                )
            
            # Step 3: Analysis - 코드 생성 및 실행
            analysis_result = self._run_analysis(
                query=query,
                runtime_data=runtime_data,
                data_summary=data_summary,
                max_retries=max_retries,
                timeout=timeout
            )
            
            execution_time = (time.time() - start_time) * 1000
            
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
        
        # 데이터 요약 생성
        data_summary = self._create_data_summary(runtime_data)
        
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
        """DataContext로 데이터 로드
        
        Returns:
            (runtime_data, data_summary)
        """
        from shared.data.context import DataContext
        
        ctx = DataContext()
        ctx.load_from_plan(execution_plan, preload_cohort=self.config.preload_cohort)
        
        # runtime_data 구성
        runtime_data = {}
        
        # Cohort
        cohort = ctx.get_cohort()
        if cohort is not None and not cohort.empty:
            runtime_data["cohort"] = cohort
        
        # Signals
        signals = ctx.get_signals()
        if signals is not None and not signals.empty:
            runtime_data["df"] = signals
        
        # 메타데이터
        runtime_data["case_ids"] = ctx.get_case_ids()
        runtime_data["param_keys"] = ctx.get_available_parameters()
        
        # 요약 생성
        data_summary = ctx.summary()
        
        # DataContext 저장 (재사용 가능)
        self._data_context = ctx
        
        return runtime_data, data_summary
    
    def _create_data_summary(self, runtime_data: Dict[str, Any]) -> Dict[str, Any]:
        """runtime_data에서 요약 생성"""
        summary = {}
        
        if "df" in runtime_data:
            df = runtime_data["df"]
            summary["signals"] = {
                "shape": df.shape,
                "columns": list(df.columns)
            }
        
        if "cohort" in runtime_data:
            cohort = runtime_data["cohort"]
            summary["cohort"] = {
                "shape": cohort.shape,
                "columns": list(cohort.columns)
            }
        
        summary["case_count"] = len(runtime_data.get("case_ids", []))
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
        
        # ExecutionContext 생성
        exec_context = self._build_execution_context(runtime_data, data_summary)
        
        # CodeRequest 생성
        request = self._build_code_request(query, exec_context, data_summary)
        
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
        
        if "df" in runtime_data:
            df = runtime_data["df"]
            cols = list(df.columns)[:10]
            cols_str = str(cols) + ("..." if len(df.columns) > 10 else "")
            available_variables["df"] = (
                f"pandas DataFrame - Signal 데이터, "
                f"shape: {df.shape}, columns: {cols_str}"
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
        available_variables["case_ids"] = f"List[str] - {len(case_ids)}개 케이스 ID"
        
        param_keys = runtime_data.get("param_keys", [])
        available_variables["param_keys"] = f"List[str] - 파라미터 키: {param_keys}"
        
        # 샘플 데이터 (LLM 참고용)
        sample_data = {}
        if "df" in runtime_data and not runtime_data["df"].empty:
            sample_df = runtime_data["df"].head(3)
            # 숫자 반올림
            sample_data["df_head"] = sample_df.round(4).to_dict(orient="records")
        
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
        data_summary: Dict[str, Any]
    ):
        """CodeRequest 생성"""
        from AnalysisAgent.src.models import CodeRequest
        
        # 힌트 생성
        hints = None
        if self.config.generate_hints:
            hints = self._generate_hints(query, data_summary)
        
        return CodeRequest(
            task_description=query,
            expected_output="분석 결과를 result 변수에 저장. 숫자, 딕셔너리, 또는 리스트 형태.",
            execution_context=exec_context,
            hints=hints,
            constraints=[
                "NaN 값은 dropna() 또는 fillna()로 처리",
                "result 변수에 최종 결과 저장 필수",
                "루프 대신 pandas/numpy 벡터 연산 사용 권장"
            ]
        )
    
    def _generate_hints(self, query: str, data_summary: Dict[str, Any]) -> Optional[str]:
        """질의 기반 구현 힌트 생성"""
        hints = []
        query_lower = query.lower()
        
        # 키워드 기반 힌트
        if "평균" in query_lower or "mean" in query_lower:
            hints.append("평균 계산: df['column'].mean() 또는 df.groupby('group')['column'].mean()")
        
        if "비교" in query_lower or "그룹" in query_lower or "성별" in query_lower:
            hints.append("그룹 비교: cohort DataFrame에서 그룹 정보 참조 (예: cohort['sex'])")
            hints.append("df와 cohort 조인이 필요할 수 있음: pd.merge(df, cohort, on='caseid')")
        
        if "상관" in query_lower or "correlation" in query_lower:
            hints.append("상관관계: scipy.stats.pearsonr(x, y) 또는 df.corr()")
        
        if "분포" in query_lower or "distribution" in query_lower:
            hints.append("분포 분석: df['column'].describe() 또는 df['column'].value_counts()")
        
        if "표준편차" in query_lower or "std" in query_lower:
            hints.append("표준편차: df['column'].std()")
        
        if "최대" in query_lower or "max" in query_lower:
            hints.append("최대값: df['column'].max()")
        
        if "최소" in query_lower or "min" in query_lower:
            hints.append("최소값: df['column'].min()")
        
        # 데이터 구조 힌트
        param_keys = data_summary.get("param_keys", [])
        if param_keys:
            hints.append(f"사용 가능한 signal 파라미터: {param_keys[:5]}")
        
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

