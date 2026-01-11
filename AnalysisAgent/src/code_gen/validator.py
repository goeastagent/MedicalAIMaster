"""코드 검증기 - 보안 검사 + 변수 참조 검증

책임: 생성된 코드의 보안 검증 및 변수 유효성 검사.
생성/실행은 하지 않음.
"""

import re
import ast
from typing import List, Tuple, Optional, Set, TYPE_CHECKING

from ..models import ValidationResult
from ..config import DEFAULT_CONFIG, ValidatorConfig

if TYPE_CHECKING:
    from ..config import ValidatorConfig


# 기본 제공 변수/함수 (Python 내장 + 분석용)
BUILTIN_NAMES = {
    # Python 내장
    'True', 'False', 'None', 'print', 'len', 'range', 'enumerate', 'zip',
    'list', 'dict', 'set', 'tuple', 'str', 'int', 'float', 'bool', 'type',
    'min', 'max', 'sum', 'abs', 'round', 'sorted', 'reversed', 'any', 'all',
    'isinstance', 'hasattr', 'getattr', 'setattr',
    # 분석용 패키지 (import 없이 사용 가능)
    'pd', 'np', 'scipy', 'stats',
    # 결과 변수
    'result',
}


class CodeValidator:
    """생성된 코드의 보안 검증 + 변수 유효성 검사
    
    책임:
    - 금지 패턴 검사
    - 금지 모듈 import 검사
    - 구문 검사
    - result 변수 존재 확인
    - [NEW] 변수 참조 유효성 검사 (사용 가능한 변수만 참조하는지)
    
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
        
        # 변수 검증 포함
        result = validator.validate(
            "result = signals['1']['HR'].mean()",
            available_variables={'signals', 'case_ids'}
        )
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
    
    def validate(
        self, 
        code: str,
        available_variables: Optional[Set[str]] = None
    ) -> ValidationResult:
        """코드 검증
        
        Args:
            code: 검증할 Python 코드
            available_variables: 사용 가능한 변수 이름 집합 (선택적)
                - 제공되면 이 변수들만 참조 가능
                - None이면 변수 참조 검증 스킵
        
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
        
        # 5. 변수 참조 검증 (available_variables 제공 시)
        if available_variables is not None:
            undefined_vars = self._check_undefined_variables(code, available_variables)
            if undefined_vars:
                # 에러 대신 경고로 처리 (LLM이 자체 변수를 만들 수 있으므로)
                # 단, 흔한 혼동 패턴은 에러로 처리
                common_confusions = {'signals', 'df', 'cohort', 'data', 'case_ids'}
                critical_undefined = undefined_vars & common_confusions - available_variables
                
                if critical_undefined:
                    errors.append(
                        f"Undefined variables that should be available: {critical_undefined}. "
                        f"Available variables are: {available_variables}"
                    )
                elif undefined_vars:
                    warnings.append(f"Potentially undefined variables: {undefined_vars}")
        
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
    
    def _check_undefined_variables(
        self, 
        code: str, 
        available_variables: Set[str]
    ) -> Set[str]:
        """코드에서 정의되지 않은 변수 참조를 찾습니다.
        
        Args:
            code: Python 코드
            available_variables: 사용 가능한 변수 이름 집합
        
        Returns:
            정의되지 않은 변수 이름 집합
        """
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return set()
        
        # 코드 내에서 정의된 변수 수집
        defined_in_code = set()
        
        # 사용된 변수 수집
        used_variables = set()
        
        for node in ast.walk(tree):
            # 변수 정의 (할당)
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    defined_in_code.update(self._extract_names_from_target(target))
            
            # for 루프 변수
            elif isinstance(node, ast.For):
                defined_in_code.update(self._extract_names_from_target(node.target))
            
            # with 문 변수
            elif isinstance(node, ast.With):
                for item in node.items:
                    if item.optional_vars:
                        defined_in_code.update(
                            self._extract_names_from_target(item.optional_vars)
                        )
            
            # comprehension 변수
            elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                for generator in node.generators:
                    defined_in_code.update(
                        self._extract_names_from_target(generator.target)
                    )
            
            # Named expression (walrus operator)
            elif isinstance(node, ast.NamedExpr):
                if isinstance(node.target, ast.Name):
                    defined_in_code.add(node.target.id)
            
            # 변수 사용 (Load context)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                used_variables.add(node.id)
        
        # 모든 유효한 변수 = 내장 + 사용가능 + 코드에서 정의
        all_valid = BUILTIN_NAMES | available_variables | defined_in_code
        
        # 정의되지 않은 변수 = 사용된 변수 - 유효한 변수
        undefined = used_variables - all_valid
        
        return undefined
    
    def _extract_names_from_target(self, target: ast.AST) -> Set[str]:
        """할당 대상에서 변수 이름 추출
        
        지원: Name, Tuple, List
        """
        names = set()
        
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                names.update(self._extract_names_from_target(elt))
        
        return names

