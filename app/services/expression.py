from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional


class Namespace:
    """
    A tiny object to support safe dotted access like answers.FLD_X.
    Missing attributes return None (like JS undefined/null-ish behavior for this demo).
    """

    __slots__ = ("_data",)

    def __init__(self, data: Mapping[str, Any]):
        self._data = dict(data)

    def __getattr__(self, item: str) -> Any:
        return self._data.get(item)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def as_dict(self) -> Dict[str, Any]:
        return dict(self._data)


@dataclass(frozen=True)
class SafeEvalConfig:
    allowed_names: frozenset[str]
    allowed_callables: frozenset[str]
    allowed_attr_roots: frozenset[str]


class SafeEvaluator(ast.NodeVisitor):
    def __init__(self, env: Dict[str, Any], cfg: SafeEvalConfig):
        self.env = env
        self.cfg = cfg

    def visit(self, node: ast.AST) -> Any:
        return super().visit(node)

    def generic_visit(self, node: ast.AST) -> Any:
        raise ValueError(f"Unsupported expression node: {type(node).__name__}")

    def visit_Expression(self, node: ast.Expression) -> Any:
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> Any:
        return node.value

    def visit_List(self, node: ast.List) -> Any:
        return [self.visit(elt) for elt in node.elts]

    def visit_Dict(self, node: ast.Dict) -> Any:
        return {self.visit(k): self.visit(v) for k, v in zip(node.keys, node.values, strict=False)}

    def visit_Name(self, node: ast.Name) -> Any:
        if node.id not in self.cfg.allowed_names:
            raise ValueError(f"Name not allowed: {node.id}")
        return self.env[node.id]

    def visit_Attribute(self, node: ast.Attribute) -> Any:
        if not isinstance(node.value, ast.Name):
            raise ValueError("Only simple dotted access is allowed")
        root = node.value.id
        if root not in self.cfg.allowed_attr_roots:
            raise ValueError(f"Attribute root not allowed: {root}")
        obj = self.visit(node.value)
        # Namespace.__getattr__ returns None for missing keys, which is ok for this demo.
        return getattr(obj, node.attr)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.Not):
            return not bool(operand)
        if isinstance(node.op, ast.USub):
            return -operand
        raise ValueError("Unsupported unary operator")

    def visit_BoolOp(self, node: ast.BoolOp) -> Any:
        if isinstance(node.op, ast.And):
            result = True
            for v in node.values:
                result = bool(self.visit(v))
                if not result:
                    return False
            return True
        if isinstance(node.op, ast.Or):
            for v in node.values:
                if bool(self.visit(v)):
                    return True
            return False
        raise ValueError("Unsupported boolean operator")

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        left = self.visit(node.left)
        right = self.visit(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        raise ValueError("Unsupported binary operator")

    def visit_Compare(self, node: ast.Compare) -> Any:
        left = self.visit(node.left)
        for op, comp in zip(node.ops, node.comparators, strict=False):
            right = self.visit(comp)
            ok: bool
            if isinstance(op, ast.Eq):
                ok = left == right
            elif isinstance(op, ast.NotEq):
                ok = left != right
            elif isinstance(op, ast.Gt):
                ok = left > right
            elif isinstance(op, ast.Lt):
                ok = left < right
            elif isinstance(op, ast.GtE):
                ok = left >= right
            elif isinstance(op, ast.LtE):
                ok = left <= right
            else:
                raise ValueError("Unsupported comparison operator")
            if not ok:
                return False
            left = right
        return True

    def visit_IfExp(self, node: ast.IfExp) -> Any:
        cond = bool(self.visit(node.test))
        return self.visit(node.body if cond else node.orelse)

    def visit_Call(self, node: ast.Call) -> Any:
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only direct function calls are allowed")
        fn_name = node.func.id
        if fn_name not in self.cfg.allowed_callables:
            raise ValueError(f"Call not allowed: {fn_name}")
        fn = self.env[fn_name]
        args = [self.visit(a) for a in node.args]
        kwargs = {kw.arg: self.visit(kw.value) for kw in node.keywords}
        return fn(*args, **kwargs)


_TERNARY_Q = "?"
_TERNARY_C = ":"


def _strip_outer_parens(s: str) -> str:
    s = s.strip()
    if not (s.startswith("(") and s.endswith(")")):
        return s
    depth = 0
    in_str = False
    for i, ch in enumerate(s):
        if ch == "'" and (i == 0 or s[i - 1] != "\\"):
            in_str = not in_str
        if in_str:
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0 and i != len(s) - 1:
                return s
    # fully wrapped
    return _strip_outer_parens(s[1:-1])


def _find_top_level_ternary(expr: str) -> Optional[tuple[int, int]]:
    """
    Returns positions of '?' and matching ':' at top level (not inside parentheses or strings).
    """
    depth = 0
    in_str = False
    q_pos = None
    nested_q = 0
    for i, ch in enumerate(expr):
        if ch == "'" and (i == 0 or expr[i - 1] != "\\"):
            in_str = not in_str
        if in_str:
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0:
            if ch == _TERNARY_Q:
                if q_pos is None:
                    q_pos = i
                else:
                    nested_q += 1
            elif ch == _TERNARY_C and q_pos is not None:
                if nested_q == 0:
                    return q_pos, i
                nested_q -= 1
    return None


def convert_ternary(expr: str) -> str:
    expr = expr.strip()
    loc = _find_top_level_ternary(expr)
    if not loc:
        return expr
    q_pos, c_pos = loc
    cond = expr[:q_pos].strip()
    a = expr[q_pos + 1 : c_pos].strip()
    b = expr[c_pos + 1 :].strip()
    # Recursively convert nested ternaries.
    cond = convert_ternary(cond)
    a = convert_ternary(a)
    b = convert_ternary(b)
    return f"({a} if {cond} else {b})"


def _wrap_numbers_as_decimal(expr: str) -> str:
    """
    Replace numeric literals outside strings with Decimal('...').
    Supports ints and decimals like 0.015.
    """
    out = []
    i = 0
    in_str = False
    while i < len(expr):
        ch = expr[i]
        if ch == "'" and (i == 0 or expr[i - 1] != "\\"):
            in_str = not in_str
            out.append(ch)
            i += 1
            continue
        if in_str:
            out.append(ch)
            i += 1
            continue
        if ch.isdigit():
            j = i
            while j < len(expr) and (expr[j].isdigit() or expr[j] == "."):
                j += 1
            token = expr[i:j]
            out.append(f"Decimal('{token}')")
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


_JS_NULLS = {"null": "None", "true": "True", "false": "False"}


def js_to_python(expr: str) -> str:
    s = expr.strip()

    # 1) Replace keywords (outside strings) — simple, schema uses only single-quoted strings.
    def repl_kw(m: re.Match[str]) -> str:
        return _JS_NULLS[m.group(0)]

    s = re.sub(r"\b(null|true|false)\b", repl_kw, s)

    # 2) Convert ternary first (keeps JS operators inside pieces for next steps).
    s = convert_ternary(s)

    # 3) Operators
    s = s.replace("===", "==")
    s = s.replace("&&", " and ")
    s = s.replace("||", " or ")

    # '!' but not '!='
    s = re.sub(r"!([^=])", r" not \1", s)

    # 4) Math.min -> min
    s = s.replace("Math.min", "min")

    # 5) Wrap numbers to Decimal
    s = _wrap_numbers_as_decimal(s)

    return s


def safe_eval(expr: str, env: Dict[str, Any], cfg: SafeEvalConfig) -> Any:
    py = js_to_python(expr)
    tree = ast.parse(py, mode="eval")
    evaluator = SafeEvaluator(env=env, cfg=cfg)
    return evaluator.visit(tree)


# ----- helpers per schema.meta.engine.expression_notes.helpers -----


def includes(array_or_string: Any, value: Any) -> bool:
    if array_or_string is None:
        return False
    if isinstance(array_or_string, str):
        return str(value) in array_or_string
    try:
        return value in array_or_string
    except TypeError:
        return False


def anySelected(arr: Any) -> bool:
    if not arr:
        return False
    return len(list(arr)) > 0


def count(arr: Any) -> int:
    if not arr:
        return 0
    return len(list(arr))


def coalesce(*args: Any) -> Any:
    for a in args:
        if a is not None:
            return a
    return None
