"""
Function Generator for LogosAI

Generates standalone Python functions from business rules and specifications.
This is part of the Self-Growing capability in the Agent Self-Evolution System.

Usage:
    # Traditional mode (requires pre-defined rules)
    from logosai.generation import FunctionGenerator

    generator = FunctionGenerator()
    code = generator.generate(
        function_name="calculate_churn_probability",
        parameters={"months_inactive": "int", "support_tickets": "int"},
        business_rules=["base = 0.10", "base += months_inactive * 0.15"],
        return_type="float"
    )

    # LLM mode (infers everything from natural language)
    generator = FunctionGenerator(use_llm=True)
    code = await generator.generate_from_query("고객 이탈 확률 계산 에이전트")
"""

from typing import Dict, List, Optional, Any
import re
from loguru import logger


class FunctionGenerator:
    """
    Generates standalone Python functions from specifications.

    Supports two modes:
    1. Rule-based: Requires pre-defined business_rules and parameters
    2. LLM-based: Infers parameters and logic from natural language query

    Unlike agent class generation, this produces minimal, focused functions
    that are directly callable and easy to test.
    """

    def __init__(
        self,
        use_type_hints: bool = True,
        use_llm: bool = False,
        llm_model: str = "gemini-2.5-flash-lite",
        llm_provider: str = "google"
    ):
        """
        Initialize the FunctionGenerator.

        Args:
            use_type_hints: Whether to include type hints in generated code
            use_llm: Whether to use LLM for parameter/logic inference
            llm_model: LLM model name (e.g., "gemini-2.5-flash", "gemini-2.5-flash-lite")
            llm_provider: LLM provider (google, openai, anthropic)
        """
        self.use_type_hints = use_type_hints
        self.use_llm = use_llm
        self.llm_model = llm_model
        self.llm_provider = llm_provider
        self._analyzer = None

        if use_llm:
            self._init_llm_analyzer()

    def _init_llm_analyzer(self):
        """Initialize the LLM analyzer (lazy loading)."""
        try:
            from .llm_analyzer import LLMAnalyzer
            self._analyzer = LLMAnalyzer(
                provider=self.llm_provider,
                model=self.llm_model
            )
            logger.info(f"LLMAnalyzer initialized: provider={self.llm_provider}, model={self.llm_model}")
        except ImportError as e:
            logger.warning(f"Could not import LLMAnalyzer: {e}")
            self._analyzer = None

    async def generate_from_query(
        self,
        query: str,
        fallback_rules: Optional[List[str]] = None,
        fallback_params: Optional[Dict[str, str]] = None,
        hint_function_name: Optional[str] = None,
        hint_parameters: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Generate a function from natural language query using LLM.

        This is the core Self-Growing capability - create new functions
        from just a natural language description.

        Args:
            query: Natural language description of the function
            fallback_rules: Optional rules to use if LLM fails
            fallback_params: Optional parameters to use if LLM fails
            hint_function_name: Optional function name hint for LLM
            hint_parameters: Optional parameter names hint for LLM

        Returns:
            Generated Python code as a string
        """
        if not self._analyzer:
            self._init_llm_analyzer()

        if not self._analyzer:
            logger.warning("LLM analyzer not available, using fallback")
            if fallback_rules and fallback_params:
                return self.generate(
                    function_name=hint_function_name or "generated_function",
                    parameters=fallback_params,
                    business_rules=fallback_rules,
                    return_type="dict",
                    docstring=query
                )
            raise RuntimeError("LLM analyzer not available and no fallback provided")

        try:
            # Initialize analyzer if needed
            await self._analyzer.initialize()

            # Step 1: Infer parameters from query (or use hints if provided)
            if hint_function_name and hint_parameters:
                # Use provided hints - no need to infer
                logger.info(f"📋 Using hints: {hint_function_name} with {list(hint_parameters.keys())}")
                from .llm_analyzer import FunctionSpec
                spec = FunctionSpec(
                    function_name=hint_function_name,
                    parameters=hint_parameters,
                    return_type="dict",
                    description=query
                )
            else:
                logger.info(f"🧠 LLM inferring parameters from query: {query[:50]}...")
                spec = await self._analyzer.infer_parameters(query)
                logger.info(f"📋 Inferred: {spec.function_name} with {list(spec.parameters.keys())}")

            # Step 2: Generate business logic
            logger.info("🧠 LLM generating business logic...")
            rules = await self._analyzer.generate_business_logic(
                query, spec.parameters, spec.function_name
            )
            logger.info(f"📋 Generated {len(rules)} business rules")

            # Step 3: Assemble function using existing logic
            code = self.generate(
                function_name=spec.function_name,
                parameters=spec.parameters,
                business_rules=rules,
                return_type=spec.return_type,
                docstring=spec.description
            )

            return code

        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            if fallback_rules and fallback_params:
                logger.info("Using fallback rules")
                return self.generate(
                    function_name="generated_function",
                    parameters=fallback_params,
                    business_rules=fallback_rules,
                    return_type="dict",
                    docstring=query
                )
            raise

    def generate(
        self,
        function_name: str,
        parameters: Dict[str, str],
        business_rules: List[str],
        return_type: str = "dict",
        docstring: Optional[str] = None
    ) -> str:
        """
        Generate a standalone Python function.

        Args:
            function_name: Name of the function to generate
            parameters: Dict of parameter names to their types
            business_rules: List of business rule strings or function names
            return_type: Return type of the function
            docstring: Optional docstring for the function

        Returns:
            Generated Python code as a string
        """
        logger.info(f"Generating function: {function_name}")
        logger.debug(f"Parameters: {parameters}")
        logger.debug(f"Business rules: {business_rules}")

        # Build function signature
        signature = self._build_signature(function_name, parameters, return_type)

        # Build docstring
        doc = self._build_docstring(function_name, parameters, return_type, docstring)

        # Build function body from business rules
        body = self._build_body(parameters, business_rules, return_type)

        # Combine all parts
        code = self._assemble_function(signature, doc, body)

        logger.info(f"Generated function with {len(code)} characters")
        return code

    def _build_signature(
        self,
        function_name: str,
        parameters: Dict[str, str],
        return_type: str
    ) -> str:
        """Build the function signature line."""
        if self.use_type_hints:
            params = ", ".join(
                f"{name}: {self._python_type(typ)}"
                for name, typ in parameters.items()
            )
            return f"def {function_name}({params}) -> {self._python_type(return_type)}:"
        else:
            params = ", ".join(parameters.keys())
            return f"def {function_name}({params}):"

    def _python_type(self, type_str: str) -> str:
        """Convert type string to Python type annotation.

        Handles detailed type descriptions like:
        - "list[dict] - each item has: id (str), urgency (int)" -> "list"
        - "dict - maps product_id (str) to quantity (int)" -> "dict"
        - "list[str] - list of category strings" -> "list"
        """
        # First, extract the base type by removing descriptions after " - "
        base_type = type_str.split(" - ")[0].strip()

        # Handle parameterized types like list[dict], list[str]
        if "[" in base_type:
            base_type = base_type.split("[")[0].strip()

        type_map = {
            "int": "int",
            "float": "float",
            "str": "str",
            "string": "str",
            "bool": "bool",
            "boolean": "bool",
            "list": "list",
            "dict": "dict",
            "any": "Any",
            "none": "None",
        }
        return type_map.get(base_type.lower(), base_type)

    def _build_docstring(
        self,
        function_name: str,
        parameters: Dict[str, str],
        return_type: str,
        custom_docstring: Optional[str] = None
    ) -> str:
        """Build the function docstring."""
        if custom_docstring:
            return f'    """{custom_docstring}"""'

        lines = [f'    """']
        lines.append(f"    {self._humanize_name(function_name)}")
        lines.append("")
        lines.append("    Args:")
        for name, typ in parameters.items():
            lines.append(f"        {name}: {self._humanize_name(name)} ({typ})")
        lines.append("")
        lines.append("    Returns:")
        lines.append(f"        {return_type}: Result of the calculation")
        lines.append('    """')
        return "\n".join(lines)

    def _humanize_name(self, name: str) -> str:
        """Convert snake_case to human readable text."""
        return name.replace("_", " ").title()

    def _build_body(
        self,
        parameters: Dict[str, str],
        business_rules: List[str],
        return_type: str
    ) -> str:
        """Build the function body from business rules."""
        lines = []

        # Check if business_rules are code snippets or function names
        if self._are_code_snippets(business_rules):
            # Direct code implementation
            lines.extend(self._implement_from_code_rules(parameters, business_rules))
        else:
            # Function name references - implement placeholder logic
            lines.extend(self._implement_from_function_refs(parameters, business_rules))

        # Add return statement if not present
        if not any("return " in line for line in lines):
            if return_type in ("dict", "Dict"):
                lines.append("    return result")
            elif return_type == "float":
                lines.append("    return float(result)")
            elif return_type == "int":
                lines.append("    return int(result)")
            else:
                lines.append("    return result")

        return "\n".join(lines)

    def _are_code_snippets(self, business_rules: List[str]) -> bool:
        """Check if business rules are code snippets (contain = or operators)."""
        if not business_rules:
            return False
        # Check first few rules for code patterns
        code_patterns = ["=", "+=", "-=", "*=", "/=", "if ", "for ", "while ", "return "]
        for rule in business_rules[:3]:
            if any(pattern in rule for pattern in code_patterns):
                return True
        return False

    def _normalize_llm_indentation(self, rules: List[str]) -> List[str]:
        """
        Normalize LLM-generated indentation to proper Python 4-space indentation.

        Problem: LLM often generates code with wrong indentation patterns:
        - 8 spaces instead of 4 for first block level
        - Progressively doubling indentation (8, 16, 24...)
        - Inconsistent indentation within same block

        Solution: Use LLM's relative indentation as a hint for nesting level,
        then normalize to proper 4-space indentation.
        """
        if not rules:
            return rules

        # Collect all indentation levels to find the base unit
        indent_values = []
        for rule in rules:
            stripped = rule.lstrip()
            if stripped:
                indent = len(rule) - len(stripped)
                indent_values.append(indent)

        if not indent_values or max(indent_values) == 0:
            # No indentation found - just return
            return rules

        # Find the minimum non-zero indentation (LLM's base indent unit)
        non_zero_indents = [i for i in indent_values if i > 0]
        if not non_zero_indents:
            return rules

        llm_base_indent = min(non_zero_indents)
        logger.info(f"🔧 Normalizing LLM indentation. Base unit: {llm_base_indent}, max: {max(indent_values)}")

        # Strategy: Map LLM indentation levels to proper Python levels
        # LLM indent 0 -> Python indent 0
        # LLM indent N -> Python indent (N / llm_base_indent) * 4
        result = []
        same_level_keywords = ['elif ', 'else:', 'except', 'finally:']

        prev_llm_indent = 0
        prev_python_indent = 0
        indent_map = {0: 0}  # Map from LLM indent to proper Python indent

        for i, rule in enumerate(rules):
            stripped = rule.strip()
            if not stripped:
                continue

            llm_indent = len(rule) - len(rule.lstrip())
            is_block_start = stripped.endswith(':')
            is_same_level = any(stripped.startswith(kw) for kw in same_level_keywords)

            # Calculate proper Python indentation based on LLM's relative indentation
            if llm_indent == 0:
                # Top level
                python_indent = 0
            elif llm_indent in indent_map:
                # We've seen this indent level before
                python_indent = indent_map[llm_indent]
            elif llm_indent > prev_llm_indent:
                # Increased indentation - new block level
                python_indent = prev_python_indent + 4
                indent_map[llm_indent] = python_indent
            elif llm_indent < prev_llm_indent:
                # Decreased indentation - closing block(s)
                # Find the closest known indent level
                known_indents = sorted(indent_map.keys())
                for known in reversed(known_indents):
                    if known <= llm_indent:
                        python_indent = indent_map[known]
                        break
                else:
                    python_indent = 0
            else:
                # Same indentation as previous
                python_indent = prev_python_indent

            # Handle elif/else - should be at same level as the matching if
            if is_same_level and python_indent >= 4:
                python_indent -= 4

            # Handle case where if is followed by another if at same block level
            # but LLM puts it at wrong indentation
            if is_block_start and not is_same_level:
                # This is an if/for/while - check if it should be closing previous blocks
                # by checking if its LLM indent suggests it's at a higher level
                if llm_indent <= prev_llm_indent and not is_same_level:
                    # LLM put this at same or lower level - might be closing blocks
                    if llm_indent in indent_map:
                        python_indent = indent_map[llm_indent]

            # Add the line with corrected indentation
            result.append(' ' * python_indent + stripped)

            # Update tracking for next iteration
            prev_llm_indent = llm_indent
            prev_python_indent = python_indent

            # If this is a block start, the NEXT line should be more indented
            if is_block_start:
                next_python_indent = python_indent + 4
                # Estimate what LLM indent the next line might have
                if i + 1 < len(rules):
                    next_rule = rules[i + 1]
                    next_stripped = next_rule.strip()
                    if next_stripped:
                        next_llm_indent = len(next_rule) - len(next_rule.lstrip())
                        if next_llm_indent > llm_indent:
                            indent_map[next_llm_indent] = next_python_indent

        logger.info(f"🔧 Normalized {len(result)} lines. Indent map: {indent_map}")
        return result

    def _fix_indentation(self, rules: List[str]) -> List[str]:
        """
        Fix indentation for code rules that have block structures (if/else/for/while).

        Strategy:
        1. Check if LLM provided indentation
        2. If LLM indentation looks wrong (doubled, inconsistent), normalize it
        3. If code is flat (no leading spaces), calculate proper indentation
        """
        if not rules:
            return rules

        # Check if LLM already provided indentation
        has_llm_indentation = any(rule.startswith('    ') or rule.startswith('\t') for rule in rules if rule.strip())

        if has_llm_indentation:
            # Check if LLM indentation is correct or needs normalization
            # Look for signs of wrong indentation: levels > 8 or doubling pattern
            max_indent = 0
            indent_levels = []
            for rule in rules:
                stripped = rule.lstrip()
                if stripped:
                    indent = len(rule) - len(stripped)
                    if indent > 0:
                        max_indent = max(max_indent, indent)
                        indent_levels.append(indent)

            # If max indent > 12 (i.e., more than 3 proper levels), or
            # if we see doubling pattern (8, 16, 24...), normalize
            needs_normalization = max_indent > 12
            if not needs_normalization and len(set(indent_levels)) >= 2:
                sorted_levels = sorted(set(indent_levels))
                # Check for doubling: 8, 16 or 8, 16, 24 etc.
                if sorted_levels[0] >= 8:
                    needs_normalization = True
                elif len(sorted_levels) >= 2 and sorted_levels[1] >= sorted_levels[0] * 2:
                    needs_normalization = True

            if needs_normalization:
                logger.info(f"🔧 LLM indentation looks wrong (max={max_indent}, levels={sorted(set(indent_levels))}), normalizing...")
                return self._normalize_llm_indentation(rules)
            else:
                # LLM indentation looks okay, use it directly
                return [rule.rstrip() for rule in rules if rule.strip()]

        # No LLM indentation - calculate it
        result = []
        indent_level = 0
        indent_size = 4

        # Keywords that are at same level as previous block but start new block
        same_level_keywords = ['elif ', 'else:', 'except ', 'finally:']

        # Track block depth to detect when blocks should end
        prev_was_block_body = False

        for i, rule in enumerate(rules):
            stripped = rule.strip()
            if not stripped:
                continue

            # Check if this line should be at same level as the previous block start
            is_same_level = any(stripped.startswith(kw) or stripped == kw.rstrip() for kw in same_level_keywords)

            if is_same_level and indent_level > 0:
                # Decrease indent before this line (elif/else/except/finally)
                indent_level -= 1
            elif prev_was_block_body and indent_level > 0:
                # Previous line was a block body statement
                # Check if this line should close the block
                is_continuation = stripped.endswith(':') or is_same_level
                if not is_continuation:
                    # Check if this looks like a "top-level" statement (uses computed values)
                    # Heuristic: if it's a simple assignment to result/score/total, close blocks
                    if stripped.startswith('result ') or stripped.startswith('result='):
                        indent_level = 0
                    elif '=' in stripped and not any(stripped.startswith(kw) for kw in ['if ', 'for ', 'while ']):
                        # Simple assignment after block body - might need to close
                        # Look ahead: if next line is elif/else, stay in block
                        if i + 1 < len(rules):
                            next_stripped = rules[i + 1].strip()
                            next_is_continuation = any(next_stripped.startswith(kw) for kw in same_level_keywords)
                            if not next_is_continuation:
                                # No continuation - this might be closing the block
                                # But keep current level for block body
                                pass
                        else:
                            # Last line - close all blocks
                            indent_level = 0

            # Add the line with current indentation
            current_indent = ' ' * (indent_level * indent_size)
            result.append(f"{current_indent}{stripped}")

            # Track if this line is a block body (not a block start)
            prev_was_block_body = not stripped.endswith(':')

            # Check if this line starts a new block
            if stripped.endswith(':'):
                indent_level += 1

        return result

    def _fix_empty_block_bodies(self, rules: List[str]) -> List[str]:
        """
        Fix empty block bodies by inserting 'pass' statements.

        Problem: When LLM output is truncated, block structures like:
            if condition:
            next_statement_at_wrong_level

        This causes "expected an indented block" syntax errors.

        Solution: Detect block headers (if/for/while/else/elif/try/except/finally)
        followed by non-indented or less-indented lines, and insert 'pass'.
        """
        if not rules:
            return rules

        result = []
        for i, rule in enumerate(rules):
            stripped = rule.strip()
            if not stripped:
                continue

            # Add current rule
            result.append(rule)

            # Check if this is a block header (ends with ':')
            if stripped.endswith(':'):
                # Get the indentation of this line
                current_indent = len(rule) - len(rule.lstrip())

                # Check next line (if exists)
                if i + 1 < len(rules):
                    next_rule = rules[i + 1]
                    next_stripped = next_rule.strip()

                    if not next_stripped:
                        # Empty line - need pass
                        result.append(' ' * (current_indent + 4) + 'pass')
                        logger.debug(f"🔧 Added 'pass' after empty block body: {stripped[:30]}")
                    else:
                        next_indent = len(next_rule) - len(next_rule.lstrip())
                        # Next line should be MORE indented than current block header
                        if next_indent <= current_indent:
                            # Next line is at same or less indent - empty block!
                            result.append(' ' * (current_indent + 4) + 'pass')
                            logger.debug(f"🔧 Added 'pass' for empty block: {stripped[:30]}")
                else:
                    # Last line is a block header - need pass
                    result.append(' ' * (current_indent + 4) + 'pass')
                    logger.debug(f"🔧 Added 'pass' after trailing block header: {stripped[:30]}")

        return result

    def _fix_truncated_statements(self, rules: List[str]) -> List[str]:
        """
        Fix truncated assignment statements.

        Problem: LLM sometimes generates incomplete statements like:
            priority_score =
            result = max(0,

        Solution: Detect and complete these patterns with sensible defaults.
        """
        import re

        if not rules:
            return rules

        result = []
        for rule in rules:
            stripped = rule.rstrip()
            leading_spaces = len(rule) - len(rule.lstrip())

            # Skip empty lines
            if not stripped.strip():
                result.append(rule)
                continue

            fixed_rule = stripped

            # Case 1: Assignment with missing value (ends with = but not ==, !=, <=, >=)
            if re.search(r'(?<![=!<>])=\s*$', stripped):
                var_part = stripped.rsplit('=', 1)[0].strip()
                # Infer type from variable name
                if any(kw in var_part.lower() for kw in ['score', 'probability', 'ratio', 'factor', 'amount', 'total', 'price', 'rate', 'value']):
                    fixed_rule = f"{var_part} = 0.0"
                elif any(kw in var_part.lower() for kw in ['count', 'num', 'days', 'months', 'years', 'level', 'index']):
                    fixed_rule = f"{var_part} = 0"
                elif any(kw in var_part.lower() for kw in ['is_', 'has_', 'can_', 'should_']):
                    fixed_rule = f"{var_part} = False"
                elif any(kw in var_part.lower() for kw in ['name', 'status', 'message', 'reason', 'type']):
                    fixed_rule = f"{var_part} = ''"
                elif any(kw in var_part.lower() for kw in ['items', 'list', 'array', 'data']):
                    fixed_rule = f"{var_part} = []"
                elif any(kw in var_part.lower() for kw in ['dict', 'map', 'result', 'output', 'config']):
                    fixed_rule = f"{var_part} = {{}}"
                else:
                    fixed_rule = f"{var_part} = 0.0"  # Default to float
                logger.info(f"🔧 Fixed truncated assignment: '{stripped}' → '{fixed_rule}'")

            # Case 2: Unclosed parentheses/brackets/braces
            open_parens = stripped.count('(') - stripped.count(')')
            open_brackets = stripped.count('[') - stripped.count(']')
            open_braces = stripped.count('{') - stripped.count('}')

            if open_parens > 0 or open_brackets > 0 or open_braces > 0:
                # Remove trailing comma if any
                if fixed_rule.endswith(','):
                    fixed_rule = fixed_rule[:-1].rstrip()
                # Add closing brackets
                fixed_rule += ')' * open_parens + ']' * open_brackets + '}' * open_braces
                logger.info(f"🔧 Closed unclosed brackets: '{stripped}' → '{fixed_rule}'")

            # Case 3: Trailing operator (ends with +, -, *, /, %)
            trailing_op_match = re.search(r'([\+\-\*/%])\s*$', fixed_rule)
            if trailing_op_match and not re.search(r'[+\-*/]=\s*$', fixed_rule):
                op = trailing_op_match.group(1)
                # Use identity values
                identity_values = {'+': '0', '-': '0', '*': '1', '/': '1', '%': '1'}
                fixed_rule = f"{fixed_rule.rstrip()}{identity_values.get(op, '0')}"
                logger.info(f"🔧 Fixed trailing operator: '{stripped}' → '{fixed_rule}'")

            # Case 4: Compound assignment with missing value (ends with +=, -=, etc.)
            if re.search(r'[+\-*/]=\s*$', fixed_rule):
                fixed_rule = f"{fixed_rule} 0"
                logger.info(f"🔧 Fixed compound assignment: '{stripped}' → '{fixed_rule}'")

            # Preserve original indentation
            result.append(' ' * leading_spaces + fixed_rule)

        return result

    def _implement_from_code_rules(
        self,
        parameters: Dict[str, str],
        business_rules: List[str]
    ) -> List[str]:
        """Implement function body from code-style business rules."""
        lines = []

        # 🎯 Step 1: Pre-process rules to fix variable initialization issues
        processed_rules = self._fix_variable_initialization(business_rules)

        # 🎯 Step 2: Fix indentation for block structures
        processed_rules = self._fix_indentation(processed_rules)

        # 🎯 Step 3: Fix empty block bodies (insert 'pass' where needed)
        processed_rules = self._fix_empty_block_bodies(processed_rules)

        # 🎯 Step 4: Fix truncated statements (e.g., "priority_score =" → "priority_score = 0.0")
        processed_rules = self._fix_truncated_statements(processed_rules)

        logger.debug(f"🔧 After _fix_truncated_statements: {len(processed_rules)} rules")
        for i, r in enumerate(processed_rules):
            logger.debug(f"   {i}: [{len(r) - len(r.lstrip())}] {r[:60]}")

        # Process business rules
        # After normalization, rules have proper relative indentation (0 for top-level, 4 for first block, etc.)
        # We just need to add 4 spaces for the function body base indent
        result_var = None
        first_assigned_var = None
        for rule in processed_rules:
            # Only strip trailing whitespace, preserve leading spaces (indentation)
            rule = rule.rstrip()
            if not rule.strip():  # Skip empty lines
                continue

            # Track what variable holds the result (strip leading spaces for analysis)
            stripped_rule = rule.lstrip()
            if "=" in stripped_rule and not any(op in stripped_rule for op in ["==", "!=", "<=", ">="]):
                var_name = stripped_rule.split("=")[0].strip()
                # Track the first assigned variable as potential result
                if first_assigned_var is None:
                    first_assigned_var = var_name
                # Check for common result variable names
                if var_name in ["result", "probability", "score", "total", "value", "output", "base", "discount"]:
                    result_var = var_name

            # Add 4-space base indent for function body
            # After _fix_indentation, rules already have proper relative indentation
            lines.append(f"    {rule}")

        # Ensure we have a result variable
        if result_var is None:
            # Look for common result variable patterns in rules
            for rule in processed_rules:
                for var in ["probability", "score", "total", "result", "value", "base", "discount"]:
                    if var in rule:
                        result_var = var
                        break
                if result_var:
                    break

        # If still no result var, use the first assigned variable
        if result_var is None and first_assigned_var:
            result_var = first_assigned_var

        if result_var and result_var != "result":
            lines.append(f"    result = {result_var}")

        return lines

    def _remove_undefined_dict_key_usage(self, business_rules: List[str]) -> List[str]:
        """
        Remove lines that use undefined variables as dictionary keys.

        Problem: LLM sometimes generates code like:
            inventory[product_id] = 0.0   # Line 3 - ERROR: product_id not defined
            status = 'success'
            ...
            for item in order_items:
                product_id = item['product_id']  # product_id defined here

        Solution: Detect this pattern and remove the problematic initialization line.
        """
        if not business_rules:
            return business_rules

        logger.debug(f"🔍 _remove_undefined_dict_key_usage: Processing {len(business_rules)} rules")

        # Step 1: Find all variables defined inside loops (for ... in ...)
        loop_defined_vars = set()
        in_loop = False
        loop_var_pattern = re.compile(r'(\w+)\s*=\s*\w+\[[\'"]\w+[\'"]\]')  # var = dict['key']

        for rule in business_rules:
            stripped = rule.strip()
            if stripped.startswith('for ') and ' in ' in stripped:
                in_loop = True
                logger.debug(f"🔍 Found for loop: {stripped[:50]}")
                continue
            if in_loop:
                # Look for variable assignments inside loop
                match = loop_var_pattern.search(stripped)
                if match:
                    loop_defined_vars.add(match.group(1))
                    logger.debug(f"🔍 Found loop var: {match.group(1)}")

        logger.debug(f"🔍 loop_defined_vars: {loop_defined_vars}")

        if not loop_defined_vars:
            return business_rules

        # Step 2: Find and remove lines that use loop-defined variables as dict keys BEFORE the loop
        dict_key_pattern = re.compile(r'(\w+)\[(\w+)\]\s*=')  # dict[var] = ...
        result = []
        loop_started = False

        for rule in business_rules:
            stripped = rule.strip()

            # Check if loop started
            if stripped.startswith('for ') and ' in ' in stripped:
                loop_started = True
                result.append(rule)
                continue

            if not loop_started:
                # Check if this line uses a loop-defined variable as dict key
                match = dict_key_pattern.search(stripped)
                if match:
                    key_var = match.group(2)
                    if key_var in loop_defined_vars:
                        logger.info(f"🔧 Removing invalid line (uses undefined '{key_var}' as dict key): {stripped}")
                        continue  # Skip this line

            result.append(rule)

        return result

    def _fix_variable_initialization(self, business_rules: List[str]) -> List[str]:
        """
        Fix variable initialization issues in business rules.

        Problem 1: Rules like "probability += x" fail if "probability" was never initialized.
        Solution: Find "base_probability = 0.10" and add "probability = base_probability" before use.

        Problem 2: Rules like "inventory[product_id] = 0.0" use undefined variable as dict key.
        Solution: Remove such lines if the variable is defined later inside a loop.
        """
        if not business_rules:
            return business_rules

        # Step 1: Remove lines that use undefined variables as dictionary keys
        business_rules = self._remove_undefined_dict_key_usage(business_rules)

        # Track which variables are truly initialized (left side only, not used on right side)
        initialized_vars = set()
        compound_uses = {}  # var_name -> first rule index where used with +=, -=, etc.

        for i, rule in enumerate(business_rules):
            rule = rule.strip()
            if not rule:
                continue

            # Check for compound assignment first (these need prior initialization)
            is_compound = False
            for op in ["+=", "-=", "*=", "/="]:
                if op in rule:
                    var_name = rule.split(op)[0].strip()
                    if var_name not in compound_uses:
                        compound_uses[var_name] = i
                    is_compound = True
                    break

            if is_compound:
                continue

            # Check for simple assignment (initialization)
            # Must have = but NOT be compound, comparison, or self-referential
            if "=" in rule and not any(op in rule for op in ["==", "!=", "<=", ">="]):
                parts = rule.split("=", 1)
                if len(parts) == 2:
                    var_name = parts[0].strip()
                    right_side = parts[1].strip()
                    # Only count as initialization if variable NOT used on right side
                    # e.g., "probability = max(0, min(1, probability))" is NOT initialization
                    if var_name not in right_side:
                        initialized_vars.add(var_name)

        # Find variables that need initialization
        new_rules = []
        for var_name, first_use_idx in compound_uses.items():
            if var_name not in initialized_vars:
                # 🔥 Skip dict/list accesses like "inventory[product_id]" - these are NOT simple variables
                # Adding "inventory[product_id] = 0.0" would fail because product_id isn't defined yet
                if '[' in var_name:
                    logger.debug(f"🔍 Skipping dict/list access, not a simple variable: {var_name}")
                    continue

                # Look for a "base_" version or similar
                base_var = f"base_{var_name}"
                if base_var in initialized_vars:
                    # Add: probability = base_probability
                    new_rules.append(f"{var_name} = {base_var}")
                    logger.info(f"🔧 Added initialization: {var_name} = {base_var}")
                else:
                    # Add default initialization
                    new_rules.append(f"{var_name} = 0.0")
                    logger.info(f"🔧 Added default initialization: {var_name} = 0.0")

        # Insert new initialization rules at the right position
        if new_rules:
            # Find where to insert (after all base_* initializations)
            insert_idx = 0
            for i, rule in enumerate(business_rules):
                if rule.strip().startswith("base_"):
                    insert_idx = i + 1

            result = business_rules[:insert_idx] + new_rules + business_rules[insert_idx:]
            return result

        return business_rules

    def _implement_from_function_refs(
        self,
        parameters: Dict[str, str],
        business_rules: List[str]
    ) -> List[str]:
        """Implement function body from function name references."""
        lines = []
        lines.append("    # Initialize result")
        lines.append("    result = {}")
        lines.append("")

        for i, func_name in enumerate(business_rules):
            func_name = func_name.strip()
            if not func_name:
                continue

            # Create a step for each function reference
            step_var = f"step_{i+1}"
            lines.append(f"    # Step {i+1}: {self._humanize_name(func_name)}")

            # Generate implementation based on function name patterns
            impl_lines = self._generate_step_implementation(func_name, parameters, step_var)
            lines.extend(impl_lines)
            lines.append(f"    result['{func_name}'] = {step_var}")
            lines.append("")

        return lines

    def _generate_step_implementation(
        self,
        func_name: str,
        parameters: Dict[str, str],
        result_var: str
    ) -> List[str]:
        """Generate implementation for a step based on function name."""
        lines = []

        # Common patterns
        if "validate" in func_name.lower():
            lines.append(f"    {result_var} = True  # Validation passed")
        elif "calculate" in func_name.lower() or "compute" in func_name.lower():
            lines.append(f"    {result_var} = 0.0")
            for param in parameters:
                lines.append(f"    {result_var} += {param} * 0.1 if isinstance({param}, (int, float)) else 0")
        elif "check" in func_name.lower():
            lines.append(f"    {result_var} = True")
        elif "get" in func_name.lower() or "fetch" in func_name.lower():
            lines.append(f"    {result_var} = {{}}")
        elif "process" in func_name.lower():
            lines.append(f"    {result_var} = {{'status': 'processed'}}")
        elif "send" in func_name.lower() or "notify" in func_name.lower():
            lines.append(f"    {result_var} = {{'sent': True}}")
        elif "update" in func_name.lower():
            lines.append(f"    {result_var} = {{'updated': True}}")
        elif "create" in func_name.lower():
            lines.append(f"    {result_var} = {{'created': True, 'id': 'generated_id'}}")
        else:
            lines.append(f"    {result_var} = None  # TODO: Implement {func_name}")

        return lines

    def _get_default_for_type(self, type_str: str) -> str:
        """Get default value for a type."""
        defaults = {
            "int": "0",
            "float": "0.0",
            "str": "''",
            "string": "''",
            "bool": "False",
            "boolean": "False",
            "list": "[]",
            "dict": "{}",
        }
        return defaults.get(type_str.lower(), "None")

    def _assemble_function(
        self,
        signature: str,
        docstring: str,
        body: str
    ) -> str:
        """Assemble the complete function code."""
        parts = [signature, docstring, body]
        return "\n".join(parts)

    def generate_with_imports(
        self,
        function_name: str,
        parameters: Dict[str, str],
        business_rules: List[str],
        return_type: str = "dict",
        docstring: Optional[str] = None
    ) -> str:
        """
        Generate a complete Python module with imports and function.

        Returns:
            Complete Python code with imports
        """
        imports = [
            "from typing import Dict, List, Any, Optional",
            "",
        ]

        function_code = self.generate(
            function_name=function_name,
            parameters=parameters,
            business_rules=business_rules,
            return_type=return_type,
            docstring=docstring
        )

        return "\n".join(imports) + "\n\n" + function_code
