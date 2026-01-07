"""코드 생성기 - LLM을 사용한 코드 생성만 담당

책임: LLM을 통한 코드 생성 + 검증.
실행은 Agent가 담당.
"""

import re
from typing import Optional, Protocol, runtime_checkable, TYPE_CHECKING

from ..models import CodeRequest, GenerationResult
from ..config import DEFAULT_CONFIG
from .validator import CodeValidator
from .prompts import build_prompt, build_error_fix_prompt

if TYPE_CHECKING:
    from ..config import GeneratorConfig


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
        # 1. 프롬프트 생성
        system_prompt, user_prompt = build_prompt(request)
        
        # 2. LLM 호출
        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        response = self.llm.ask_text(full_prompt, max_tokens=self.max_tokens)
        
        # 3. 코드 추출
        code = self._extract_code(response)
        
        # 4. 검증
        validation = self.validator.validate(code)
        
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
        system_prompt, user_prompt = build_error_fix_prompt(
            request, previous_code, error_message
        )
        
        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        response = self.llm.ask_text(full_prompt, max_tokens=self.max_tokens)
        
        code = self._extract_code(response)
        validation = self.validator.validate(code)
        
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

