"""
LLM-based Query Analyzer for Function Generation

Analyzes natural language queries to extract:
1. Function parameters (names and types)
2. Business logic (executable Python code)

This enables true "Self-Growing" - generating functions from NL alone.
"""

import json
import re
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from ..utils.llm_client import LLMClient, LLMResponse


@dataclass
class FunctionSpec:
    """Specification for a function extracted from NL query."""
    function_name: str
    parameters: Dict[str, str]  # name -> type
    return_type: str
    description: str


class LLMAnalyzer:
    """
    LLM-based analyzer for extracting function specifications from natural language.

    Usage:
        analyzer = LLMAnalyzer()
        await analyzer.initialize()

        # Infer parameters from query
        spec = await analyzer.infer_parameters("고객 이탈 확률 계산 에이전트")

        # Generate business logic
        rules = await analyzer.generate_business_logic(query, spec.parameters)
    """

    def __init__(
        self,
        provider: str = "google",
        model: str = "gemini-2.5-flash",
        temperature: float = 0.2  # Low for deterministic code generation
    ):
        """
        Initialize LLMAnalyzer.

        Args:
            provider: LLM provider (google, openai, anthropic)
            model: Model name
            temperature: Sampling temperature (lower = more deterministic)
        """
        self.provider = provider
        self.model = model
        self.temperature = temperature
        self._client: Optional[LLMClient] = None
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize the LLM client."""
        if self._initialized:
            return True

        try:
            self._client = LLMClient(
                provider=self.provider,
                model=self.model,
                temperature=self.temperature,
                max_tokens=4000  # Increased to prevent truncation for complex queries
            )
            await self._client.initialize()
            self._initialized = True
            logger.info(f"LLMAnalyzer initialized with {self.provider}/{self.model}")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize LLMAnalyzer: {e}")
            return False

    async def infer_parameters(self, query: str) -> FunctionSpec:
        """
        Infer function parameters from natural language query.

        Args:
            query: Natural language description of the function

        Returns:
            FunctionSpec with function_name, parameters, return_type, description
        """
        if not self._initialized:
            await self.initialize()

        prompt = self._build_parameter_inference_prompt(query)

        try:
            response = await self._client.invoke(prompt)
            spec = self._parse_parameter_response(response.content, query)
            logger.info(f"Inferred parameters for '{spec.function_name}': {list(spec.parameters.keys())}")
            return spec
        except Exception as e:
            logger.error(f"Parameter inference failed: {e}")
            # Return minimal fallback
            return FunctionSpec(
                function_name="generated_function",
                parameters={"input_data": "dict"},
                return_type="dict",
                description=query
            )

    async def generate_business_logic(
        self,
        query: str,
        parameters: Dict[str, str],
        function_name: str = ""
    ) -> List[str]:
        """
        Generate executable business logic from query.

        Args:
            query: Natural language description
            parameters: Inferred parameters
            function_name: Name of the function

        Returns:
            List of Python code statements
        """
        if not self._initialized:
            await self.initialize()

        # Detect if this is a complex query that should return a dict
        is_complex_query = any(keyword in query.lower() for keyword in [
            'dict', 'dict로 반환', '포함한 dict',
            'first_task', 'has_', 'order', 'status',
            'workflow', 'result', 'categories', 'segment',
            'list', '리스트', 'multi-step', '여러 단계'
        ])

        min_expected_rules = 6 if is_complex_query else 3

        prompt = self._build_logic_generation_prompt(query, parameters, function_name)

        try:
            response = await self._client.invoke(prompt)
            rules = self._parse_logic_response(response.content)

            # Check if LLM oversimplified the response
            if len(rules) < min_expected_rules and is_complex_query:
                logger.warning(f"LLM returned only {len(rules)} rules for complex query (expected >= {min_expected_rules}). Retrying with explicit prompt...")

                # Retry with more explicit instructions
                retry_prompt = self._build_explicit_retry_prompt(query, parameters, function_name, rules)
                retry_response = await self._client.invoke(retry_prompt)
                retry_rules = self._parse_logic_response(retry_response.content)

                if len(retry_rules) >= len(rules):
                    rules = retry_rules
                    logger.info(f"Retry successful: {len(rules)} rules generated")

            # Fix undefined variable references using parameter names
            rules = self._fix_undefined_variables(rules, list(parameters.keys()))
            logger.info(f"Generated {len(rules)} business logic statements")
            return rules
        except Exception as e:
            logger.error(f"Business logic generation failed: {e}")
            # Return minimal fallback
            return ["result = None  # TODO: Implement logic"]

    def _build_explicit_retry_prompt(
        self,
        query: str,
        parameters: Dict[str, str],
        function_name: str,
        previous_rules: List[str]
    ) -> str:
        """Build a retry prompt when LLM oversimplifies."""
        param_list = ", ".join(parameters.keys())

        return f'''The previous response was too simplified. Generate MORE DETAILED business logic.

Function: {function_name}
Parameters: {param_list}
Description: {query}

Previous response (TOO SIMPLIFIED):
{previous_rules}

REQUIREMENTS:
1. Generate AT LEAST 8 statements with explicit intermediate steps
2. Use explicit for loops instead of one-liner comprehensions
3. Initialize variables before using them
4. Build the result dict with named intermediate variables
5. Each for loop must have properly indented body (4 spaces)
6. Each if statement must have properly indented body (4 spaces)

Generate a JSON array with MORE statements:
["statement1", "statement2", "statement3", "statement4", "statement5", "statement6", "statement7", "statement8", "result = final_dict"]'''

    def _build_parameter_inference_prompt(self, query: str) -> str:
        """Build prompt for parameter inference."""
        return f'''You are a Python function designer. Analyze the following natural language request and extract the function specification.

Request: {query}

Respond ONLY with a valid JSON object (no markdown, no explanation):
{{
    "function_name": "snake_case_function_name",
    "parameters": {{
        "param1": "int",
        "param2": "float",
        "param3": "str"
    }},
    "return_type": "float",
    "description": "brief description in English"
}}

Guidelines:
- function_name: Use descriptive snake_case, prefix with "calculate_" for calculations
- parameters: Infer from context. Use types: int, float, str, bool, list, dict
- return_type: Usually float for calculations, dict for complex outputs
- description: Brief English description

Example for "고객 이탈 확률 계산":
{{
    "function_name": "calculate_churn_probability",
    "parameters": {{
        "months_inactive": "int",
        "support_tickets": "int",
        "payment_delays": "int",
        "usage_decline_pct": "float"
    }},
    "return_type": "float",
    "description": "Calculate customer churn probability"
}}'''

    def _build_logic_generation_prompt(
        self,
        query: str,
        parameters: Dict[str, str],
        function_name: str
    ) -> str:
        """Build prompt for business logic generation."""
        # Build detailed parameter descriptions
        param_lines = []
        for k, v in parameters.items():
            param_lines.append(f"  - {k}: {v}")
        params_detailed = "\n".join(param_lines)

        # Detect if this is a multi-step task that needs dict output
        needs_dict_output = any(keyword in query.lower() for keyword in [
            'return dict', 'return a dict', "반환해", "dict로",
            'has_', 'workflow_complete', 'steps_count',
            'first_task', 'top_recommendation', 'status'
        ])

        return_instruction = ""
        if needs_dict_output:
            return_instruction = """
10. IMPORTANT: The description asks for a dict return. Set 'result' to a dict with the required keys.
    Example: result = {"has_clv": True, "clv": clv_value, "segment": segment_name}
11. For boolean fields like 'has_X', set them to True if the computation was performed.
12. CRITICAL: When iterating over list parameters, access item fields ONLY as described above.
    - for product in products: product_id = product['id']  # DON'T use product as dict key!
    - for item in order_items: pid = item['product_id']  # Use exact field names from parameter description
13. CRITICAL: NEVER use a variable before it's defined in a loop.
    - WRONG: inventory[item_id] = 0.0 followed by for item in items: item_id = item['id']
    - CORRECT: for item in items: item_id = item['product_id']; inventory[item_id] = ...
14. When using dict items as keys, use their 'id' or 'product_id' field: scores[product['id']] = 0, NOT scores[product] = 0
15. CRITICAL: Check parameter types from the description above!
    - If type says "list[str]" iterate directly: for seg in segments: use seg
    - If type says "list[dict]" with fields, access those exact fields: for p in products: use p['id']
16. ONLY access fields that are explicitly listed in the parameter description. Do NOT assume other fields exist.
"""
        else:
            return_instruction = """
10. For numeric results, store in 'result' variable as float or int.
11. CRITICAL: NEVER use a variable before it's defined in a loop.
12. ONLY access fields that are explicitly listed in the parameter description.
"""

        return f'''You are a Python code generator. Generate executable business logic for this function.

Function: {function_name}

Parameters (with detailed structure):
{params_detailed}

Description: {query}

Generate a JSON array of Python statements that implement the business logic.
Each statement must be valid Python code.

CRITICAL RULES:
1. ONLY use the provided parameters: {list(parameters.keys())}
2. Initialize variables BEFORE using += or -= operators (e.g., "probability = 0.0" before "probability += x")
3. Include boundary checks (min, max) where appropriate
4. Store final result in a variable named 'result'
5. Use simple arithmetic and conditionals only
6. NO imports, NO function definitions, NO classes
7. For if/elif/else blocks: use 4-space indentation for body statements
8. ALWAYS initialize result variable at the start
9. After if/elif/else chain, put the final result assignment at root level (no indent)
{return_instruction}
STATEMENT COMPLETENESS RULES (CRITICAL):
17. EVERY statement MUST be syntactically complete with all parentheses/brackets closed.
18. NEVER end a statement with an operator like +, -, *, /, =
19. NEVER leave function calls incomplete (e.g., "max(0, x" is INVALID, must be "max(0, x)")
20. Each statement MUST be independently parseable Python code.
21. Keep statements SHORT and SIMPLE. If logic is complex, break into multiple statements.
22. FORBIDDEN patterns: "max(0, value", "sum(x for", "value +", "min(a,", "[item for"

INDENTATION RULES (CRITICAL):
23. For loops: "for item in items:" then "    body_statement" (4 spaces for body)
24. If blocks: "if condition:" then "    body_statement" (4 spaces for body)
25. Keep each indented block SIMPLE - prefer one or two lines inside.
26. After a block ends, return to root level (0 spaces).

COMPLEXITY AND OUTPUT RULES (CRITICAL):
27. For multi-step tasks: Generate at least 6-10 statements with clear intermediate steps.
28. NEVER oversimplify - if description mentions multiple steps, implement each step explicitly.
29. When iterating over lists, use explicit for loops with proper indentation instead of one-liner comprehensions.
30. For dict outputs: Build intermediate variables FIRST, then construct the dict at the end.
31. ALWAYS match the expected output structure exactly as described in the query.

Respond ONLY with a valid JSON array (no markdown, no explanation):
["statement1", "statement2", "result = final_value"]

Example for simple calculation:
["base_probability = 0.10", "probability = base_probability", "probability += months_inactive * 0.15", "probability = max(0.0, min(1.0, probability))", "result = probability"]

Example for task prioritization with dict output (CORRECT PATTERN):
["scored_tasks = []", "for task in tasks:", "    score = task['urgency'] * 2 + task['importance'] * 3", "    scored_tasks.append((task['id'], score))", "scored_tasks.sort(key=lambda x: x[1], reverse=True)", "first_task = scored_tasks[0][0] if scored_tasks else None", "has_critical = False", "for task_id, score in scored_tasks:", "    if score > 50:", "        has_critical = True", "order = [t[0] for t in scored_tasks]", "result = {{'first_task': first_task, 'has_critical': has_critical, 'order': order}}"]

Example with for loop processing items (CORRECT PATTERN):
["total = 0.0", "all_available = True", "for item in order_items:", "    item_id = item['product_id']", "    quantity = item['quantity']", "    if inventory.get(item_id, 0) < quantity:", "        all_available = False", "    total += item['quantity'] * item['unit_price']", "status = 'complete' if all_available else 'failed'", "result = {{'status': status, 'has_discount': True, 'total': total}}"]

Example with customer analysis (CORRECT PATTERN):
["clv = 0.0", "for t in transactions:", "    clv += t['amount']", "churn_risk = 'high' if support_tickets > 3 else 'low'", "segment = 'premium' if clv > 500 else 'standard'", "result = {{'has_clv': True, 'clv': clv, 'has_churn_prediction': True, 'churn_risk': churn_risk, 'has_segment': True, 'segment': segment}}"]'''

    def _parse_parameter_response(self, response: str, original_query: str) -> FunctionSpec:
        """Parse LLM response for parameter inference."""
        try:
            # Clean up response - remove markdown code blocks if present
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r'^```\w*\n?', '', cleaned)
                cleaned = re.sub(r'\n?```$', '', cleaned)

            data = json.loads(cleaned)

            return FunctionSpec(
                function_name=data.get("function_name", "generated_function"),
                parameters=data.get("parameters", {"input_data": "dict"}),
                return_type=data.get("return_type", "dict"),
                description=data.get("description", original_query)
            )
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse parameter response: {e}")
            logger.debug(f"Response was: {response[:200]}")
            # Try to extract function name at least
            func_match = re.search(r'"function_name":\s*"([^"]+)"', response)
            func_name = func_match.group(1) if func_match else "generated_function"

            return FunctionSpec(
                function_name=func_name,
                parameters={"input_data": "dict"},
                return_type="dict",
                description=original_query
            )

    def _is_truncated(self, code: str) -> bool:
        """
        Detect if a code statement is truncated (incomplete).

        Checks for:
        - Unclosed parentheses: max(0, x
        - Unclosed brackets: [a, b, c
        - Unclosed braces: {'key': val
        - Unclosed string literals: "text or 'text
        - Incomplete operators: priority_score +=  (no value after operator)
        - Trailing binary operators: x = y +  (no operand after +)
        """
        stripped = code.rstrip()

        # Count open/close parentheses
        open_parens = code.count('(') - code.count(')')
        open_brackets = code.count('[') - code.count(']')
        open_braces = code.count('{') - code.count('}')

        if open_parens > 0 or open_brackets > 0 or open_braces > 0:
            return True

        # Check for unclosed string literals (simple check)
        # Count quotes, ignoring escaped quotes
        cleaned = re.sub(r'\\"', '', code)
        cleaned = re.sub(r"\\'", '', cleaned)
        double_quotes = cleaned.count('"')
        single_quotes = cleaned.count("'")

        if double_quotes % 2 != 0 or single_quotes % 2 != 0:
            return True

        # Check for incomplete assignment/augmented operators
        # Pattern: var += (nothing), var = (nothing), var -= (nothing)
        if re.search(r'[+\-*/]=\s*$', stripped):
            return True  # Ends with +=, -=, *=, /= without value

        if re.search(r'(?<![=!<>])=\s*$', stripped):
            return True  # Ends with = without value (but not ==, !=, <=, >=)

        # Check for trailing binary operators
        # Pattern: x = y + (nothing), score * (nothing)
        if re.search(r'[\+\-\*/%]\s*$', stripped) and not re.search(r'[+\-*/]=\s*$', stripped):
            return True  # Ends with +, -, *, /, % without operand

        # Check for trailing comma (incomplete list/tuple/args)
        if stripped.endswith(','):
            return True

        return False

    def _complete_truncated_assignment(self, code: str) -> Optional[str]:
        """
        Try to complete a truncated assignment with a default value.

        Examples:
        - "x =" → "x = 0.0"
        - "x = max(0, y" → "x = max(0, y)"  (close parentheses)
        - "x = [a, b," → "x = [a, b]"  (close bracket)
        """
        stripped = code.rstrip()

        # Case 1: Assignment with missing value (ends with =)
        if re.search(r'(?<![=!<>])=\s*$', stripped):
            # Variable name is before the =
            var_part = stripped.rsplit('=', 1)[0].strip()
            # Infer type from variable name
            if any(kw in var_part.lower() for kw in ['score', 'probability', 'ratio', 'factor', 'amount', 'total', 'price', 'rate']):
                return f"{var_part} = 0.0"
            elif any(kw in var_part.lower() for kw in ['count', 'num', 'days', 'months', 'years', 'level', 'index']):
                return f"{var_part} = 0"
            elif any(kw in var_part.lower() for kw in ['is_', 'has_', 'can_', 'should_']):
                return f"{var_part} = False"
            elif any(kw in var_part.lower() for kw in ['name', 'status', 'message', 'reason', 'level', 'risk']):
                return f"{var_part} = ''"
            elif any(kw in var_part.lower() for kw in ['items', 'list', 'array', 'data']):
                return f"{var_part} = []"
            elif any(kw in var_part.lower() for kw in ['dict', 'map', 'result', 'output', 'config']):
                return f"{var_part} = {{}}"
            else:
                return f"{var_part} = 0.0"  # Default to float

        # Case 2: Unclosed parentheses - close them
        open_parens = code.count('(') - code.count(')')
        open_brackets = code.count('[') - code.count(']')
        open_braces = code.count('{') - code.count('}')

        if open_parens > 0 or open_brackets > 0 or open_braces > 0:
            completed = stripped
            # Remove trailing comma if any
            if completed.endswith(','):
                completed = completed[:-1].rstrip()
            # Add closing brackets
            completed += ')' * open_parens + ']' * open_brackets + '}' * open_braces
            return completed

        # Case 3: Trailing operator - add identity value for the operator
        trailing_op_match = re.search(r'([\+\-\*/%])\s*$', stripped)
        if trailing_op_match:
            op = trailing_op_match.group(1)
            # Use identity values that don't change the result
            identity_values = {
                '+': '0',    # x + 0 = x
                '-': '0',    # x - 0 = x
                '*': '1',    # x * 1 = x
                '/': '1',    # x / 1 = x
                '%': '1',    # x % 1 = 0 (often used for modulo operations)
            }
            identity = identity_values.get(op, '0')
            return f"{stripped}{identity}"

        # Case 4: Compound assignment with missing value (ends with +=, -=, etc.)
        if re.search(r'[+\-*/]=\s*$', stripped):
            return f"{stripped} 0"

        return None

    def _parse_logic_response(self, response: str) -> List[str]:
        """Parse LLM response for business logic."""
        try:
            # Clean up response
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r'^```\w*\n?', '', cleaned)
                cleaned = re.sub(r'\n?```$', '', cleaned)

            rules = json.loads(cleaned)

            if isinstance(rules, list):
                # Filter out empty strings but PRESERVE leading spaces (indentation)
                valid_rules = []
                prev_was_block_start = False  # Track if previous line ended with ':'
                for rule in rules:
                    if isinstance(rule, str) and rule.strip():
                        cleaned_rule = self._clean_code_line(rule)
                        if cleaned_rule and cleaned_rule.strip():
                            # Handle truncated statements
                            if self._is_truncated(cleaned_rule):
                                logger.warning(f"Truncated statement detected: {cleaned_rule[:50]}...")
                                # Try to complete truncated assignment with default value
                                completed_rule = self._complete_truncated_assignment(cleaned_rule)
                                if completed_rule:
                                    logger.info(f"Completed truncated assignment: {completed_rule[:50]}...")
                                    cleaned_rule = completed_rule
                                else:
                                    # Can't complete - skip but handle empty block case
                                    if prev_was_block_start:
                                        # Get indentation from current rule or default to 4 more than previous
                                        indent = len(cleaned_rule) - len(cleaned_rule.lstrip())
                                        if indent == 0:
                                            indent = 4  # Default indent
                                        valid_rules.append(' ' * indent + 'pass')
                                        logger.info(f"Added 'pass' for empty block body")
                                        prev_was_block_start = False
                                    continue
                            valid_rules.append(cleaned_rule)
                            prev_was_block_start = cleaned_rule.rstrip().endswith(':')
                        else:
                            prev_was_block_start = False
                    else:
                        prev_was_block_start = False
                # Fix indentation issues across all rules
                valid_rules = self._fix_indentation(valid_rules)
                return valid_rules if valid_rules else ["result = None"]
            else:
                logger.warning(f"Unexpected response type: {type(rules)}")
                return ["result = None"]

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse logic response: {e}")
            logger.debug(f"Response was: {response[:200]}")

            # Try to extract statements manually
            lines = response.split('\n')
            rules = []
            for line in lines:
                stripped = line.strip().strip('"').strip("'").strip(',').strip('[').strip(']')
                if stripped and not stripped.startswith('#') and '=' in stripped:
                    cleaned_line = self._clean_code_line(stripped)
                    if cleaned_line and not self._is_truncated(cleaned_line):
                        rules.append(cleaned_line)

            # Fix indentation issues
            rules = self._fix_indentation(rules)
            return rules if rules else ["result = None"]

    def _fix_undefined_variables(self, rules: List[str], parameters: List[str]) -> List[str]:
        """
        Fix undefined variable references in generated code.

        Detects when a variable is used but never defined, and attempts to
        find a similar defined variable to substitute.

        Example:
            Input: ["churn_probability = 0.5", "result = probability"]
            Output: ["churn_probability = 0.5", "result = churn_probability"]

        Args:
            rules: List of code statements
            parameters: List of function parameter names (always defined)
        """
        if not rules:
            return rules

        # Track defined variables
        defined_vars = set(parameters)

        # First pass: collect all defined variables
        for rule in rules:
            stripped = rule.strip()
            # Match simple assignments: var = value (not ==, +=, -=, etc.)
            match = re.match(r'^(\w+)\s*=(?!=)', stripped)
            if match:
                defined_vars.add(match.group(1))
            # Match for loop variables: for var in ...
            for_match = re.match(r'^for\s+(\w+)\s+in\s+', stripped)
            if for_match:
                defined_vars.add(for_match.group(1))
            # Match tuple unpacking in for: for x, y in ...
            for_tuple_match = re.match(r'^for\s+(\w+)\s*,\s*(\w+)\s+in\s+', stripped)
            if for_tuple_match:
                defined_vars.add(for_tuple_match.group(1))
                defined_vars.add(for_tuple_match.group(2))
            # Match list comprehension temp vars: [x for x in items]
            comp_matches = re.findall(r'for\s+(\w+)\s+in\s+', stripped)
            for comp_var in comp_matches:
                defined_vars.add(comp_var)

        # Second pass: fix undefined variables
        fixed_rules = []
        for rule in rules:
            fixed_rule = rule
            stripped = rule.strip()

            # Find all variable references (not definitions)
            # Skip if it's a function definition or import
            if stripped.startswith('def ') or stripped.startswith('import '):
                fixed_rules.append(rule)
                continue

            # Look for pattern: result = undefined_var (simple assignment to undefined)
            match = re.match(r'^result\s*=\s*(\w+)\s*$', stripped)
            if match:
                var_used = match.group(1)
                if var_used not in defined_vars:
                    # Try to find a similar variable
                    best_match = self._find_similar_variable(var_used, defined_vars)
                    if best_match:
                        fixed_rule = f"result = {best_match}"
                        logger.warning(f"Fixed undefined var: '{var_used}' -> '{best_match}'")

            fixed_rules.append(fixed_rule)

        return fixed_rules

    def _find_similar_variable(self, undefined_var: str, defined_vars: set) -> Optional[str]:
        """
        Find a similar variable name from defined variables.

        Uses simple heuristics:
        - If undefined_var is a suffix of a defined variable (e.g., 'probability' matches 'churn_probability')
        - If undefined_var is a prefix of a defined variable
        - If defined variable contains undefined_var as substring
        """
        candidates = []

        for defined in defined_vars:
            # Skip common variables like 'result', 'i', 'x', etc.
            if defined in ['result', 'i', 'j', 'k', 'x', 'y', 'z', 'item', 'key', 'value']:
                continue

            # Check if undefined is suffix: probability -> churn_probability
            if defined.endswith('_' + undefined_var) or defined.endswith(undefined_var):
                candidates.append((defined, 3))  # High priority

            # Check if undefined is prefix: churn -> churn_probability
            if defined.startswith(undefined_var + '_') or defined.startswith(undefined_var):
                candidates.append((defined, 2))  # Medium priority

            # Check substring: prob -> probability, total -> total_amount
            if undefined_var in defined:
                candidates.append((defined, 1))  # Low priority

        if candidates:
            # Sort by priority (descending) and return best match
            candidates.sort(key=lambda x: x[1], reverse=True)
            return candidates[0][0]

        return None

    def _fix_indentation(self, rules: List[str]) -> List[str]:
        """
        Fix indentation issues in generated code rules.

        Tracks expected indent depth and fixes lines that don't match:
        1. After a ':' line, expect indent to increase by 4
        2. When we see 'result =' at 0sp, reset expected indent
        3. Fix lines that have wrong or missing indent

        Example fix:
            for task in tasks:        # expected_indent = 0, sets to 4
                score = ...           # correct at 4sp
            append(...)               # WRONG at 0sp, fix to 4sp
                if condition:         # correct at 4sp, sets expected to 8
                action = True         # WRONG at 4sp, fix to 8sp
            result = ...              # correct at 0sp, resets expected
        """
        if not rules:
            return rules

        fixed_rules = []
        indent_stack = [0]  # Stack of expected indent levels

        # Keywords that start blocks
        block_starters = ('for ', 'if ', 'elif ', 'else:', 'while ', 'with ', 'try:', 'except', 'finally:', 'def ', 'class ')
        # Keywords that end block processing (should be at root level)
        root_level_keywords = ('result =', 'return ')

        for i, rule in enumerate(rules):
            stripped = rule.lstrip()
            if not stripped:
                fixed_rules.append(rule)
                continue

            leading_spaces = len(rule) - len(stripped)
            expected_indent = indent_stack[-1]

            # Check if this line should be at root level
            is_root_level = any(stripped.startswith(kw) for kw in root_level_keywords)

            # Check if this is a block starter
            is_block_starter = any(stripped.startswith(kw) for kw in block_starters)

            # Handle root level keywords - reset indent
            if is_root_level:
                indent_stack = [0]
                if leading_spaces != 0:
                    fixed_rule = stripped
                    logger.debug(f"Fixed to root level: {repr(rule[:40])}")
                    fixed_rules.append(fixed_rule)
                else:
                    fixed_rules.append(rule)
                continue

            # If current line ends with ':', it's a block starter
            # The content should be at expected_indent, and next line at expected_indent + 4
            if stripped.endswith(':'):
                # Block starter should be at expected_indent OR current indent if already indented
                if leading_spaces < expected_indent and not is_block_starter:
                    # Under-indented - fix it
                    fixed_rule = ' ' * expected_indent + stripped
                    logger.debug(f"Fixed block starter indent: {repr(rule[:40])} -> {repr(fixed_rule[:40])}")
                    fixed_rules.append(fixed_rule)
                else:
                    fixed_rules.append(rule)
                # Push new expected indent for block body
                new_indent = max(leading_spaces, expected_indent) + 4
                indent_stack.append(new_indent)
            else:
                # Regular statement - should be at expected_indent
                if leading_spaces < expected_indent:
                    # Under-indented - could be:
                    # 1. End of block (dedent) if it's a block starter at lower level
                    # 2. Missing indent that needs fixing

                    if is_block_starter:
                        # This is elif/else/except at same level as if/try
                        # Pop until we find matching indent
                        while len(indent_stack) > 1 and indent_stack[-1] > leading_spaces + 4:
                            indent_stack.pop()
                        fixed_rules.append(rule)
                    else:
                        # Regular statement with wrong indent - fix it
                        fixed_rule = ' ' * expected_indent + stripped
                        logger.debug(f"Fixed under-indent: {repr(rule[:40])} -> {repr(fixed_rule[:40])}")
                        fixed_rules.append(fixed_rule)
                elif leading_spaces > expected_indent and i > 0:
                    # Over-indented - might be orphan indent
                    prev_stripped = fixed_rules[-1].lstrip() if fixed_rules else ''
                    if not prev_stripped.endswith(':'):
                        # Previous line didn't start a block - orphan indent
                        fixed_rule = ' ' * expected_indent + stripped
                        logger.debug(f"Fixed orphan indent: {repr(rule[:40])} -> {repr(fixed_rule[:40])}")
                        fixed_rules.append(fixed_rule)
                    else:
                        # Proper indent after ':'
                        fixed_rules.append(rule)
                else:
                    fixed_rules.append(rule)

        return fixed_rules

    def _clean_code_line(self, rule: str) -> str:
        """
        Clean a code line from gemini-2.5 generation artifacts.

        Fixes:
        1. Trailing spurious quotes: result = 0.0" → result = 0.0
        2. JSON escaped quotes: \\" → "
        3. Code wrapped in quotes: "code line" → code line
        4. JavaScript booleans: false → False, true → True
        5. JavaScript null: null → None
        """
        # Only strip trailing whitespace, preserve leading spaces (indentation)
        cleaned_rule = rule.rstrip()

        # Fix JavaScript booleans and null (must be done carefully to avoid changing string contents)
        # Only replace when it's a standalone value, not inside a string
        # Pattern: = false, : false, (false, [false, {false
        cleaned_rule = re.sub(r'(\s*[=:,\(\[\{]\s*)false(\s*[,\)\]\}:]|$)', r'\1False\2', cleaned_rule)
        cleaned_rule = re.sub(r'(\s*[=:,\(\[\{]\s*)true(\s*[,\)\]\}:]|$)', r'\1True\2', cleaned_rule)
        # Fix JavaScript null → Python None
        cleaned_rule = re.sub(r'(\s*[=:,\(\[\{]\s*)null(\s*[,\)\]\}:]|$)', r'\1None\2', cleaned_rule)

        # Fix 1: Remove wrapping quotes if the entire line is quoted
        # Pattern: "total_amount = 0.0" → total_amount = 0.0
        if len(cleaned_rule) >= 2:
            if (cleaned_rule.startswith('"') and cleaned_rule.endswith('"')) or \
               (cleaned_rule.startswith("'") and cleaned_rule.endswith("'")):
                # Check if it's a wrapped code line (not a string assignment)
                inner = cleaned_rule[1:-1]
                # If inner looks like code (has = and no unbalanced quotes), unwrap it
                if '=' in inner and inner.count('"') % 2 == 0 and inner.count("'") % 2 == 0:
                    cleaned_rule = inner

        # Fix 2: Unescape JSON escaped quotes: \\" → " and \\' → '
        cleaned_rule = cleaned_rule.replace('\\"', '"').replace("\\'", "'")

        # Fix 3: Strip trailing spurious double quotes (gemini-2.5 bug)
        # Pattern: result = 0.0" → result = 0.0
        while cleaned_rule.endswith('"') and not self._is_valid_string_ending(cleaned_rule):
            cleaned_rule = cleaned_rule[:-1].rstrip()

        # Fix 4: Handle lines that are just quoted strings of code
        # Pattern: "    indented code" → check and unwrap
        if cleaned_rule.startswith('"') and '=' in cleaned_rule:
            # Try to find matching closing quote
            if cleaned_rule.count('"') == 1:
                # Only opening quote, strip it
                cleaned_rule = cleaned_rule[1:]

        return cleaned_rule

    def _is_valid_string_ending(self, code: str) -> bool:
        """
        Check if a trailing double quote is part of a valid Python string.

        Returns True if the quote is part of a legitimate string literal.
        Returns False if it's a spurious quote (gemini-2.5 bug).

        Examples:
            'result = "hello"' -> True (valid string)
            'result = 0.0"' -> False (spurious quote)
            "x = 'test'" -> False (ends with single quote, different check)
        """
        if not code.endswith('"'):
            return True

        # Count unescaped double quotes
        # A valid string has an even number of unescaped quotes (opening + closing pairs)
        quote_count = 0
        i = 0
        while i < len(code):
            if code[i] == '\\' and i + 1 < len(code):
                i += 2  # Skip escaped character
                continue
            if code[i] == '"':
                quote_count += 1
            i += 1

        # If odd number of quotes, the trailing quote is likely spurious
        # (it would be unmatched)
        if quote_count % 2 == 1:
            return False

        # Additional check: if line ends with pattern like "= 0.0"" or "+= x""
        # These are clearly spurious
        if re.search(r'[0-9a-zA-Z_)\]]\s*"$', code):
            # Check if there's a matching opening quote for this closing quote
            # by looking for string patterns
            if not re.search(r'["\'].*["\']$', code):
                return False

        return True

    async def analyze_query(self, query: str) -> tuple[FunctionSpec, List[str]]:
        """
        Complete analysis: infer parameters and generate logic.

        Args:
            query: Natural language description

        Returns:
            Tuple of (FunctionSpec, business_rules)
        """
        spec = await self.infer_parameters(query)
        rules = await self.generate_business_logic(query, spec.parameters, spec.function_name)
        return spec, rules
