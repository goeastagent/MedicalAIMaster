"""코드 검증기 - 보안 검사만 담당

책임: 생성된 코드의 보안 검증만 담당.
생성/실행은 하지 않음.
"""

import re
import ast
from typing import List, Tuple, Optional, TYPE_CHECKING

from ..models import ValidationResult
from ..config import DEFAULT_CONFIG, ValidatorConfig

if TYPE_CHECKING:
    from ..config import ValidatorConfig


class CodeValidator:
    """생성된 코드의 보안 검증
    
    책임:
    - 금지 패턴 검사
    - 금지 모듈 import 검사
    - 구문 검사
    - result 변수 존재 확인
    
    사용하지 않음:
    - 코드 생성 (Generator 담당)
    - 코드 실행 (Executor 담당)
    
    Example:
        validator = CodeValidator()
        result = validator.validate("result = df['HR'].mean()")
        
        if result.is_valid:
            print("Code is safe to execute")
        else:
            print(f"Errors: {result.errors}")
    """
    
    def __init__(self, config: Optional["ValidatorConfig"] = None):
        """
        Args:
            config: 검증 설정 (None이면 기본 설정 사용)
        """
        self._config = config or DEFAULT_CONFIG.validator
        
        # Config에서 설정 로드
        self.FORBIDDEN_PATTERNS = self._config.forbidden_patterns
        self.FORBIDDEN_MODULES = self._config.forbidden_modules
        self.ALLOWED_MODULES = self._config.allowed_modules
    
    def validate(self, code: str) -> ValidationResult:
        """코드 검증
        
        Args:
            code: 검증할 Python 코드
        
        Returns:
            ValidationResult with is_valid, errors, warnings
        """
        errors = []
        warnings = []
        
        # 빈 코드 체크
        if not code or not code.strip():
            errors.append("Empty code")
            return ValidationResult(is_valid=False, errors=errors)
        
        # 1. 구문 검사
        syntax_error = self._check_syntax(code)
        if syntax_error:
            errors.append(f"Syntax error: {syntax_error}")
            return ValidationResult(is_valid=False, errors=errors)
        
        # 2. 금지 패턴 검사
        pattern_errors = self._check_forbidden_patterns(code)
        errors.extend(pattern_errors)
        
        # 3. Import 검사
        import_errors, import_warnings = self._check_imports(code)
        errors.extend(import_errors)
        warnings.extend(import_warnings)
        
        # 4. result 변수 존재 확인 (경고만)
        if not self._has_result_variable(code):
            warnings.append("No 'result' variable assignment found")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )
    
    def _check_syntax(self, code: str) -> Optional[str]:
        """구문 검사"""
        try:
            ast.parse(code)
            return None
        except SyntaxError as e:
            return f"Line {e.lineno}: {e.msg}"
    
    def _check_forbidden_patterns(self, code: str) -> List[str]:
        """금지 패턴 검사"""
        errors = []
        for pattern, description in self.FORBIDDEN_PATTERNS:
            if re.search(pattern, code, re.IGNORECASE):
                errors.append(f"Forbidden pattern detected: {description}")
        return errors
    
    def _check_imports(self, code: str) -> Tuple[List[str], List[str]]:
        """Import 검사"""
        errors = []
        warnings = []
        
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module = alias.name.split('.')[0]
                        if module in self.FORBIDDEN_MODULES:
                            errors.append(f"Forbidden module: {module}")
                        elif module not in self.ALLOWED_MODULES:
                            warnings.append(f"Unknown module: {module}")
                
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        module = node.module.split('.')[0]
                        if module in self.FORBIDDEN_MODULES:
                            errors.append(f"Forbidden module: {module}")
                        elif module not in self.ALLOWED_MODULES:
                            warnings.append(f"Unknown module: {module}")
        except:
            pass  # 구문 에러는 이미 체크됨
        
        return errors, warnings
    
    def _has_result_variable(self, code: str) -> bool:
        """result 변수 할당 확인"""
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == 'result':
                            return True
                # Named expression (walrus operator): result := ...
                elif isinstance(node, ast.NamedExpr):
                    if isinstance(node.target, ast.Name) and node.target.id == 'result':
                        return True
        except:
            pass
        return False

