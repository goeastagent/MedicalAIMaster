"""
AnalysisAgent 통합 테스트

Usage:
    cd /Users/goeastagent/products/MedicalAIMaster
    source venv/bin/activate
    python -m pytest AnalysisAgent/tests/test_analysis_agent.py -v
    
    # 또는 직접 실행
    python AnalysisAgent/tests/test_analysis_agent.py
"""

import sys
import os
import logging

# 프로젝트 루트 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
import pandas as pd
import numpy as np

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(name)s | %(levelname)s | %(message)s')


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_df():
    """샘플 DataFrame 생성"""
    np.random.seed(42)
    return pd.DataFrame({
        'caseid': [f'case_{i}' for i in range(100)],
        'HR': np.random.normal(75, 15, 100),
        'SpO2': np.random.normal(97, 2, 100),
        'Age': np.random.randint(20, 80, 100),
        'Gender': np.random.choice(['M', 'F'], 100),
    })


@pytest.fixture
def agent_config():
    """Rule-based planning 설정 (LLM 호출 없이 테스트)"""
    from AnalysisAgent.src import AnalysisAgentConfig
    return AnalysisAgentConfig(
        use_llm_planning=False,
        use_cache=True,
        code_gen_max_retries=2,
        code_gen_timeout=30,
    )


@pytest.fixture
def agent(agent_config):
    """AnalysisAgent 인스턴스"""
    from AnalysisAgent.src import AnalysisAgent
    return AnalysisAgent(config=agent_config)


# =============================================================================
# ContextBuilder Tests
# =============================================================================

class TestContextBuilder:
    """ContextBuilder 테스트"""
    
    def test_build_from_dataframes(self, sample_df):
        """DataFrame에서 AnalysisContext 생성"""
        from AnalysisAgent.src import ContextBuilder
        
        builder = ContextBuilder()
        context = builder.build_from_dataframes(
            dataframes={"df": sample_df},
            descriptions={"df": "Test data"}
        )
        
        assert "df" in context.data_schemas
        assert context.data_schemas["df"].shape == (100, 5)
        assert len(context.data_schemas["df"].columns) == 5
    
    def test_column_type_inference(self, sample_df):
        """컬럼 타입 추론"""
        from AnalysisAgent.src import ContextBuilder
        
        builder = ContextBuilder()
        context = builder.build_from_dataframes({"df": sample_df})
        
        schema = context.data_schemas["df"]
        columns = {c.name: c.dtype for c in schema.columns}
        
        assert columns["HR"] == "numeric"
        assert columns["SpO2"] == "numeric"
        assert columns["Gender"] == "categorical"
    
    def test_statistics_computation(self, sample_df):
        """통계 정보 계산"""
        from AnalysisAgent.src import ContextBuilder
        
        builder = ContextBuilder(compute_statistics=True)
        context = builder.build_from_dataframes({"df": sample_df})
        
        hr_col = next(c for c in context.data_schemas["df"].columns if c.name == "HR")
        
        assert hr_col.statistics is not None
        assert "mean" in hr_col.statistics
        assert "std" in hr_col.statistics
        assert "min" in hr_col.statistics
        assert "max" in hr_col.statistics


# =============================================================================
# Planner Tests
# =============================================================================

class TestAnalysisPlanner:
    """AnalysisPlanner 테스트"""
    
    def test_plan_simple_mean(self, sample_df):
        """단순 평균 계획 (rule-based)"""
        from AnalysisAgent.src import ContextBuilder, AnalysisPlanner
        
        builder = ContextBuilder()
        context = builder.build_from_dataframes({"df": sample_df})
        
        planner = AnalysisPlanner()
        result = planner.plan_simple("HR의 평균을 구해줘", context)
        
        assert result.success
        assert result.plan is not None
        assert result.plan.analysis_type == "mean"
        assert len(result.plan.steps) >= 1
    
    def test_plan_simple_correlation(self, sample_df):
        """상관관계 계획 (rule-based)"""
        from AnalysisAgent.src import ContextBuilder, AnalysisPlanner
        
        builder = ContextBuilder()
        context = builder.build_from_dataframes({"df": sample_df})
        
        planner = AnalysisPlanner()
        result = planner.plan_simple("HR과 SpO2의 상관관계를 분석해줘", context)
        
        assert result.success
        assert result.plan.analysis_type == "correlation"
    
    def test_plan_validation(self, sample_df):
        """계획 유효성 검증"""
        from AnalysisAgent.src import ContextBuilder, AnalysisPlanner
        
        builder = ContextBuilder()
        context = builder.build_from_dataframes({"df": sample_df})
        
        planner = AnalysisPlanner()
        # rule-based에서 매칭되는 쿼리 사용
        result = planner.plan_simple("HR의 평균을 계산해줘", context)
        
        if result.success:
            errors = result.plan.validate()
            assert len(errors) == 0  # 유효한 계획


# =============================================================================
# Executor Tests
# =============================================================================

class TestStepExecutor:
    """StepExecutor 테스트"""
    
    def test_execute_simple_plan(self, sample_df):
        """단순 계획 실행"""
        from AnalysisAgent.src import (
            ContextBuilder, AnalysisPlanner, StepExecutor
        )
        
        # Context & Plan
        builder = ContextBuilder()
        context = builder.build_from_dataframes({"df": sample_df})
        
        planner = AnalysisPlanner()
        result = planner.plan_simple("Calculate mean of HR", context)
        
        assert result.success
        
        # Execute
        executor = StepExecutor(max_retries=2, timeout_seconds=30)
        state = executor.execute_plan(result.plan, {"df": sample_df})
        
        assert not state.has_errors()
        assert state.get_final_result() is not None
    
    def test_execute_with_tool(self, sample_df):
        """Tool을 사용한 실행"""
        from AnalysisAgent.src import (
            StepExecutor, ToolRegistry, BaseTool, ToolMetadata,
            StepInput, StepOutput, PlanStep, AnalysisPlan
        )
        
        # Custom tool 정의
        class MeanTool(BaseTool):
            @property
            def metadata(self):
                return ToolMetadata(
                    name="compute_mean",
                    description="Calculate mean",
                    output_type="numeric",
                    tags=["statistics"]
                )
            
            def execute(self, step_input: StepInput) -> StepOutput:
                df = step_input.get_dataframe()
                col = step_input.input_columns[0] if step_input.input_columns else "HR"
                return StepOutput.success(
                    step_id=step_input.step_id,
                    result=df[col].mean(),
                    result_type="numeric",
                    output_key=f"{step_input.step_id}_result"
                )
        
        # Registry에 등록
        registry = ToolRegistry()
        registry.clear()
        registry.register(MeanTool())
        
        # Plan 생성
        plan = AnalysisPlan(
            query="Calculate mean",
            analysis_type="statistics",
            steps=[
                PlanStep(
                    id="step_1",
                    order=0,
                    action="compute_mean",
                    description="Calculate mean HR",
                    execution_mode="tool",
                    tool_name="compute_mean",
                    inputs=["df"],
                    input_columns=["HR"],
                    output_key="mean_result",
                    expected_output_type="numeric"
                )
            ]
        )
        
        # Execute
        executor = StepExecutor(tool_registry=registry)
        state = executor.execute_plan(plan, {"df": sample_df})
        
        assert not state.has_errors()
        assert isinstance(state.get_final_result(), float)


# =============================================================================
# ResultStore Tests
# =============================================================================

class TestResultStore:
    """ResultStore 테스트"""
    
    def test_save_and_get(self):
        """결과 저장 및 조회"""
        from AnalysisAgent.src import ResultStore, AnalysisResult
        
        store = ResultStore(max_size=10)
        store.clear()
        
        result = AnalysisResult.create_success(
            query="Test query",
            final_result=42.0,
            final_result_type="numeric",
            plan={},
            step_results=[],
            execution_time_ms=100.0
        )
        
        store.save(result)
        
        retrieved = store.get(result.id)
        assert retrieved is not None
        assert retrieved.final_result == 42.0
    
    def test_cache_hit(self):
        """캐시 히트"""
        from AnalysisAgent.src import ResultStore, AnalysisResult
        
        store = ResultStore(enable_cache=True)
        store.clear()
        
        result = AnalysisResult.create_success(
            query="Calculate mean",
            final_result=75.0,
            final_result_type="numeric",
            plan={},
            step_results=[],
            execution_time_ms=100.0,
            input_summary={"dataframes": {"df": {"shape": [100, 5]}}}
        )
        
        store.save(result)
        
        # 같은 쿼리로 캐시 조회
        cached = store.get_cached(
            "Calculate mean",
            {"dataframes": {"df": {"shape": [100, 5]}}}
        )
        
        assert cached is not None
        assert cached.final_result == 75.0
    
    def test_cache_miss(self):
        """캐시 미스"""
        from AnalysisAgent.src import ResultStore, AnalysisResult
        
        store = ResultStore(enable_cache=True)
        store.clear()
        
        result = AnalysisResult.create_success(
            query="Query A",
            final_result=1.0,
            final_result_type="numeric",
            plan={},
            step_results=[],
            execution_time_ms=100.0
        )
        
        store.save(result)
        
        # 다른 쿼리
        cached = store.get_cached("Query B", {})
        assert cached is None
    
    def test_lru_eviction(self):
        """LRU 캐시 제거"""
        from AnalysisAgent.src import ResultStore, AnalysisResult
        
        store = ResultStore(max_size=3)
        store.clear()
        
        # 3개 저장
        for i in range(3):
            result = AnalysisResult.create_success(
                query=f"Query {i}",
                final_result=float(i),
                final_result_type="numeric",
                plan={},
                step_results=[],
                execution_time_ms=100.0
            )
            store.save(result)
        
        assert len(store) == 3
        
        # 4번째 저장 → 1번째 제거
        result = AnalysisResult.create_success(
            query="Query 3",
            final_result=3.0,
            final_result_type="numeric",
            plan={},
            step_results=[],
            execution_time_ms=100.0
        )
        store.save(result)
        
        assert len(store) == 3


# =============================================================================
# AnalysisAgent Integration Tests
# =============================================================================

class TestAnalysisAgentIntegration:
    """AnalysisAgent 통합 테스트"""
    
    def test_analyze_dataframes_mean(self, agent, sample_df):
        """DataFrame 평균 분석"""
        result = agent.analyze_dataframes(
            query="Calculate mean of HR",
            dataframes={"df": sample_df}
        )
        
        assert result.status == "success"
        assert result.final_result is not None
        assert isinstance(result.final_result, (int, float))
    
    def test_analyze_dataframes_with_cache(self, agent, sample_df):
        """캐시 동작 확인"""
        # 첫 번째 호출
        result1 = agent.analyze_dataframes(
            query="Calculate mean of SpO2",
            dataframes={"df": sample_df}
        )
        
        assert result1.status == "success"
        
        # 두 번째 호출 (캐시)
        result2 = agent.analyze_dataframes(
            query="Calculate mean of SpO2",
            dataframes={"df": sample_df}
        )
        
        assert result2.status == "cached"
        assert result2.final_result == result1.final_result
    
    def test_analyze_multiple_queries(self, agent, sample_df):
        """다양한 쿼리 테스트"""
        queries = [
            "HR의 평균을 구해줘",
            "SpO2의 표준편차를 계산해줘",
            "HR과 SpO2의 상관관계를 분석해줘",
        ]
        
        for query in queries:
            result = agent.analyze_dataframes(
                query=query,
                dataframes={"df": sample_df}
            )
            
            # 성공 또는 캐시 (에러 아님)
            assert result.status in ["success", "cached"], f"Failed: {query}, Error: {result.error}"
    
    def test_get_stats(self, agent, sample_df):
        """Agent stats 확인"""
        # 분석 실행 (rule-based에서 매칭되는 쿼리)
        agent.analyze_dataframes(
            query="HR의 평균을 구해줘",
            dataframes={"df": sample_df}
        )
        
        stats = agent.get_stats()
        
        assert "result_store" in stats
        assert "tool_count" in stats
        assert "config" in stats
    
    def test_clear_cache(self, agent, sample_df):
        """캐시 클리어"""
        # 분석 실행 (rule-based에서 매칭되는 쿼리)
        agent.analyze_dataframes(
            query="Age의 평균을 구해줘",
            dataframes={"df": sample_df}
        )
        
        # 캐시 클리어
        cleared = agent.clear_cache()
        assert cleared >= 0
        
        # 다시 실행하면 캐시 미스
        result = agent.analyze_dataframes(
            query="Age의 평균을 구해줘",
            dataframes={"df": sample_df}
        )
        
        # 캐시 클리어 후이므로 success (cached 아님)
        assert result.status == "success"


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    # pytest 실행 또는 직접 실행
    print("=" * 60)
    print("🧪 AnalysisAgent 테스트 실행")
    print("=" * 60)
    
    # pytest로 실행
    exit_code = pytest.main([__file__, "-v", "--tb=short"])
    
    sys.exit(exit_code)
