"""코드 생성기 - LLM을 사용한 코드 생성만 담당

책임: LLM을 통한 코드 생성 + 검증.
실행은 Agent가 담당.

지원 모드:
- 기본 모드: 단일 코드 블록 생성 (result 변수에 결과 저장)
- Map-Reduce 모드: map_func, reduce_func 두 함수 생성 (대용량 처리)
"""

import re
import ast
import logging
from typing import Optional, Protocol, runtime_checkable, Tuple, List, TYPE_CHECKING

from ..models import CodeRequest, GenerationResult, MapReduceRequest, MapReduceGenerationResult
from ..config import DEFAULT_CONFIG
from .validator import CodeValidator
from .prompts import (
    build_prompt, 
    build_error_fix_prompt,
    build_mapreduce_prompt,
    build_mapreduce_error_fix_prompt,
)

if TYPE_CHECKING:
    from ..config import GeneratorConfig

logger = logging.getLogger("AnalysisAgent.code_gen.generator")


@runtime_checkable
class LLMClientProtocol(Protocol):
    """LLM 클라이언트 인터페이스
    
    shared.llm.client의 AbstractLLMClient와 호환.
    """
    def ask_text(self, prompt: str, max_tokens: int = None) -> str:
        """텍스트 응답 요청"""
        ...


class CodeGenerator:
    """코드 생성기 - 생성과 검증만 담당
    
    책임:
    - LLM을 통한 코드 생성
    - 생성된 코드 검증
    
    사용하지 않음:
    - 코드 실행 (Agent/Executor 담당)
    - 데이터 접근 (Agent가 runtime_data 준비)
    
    Example:
        from shared.llm import get_llm_client
        
        generator = CodeGenerator(llm_client=get_llm_client())
        
        request = CodeRequest(
            task_description="심박수 평균 계산",
            expected_output="float",
            execution_context=context
        )
        
        result = generator.generate(request)
        
        if result.is_valid:
            print(f"Generated code:\\n{result.code}")
        else:
            print(f"Validation errors: {result.validation_errors}")
    """
    
    def __init__(
        self,
        llm_client: LLMClientProtocol,
        validator: Optional[CodeValidator] = None,
        max_tokens: int = None,
        config: Optional["GeneratorConfig"] = None,
    ):
        """
        Args:
            llm_client: LLM 클라이언트 (shared.llm.client)
            validator: CodeValidator (없으면 기본 생성)
            max_tokens: LLM 응답 최대 토큰 수
            config: GeneratorConfig (개별 파라미터보다 우선)
        """
        _config = config or DEFAULT_CONFIG.generator
        
        self.llm = llm_client
        self.validator = validator or CodeValidator()
        self.max_tokens = max_tokens if max_tokens is not None else _config.max_tokens
        self.max_retries = _config.max_retries
    
    def generate(self, request: CodeRequest) -> GenerationResult:
        """코드 생성 + 검증
        
        Args:
            request: 코드 생성 요청
        
        Returns:
            GenerationResult with code and validation info
        """
        logger.info(f"🔧 Generating code for: '{request.task_description[:50]}...'")
        
        # 1. 프롬프트 생성
        system_prompt, user_prompt = build_prompt(request)
        logger.debug(f"   Prompt length: {len(system_prompt) + len(user_prompt)} chars")
        
        # 2. LLM 호출
        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        logger.debug("   Calling LLM...")
        response = self.llm.ask_text(full_prompt, max_tokens=self.max_tokens)
        logger.debug(f"   LLM response length: {len(response)} chars")
        
        # 3. 코드 추출
        code = self._extract_code(response)
        logger.debug(f"   Extracted code:\n{code[:200]}{'...' if len(code) > 200 else ''}")
        
        # 4. 검증 (사용 가능한 변수 목록 전달)
        available_vars = set(request.execution_context.available_variables.keys())
        validation = self.validator.validate(code, available_variables=available_vars)
        
        if validation.is_valid:
            logger.info("✅ Code generated and validated successfully")
        else:
            logger.warning(f"⚠️ Code validation failed: {validation.errors}")
        
        return GenerationResult(
            code=code,
            is_valid=validation.is_valid,
            validation_errors=validation.errors,
            validation_warnings=validation.warnings
        )
    
    def generate_with_fix(
        self,
        request: CodeRequest,
        previous_code: str,
        error_message: str
    ) -> GenerationResult:
        """에러 정보를 바탕으로 코드 재생성
        
        Args:
            request: 원본 요청
            previous_code: 실패한 이전 코드
            error_message: 에러 메시지
        
        Returns:
            GenerationResult
        """
        logger.info(f"🔄 Regenerating code to fix error: {error_message[:50]}...")
        
        system_prompt, user_prompt = build_error_fix_prompt(
            request, previous_code, error_message
        )
        
        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        response = self.llm.ask_text(full_prompt, max_tokens=self.max_tokens)
        
        code = self._extract_code(response)
        
        # 검증 (사용 가능한 변수 목록 전달)
        available_vars = set(request.execution_context.available_variables.keys())
        validation = self.validator.validate(code, available_variables=available_vars)
        
        if validation.is_valid:
            logger.info("✅ Fixed code generated successfully")
        else:
            logger.warning(f"⚠️ Fixed code validation failed: {validation.errors}")
        
        return GenerationResult(
            code=code,
            is_valid=validation.is_valid,
            validation_errors=validation.errors,
            validation_warnings=validation.warnings
        )
    
    def _extract_code(self, response: str) -> str:
        """LLM 응답에서 코드 블록 추출
        
        다음 형식을 지원:
        - ```python ... ```
        - ``` ... ```
        - 순수 코드 (코드 블록 없이)
        
        Args:
            response: LLM 응답 텍스트
        
        Returns:
            추출된 Python 코드
        """
        if not response:
            return ""
        
        # 1. ```python ... ``` 블록 찾기
        pattern = r'```python\s*(.*?)\s*```'
        matches = re.findall(pattern, response, re.DOTALL)
        
        if matches:
            return matches[0].strip()
        
        # 2. ``` ... ``` 블록 찾기 (언어 지정 없이)
        pattern = r'```\s*(.*?)\s*```'
        matches = re.findall(pattern, response, re.DOTALL)
        
        if matches:
            # 첫 번째 줄이 언어 이름일 수 있으므로 체크
            code = matches[0].strip()
            first_line = code.split('\n')[0].strip().lower()
            if first_line in ('python', 'py'):
                code = '\n'.join(code.split('\n')[1:])
            return code.strip()
        
        # 3. 코드 블록 없으면 전체를 코드로 간주
        # 단, 명확한 설명 텍스트는 제거 시도
        lines = response.strip().split('\n')
        code_lines = []
        in_code = False
        
        for line in lines:
            stripped = line.strip()
            # Python 코드처럼 보이는 줄 감지
            if (stripped.startswith(('import ', 'from ', 'result', 'df', 'np.', 'pd.'))
                or '=' in stripped
                or stripped.startswith('#')
                or stripped == ''
                or in_code):
                code_lines.append(line)
                in_code = True
        
        if code_lines:
            return '\n'.join(code_lines).strip()
        
        return response.strip()
    
    # =========================================================================
    # Map-Reduce 패턴 코드 생성 (대용량 데이터 처리)
    # =========================================================================
    
    def generate_mapreduce(
        self, 
        request: MapReduceRequest
    ) -> MapReduceGenerationResult:
        """Map-Reduce 패턴의 map_func, reduce_func 코드 생성
        
        대용량 데이터셋을 배치 처리할 때 사용.
        LLM이 두 개의 함수를 생성:
        - map_func: 각 엔티티별 처리
        - reduce_func: 중간 결과 집계
        
        Args:
            request: MapReduceRequest (태스크, 데이터 스키마 정보)
        
        Returns:
            MapReduceGenerationResult:
                - full_code: 전체 생성 코드
                - map_code: 추출된 map_func 정의
                - reduce_code: 추출된 reduce_func 정의
                - is_valid: 검증 통과 여부
                - validation_errors: 에러 목록
        
        Example:
            request = MapReduceRequest(
                task_description="각 환자별 평균 심박수 계산",
                expected_output="{patient_id: mean_hr} 형태의 dict",
                entity_id_column="caseid",
                total_entities=6384,
                entity_data_columns=["Time", "HR", "SpO2"],
            )
            
            result = generator.generate_mapreduce(request)
            
            if result.is_valid:
                print(f"Map function:\\n{result.map_code}")
                print(f"Reduce function:\\n{result.reduce_code}")
        """
        logger.info(f"🔧 Generating Map-Reduce code for: '{request.task_description[:50]}...'")
        logger.info(f"   Total entities: {request.total_entities}")
        
        # 1. 프롬프트 생성
        system_prompt, user_prompt = build_mapreduce_prompt(request)
        prompt_length = len(system_prompt) + len(user_prompt)
        logger.debug(f"   Prompt length: {prompt_length} chars")
        
        # 2. LLM 호출
        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        logger.debug("   Calling LLM for Map-Reduce code...")
        response = self.llm.ask_text(full_prompt, max_tokens=self.max_tokens)
        logger.debug(f"   LLM response length: {len(response)} chars")
        
        # 3. 코드 추출
        full_code = self._extract_code(response)
        logger.debug(f"   Extracted code:\n{full_code[:300]}{'...' if len(full_code) > 300 else ''}")
        
        # 4. map_func, reduce_func 분리 추출
        map_code, reduce_code = self._extract_mapreduce_functions(full_code)
        
        # 5. 검증
        validation_errors, validation_warnings = self._validate_mapreduce_code(
            full_code, map_code, reduce_code
        )
        
        is_valid = len(validation_errors) == 0
        
        if is_valid:
            logger.info("✅ Map-Reduce code generated and validated successfully")
        else:
            logger.warning(f"⚠️ Map-Reduce code validation failed: {validation_errors}")
        
        return MapReduceGenerationResult(
            full_code=full_code,
            map_code=map_code,
            reduce_code=reduce_code,
            is_valid=is_valid,
            validation_errors=validation_errors,
            validation_warnings=validation_warnings,
        )
    
    def generate_mapreduce_with_fix(
        self,
        request: MapReduceRequest,
        previous_code: str,
        error_message: str,
        error_phase: str = "unknown",
    ) -> MapReduceGenerationResult:
        """에러 정보를 바탕으로 Map-Reduce 코드 재생성
        
        Args:
            request: 원본 요청
            previous_code: 실패한 이전 코드
            error_message: 에러 메시지
            error_phase: 에러 발생 단계 ("map", "reduce", "validation")
        
        Returns:
            MapReduceGenerationResult
        """
        logger.info(f"🔄 Regenerating Map-Reduce code to fix error: {error_message[:50]}...")
        logger.info(f"   Error phase: {error_phase}")
        
        # 에러 수정 프롬프트 생성
        system_prompt, user_prompt = build_mapreduce_error_fix_prompt(
            request, previous_code, error_message, error_phase
        )
        
        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        response = self.llm.ask_text(full_prompt, max_tokens=self.max_tokens)
        
        full_code = self._extract_code(response)
        map_code, reduce_code = self._extract_mapreduce_functions(full_code)
        
        validation_errors, validation_warnings = self._validate_mapreduce_code(
            full_code, map_code, reduce_code
        )
        
        is_valid = len(validation_errors) == 0
        
        if is_valid:
            logger.info("✅ Fixed Map-Reduce code generated successfully")
        else:
            logger.warning(f"⚠️ Fixed Map-Reduce code validation failed: {validation_errors}")
        
        return MapReduceGenerationResult(
            full_code=full_code,
            map_code=map_code,
            reduce_code=reduce_code,
            is_valid=is_valid,
            validation_errors=validation_errors,
            validation_warnings=validation_warnings,
        )
    
    def _extract_mapreduce_functions(self, code: str) -> Tuple[str, str]:
        """코드에서 map_func, reduce_func 정의 추출
        
        AST를 사용하여 함수 정의를 정확하게 추출.
        
        Args:
            code: 전체 생성 코드
        
        Returns:
            (map_code, reduce_code) 튜플
            함수를 찾지 못하면 빈 문자열 반환
        """
        if not code.strip():
            return "", ""
        
        map_code = ""
        reduce_code = ""
        
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            logger.warning(f"   SyntaxError parsing code: {e}")
            # Syntax error인 경우 정규식으로 시도
            return self._extract_functions_regex(code)
        
        # AST에서 함수 정의 찾기
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef):
                # 함수 소스 코드 추출
                func_source = self._get_function_source(code, node)
                
                if node.name == "map_func":
                    map_code = func_source
                    logger.debug(f"   Found map_func: {len(func_source)} chars")
                elif node.name == "reduce_func":
                    reduce_code = func_source
                    logger.debug(f"   Found reduce_func: {len(func_source)} chars")
        
        return map_code, reduce_code
    
    def _get_function_source(self, code: str, func_node: ast.FunctionDef) -> str:
        """AST 노드에서 함수 소스 코드 추출
        
        Args:
            code: 전체 코드
            func_node: 함수 정의 AST 노드
        
        Returns:
            함수 소스 코드 문자열
        """
        lines = code.split('\n')
        
        # 시작 줄 (0-indexed)
        start_line = func_node.lineno - 1
        
        # 종료 줄 찾기: 다음 함수 또는 코드 끝
        end_line = len(lines)
        
        # 데코레이터 포함
        if func_node.decorator_list:
            start_line = func_node.decorator_list[0].lineno - 1
        
        # 함수 끝 찾기 (end_lineno 사용 가능한 경우)
        if hasattr(func_node, 'end_lineno') and func_node.end_lineno:
            end_line = func_node.end_lineno
        else:
            # Python 3.7 이하: 들여쓰기로 추정
            func_indent = len(lines[start_line]) - len(lines[start_line].lstrip())
            for i in range(start_line + 1, len(lines)):
                line = lines[i]
                stripped = line.strip()
                if stripped and not stripped.startswith('#'):
                    current_indent = len(line) - len(line.lstrip())
                    if current_indent <= func_indent and stripped:
                        # 같거나 더 적은 들여쓰기 = 함수 끝
                        end_line = i
                        break
        
        return '\n'.join(lines[start_line:end_line])
    
    def _extract_functions_regex(self, code: str) -> Tuple[str, str]:
        """정규식으로 함수 추출 (fallback)
        
        AST 파싱 실패 시 사용.
        
        Args:
            code: 전체 코드
        
        Returns:
            (map_code, reduce_code) 튜플
        """
        map_code = ""
        reduce_code = ""
        
        # map_func 찾기
        map_pattern = r'(def\s+map_func\s*\([^)]*\)\s*(?:->.*?)?:\s*(?:""".*?"""|\'\'\'.+?\'\'\')?\s*(?:.*?(?=\ndef\s|\Z)))'
        map_matches = re.findall(map_pattern, code, re.DOTALL)
        if map_matches:
            map_code = map_matches[0].strip()
        
        # reduce_func 찾기
        reduce_pattern = r'(def\s+reduce_func\s*\([^)]*\)\s*(?:->.*?)?:\s*(?:""".*?"""|\'\'\'.+?\'\'\')?\s*(?:.*?(?=\ndef\s|\Z)))'
        reduce_matches = re.findall(reduce_pattern, code, re.DOTALL)
        if reduce_matches:
            reduce_code = reduce_matches[0].strip()
        
        return map_code, reduce_code
    
    def _validate_mapreduce_code(
        self, 
        full_code: str, 
        map_code: str, 
        reduce_code: str
    ) -> Tuple[List[str], List[str]]:
        """Map-Reduce 코드 검증
        
        Args:
            full_code: 전체 코드
            map_code: map_func 코드
            reduce_code: reduce_func 코드
        
        Returns:
            (errors, warnings) 튜플
        """
        errors = []
        warnings = []
        
        # 1. 함수 존재 여부
        if not map_code:
            errors.append("map_func not found in generated code")
        if not reduce_code:
            errors.append("reduce_func not found in generated code")
        
        if errors:
            return errors, warnings
        
        # 2. 기본 Validator로 전체 코드 검증 (금지 패턴 등)
        # available_variables는 Map-Reduce에서 동적으로 제공되므로 빈 set
        validation = self.validator.validate(full_code, available_variables=set())
        
        # Validator 에러 중 NameError 관련은 무시 (entity_data 등은 런타임에 제공)
        for err in validation.errors:
            err_lower = err.lower()
            # 변수 정의 관련 에러는 무시 (런타임 변수)
            if "not defined" not in err_lower and "undefined" not in err_lower:
                errors.append(err)
        
        warnings.extend(validation.warnings)
        
        # 3. 함수 시그니처 검증
        map_sig_errors = self._validate_function_signature(
            map_code, "map_func", 
            expected_params=["entity_id", "entity_data", "metadata_row"]
        )
        reduce_sig_errors = self._validate_function_signature(
            reduce_code, "reduce_func",
            expected_params=["intermediate_results", "full_metadata"]
        )
        
        # 시그니처 에러는 경고로 처리 (파라미터 이름은 다를 수 있음)
        warnings.extend(map_sig_errors)
        warnings.extend(reduce_sig_errors)
        
        return errors, warnings
    
    def _validate_function_signature(
        self, 
        func_code: str, 
        func_name: str,
        expected_params: List[str]
    ) -> List[str]:
        """함수 시그니처 검증
        
        Args:
            func_code: 함수 코드
            func_name: 함수 이름
            expected_params: 예상 파라미터 이름 목록
        
        Returns:
            경고 목록
        """
        warnings = []
        
        try:
            tree = ast.parse(func_code)
        except SyntaxError:
            return [f"{func_name}: SyntaxError in function code"]
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                # 파라미터 수 확인
                actual_params = [arg.arg for arg in node.args.args]
                
                if len(actual_params) != len(expected_params):
                    warnings.append(
                        f"{func_name}: Expected {len(expected_params)} parameters, "
                        f"got {len(actual_params)}"
                    )
                
                # 파라미터 이름 확인 (힌트)
                for expected, actual in zip(expected_params, actual_params):
                    if expected != actual:
                        warnings.append(
                            f"{func_name}: Parameter '{actual}' (expected '{expected}')"
                        )
                
                break
        
        return warnings

