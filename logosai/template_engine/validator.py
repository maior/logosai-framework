"""
Template Validator for LogosAI

Validates rendered code for syntax, security, and LogosAI compliance.
"""

import ast
import re
from typing import List, Tuple, Set, Optional
import logging

logger = logging.getLogger(__name__)


class ValidationError:
    """Represents a validation error"""
    
    def __init__(self, error_type: str, message: str, line: Optional[int] = None):
        self.error_type = error_type
        self.message = message
        self.line = line
        
    def __str__(self):
        if self.line:
            return f"[{self.error_type}] Line {self.line}: {self.message}"
        return f"[{self.error_type}] {self.message}"


class TemplateValidator:
    """Validates rendered agent code"""
    
    # Required methods for LogosAI agents
    REQUIRED_METHODS = {'setup', 'process', 'validate_input', 'format_output'}
    
    # Dangerous functions that should not be used
    DANGEROUS_FUNCTIONS = {
        'eval', 'exec', '__import__', 'compile', 'execfile',
        'input', 'raw_input', 'reload'
    }
    
    # Required imports for LogosAI agents
    REQUIRED_IMPORTS = {
        'from logosai import LogosAIAgent',
        'from typing import'
    }
    
    def validate_rendered_code(self, code: str) -> Tuple[bool, List[ValidationError]]:
        """
        Validate rendered Python code.
        
        Args:
            code: Python code string to validate
            
        Returns:
            Tuple of (is_valid, errors)
        """
        errors = []
        
        # 1. Syntax validation
        syntax_errors = self._validate_syntax(code)
        errors.extend(syntax_errors)
        
        if syntax_errors:  # Can't proceed with AST if syntax is invalid
            return False, errors
            
        # 2. Required methods validation
        method_errors = self._validate_required_methods(code)
        errors.extend(method_errors)
        
        # 3. Security validation
        security_errors = self._validate_security(code)
        errors.extend(security_errors)
        
        # 4. Import validation
        import_errors = self._validate_imports(code)
        errors.extend(import_errors)
        
        # 5. LogosAI compliance validation
        compliance_errors = self._validate_logosai_compliance(code)
        errors.extend(compliance_errors)
        
        return len(errors) == 0, errors
        
    def _validate_syntax(self, code: str) -> List[ValidationError]:
        """Validate Python syntax"""
        errors = []
        
        try:
            ast.parse(code)
        except SyntaxError as e:
            errors.append(ValidationError(
                "SyntaxError",
                str(e),
                e.lineno
            ))
            
        return errors
        
    def _validate_required_methods(self, code: str) -> List[ValidationError]:
        """Validate that all required methods are present"""
        errors = []
        
        try:
            tree = ast.parse(code)
            
            # Find all class definitions
            classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
            
            if not classes:
                errors.append(ValidationError(
                    "StructureError",
                    "No class definition found"
                ))
                return errors
                
            # Check for LogosAIAgent inheritance
            agent_classes = []
            for cls in classes:
                for base in cls.bases:
                    if isinstance(base, ast.Name) and base.id == 'LogosAIAgent':
                        agent_classes.append(cls)
                        
            if not agent_classes:
                errors.append(ValidationError(
                    "InheritanceError",
                    "No class inheriting from LogosAIAgent found"
                ))
                return errors
                
            # Check required methods in agent classes
            for cls in agent_classes:
                class_methods = {
                    node.name for node in cls.body 
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
                
                missing_methods = self.REQUIRED_METHODS - class_methods
                for method in missing_methods:
                    errors.append(ValidationError(
                        "MissingMethodError",
                        f"Required method '{method}' not found in class '{cls.name}'"
                    ))
                    
        except Exception as e:
            errors.append(ValidationError(
                "ValidationError",
                f"Failed to validate methods: {e}"
            ))
            
        return errors
        
    def _validate_security(self, code: str) -> List[ValidationError]:
        """Validate code for security issues"""
        errors = []
        
        try:
            tree = ast.parse(code)
            
            # Check for dangerous function calls
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func_name = None
                    
                    if isinstance(node.func, ast.Name):
                        func_name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        func_name = node.func.attr
                        
                    if func_name in self.DANGEROUS_FUNCTIONS:
                        errors.append(ValidationError(
                            "SecurityError",
                            f"Dangerous function '{func_name}' is not allowed",
                            node.lineno
                        ))
                        
            # Check for suspicious imports
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in ['os', 'subprocess', 'socket']:
                            errors.append(ValidationError(
                                "SecurityError",
                                f"Import of '{alias.name}' may pose security risks",
                                node.lineno
                            ))
                            
        except Exception as e:
            errors.append(ValidationError(
                "ValidationError",
                f"Failed to validate security: {e}"
            ))
            
        return errors
        
    def _validate_imports(self, code: str) -> List[ValidationError]:
        """Validate required imports"""
        errors = []
        
        # Simple regex check for required imports
        for required_import in self.REQUIRED_IMPORTS:
            pattern = re.escape(required_import)
            if not re.search(pattern, code):
                errors.append(ValidationError(
                    "ImportError",
                    f"Required import missing: {required_import}"
                ))
                
        return errors
        
    def _validate_logosai_compliance(self, code: str) -> List[ValidationError]:
        """Validate LogosAI specific compliance rules"""
        errors = []
        
        try:
            tree = ast.parse(code)
            
            # Check for proper async/await usage in process method
            for node in ast.walk(tree):
                if isinstance(node, ast.AsyncFunctionDef) and node.name == 'process':
                    # Check if it has proper error handling
                    has_try_except = any(
                        isinstance(child, ast.Try) for child in node.body
                    )
                    if not has_try_except:
                        errors.append(ValidationError(
                            "ComplianceError",
                            "Process method should include error handling",
                            node.lineno
                        ))
                        
            # Check for proper logging setup
            has_logger = 'logger' in code or 'self.logger' in code
            if not has_logger:
                errors.append(ValidationError(
                    "ComplianceWarning",
                    "Consider adding logging for better debugging"
                ))
                
        except Exception as e:
            errors.append(ValidationError(
                "ValidationError",
                f"Failed to validate compliance: {e}"
            ))
            
        return errors
        
    def validate_template_syntax(self, template_content: str) -> Tuple[bool, List[str]]:
        """
        Validate Jinja2 template syntax.
        
        Args:
            template_content: Jinja2 template string
            
        Returns:
            Tuple of (is_valid, errors)
        """
        from jinja2 import Environment, TemplateSyntaxError
        
        errors = []
        env = Environment()
        
        try:
            env.parse(template_content)
            return True, []
        except TemplateSyntaxError as e:
            errors.append(f"Template syntax error at line {e.lineno}: {e.message}")
            return False, errors