"""
Safe formula engine for custom calculated columns in data exports.
Supports Excel-like functions evaluated per-row.

Column references use curly-brace syntax: {column_key}
Supported functions: CONCAT, UPPER, LOWER, LEFT, RIGHT, TRIM,
                     IF, ROUND, ABS, MIN, MAX,
                     YEAR, MONTH, DAY,
                     FORMAT_TIME, FORMAT_SCHEDULE
Operators: + - * / > < >= <= == !=
"""

import re
from datetime import date, time
from typing import Any, Dict, List, Optional, Union


# ── Token types ──────────────────────────────────────────────────

class TokenType:
    COLUMN_REF = "COLUMN_REF"
    STRING = "STRING"
    NUMBER = "NUMBER"
    FUNCTION = "FUNCTION"
    LPAREN = "LPAREN"
    RPAREN = "RPAREN"
    COMMA = "COMMA"
    OPERATOR = "OPERATOR"
    EOF = "EOF"


class Token:
    __slots__ = ("type", "value")

    def __init__(self, type: str, value: Any):
        self.type = type
        self.value = value

    def __repr__(self):
        return f"Token({self.type}, {self.value!r})"


# ── Tokenizer ────────────────────────────────────────────────────

FUNCTIONS = {
    "CONCAT", "UPPER", "LOWER", "LEFT", "RIGHT", "TRIM",
    "IF", "ROUND", "ABS", "MIN", "MAX",
    "YEAR", "MONTH", "DAY",
    "FORMAT_TIME", "FORMAT_SCHEDULE",
}

OPERATORS = {">=", "<=", "==", "!=", ">", "<", "+", "-", "*", "/"}


def tokenize(formula: str) -> List[Token]:
    tokens: List[Token] = []
    i = 0
    n = len(formula)

    while i < n:
        ch = formula[i]

        # Whitespace
        if ch in " \t\n\r":
            i += 1
            continue

        # Column reference {column_key}
        if ch == "{":
            end = formula.index("}", i + 1)
            tokens.append(Token(TokenType.COLUMN_REF, formula[i + 1 : end]))
            i = end + 1
            continue

        # String literal
        if ch == '"':
            j = i + 1
            s = ""
            while j < n and formula[j] != '"':
                if formula[j] == "\\" and j + 1 < n:
                    s += formula[j + 1]
                    j += 2
                else:
                    s += formula[j]
                    j += 1
            tokens.append(Token(TokenType.STRING, s))
            i = j + 1
            continue

        # Parentheses
        if ch == "(":
            tokens.append(Token(TokenType.LPAREN, "("))
            i += 1
            continue
        if ch == ")":
            tokens.append(Token(TokenType.RPAREN, ")"))
            i += 1
            continue

        # Comma
        if ch == ",":
            tokens.append(Token(TokenType.COMMA, ","))
            i += 1
            continue

        # Two-character operators
        if i + 1 < n and formula[i : i + 2] in OPERATORS:
            tokens.append(Token(TokenType.OPERATOR, formula[i : i + 2]))
            i += 2
            continue

        # Single-character operators
        if ch in "+-*/><=!":
            tokens.append(Token(TokenType.OPERATOR, ch))
            i += 1
            continue

        # Numbers
        if ch.isdigit() or (ch == "." and i + 1 < n and formula[i + 1].isdigit()):
            j = i
            has_dot = False
            while j < n and (formula[j].isdigit() or (formula[j] == "." and not has_dot)):
                if formula[j] == ".":
                    has_dot = True
                j += 1
            tokens.append(Token(TokenType.NUMBER, float(formula[i:j])))
            i = j
            continue

        # Identifiers (function names)
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (formula[j].isalnum() or formula[j] == "_"):
                j += 1
            word = formula[i:j].upper()
            if word in FUNCTIONS:
                tokens.append(Token(TokenType.FUNCTION, word))
            else:
                raise FormulaError(f"Unknown identifier: {formula[i:j]}")
            i = j
            continue

        raise FormulaError(f"Unexpected character: {ch}")

    tokens.append(Token(TokenType.EOF, None))
    return tokens


# ── AST Nodes ────────────────────────────────────────────────────

class ASTNode:
    pass


class ColumnRef(ASTNode):
    def __init__(self, key: str):
        self.key = key


class Literal(ASTNode):
    def __init__(self, value: Any):
        self.value = value


class FunctionCall(ASTNode):
    def __init__(self, name: str, args: List[ASTNode]):
        self.name = name
        self.args = args


class BinaryOp(ASTNode):
    def __init__(self, op: str, left: ASTNode, right: ASTNode):
        self.op = op
        self.left = left
        self.right = right


# ── Parser ───────────────────────────────────────────────────────

class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Token:
        return self.tokens[self.pos]

    def advance(self) -> Token:
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def expect(self, token_type: str) -> Token:
        token = self.advance()
        if token.type != token_type:
            raise FormulaError(f"Expected {token_type}, got {token.type}")
        return token

    def parse(self) -> ASTNode:
        node = self.parse_expression()
        if self.peek().type != TokenType.EOF:
            raise FormulaError(f"Unexpected token after expression: {self.peek()}")
        return node

    def parse_expression(self) -> ASTNode:
        return self.parse_comparison()

    def parse_comparison(self) -> ASTNode:
        left = self.parse_additive()
        while self.peek().type == TokenType.OPERATOR and self.peek().value in (">", "<", ">=", "<=", "==", "!="):
            op = self.advance().value
            right = self.parse_additive()
            left = BinaryOp(op, left, right)
        return left

    def parse_additive(self) -> ASTNode:
        left = self.parse_multiplicative()
        while self.peek().type == TokenType.OPERATOR and self.peek().value in ("+", "-"):
            op = self.advance().value
            right = self.parse_multiplicative()
            left = BinaryOp(op, left, right)
        return left

    def parse_multiplicative(self) -> ASTNode:
        left = self.parse_primary()
        while self.peek().type == TokenType.OPERATOR and self.peek().value in ("*", "/"):
            op = self.advance().value
            right = self.parse_primary()
            left = BinaryOp(op, left, right)
        return left

    def parse_primary(self) -> ASTNode:
        token = self.peek()

        if token.type == TokenType.COLUMN_REF:
            self.advance()
            return ColumnRef(token.value)

        if token.type == TokenType.STRING:
            self.advance()
            return Literal(token.value)

        if token.type == TokenType.NUMBER:
            self.advance()
            return Literal(token.value)

        if token.type == TokenType.FUNCTION:
            return self.parse_function_call()

        if token.type == TokenType.LPAREN:
            self.advance()
            node = self.parse_expression()
            self.expect(TokenType.RPAREN)
            return node

        raise FormulaError(f"Unexpected token: {token}")

    def parse_function_call(self) -> ASTNode:
        name = self.advance().value
        self.expect(TokenType.LPAREN)
        args: List[ASTNode] = []
        if self.peek().type != TokenType.RPAREN:
            args.append(self.parse_expression())
            while self.peek().type == TokenType.COMMA:
                self.advance()
                args.append(self.parse_expression())
        self.expect(TokenType.RPAREN)
        return FunctionCall(name, args)


# ── Evaluator ────────────────────────────────────────────────────

def _to_num(v: Any) -> float:
    if v is None or v == "":
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _to_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v)


def evaluate_node(node: ASTNode, row: Dict[str, Any]) -> Any:
    if isinstance(node, Literal):
        return node.value

    if isinstance(node, ColumnRef):
        return row.get(node.key, "")

    if isinstance(node, BinaryOp):
        left = evaluate_node(node.left, row)
        right = evaluate_node(node.right, row)
        op = node.op

        if op in (">", "<", ">=", "<=", "==", "!="):
            lv = _to_num(left) if isinstance(right, (int, float)) else _to_str(left)
            rv = _to_num(right) if isinstance(left, (int, float)) else _to_str(right)
            # Try numeric comparison first
            try:
                lv, rv = _to_num(left), _to_num(right)
            except Exception:
                lv, rv = _to_str(left), _to_str(right)
            if op == ">":
                return lv > rv
            if op == "<":
                return lv < rv
            if op == ">=":
                return lv >= rv
            if op == "<=":
                return lv <= rv
            if op == "==":
                return lv == rv
            if op == "!=":
                return lv != rv

        if op == "+":
            # String concatenation if either side is a string
            if isinstance(left, str) or isinstance(right, str):
                return _to_str(left) + _to_str(right)
            return _to_num(left) + _to_num(right)
        if op == "-":
            return _to_num(left) - _to_num(right)
        if op == "*":
            return _to_num(left) * _to_num(right)
        if op == "/":
            r = _to_num(right)
            if r == 0:
                return 0
            return _to_num(left) / r

    if isinstance(node, FunctionCall):
        args = [evaluate_node(a, row) for a in node.args]
        return _eval_function(node.name, args)

    raise FormulaError(f"Unknown AST node: {type(node)}")


def _eval_function(name: str, args: List[Any]) -> Any:
    if name == "CONCAT":
        return "".join(_to_str(a) for a in args)

    if name == "UPPER":
        return _to_str(args[0]).upper() if args else ""

    if name == "LOWER":
        return _to_str(args[0]).lower() if args else ""

    if name == "LEFT":
        s = _to_str(args[0]) if args else ""
        n = int(_to_num(args[1])) if len(args) > 1 else 0
        return s[:n]

    if name == "RIGHT":
        s = _to_str(args[0]) if args else ""
        n = int(_to_num(args[1])) if len(args) > 1 else 0
        return s[-n:] if n > 0 else ""

    if name == "TRIM":
        return _to_str(args[0]).strip() if args else ""

    if name == "IF":
        condition = args[0] if args else False
        true_val = args[1] if len(args) > 1 else ""
        false_val = args[2] if len(args) > 2 else ""
        return true_val if condition else false_val

    if name == "ROUND":
        val = _to_num(args[0]) if args else 0
        decimals = int(_to_num(args[1])) if len(args) > 1 else 0
        return round(val, decimals)

    if name == "ABS":
        return abs(_to_num(args[0])) if args else 0

    if name == "MIN":
        nums = [_to_num(a) for a in args]
        return min(nums) if nums else 0

    if name == "MAX":
        nums = [_to_num(a) for a in args]
        return max(nums) if nums else 0

    if name == "YEAR":
        s = _to_str(args[0]) if args else ""
        try:
            return int(s[:4])
        except (ValueError, IndexError):
            return 0

    if name == "MONTH":
        s = _to_str(args[0]) if args else ""
        try:
            return int(s[5:7])
        except (ValueError, IndexError):
            return 0

    if name == "DAY":
        s = _to_str(args[0]) if args else ""
        try:
            return int(s[8:10])
        except (ValueError, IndexError):
            return 0

    if name == "FORMAT_TIME":
        s = _to_str(args[0]) if args else ""
        # Already in HH:MM or HH:MM:SS format usually
        return s[:5] if len(s) >= 5 else s

    if name == "FORMAT_SCHEDULE":
        start = _to_str(args[0]) if args else ""
        end = _to_str(args[1]) if len(args) > 1 else ""
        st = start[:5] if len(start) >= 5 else start
        et = end[:5] if len(end) >= 5 else end
        if st and et:
            return f"{st}-{et}"
        return st or et

    raise FormulaError(f"Unknown function: {name}")


# ── Public API ───────────────────────────────────────────────────

class FormulaError(Exception):
    pass


class FormulaEngine:
    @staticmethod
    def evaluate(formula: str, row: Dict[str, Any]) -> Any:
        """Evaluate a formula string against a data row."""
        try:
            tokens = tokenize(formula)
            parser = Parser(tokens)
            ast = parser.parse()
            return evaluate_node(ast, row)
        except FormulaError:
            raise
        except Exception as e:
            raise FormulaError(f"Formula evaluation error: {e}")

    @staticmethod
    def validate(formula: str) -> Optional[str]:
        """Validate a formula and return error message or None if valid."""
        try:
            tokens = tokenize(formula)
            parser = Parser(tokens)
            parser.parse()
            return None
        except FormulaError as e:
            return str(e)
        except Exception as e:
            return f"Invalid formula: {e}"
