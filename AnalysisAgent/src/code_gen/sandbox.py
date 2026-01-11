"""샌드박스 실행기 - 안전한 코드 실행만 담당

책임: 코드 실행만 담당. 생성/검증은 하지 않음.
Agent가 검증된 코드와 runtime_data를 전달하면 실행 후 결과 반환.

지원 모드:
- 기본 모드: 단일 코드 블록 실행
- Map-Reduce 모드: map_func / reduce_func 함수 실행
"""

import sys
import time
import traceback
import threading
import logging
from io import StringIO
from typing import Dict, Any, Optional, Tuple, List, TYPE_CHECKING
from contextlib import contextmanager

from ..models import ExecutionResult
from ..config import DEFAULT_CONFIG

if TYPE_CHECKING:
    from ..config import SandboxConfig
    import pandas as pd

logger = logging.getLogger("AnalysisAgent.code_gen.sandbox")

# RestrictedPython 사용 여부
try:
    from RestrictedPython import compile_restricted
    from RestrictedPython.Guards import (
        safe_builtins,
        guarded_iter_unpack_sequence,
        safer_getattr,
    )
    from RestrictedPython.Eval import default_guarded_getiter, default_guarded_getitem
    from RestrictedPython.PrintCollector import PrintCollector
    HAS_RESTRICTED_PYTHON = True
except ImportError:
    HAS_RESTRICTED_PYTHON = False


def _flexible_iter_unpack_sequence(it, spec, _getiter_):
    """범용 tuple unpacking guard - 다양한 타입 지원
    
    RestrictedPython의 guarded_iter_unpack_sequence는 일부 객체에서 실패함:
    - scipy.stats 결과 객체 (PearsonRResult, SpearmanrResult 등)
    - numpy 특수 반환 타입
    - NamedTuple 유사 객체
    
    이 함수는 다음 순서로 unpacking 시도:
    1. tuple/list로 직접 변환
    2. __iter__ 메서드 사용
    3. 인덱싱 사용 (Result 객체 등)
    4. 기존 guarded_iter_unpack_sequence fallback
    
    Args:
        it: unpacking할 객체
        spec: 예상 요소 수 (int 또는 tuple)
        _getiter_: iterator guard 함수
    
    Returns:
        unpacking된 값들의 tuple
    """
    # spec이 int면 단순 개수, tuple이면 (min, max) 또는 복잡한 스펙
    if isinstance(spec, int):
        expected_len = spec
    elif isinstance(spec, tuple) and len(spec) >= 1:
        expected_len = spec[0] if isinstance(spec[0], int) else len(spec)
    else:
        expected_len = None
    
    # 방법 1: 이미 tuple/list인 경우 직접 사용
    if isinstance(it, (tuple, list)):
        result = tuple(it)
        if expected_len is not None and len(result) != expected_len:
            raise ValueError(f"not enough values to unpack (expected {expected_len}, got {len(result)})")
        return result
    
    # 방법 2: scipy.stats Result 객체 등 특수 타입 처리
    # 이들은 __iter__가 있지만 RestrictedPython guard와 충돌
    obj_type = type(it).__name__
    if 'Result' in obj_type or hasattr(it, '_fields') or hasattr(it, 'statistic'):
        try:
            # 인덱싱으로 접근 시도
            if expected_len is not None:
                result = tuple(it[i] for i in range(expected_len))
                return result
            # 길이를 알 수 없으면 list로 변환 시도
            result = tuple(list(it))
            return result
        except (TypeError, IndexError):
            pass
    
    # 방법 3: numpy array 또는 ndarray 처리
    try:
        import numpy as np
        if isinstance(it, np.ndarray):
            result = tuple(it.tolist() if it.ndim > 0 else [it.item()])
            if expected_len is not None and len(result) != expected_len:
                raise ValueError(f"not enough values to unpack (expected {expected_len}, got {len(result)})")
            return result
    except ImportError:
        pass
    
    # 방법 4: __iter__를 통한 일반적인 iterable 처리
    try:
        # 직접 tuple 변환 시도 (guard 우회)
        result = tuple(it)
        if expected_len is not None and len(result) != expected_len:
            raise ValueError(f"not enough values to unpack (expected {expected_len}, got {len(result)})")
        return result
    except TypeError:
        pass
    
    # 방법 5: 기존 guarded_iter_unpack_sequence fallback
    if HAS_RESTRICTED_PYTHON:
        return guarded_iter_unpack_sequence(it, spec, _getiter_)
    
    raise TypeError(f"cannot unpack non-iterable {type(it).__name__} object")


class ExecutionTimeoutError(Exception):
    """실행 시간 초과 에러"""
    pass


class SandboxExecutor:
    """안전한 코드 실행 환경
    
    책임:
    - 코드 실행만 담당
    - 타임아웃 처리
    - 안전한 실행 환경 구성
    
    사용하지 않음:
    - 코드 생성 (Generator 담당)
    - 코드 검증 (Validator 담당)
    
    Example:
        executor = SandboxExecutor(timeout_seconds=30)
        
        runtime_data = {
            "df": signal_dataframe,
            "cohort": cohort_dataframe,
            "case_ids": ["1", "2", "3"],
        }
        
        result = executor.execute(
            code="result = df['HR'].mean()",
            runtime_data=runtime_data
        )
        
        if result.success:
            print(f"Result: {result.result}")
        else:
            print(f"Error: {result.error}")
    """
    
    def __init__(
        self,
        timeout_seconds: int = None,
        max_output_size: int = None,
        capture_stdout: bool = None,
        config: Optional["SandboxConfig"] = None,
    ):
        """
        Args:
            timeout_seconds: 최대 실행 시간 (초)
            max_output_size: 결과 크기 제한 (bytes)
            capture_stdout: print 출력 캡처 여부
            config: SandboxConfig (개별 파라미터보다 우선)
        """
        _config = config or DEFAULT_CONFIG.sandbox
        
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else _config.timeout_seconds
        self.max_output_size = max_output_size if max_output_size is not None else _config.max_result_size
        self.capture_stdout = capture_stdout if capture_stdout is not None else _config.capture_stdout
    
    def execute(
        self,
        code: str,
        runtime_data: Dict[str, Any],
    ) -> ExecutionResult:
        """코드 실행
        
        Args:
            code: 실행할 Python 코드 (이미 검증된 코드여야 함)
            runtime_data: 실행 시 사용할 변수들
                {
                    "df": pandas.DataFrame (Signal 데이터),
                    "cohort": pandas.DataFrame (Cohort 데이터),
                    "case_ids": List[str],
                    "param_keys": List[str],
                    ...
                }
        
        Returns:
            ExecutionResult: 실행 결과
        """
        start_time = time.time()
        stdout_capture = StringIO() if self.capture_stdout else None
        
        logger.info("⚙️ Executing generated code in sandbox...")
        logger.debug(f"   Code preview: {code[:100]}{'...' if len(code) > 100 else ''}")
        
        try:
            # 실행 환경 구성
            exec_globals = self._create_exec_globals(runtime_data)
            
            # stdout 캡처 설정
            if self.capture_stdout:
                old_stdout = sys.stdout
                sys.stdout = stdout_capture
            
            try:
                # 타임아웃 적용하여 실행
                result, printed_output = self._execute_with_timeout(code, exec_globals)
                
                execution_time_ms = (time.time() - start_time) * 1000
                
                # 결과 크기 체크
                result = self._truncate_result(result)
                
                # stdout 결합 (sys.stdout 캡처 + RestrictedPython PrintCollector)
                stdout_output = ""
                if stdout_capture:
                    stdout_output = stdout_capture.getvalue()
                if printed_output:
                    stdout_output = (stdout_output + printed_output).strip()
                
                logger.info(f"✅ Code executed successfully ({execution_time_ms:.1f}ms)")
                logger.debug(f"   Result type: {type(result).__name__}")
                
                return ExecutionResult(
                    success=True,
                    result=result,
                    execution_time_ms=execution_time_ms,
                    stdout=stdout_output if stdout_output else None,
                )
            
            finally:
                if self.capture_stdout:
                    sys.stdout = old_stdout
        
        except ExecutionTimeoutError:
            logger.error(f"⏰ Execution timed out after {self.timeout_seconds}s")
            return ExecutionResult(
                success=False,
                error=f"Execution timed out after {self.timeout_seconds} seconds",
                error_type="timeout",
                execution_time_ms=self.timeout_seconds * 1000,
            )
        
        except MemoryError:
            logger.error("💾 Memory limit exceeded")
            return ExecutionResult(
                success=False,
                error="Memory limit exceeded",
                error_type="memory",
            )
        
        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.error(f"❌ Runtime error: {error_msg}")
            
            return ExecutionResult(
                success=False,
                error=error_msg,
                error_type="runtime",
                execution_time_ms=execution_time_ms,
            )
    
    def _create_exec_globals(self, runtime_data: Dict[str, Any]) -> Dict[str, Any]:
        """실행 환경의 globals 구성
        
        안전한 builtins + 허용된 모듈 + 런타임 데이터
        """
        # 안전한 builtins
        allowed_builtins = self._get_safe_builtins()
        
        # 허용된 모듈 로드
        allowed_modules = self._get_allowed_modules()
        
        exec_globals = {
            '__builtins__': allowed_builtins,
            **allowed_modules,
        }
        
        # RestrictedPython guards 추가
        if HAS_RESTRICTED_PYTHON:
            exec_globals['_getiter_'] = default_guarded_getiter
            exec_globals['_getitem_'] = default_guarded_getitem
            exec_globals['_getattr_'] = safer_getattr
            
            # write guard (item assignment: obj[key] = value)
            def guarded_write(obj):
                return obj
            exec_globals['_write_'] = guarded_write
            
            # 커스텀 unpack sequence guard - 더 많은 타입 지원
            exec_globals['_iter_unpack_sequence_'] = _flexible_iter_unpack_sequence
            exec_globals['_unpack_sequence_'] = lambda it, spec, _getiter_: _flexible_iter_unpack_sequence(it, spec, _getiter_)
            
            # print guard - PrintCollector 인스턴스 사용
            exec_globals['_print_'] = PrintCollector
        
        # 런타임 데이터 추가 (덮어쓰기 허용)
        exec_globals.update(runtime_data)
        
        return exec_globals
    
    def _get_safe_builtins(self) -> Dict[str, Any]:
        """안전한 built-in 함수들"""
        if HAS_RESTRICTED_PYTHON:
            # RestrictedPython의 safe_builtins 기반
            builtins = dict(safe_builtins)
        else:
            # 직접 정의
            builtins = {}
        
        # 공통으로 허용하는 builtins
        allowed = {
            # 상수
            'True': True,
            'False': False,
            'None': None,
            
            # 타입
            'bool': bool,
            'int': int,
            'float': float,
            'str': str,
            'list': list,
            'dict': dict,
            'tuple': tuple,
            'set': set,
            'frozenset': frozenset,
            'type': type,
            
            # 수학
            'abs': abs,
            'round': round,
            'min': min,
            'max': max,
            'sum': sum,
            'pow': pow,
            'divmod': divmod,
            
            # 이터레이션
            'len': len,
            'range': range,
            'enumerate': enumerate,
            'zip': zip,
            'map': map,
            'filter': filter,
            'sorted': sorted,
            'reversed': reversed,
            'all': all,
            'any': any,
            
            # 기타 유틸
            'isinstance': isinstance,
            'issubclass': issubclass,
            'hasattr': hasattr,
            'getattr': getattr,
            'slice': slice,
            'iter': iter,
            'next': next,
            'callable': callable,
            'repr': repr,
            'hash': hash,
            'id': id,
            
            # 출력 (디버깅용)
            'print': print,
        }
        
        builtins.update(allowed)
        return builtins
    
    def _get_allowed_modules(self) -> Dict[str, Any]:
        """허용된 모듈 로드"""
        modules = {}
        
        # pandas
        try:
            import pandas as pd
            modules['pd'] = pd
            modules['pandas'] = pd
        except ImportError:
            pass
        
        # numpy
        try:
            import numpy as np
            modules['np'] = np
            modules['numpy'] = np
        except ImportError:
            pass
        
        # scipy.stats
        try:
            from scipy import stats
            import scipy
            modules['stats'] = stats
            modules['scipy'] = scipy
        except ImportError:
            pass
        
        # math
        import math
        modules['math'] = math
        
        # datetime
        import datetime
        modules['datetime'] = datetime
        
        # statistics (표준 라이브러리)
        import statistics
        modules['statistics'] = statistics
        
        return modules
    
    def _execute_with_timeout(self, code: str, exec_globals: Dict) -> tuple:
        """타임아웃을 적용하여 코드 실행
        
        Unix: signal.alarm 사용
        Windows/기타: threading 사용 (완벽하지 않음)
        
        Returns:
            tuple: (result, printed_output)
        """
        result_container = {'result': None, 'error': None, 'printed': None}
        
        def run_code():
            try:
                if HAS_RESTRICTED_PYTHON:
                    # RestrictedPython 6.x: compile_restricted는 직접 code 객체 반환
                    # 에러 발생 시 SyntaxError 예외 발생
                    byte_code = compile_restricted(code, '<generated>', 'exec')
                    exec(byte_code, exec_globals)
                else:
                    exec(code, exec_globals)
                
                result_container['result'] = exec_globals.get('result')
                
                # RestrictedPython PrintCollector 출력 수집
                if '_print_' in exec_globals and 'printed' in exec_globals:
                    result_container['printed'] = exec_globals.get('printed', '')
            except Exception as e:
                result_container['error'] = e
        
        # Unix에서는 signal.alarm이 더 정확하지만,
        # 크로스 플랫폼 호환성을 위해 threading 사용
        thread = threading.Thread(target=run_code)
        thread.start()
        thread.join(timeout=self.timeout_seconds)
        
        if thread.is_alive():
            # 타임아웃 - 스레드가 아직 실행 중
            # 참고: Python에서는 스레드를 강제 종료할 수 없음
            # 실제 프로덕션에서는 별도 프로세스 사용 권장
            raise ExecutionTimeoutError()
        
        if result_container['error']:
            raise result_container['error']
        
        return result_container['result'], result_container['printed']
    
    def _truncate_result(self, result: Any) -> Any:
        """결과 크기 제한
        
        너무 큰 결과는 잘라서 반환
        """
        if result is None:
            return None
        
        # DataFrame인 경우 크기 체크
        try:
            import pandas as pd
            if isinstance(result, pd.DataFrame):
                if len(result) > 10000:
                    # 너무 큰 DataFrame은 요약 정보만 반환
                    return {
                        '_type': 'DataFrame',
                        '_truncated': True,
                        'shape': result.shape,
                        'columns': list(result.columns),
                        'head': result.head(10).to_dict(),
                        'tail': result.tail(10).to_dict(),
                    }
        except ImportError:
            pass
        
        # 문자열인 경우 길이 제한
        if isinstance(result, str):
            if len(result) > self.max_output_size:
                return result[:self.max_output_size] + f"... (truncated, total {len(result)} chars)"
        
        # 리스트/배열인 경우 길이 제한
        if isinstance(result, (list, tuple)):
            if len(result) > 1000:
                return {
                    '_type': type(result).__name__,
                    '_truncated': True,
                    'length': len(result),
                    'first_10': list(result[:10]),
                    'last_10': list(result[-10:]),
                }
        
        return result
    
    # =========================================================================
    # Map-Reduce 패턴 실행 메서드 (대용량 데이터 처리)
    # =========================================================================
    
    def execute_map(
        self,
        map_code: str,
        entity_id: str,
        entity_data: "pd.DataFrame",
        metadata_row: "pd.Series",
    ) -> Tuple[bool, Any, Optional[str]]:
        """map_func 실행 (단일 엔티티 처리)
        
        map_func를 정의하고 호출하여 중간 결과 반환.
        
        Args:
            map_code: map_func 정의 코드
            entity_id: 엔티티 식별자
            entity_data: 엔티티 데이터 DataFrame
            metadata_row: 엔티티 메타데이터 Series
        
        Returns:
            (success, result, error_message) 튜플
            - success: 실행 성공 여부
            - result: map_func 반환값 (실패 시 None)
            - error_message: 에러 메시지 (성공 시 None)
        
        Example:
            success, result, error = executor.execute_map(
                map_code="def map_func(entity_id, entity_data, metadata_row):\\n    return entity_data['HR'].mean()",
                entity_id="patient_001",
                entity_data=signal_df,
                metadata_row=patient_info,
            )
        """
        import pandas as pd
        
        # map_func 정의 + 호출 코드 조합
        exec_code = f"""
{map_code}

# Call map_func with provided arguments
_map_result = map_func(entity_id, entity_data, metadata_row)
result = _map_result
"""
        
        # 런타임 데이터 준비
        runtime_data = {
            "entity_id": entity_id,
            "entity_data": entity_data if entity_data is not None else pd.DataFrame(),
            "metadata_row": metadata_row if metadata_row is not None else pd.Series(),
        }
        
        # 실행
        exec_result = self.execute(exec_code, runtime_data)
        
        if exec_result.success:
            return True, exec_result.result, None
        else:
            return False, None, exec_result.error
    
    def execute_reduce(
        self,
        reduce_code: str,
        intermediate_results: List[Any],
        full_metadata: "pd.DataFrame",
    ) -> Tuple[bool, Any, Optional[str]]:
        """reduce_func 실행 (중간 결과 집계)
        
        reduce_func를 정의하고 호출하여 최종 결과 반환.
        
        Args:
            reduce_code: reduce_func 정의 코드
            intermediate_results: map_func 결과 리스트 (None 값 제외됨)
            full_metadata: 전체 메타데이터 DataFrame
        
        Returns:
            (success, result, error_message) 튜플
            - success: 실행 성공 여부
            - result: reduce_func 반환값 (실패 시 None)
            - error_message: 에러 메시지 (성공 시 None)
        
        Example:
            success, final_result, error = executor.execute_reduce(
                reduce_code="def reduce_func(intermediate_results, full_metadata):\\n    return sum(intermediate_results) / len(intermediate_results)",
                intermediate_results=[72.5, 68.3, 75.1, ...],
                full_metadata=cohort_df,
            )
        """
        import pandas as pd
        
        # None 값 필터링
        filtered_results = [r for r in intermediate_results if r is not None]
        
        # reduce_func 정의 + 호출 코드 조합
        exec_code = f"""
{reduce_code}

# Call reduce_func with provided arguments
_reduce_result = reduce_func(intermediate_results, full_metadata)
result = _reduce_result
"""
        
        # 런타임 데이터 준비
        runtime_data = {
            "intermediate_results": filtered_results,
            "full_metadata": full_metadata if full_metadata is not None else pd.DataFrame(),
        }
        
        # 실행
        exec_result = self.execute(exec_code, runtime_data)
        
        if exec_result.success:
            return True, exec_result.result, None
        else:
            return False, None, exec_result.error
    
    def execute_mapreduce_batch(
        self,
        map_code: str,
        reduce_code: str,
        batch_data: List[Dict[str, Any]],
        full_metadata: "pd.DataFrame",
        parallel: bool = True,
        max_workers: int = 4,
    ) -> Tuple[List[Any], List[Dict[str, str]], float]:
        """배치 단위 Map-Reduce 실행
        
        배치 내 모든 엔티티에 대해 map_func 실행 후 결과 반환.
        reduce_func는 호출하지 않음 (Orchestrator에서 최종 집계).
        
        Args:
            map_code: map_func 정의 코드
            reduce_code: reduce_func 정의 코드 (현재 미사용)
            batch_data: 배치 데이터 리스트
                [{"entity_id": str, "entity_data": DataFrame, "metadata_row": Series}, ...]
            full_metadata: 전체 메타데이터 DataFrame
            parallel: 병렬 처리 여부
            max_workers: 병렬 워커 수
        
        Returns:
            (results, errors, elapsed_ms) 튜플
            - results: map_func 결과 리스트 (None 포함 가능)
            - errors: 에러 정보 리스트 [{"entity_id": str, "error": str}, ...]
            - elapsed_ms: 실행 시간 (밀리초)
        
        Example:
            batch = [
                {"entity_id": "p1", "entity_data": df1, "metadata_row": m1},
                {"entity_id": "p2", "entity_data": df2, "metadata_row": m2},
            ]
            results, errors, elapsed = executor.execute_mapreduce_batch(
                map_code, reduce_code, batch, cohort_df
            )
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        start_time = time.time()
        results = []
        errors = []
        
        if parallel and len(batch_data) > 1:
            # 병렬 실행
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {}
                
                for item in batch_data:
                    future = executor.submit(
                        self.execute_map,
                        map_code,
                        item["entity_id"],
                        item["entity_data"],
                        item["metadata_row"],
                    )
                    futures[future] = item["entity_id"]
                
                for future in as_completed(futures):
                    entity_id = futures[future]
                    try:
                        success, result, error = future.result()
                        if success:
                            results.append(result)
                        else:
                            results.append(None)
                            errors.append({"entity_id": entity_id, "error": error})
                    except Exception as e:
                        results.append(None)
                        errors.append({"entity_id": entity_id, "error": str(e)})
        else:
            # 순차 실행
            for item in batch_data:
                success, result, error = self.execute_map(
                    map_code,
                    item["entity_id"],
                    item["entity_data"],
                    item["metadata_row"],
                )
                if success:
                    results.append(result)
                else:
                    results.append(None)
                    errors.append({"entity_id": item["entity_id"], "error": error})
        
        elapsed_ms = (time.time() - start_time) * 1000
        
        return results, errors, elapsed_ms

