"""A tiny, safe arithmetic evaluator for composite KPI expressions.

Composite KPIs combine other KPIs, e.g. ``0.6 * SECONDARY_NSV + 0.4 * ECO`` or
``FOCUS_SALES / SECONDARY_NSV * 100``. We must NOT use ``eval``; instead we parse
to an AST and walk a whitelist of nodes (numbers, names → variables, + - * /,
parentheses, unary minus). Anything else raises ValueError. Division by zero
yields Decimal('0') so a missing denominator never blows up a payout run.
"""
import ast
from decimal import Decimal


class ExpressionError(ValueError):
    pass


_BIN_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div)


def extract_names(expression: str) -> set[str]:
    """Return the set of variable names referenced by an expression (used to
    validate that every component KPI code in a composite actually exists)."""
    try:
        tree = ast.parse(expression, mode='eval')
    except SyntaxError as exc:
        raise ExpressionError(f'Invalid expression: {exc.msg}') from exc
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


def safe_eval(expression: str, variables: dict[str, Decimal]) -> Decimal:
    """Evaluate ``expression`` with the given variable values, as Decimal."""
    if not expression or not expression.strip():
        raise ExpressionError('Empty expression.')
    try:
        tree = ast.parse(expression, mode='eval')
    except SyntaxError as exc:
        raise ExpressionError(f'Invalid expression: {exc.msg}') from exc
    return _eval(tree.body, variables)


def _eval(node, variables: dict[str, Decimal]) -> Decimal:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ExpressionError(f'Unsupported constant: {node.value!r}')
        return Decimal(str(node.value))

    if isinstance(node, ast.Name):
        if node.id not in variables:
            raise ExpressionError(f'Unknown reference: {node.id!r}')
        return Decimal(str(variables[node.id]))

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        operand = _eval(node.operand, variables)
        return -operand if isinstance(node.op, ast.USub) else operand

    if isinstance(node, ast.BinOp) and isinstance(node.op, _BIN_OPS):
        left = _eval(node.left, variables)
        right = _eval(node.right, variables)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        # Div — guard against zero denominator
        return left / right if right != 0 else Decimal('0')

    raise ExpressionError('Expression contains an unsupported operation.')
