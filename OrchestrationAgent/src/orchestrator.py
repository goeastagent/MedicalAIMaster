"""경량 Orchestrator - ExtractionAgent + DataContext + CodeGen 연결

책임:
- ExtractionAgent 호출하여 Execution Plan 획득
- DataContext로 데이터 로드
- AnalysisAgent(CodeGen)로 분석 코드 생성 및 실행
- 결과 통합 및 반환
"""

import time
import gc
import logging
from typing import Dict, Any, Optional, Tuple, List, Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed

from .models import OrchestrationResult, DataSummary
from .config import OrchestratorConfig, DEFAULT_CONFIG

logger = logging.getLogger("OrchestrationAgent.orchestrator")


class Orchestrator:
    """
    ExtractionAgent와 AnalysisAgent(CodeGen)를 연결하는 오케스트레이터
    
    사용법:
        orchestrator = Orchestrator()
        result = orchestrator.run("위암 환자의 심박수 평균을 단일 float 값으로 구해줘")
        
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
        self._code_execution_engine = None  # 통합 실행 엔진
        self._llm_client = None
    
    # =========================================================================
    # Public API
    # =========================================================================
    
    def run(
        self, 
        query: str,
        max_retries: Optional[int] = None,
        timeout_seconds: Optional[int] = None,
        _extraction_result: Optional[Dict[str, Any]] = None,
    ) -> OrchestrationResult:
        """
        질의 실행 - 전체 파이프라인
        
        Args:
            query: 자연어 질의
            max_retries: 코드 생성 재시도 횟수 (None이면 config 값)
            timeout_seconds: 실행 타임아웃 (None이면 config 값)
            _extraction_result: 이미 수행된 extraction 결과 (run_auto에서 전달, 외부 호출 금지)
        
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
            if _extraction_result is not None:
                logger.info("📝 Step 1/3: Reusing pre-computed extraction result")
                extraction_result = _extraction_result
            else:
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
            runtime_data: 이미 로드된 데이터
                - 새 형식: {"signals": Dict[caseid, DataFrame], "cohort": DataFrame}
                - 기존 형식: {"df": DataFrame, "cohort": DataFrame} (하위호환)
            max_retries: 재시도 횟수
        
        Returns:
            OrchestrationResult
        
        Example (새 형식):
            runtime_data = {
                "signals": {"case1": df1, "case2": df2},
                "cohort": cohort_df,
            }
            
        Example (기존 형식 - 하위호환):
            runtime_data = {
                "df": signals_df,
                "cohort": cohort_df,
            }
        """
        start_time = time.time()
        max_retries = max_retries if max_retries is not None else self.config.max_retries
        
        logger.info(f"🧮 Running analysis only for: '{query[:50]}{'...' if len(query) > 50 else ''}'")
        
        # 동적 접근 가이드 생성 (데이터 구조에 맞게)
        runtime_data = self._prepare_runtime_data_with_guide(runtime_data)
        
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
        validation = result.get("validation", {}) or {}
        return {
            "execution_plan": result.get("validated_plan") or result.get("execution_plan"),
            "confidence": validation.get("confidence", 0.0),
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
        """runtime_data에서 요약 생성 (새 형식 + 기존 형식 지원)"""
        summary = {}
        
        # 새 형식: signals Dict
        if "signals" in runtime_data and runtime_data["signals"]:
            signals_dict = runtime_data["signals"]
            sample_cid = list(signals_dict.keys())[0]
            sample_df = signals_dict[sample_cid]
            summary["signals"] = {
                "case_count": len(signals_dict),
                "total_rows": sum(len(df) for df in signals_dict.values()),
                "sample_shape": sample_df.shape,
                "columns": list(sample_df.columns)
            }
        
        # 기존 형식: df (하위호환)
        elif "df" in runtime_data and hasattr(runtime_data["df"], "shape"):
            df = runtime_data["df"]
            summary["signals"] = {
                "shape": df.shape,
                "columns": list(df.columns)
            }
        
        if "cohort" in runtime_data and hasattr(runtime_data["cohort"], "shape"):
            cohort = runtime_data["cohort"]
            summary["cohort"] = {
                "shape": cohort.shape,
                "columns": list(cohort.columns)
            }
        
        summary["case_count"] = len(runtime_data.get("case_ids", []))
        summary["total_cases"] = runtime_data.get("total_cases", 0)
        summary["param_keys"] = runtime_data.get("param_keys", [])
        
        return summary
    
    def _prepare_runtime_data_with_guide(self, runtime_data: Dict[str, Any]) -> Dict[str, Any]:
        """runtime_data에 동적 접근 가이드 추가 (기존 df 형태도 지원)"""
        # 이미 가이드가 있으면 그대로 반환
        if "_access_guide" in runtime_data:
            return runtime_data
        
        # 메타데이터에서 동적으로 entity_id 컬럼 가져오기
        entity_col = "id"  # 기본값
        if self._data_context and self._data_context.entity_id_column:
            entity_col = self._data_context.entity_id_column
        elif "_plan_metadata" in runtime_data:
            entity_col = runtime_data["_plan_metadata"].get("entity_id_column") or "id"
        
        guide_parts = ["## Available Data\n"]
        
        # 새 형식: signals Dict
        if "signals" in runtime_data and runtime_data["signals"]:
            signals_dict = runtime_data["signals"]
            sample_cid = list(signals_dict.keys())[0]
            sample_df = signals_dict[sample_cid]
            columns = list(sample_df.columns)
            # Time 컬럼 제외한 실제 데이터 컬럼
            data_columns = [c for c in columns if c != "Time"]
            first_col = data_columns[0] if data_columns else "col"
            
            guide_parts.append(f"""### signals: Dict[{entity_col} → DataFrame]
- Type: Case-level independent time series data
- Entity identifier: `{entity_col}`
- Loaded cases: {list(signals_dict.keys())[:5]}{'...' if len(signals_dict) > 5 else ''} (total: {len(signals_dict)})
- **EXACT DataFrame columns: {columns}**
- Sample shape: {sample_df.shape}

⚠️ **CRITICAL: Use EXACT column names from the list above!**
Column names contain device prefixes like 'Solar8000/HR', NOT just 'HR'.

**Access Patterns (using actual column name):**
```python
# Single case - USE EXACT COLUMN NAME
signals['{sample_cid}']['{first_col}'].dropna().mean()

# All cases (RECOMMENDED for statistics)
case_stats = {{cid: df['{first_col}'].dropna().mean() for cid, df in signals.items()}}
overall_mean = np.nanmean(list(case_stats.values()))
```
""")
        
        # 기존 형식: df (하위호환)
        elif "df" in runtime_data and hasattr(runtime_data["df"], "columns"):
            df = runtime_data["df"]
            columns = list(df.columns)
            
            # df에서 가능한 entity 컬럼 찾기
            possible_entity_cols = [c for c in columns if 'id' in c.lower() or 'case' in c.lower()]
            detected_entity = possible_entity_cols[0] if possible_entity_cols else entity_col
            
            guide_parts.append(f"""### df: pandas DataFrame
- Type: Signal data (all cases concatenated)
- Shape: {df.shape}
- Columns: {columns}

**Access Patterns:**
```python
# Direct access
df['ColumnName'].mean()

# Group by entity (if available)
df.groupby('{detected_entity}')['ColumnName'].mean()
```
""")
        
        # Cohort
        if "cohort" in runtime_data and hasattr(runtime_data["cohort"], "columns"):
            cohort = runtime_data["cohort"]
            columns = list(cohort.columns)[:15]
            
            guide_parts.append(f"""
### cohort: pandas DataFrame
- Shape: {cohort.shape}
- Entity identifier: `{entity_col}`
- Columns: {columns}{'...' if len(cohort.columns) > 15 else ''}

**Access:**
```python
cohort[cohort['column'] == 'value']
case_list = cohort[cohort['filter'] == 'value']['{entity_col}'].astype(str).tolist()
```
""")
        
        guide_parts.append("""
## Analysis Guidelines
1. Assign final result to `result` variable
2. Handle NaN with dropna() or fillna()
""")
        
        runtime_data["_access_guide"] = "\n".join(guide_parts)
        return runtime_data
    
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
        """CodeExecutionEngine으로 분석 코드 생성 및 실행
        
        Returns:
            {"success": bool, "result": Any, "code": str, "error": str, "retry_count": int}
        """
        # 컴포넌트 초기화
        if self._code_execution_engine is None:
            self._init_code_gen_components(timeout, max_retries)
        
        # 동적 접근 가이드 추출 (LLM 프롬프트용)
        access_guide = runtime_data.pop("_access_guide", None)
        
        # ExecutionContext 생성
        exec_context = self._build_execution_context(runtime_data, data_summary)
        
        # CodeRequest 생성 (동적 가이드 + 메타데이터 기반 힌트 포함)
        request = self._build_code_request(
            query, exec_context, data_summary, 
            runtime_data=runtime_data, 
            access_guide=access_guide
        )
        
        # CodeExecutionEngine으로 생성 + 실행 (with retry)
        result = self._code_execution_engine.execute(
            request, 
            runtime_data,
            log_prefix="[Orchestrator] "
        )
        
        return result.to_dict()
    
    def _init_code_gen_components(self, timeout: int = 30, max_retries: int = 2):
        """CodeExecutionEngine 초기화"""
        from AnalysisAgent.src.code_gen import (
            CodeGenerator, 
            SandboxExecutor, 
            CodeExecutionEngine
        )
        from shared.llm import get_llm_client
        
        if self._llm_client is None:
            self._llm_client = get_llm_client()
        
        self._code_generator = CodeGenerator(llm_client=self._llm_client)
        self._sandbox = SandboxExecutor(timeout_seconds=timeout)
        self._code_execution_engine = CodeExecutionEngine(
            generator=self._code_generator,
            sandbox=self._sandbox,
            max_retries=max_retries
        )
    
    def _get_entity_column(self, runtime_data: Optional[Dict[str, Any]] = None) -> str:
        """
        entity_id 컬럼명 추출 (중복 제거용 헬퍼)
        
        Args:
            runtime_data: 런타임 데이터 (메타데이터 포함 가능)
        
        Returns:
            entity_id 컬럼명 (기본값: "id")
        """
        if self._data_context and self._data_context.entity_id_column:
            return self._data_context.entity_id_column
        if runtime_data and "_plan_metadata" in runtime_data:
            return runtime_data["_plan_metadata"].get("entity_id_column") or "id"
        return "id"
    
    def _build_execution_context(
        self, 
        runtime_data: Dict[str, Any],
        data_summary: Dict[str, Any]
    ):
        """CodeGen용 ExecutionContext 생성 (컬럼 설명 포함)"""
        from AnalysisAgent.src.models import ExecutionContext, DataSchema, ColumnDescription
        
        entity_col = self._get_entity_column(runtime_data)
        
        # ParameterRegistry에서 컬럼 설명 가져오기
        column_descriptions = {}
        if self._data_context:
            column_descriptions = self._data_context.get_column_descriptions()
        
        # 사용 가능한 변수 설명
        available_variables = {}
        data_schemas = {}
        
        # signals: Dict[entity_id, DataFrame]
        if "signals" in runtime_data and runtime_data["signals"]:
            signals_dict = runtime_data["signals"]
            case_count = len(signals_dict)
            sample_cid = list(signals_dict.keys())[0]
            sample_df = signals_dict[sample_cid]
            cols = list(sample_df.columns)
            
            available_variables["signals"] = (
                f"Dict[{entity_col}, DataFrame] - 케이스별 시계열 데이터, {case_count} cases"
            )
            
            # DataSchema with column descriptions 생성
            schema_col_descs = {}
            for col in cols:
                if col in column_descriptions:
                    cd = column_descriptions[col]
                    schema_col_descs[col] = ColumnDescription(
                        name=cd.get("name", col),
                        dtype=cd.get("dtype") or str(sample_df[col].dtype),
                        semantic_name=cd.get("semantic_name"),
                        unit=cd.get("unit"),
                        description=cd.get("description"),
                    )
                else:
                    # DB에 없는 컬럼은 기본 정보
                    schema_col_descs[col] = ColumnDescription(
                        name=col,
                        dtype=str(sample_df[col].dtype)
                    )
            
            # ParameterRegistry에 실제 데이터 정보 보강
            if self._data_context:
                self._data_context.enrich_param_registry_from_data(sample_df)
            
            data_schemas["signals_sample"] = DataSchema(
                name=f"signals[{entity_col}]",
                description="케이스별 시계열 DataFrame",
                columns=cols,
                dtypes={col: str(sample_df[col].dtype) for col in cols},
                shape=sample_df.shape,
                sample_rows=sample_df.head(2).to_dict(orient="records"),
                column_descriptions=schema_col_descs
            )
        
        if "cohort" in runtime_data and not runtime_data["cohort"].empty:
            cohort = runtime_data["cohort"]
            cols = list(cohort.columns)
            available_variables["cohort"] = (
                f"pandas DataFrame - Cohort 메타데이터, shape: {cohort.shape}"
            )
            
            # Cohort도 DataSchema 생성
            cohort_col_descs = {}
            for col in cols[:20]:  # cohort는 컬럼이 많을 수 있어 제한
                cohort_col_descs[col] = ColumnDescription(
                    name=col,
                    dtype=str(cohort[col].dtype)
                )
            
            data_schemas["cohort"] = DataSchema(
                name="cohort",
                description="Cohort 메타데이터 DataFrame",
                columns=cols[:20],  # 처음 20개만
                dtypes={col: str(cohort[col].dtype) for col in cols[:20]},
                shape=cohort.shape,
                sample_rows=cohort.head(2).to_dict(orient="records"),
                column_descriptions=cohort_col_descs
            )
        
        case_ids = runtime_data.get("case_ids", [])
        available_variables["case_ids"] = f"List[str] - {len(case_ids)} loaded entity IDs"
        
        total_cases = runtime_data.get("total_cases", len(case_ids))
        available_variables["total_cases"] = f"int - total entities: {total_cases}"
        
        param_keys = runtime_data.get("param_keys", [])
        available_variables["param_keys"] = f"List[str] - parameter keys: {param_keys}"
        
        return ExecutionContext(
            available_variables=available_variables,
            data_schemas=data_schemas,
            sample_data=None  # data_schemas가 있으면 sample_data 불필요
        )
    
    def _build_code_request(
        self, 
        query: str,
        exec_context,
        data_summary: Dict[str, Any],
        runtime_data: Optional[Dict[str, Any]] = None,
        access_guide: Optional[str] = None
    ):
        """CodeRequest 생성"""
        from AnalysisAgent.src.models import CodeRequest
        
        entity_col = self._get_entity_column(runtime_data)
        
        # 동적 접근 가이드 + 기존 힌트 결합
        hints_parts = []
        
        # 1. 동적 데이터 접근 가이드 (우선)
        if access_guide:
            hints_parts.append(access_guide)
        
        # 2. 질의 기반 추가 힌트
        if self.config.generate_hints:
            additional_hints = self._generate_hints(query, data_summary, runtime_data)
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
                f"Use signals[{entity_col}] to access individual case DataFrame"
            ]
        )
    
    def _generate_hints(
        self, 
        query: str, 
        data_summary: Dict[str, Any],
        runtime_data: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        질의 기반 추가 힌트 생성 (동적 가이드 보완용)
        
        Args:
            query: 사용자 질의
            data_summary: 데이터 요약
            runtime_data: 런타임 데이터 (메타데이터 포함)
        """
        hints = []
        query_lower = query.lower()
        entity_col = self._get_entity_column(runtime_data)
        
        # param_keys 추출 (실제 컬럼명)
        param_keys = data_summary.get("param_keys", [])
        first_param = param_keys[0] if param_keys else "col"
        
        # 키워드 기반 힌트 (signals Dict 기반 - 실제 컬럼명 사용)
        if "평균" in query_lower or "mean" in query_lower:
            hints.append("Mean calculation (per-case recommended):")
            hints.append("  case_means = {cid: df['col'].mean() for cid, df in signals.items()}")
            hints.append("  result = np.mean(list(case_means.values()))")
        
        if "비교" in query_lower or "그룹" in query_lower or "성별" in query_lower:
            hints.append("Group comparison: use cohort to filter cases by group")
            # 동적 entity_col 사용 (하드코딩 제거)
            hints.append(f"  target_cases = cohort[cohort['column'] == 'value']['{entity_col}'].astype(str).tolist()")
            hints.append("  filtered_signals = {cid: signals[cid] for cid in target_cases if cid in signals}")
        
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
    
    # =========================================================================
    # Map-Reduce Execution Mode
    # =========================================================================
    
    def run_mapreduce(
        self,
        query: str,
        batch_size: Optional[int] = None,
        max_workers: Optional[int] = None,
        max_retries: Optional[int] = None,
        timeout_seconds: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int, int], None]] = None,
        _extraction_result: Optional[Dict[str, Any]] = None,
    ) -> OrchestrationResult:
        """
        Map-Reduce 모드로 대용량 데이터 처리
        
        메모리 효율적인 배치 처리로 대량의 케이스를 분석합니다.
        LLM이 map_func와 reduce_func를 생성하고,
        배치 단위로 map_func를 실행한 후 최종 reduce_func로 집계합니다.
        
        Args:
            query: 자연어 질의
            batch_size: 배치당 케이스 수 (None이면 config.batch_size)
            max_workers: 병렬 워커 수 (None이면 config.mapreduce_max_workers)
            max_retries: 코드 생성 재시도 횟수
            timeout_seconds: 실행 타임아웃
            progress_callback: 진행 콜백 fn(batch_idx, total_batches, processed_count)
            _extraction_result: 이미 수행된 extraction 결과 (run_auto에서 전달, 외부 호출 금지)
        
        Returns:
            OrchestrationResult
        
        Example:
            # 대용량 데이터 처리
            config = OrchestratorConfig(
                execution_mode="mapreduce",
                max_signal_cases=0,  # 무제한
                batch_size=100,
            )
            orchestrator = Orchestrator(config=config)
            
            def on_progress(batch_idx, total, processed):
                print(f"Batch {batch_idx+1}/{total}: {processed} cases processed")
            
            result = orchestrator.run_mapreduce(
                "모든 환자의 SBP 평균을 단일 float 값으로 구해줘",
                progress_callback=on_progress
            )
        """
        start_time = time.time()
        
        batch_size = batch_size or self.config.batch_size
        max_workers = max_workers or self.config.mapreduce_max_workers
        max_retries = max_retries if max_retries is not None else self.config.max_retries
        timeout = timeout_seconds if timeout_seconds is not None else self.config.timeout_seconds
        
        logger.info(f"🚀 Starting Map-Reduce pipeline for query: '{query[:50]}...'")
        logger.info(f"   Settings: batch_size={batch_size}, max_workers={max_workers}")
        
        try:
            # Step 1: Extraction - 실행 계획 생성
            if _extraction_result is not None:
                logger.info("📝 Step 1/4: Reusing pre-computed extraction result")
                extraction_result = _extraction_result
            else:
                logger.info("📝 Step 1/4: Running ExtractionAgent...")
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
            logger.info(f"✅ Extraction complete (confidence: {extraction_confidence:.2f})")
            
            # Step 2: DataContext 초기화 및 메타데이터 로드
            logger.info("📦 Step 2/4: Initializing DataContext...")
            from shared.data.context import DataContext
            
            ctx = DataContext()
            ctx.load_from_plan(execution_plan, preload_cohort=True)
            self._data_context = ctx
            
            # 케이스 수 확인
            total_cases = len(ctx.get_available_case_ids())
            cohort = ctx.get_cohort()
            param_keys = ctx.get_available_parameters()
            
            logger.info(f"✅ DataContext ready: {total_cases} cases, params: {param_keys[:5]}...")
            
            if total_cases == 0:
                logger.error("❌ No cases available")
                return OrchestrationResult(
                    status="error",
                    error_message="No cases available for processing",
                    error_stage="data_load",
                    extraction_plan=execution_plan,
                    execution_time_ms=(time.time() - start_time) * 1000
                )
            
            # Step 3: Map-Reduce 코드 생성
            logger.info("🧬 Step 3/4: Generating Map-Reduce code...")
            mapreduce_result = self._generate_mapreduce_code(
                query=query,
                ctx=ctx,
                cohort=cohort,
                param_keys=param_keys,
                total_cases=total_cases,
                max_retries=max_retries,
            )
            
            if not mapreduce_result["success"]:
                logger.error(f"❌ Map-Reduce code generation failed: {mapreduce_result.get('error')}")
                return OrchestrationResult(
                    status="error",
                    error_message=f"Map-Reduce code generation failed: {mapreduce_result.get('error')}",
                    error_stage="code_generation",
                    extraction_plan=execution_plan,
                    generated_code=mapreduce_result.get("full_code"),
                    execution_time_ms=(time.time() - start_time) * 1000
                )
            
            map_code = mapreduce_result["map_code"]
            reduce_code = mapreduce_result["reduce_code"]
            full_code = mapreduce_result["full_code"]
            
            logger.info("✅ Map-Reduce code generated")
            
            # Step 4: Map-Reduce 실행
            logger.info("⚡ Step 4/4: Executing Map-Reduce...")
            execution_result = self._execute_mapreduce(
                ctx=ctx,
                cohort=cohort,
                map_code=map_code,
                reduce_code=reduce_code,
                param_keys=param_keys,
                batch_size=batch_size,
                max_workers=max_workers,
                timeout=timeout,
                progress_callback=progress_callback,
            )
            
            execution_time = (time.time() - start_time) * 1000
            
            if execution_result["success"]:
                logger.info(f"✅ Map-Reduce completed successfully in {execution_time:.0f}ms")
                return OrchestrationResult(
                    status="success",
                    result=execution_result["result"],
                    generated_code=full_code,
                    extraction_plan=execution_plan,
                    extraction_confidence=extraction_confidence,
                    data_summary=DataSummary(
                        signals_count=total_cases,
                        total_rows=execution_result.get("total_rows", 0),
                        cohort_shape=cohort.shape if cohort is not None else None,
                        param_keys=param_keys,
                    ).model_dump(),
                    execution_time_ms=execution_time,
                    metadata={
                        "mode": "mapreduce",
                        "batch_size": batch_size,
                        "total_batches": execution_result.get("total_batches", 0),
                        "map_success_count": execution_result.get("map_success_count", 0),
                        "map_error_count": execution_result.get("map_error_count", 0),
                    }
                )
            else:
                logger.error(f"❌ Map-Reduce execution failed: {execution_result.get('error')}")
                return OrchestrationResult(
                    status="error",
                    error_message=f"Map-Reduce execution failed: {execution_result.get('error')}",
                    error_stage="execution",
                    generated_code=full_code,
                    extraction_plan=execution_plan,
                    execution_time_ms=execution_time,
                    metadata={
                        "mode": "mapreduce",
                        "map_errors": execution_result.get("map_errors", []),
                    }
                )
                
        except Exception as e:
            logger.exception(f"❌ Map-Reduce pipeline error: {e}")
            return OrchestrationResult(
                status="error",
                error_message=str(e),
                error_stage="unknown",
                execution_time_ms=(time.time() - start_time) * 1000
            )
    
    def _generate_mapreduce_code(
        self,
        query: str,
        ctx: Any,
        cohort: Any,
        param_keys: List[str],
        total_cases: int,
        max_retries: int = 2,
    ) -> Dict[str, Any]:
        """
        Map-Reduce 코드 생성
        
        LLM을 호출하여 map_func와 reduce_func 코드를 생성합니다.
        
        Returns:
            {
                "success": bool,
                "map_code": str,
                "reduce_code": str,
                "full_code": str,
                "error": Optional[str]
            }
        """
        from AnalysisAgent.src.models.code_gen import MapReduceRequest
        from AnalysisAgent.src.code_gen.prompts import build_mapreduce_prompt
        
        # 샘플 데이터 준비 (첫 번째 케이스)
        entity_data_sample = None
        entity_data_dtypes = {}
        entity_data_columns = []
        
        sample_batch = None
        for batch in ctx.iter_cases_batch(batch_size=1, param_keys=param_keys):
            sample_batch = batch
            break
        
        # entity_id 컬럼 결정
        entity_id_column = ctx.entity_id_column or "id"
        
        # 샘플 DataFrame 추출
        sample_df = None
        if sample_batch and sample_batch["signals"]:
            sample_entity_id = sample_batch["entity_ids"][0]
            sample_df = sample_batch["signals"][sample_entity_id]
        
        # AnalysisContextBuilder를 사용하여 풍부한 데이터 컨텍스트 생성
        from shared.data.analysis_context import AnalysisContextBuilder
        context_builder = AnalysisContextBuilder(ctx)
        rich_context = context_builder.build_mapreduce_context(
            entity_sample=sample_df,
            cohort=cohort,
            total_cases=total_cases,
        )
        
        # 컨텍스트에서 필요한 정보 추출
        entity_data_columns = rich_context["entity_data_columns"]
        entity_data_dtypes = rich_context["entity_data_dtypes"]
        entity_data_sample = rich_context["entity_data_sample"]
        metadata_columns = rich_context["metadata_columns"]
        metadata_dtypes = rich_context["metadata_dtypes"]
        metadata_sample = rich_context["metadata_sample"]
        dataset_description = rich_context["dataset_description"]
        
        # MapReduceRequest 생성
        request = MapReduceRequest(
            task_description=query,
            expected_output="The result format depends on the query",
            hints="",
            dataset_description=dataset_description,
            entity_id_column=entity_id_column,
            total_entities=total_cases,
            entity_data_columns=entity_data_columns,
            entity_data_dtypes=entity_data_dtypes,
            entity_data_sample=entity_data_sample,
            metadata_columns=metadata_columns,
            metadata_dtypes=metadata_dtypes,
            metadata_sample=metadata_sample,
        )
        
        # 프롬프트 생성
        system_prompt, user_prompt = build_mapreduce_prompt(request)
        
        # 시스템 프롬프트와 유저 프롬프트 결합
        full_prompt = f"""[SYSTEM INSTRUCTIONS]
{system_prompt}

[USER REQUEST]
{user_prompt}"""
        
        # LLM 호출
        llm_client = self._get_llm_client()
        
        for attempt in range(max_retries + 1):
            try:
                logger.debug(f"Map-Reduce code generation attempt {attempt + 1}/{max_retries + 1}")
                
                response = llm_client.ask_text(full_prompt)
                
                # 응답 파싱
                parsed = self._parse_mapreduce_response(response)
                
                if parsed["success"]:
                    # 코드 검증 (컬럼 검증 포함)
                    validation_result = self._validate_mapreduce_code(
                        parsed["map_code"],
                        parsed["reduce_code"],
                        entity_data_columns=entity_data_columns,
                    )
                    
                    if validation_result["valid"]:
                        return {
                            "success": True,
                            "map_code": parsed["map_code"],
                            "reduce_code": parsed["reduce_code"],
                            "full_code": parsed["full_code"],
                        }
                    else:
                        # 검증 실패 시 수정 요청
                        logger.warning(f"Map-Reduce code validation failed: {validation_result['errors']}")
                        if attempt < max_retries:
                            # 에러 수정 프롬프트로 재시도
                            from AnalysisAgent.src.code_gen.prompts import build_mapreduce_error_fix_prompt
                            error_str = "\n".join(validation_result["errors"])
                            fix_prompt = build_mapreduce_error_fix_prompt(
                                previous_code=parsed["full_code"],
                                error_message=error_str,
                                request=request,
                                error_phase="validation",
                            )
                            full_prompt = f"{system_prompt}\n\n{fix_prompt}"
                            continue
                else:
                    logger.warning(f"Map-Reduce response parsing failed")
                    
            except Exception as e:
                logger.warning(f"Map-Reduce generation attempt {attempt + 1} failed: {e}")
                if attempt == max_retries:
                    return {"success": False, "error": str(e)}
        
        return {"success": False, "error": "Max retries exceeded"}
    
    def _parse_mapreduce_response(self, response: str) -> Dict[str, Any]:
        """
        LLM 응답에서 map_func와 reduce_func 코드 추출
        
        Expected format:
        ```python
        # MAP FUNCTION
        def map_func(entity_id, entity_data, metadata_row):
            ...
            return result
        
        # REDUCE FUNCTION
        def reduce_func(intermediate_results, full_metadata):
            ...
            return final_result
        ```
        """
        import re
        
        # 코드 블록 추출
        code_blocks = re.findall(r'```(?:python)?\s*([\s\S]*?)```', response)
        
        if not code_blocks:
            return {"success": False, "error": "No code blocks found"}
        
        full_code = "\n\n".join(code_blocks)
        
        # map_func 추출
        map_match = re.search(
            r'def\s+map_func\s*\([^)]*\)\s*(?:->.*?)?:\s*([\s\S]*?)(?=\ndef\s+|\Z)',
            full_code
        )
        
        # reduce_func 추출
        reduce_match = re.search(
            r'def\s+reduce_func\s*\([^)]*\)\s*(?:->.*?)?:\s*([\s\S]*?)(?=\ndef\s+|\Z)',
            full_code
        )
        
        if not map_match or not reduce_match:
            return {"success": False, "error": "Could not find map_func or reduce_func"}
        
        # 함수 전체 추출
        map_func_match = re.search(
            r'(def\s+map_func\s*\([^)]*\)\s*(?:->.*?)?:[\s\S]*?)(?=\ndef\s+|\Z)',
            full_code
        )
        reduce_func_match = re.search(
            r'(def\s+reduce_func\s*\([^)]*\)\s*(?:->.*?)?:[\s\S]*?)(?=\ndef\s+|\Z)',
            full_code
        )
        
        map_code = map_func_match.group(1).strip() if map_func_match else ""
        reduce_code = reduce_func_match.group(1).strip() if reduce_func_match else ""
        
        return {
            "success": True,
            "map_code": map_code,
            "reduce_code": reduce_code,
            "full_code": full_code,
        }
    
    def _validate_mapreduce_code(
        self,
        map_code: str,
        reduce_code: str,
        entity_data_columns: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Map-Reduce 코드 검증
        
        Args:
            map_code: map_func 코드
            reduce_code: reduce_func 코드
            entity_data_columns: 실제 entity_data DataFrame 컬럼 목록 (검증용)
        
        Returns:
            {"valid": bool, "errors": List[str], "warnings": List[str]}
        """
        import re
        
        errors = []
        warnings = []
        
        # 기본 구문 검사
        try:
            compile(map_code, "<map_func>", "exec")
        except SyntaxError as e:
            errors.append(f"map_func syntax error: {e}")
        
        try:
            compile(reduce_code, "<reduce_func>", "exec")
        except SyntaxError as e:
            errors.append(f"reduce_func syntax error: {e}")
        
        # 필수 요소 검사
        if "def map_func" not in map_code:
            errors.append("map_func definition not found")
        
        if "def reduce_func" not in reduce_code:
            errors.append("reduce_func definition not found")
        
        if "return" not in map_code:
            errors.append("map_func must have a return statement")
        
        if "return" not in reduce_code:
            errors.append("reduce_func must have a return statement")
        
        # 컬럼 참조 검증 (잘못된 컬럼 접근 패턴 감지)
        full_code = map_code + "\n" + reduce_code
        
        # 흔히 잘못 가정되는 컬럼명 패턴 (존재하지 않을 가능성이 높은 컬럼)
        common_assumed_columns = ['Time', 'Timestamp', 'DateTime', 'time', 'timestamp', 'datetime', 'Value', 'value']
        
        for col in common_assumed_columns:
            # 다양한 컬럼 접근 패턴 감지
            patterns = [
                rf"entity_data\[[\'\"]({col})[\'\"]\]",      # entity_data['Time']
                rf"entity_data\[\[.*[\'\"]({col})[\'\"]",    # entity_data[['Time']] 또는 entity_data[['A', 'Time']]
                rf"entity_data\.{col}\b",                    # entity_data.Time
                rf"\[[\'\"]({col})[\'\"]\]",                 # ['Time'] 일반 슬라이싱
                rf"\.loc\[.*[\'\"]({col})[\'\"]",            # .loc[..., 'Time']
                rf"\.iloc\[.*[\'\"]({col})[\'\"]",           # .iloc with Time (shouldn't happen but check)
            ]
            for pattern in patterns:
                if re.search(pattern, full_code, re.IGNORECASE):
                    # entity_data_columns가 제공되었고 해당 컬럼이 없으면 ERROR
                    if entity_data_columns and col not in entity_data_columns and col.lower() not in [c.lower() for c in entity_data_columns]:
                        errors.append(
                            f"🚨 Code references '{col}' column which does NOT exist! "
                            f"Available columns: {entity_data_columns}. "
                            f"Use entity_data.index for row position or iloc[] for slicing."
                        )
                        break
        
        # set_index('Time') 패턴 감지
        if re.search(r"set_index\s*\(\s*['\"]Time['\"]", full_code, re.IGNORECASE):
            if entity_data_columns and 'Time' not in entity_data_columns:
                errors.append(
                    "🚨 Code uses set_index('Time') but 'Time' column does NOT exist! "
                    f"Available columns: {entity_data_columns}. "
                    "Use entity_data.index instead."
                )
        
        # resample() 패턴 감지 (Time index가 필요)
        if re.search(r"\.resample\s*\(", full_code):
            if entity_data_columns and 'Time' not in entity_data_columns:
                errors.append(
                    "🚨 Code uses .resample() which requires DatetimeIndex. "
                    f"Available columns: {entity_data_columns}. "
                    "Use iloc[] slicing for segmentation instead: entity_data.iloc[start:end]"
                )
        
        # 경고 로깅
        for w in warnings:
            logger.warning(f"⚠️ Code validation warning: {w}")
        
        # 에러 로깅
        for e in errors:
            logger.error(f"❌ Code validation error: {e}")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }
    
    def _execute_mapreduce(
        self,
        ctx: Any,
        cohort: Any,
        map_code: str,
        reduce_code: str,
        param_keys: List[str],
        batch_size: int,
        max_workers: int,
        timeout: int,
        progress_callback: Optional[Callable[[int, int, int], None]] = None,
    ) -> Dict[str, Any]:
        """
        Map-Reduce 실행
        
        배치 단위로 데이터를 로드하고, map_func를 실행한 후,
        최종 reduce_func로 집계합니다.
        """
        from typing import Any as _Any, List as _List, Dict as _Dict, Optional as _Opt, Tuple as _Tup
        
        # SandboxExecutor를 사용하여 RestrictedPython 환경에서 함수 컴파일
        try:
            from AnalysisAgent.src.code_gen.sandbox import SandboxExecutor, HAS_RESTRICTED_PYTHON
            if HAS_RESTRICTED_PYTHON:
                from RestrictedPython import compile_restricted
            
            sandbox = self._sandbox or SandboxExecutor(timeout_seconds=timeout)
            exec_globals = sandbox._create_exec_globals({})
            
            exec_globals.update({
                "Any": _Any, "List": _List, "Dict": _Dict,
                "Optional": _Opt, "Tuple": _Tup,
            })
            
            # map_func 컴파일 (RestrictedPython 적용)
            map_globals = dict(exec_globals)
            if HAS_RESTRICTED_PYTHON:
                map_byte_code = compile_restricted(map_code, '<map_func>', 'exec')
                exec(map_byte_code, map_globals)
            else:
                exec(map_code, map_globals)
            map_func = map_globals.get("map_func")
            
            if not callable(map_func):
                return {"success": False, "error": "map_func is not callable"}
            
            # reduce_func 컴파일 (RestrictedPython 적용)
            reduce_globals = dict(exec_globals)
            if HAS_RESTRICTED_PYTHON:
                reduce_byte_code = compile_restricted(reduce_code, '<reduce_func>', 'exec')
                exec(reduce_byte_code, reduce_globals)
            else:
                exec(reduce_code, reduce_globals)
            reduce_func = reduce_globals.get("reduce_func")
            
            if not callable(reduce_func):
                return {"success": False, "error": "reduce_func is not callable"}
                
        except Exception as e:
            return {"success": False, "error": f"Code compilation error: {e}"}
        
        # Map Phase
        intermediate_results = []
        map_errors = []
        total_rows = 0
        processed_count = 0
        total_batches = 0
        map_success_count = 0
        map_error_count = 0
        skipped_empty_count = 0
        skipped_no_signal_count = 0
        first_error_logged = False
        
        logger.info(f"🗺️ Starting Map Phase (batch_size={batch_size})...")
        
        try:
            for batch in ctx.iter_cases_batch(
                batch_size=batch_size,
                param_keys=param_keys,
                apply_temporal=True,
                parallel=self.config.mapreduce_parallel,
                max_workers=max_workers,
            ):
                batch_idx = batch["batch_index"]
                total_batches = batch["total_batches"]
                
                logger.debug(f"  Processing batch {batch_idx + 1}/{total_batches} ({batch['batch_size']} cases)")
                
                # 배치 내 map_func 실행
                for entity_id in batch["entity_ids"]:
                    try:
                        entity_data = batch["signals"].get(entity_id)
                        
                        # 신호 데이터가 없는 케이스 건너뛰기 (정상 동작)
                        if entity_data is None:
                            skipped_no_signal_count += 1
                            continue
                        
                        if entity_data.empty:
                            skipped_empty_count += 1
                            continue
                        
                        # 요청한 컬럼이 있는지 확인
                        available_cols = list(entity_data.columns)
                        required_cols = [p for p in param_keys if p not in ['caseid', 'subjectid', 'id']]
                        missing_cols = [c for c in required_cols if c not in available_cols]
                        
                        if missing_cols and len(available_cols) <= 1:  # Time만 있거나 없는 경우
                            skipped_no_signal_count += 1
                            continue
                        
                        total_rows += len(entity_data)
                        
                        # 메타데이터 행 추출
                        metadata_row = ctx.get_batch_metadata_row(
                            batch["metadata_rows"],
                            entity_id
                        )
                        
                        # map_func 호출
                        result = map_func(entity_id, entity_data, metadata_row)
                        
                        if result is not None:
                            intermediate_results.append(result)
                            map_success_count += 1
                        
                    except Exception as e:
                        map_error_count += 1
                        error_str = str(e)
                        
                        # 첫 번째 에러에서 상세 정보 출력
                        if not first_error_logged:
                            logger.warning(f"  ⚠️ First map error for {entity_id}: {error_str}")
                            if entity_data is not None:
                                logger.warning(f"     entity_data columns: {list(entity_data.columns)}")
                                logger.warning(f"     entity_data shape: {entity_data.shape}")
                            first_error_logged = True
                        
                        map_errors.append({
                            "entity_id": entity_id,
                            "error": error_str,
                        })
                        
                        # 동일 에러가 너무 많으면 조기 종료
                        if map_error_count >= 100:
                            logger.error(f"❌ Too many map errors ({map_error_count}), stopping early")
                            break
                
                processed_count += batch["batch_size"]
                
                # 진행 콜백 호출
                if progress_callback:
                    progress_callback(batch_idx, total_batches, processed_count)
                
                # 에러가 너무 많으면 중단
                if map_error_count >= 100:
                    break
                
                # 배치 처리 후 메모리 정리
                del batch
                gc.collect()
            
            logger.info(f"✅ Map Phase complete:")
            logger.info(f"   Successes: {map_success_count}")
            logger.info(f"   Errors: {map_error_count}")
            logger.info(f"   Skipped (no signal): {skipped_no_signal_count}")
            logger.info(f"   Skipped (empty): {skipped_empty_count}")
            
        except Exception as e:
            return {"success": False, "error": f"Map Phase error: {e}", "map_errors": map_errors}
        
        # Reduce Phase
        logger.info(f"📊 Starting Reduce Phase ({len(intermediate_results)} intermediate results)...")
        
        try:
            final_result = reduce_func(intermediate_results, cohort)
            
            logger.info("✅ Reduce Phase complete")
            
            return {
                "success": True,
                "result": final_result,
                "total_rows": total_rows,
                "total_batches": total_batches,
                "map_success_count": map_success_count,
                "map_error_count": map_error_count,
                "map_errors": map_errors[:10],  # 처음 10개만
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"Reduce Phase error: {e}",
                "map_errors": map_errors[:10],
            }
    
    def _get_llm_client(self):
        """LLM 클라이언트 반환 (Lazy init)"""
        if self._llm_client is None:
            from shared.llm.client import get_llm_client
            self._llm_client = get_llm_client()
        return self._llm_client
    
    # =========================================================================
    # Auto Mode Selection
    # =========================================================================
    
    def run_auto(
        self,
        query: str,
        max_retries: Optional[int] = None,
        timeout_seconds: Optional[int] = None,
        **kwargs,
    ) -> OrchestrationResult:
        """
        자동 모드 선택 실행
        
        케이스 수에 따라 standard 또는 mapreduce 모드를 자동 선택합니다.
        
        Args:
            query: 자연어 질의
            max_retries: 코드 생성 재시도 횟수
            timeout_seconds: 실행 타임아웃
            **kwargs: 모드별 추가 인자 (batch_size, max_workers 등)
        
        Returns:
            OrchestrationResult
        
        Example:
            config = OrchestratorConfig(
                execution_mode="auto",
                mapreduce_threshold=100,
            )
            orchestrator = Orchestrator(config=config)
            result = orchestrator.run_auto("모든 환자의 심박수 평균을 단일 float 값으로 구해줘")
        """
        # 먼저 Extraction으로 케이스 수 파악
        extraction_result = self._run_extraction(query)
        
        if not extraction_result.get("execution_plan"):
            return OrchestrationResult(
                status="error",
                error_message="Extraction failed",
                error_stage="extraction",
            )
        
        execution_plan = extraction_result["execution_plan"]
        
        # DataContext로 케이스 수 확인
        from shared.data.context import DataContext
        ctx = DataContext()
        ctx.load_from_plan(execution_plan, preload_cohort=True)
        
        total_cases = len(ctx.get_available_case_ids())
        threshold = self.config.mapreduce_threshold
        
        logger.info(f"🔍 Auto mode: {total_cases} cases (threshold: {threshold})")
        
        # 모드 선택 — extraction 결과를 전달하여 재실행 방지
        if total_cases > threshold:
            logger.info(f"📊 Selecting Map-Reduce mode (cases > threshold)")
            return self.run_mapreduce(
                query=query,
                max_retries=max_retries,
                timeout_seconds=timeout_seconds,
                _extraction_result=extraction_result,
                **kwargs,
            )
        else:
            logger.info(f"⚡ Selecting Standard mode (cases <= threshold)")
            return self.run(
                query=query,
                max_retries=max_retries,
                timeout_seconds=timeout_seconds,
                _extraction_result=extraction_result,
            )

