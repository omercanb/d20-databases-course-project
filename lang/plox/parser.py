from typing import List, Optional

from plox.types import expr as expr_module
from plox.types import stmt as stmt_module
from plox.types.lox_token import Token
from plox.types.token_type import TokenType


class ParseError(Exception):
    pass


class Parser:
    def __init__(self, tokens: List[Token]) -> None:
        self.tokens: List[Token] = tokens
        self.current: int = 0
        self.current_loop_nesting_depth: int = 0

    def parse(self) -> List[stmt_module.Stmt]:
        statements = []
        while not self.is_at_end():
            stmt = self.declaration()
            if stmt is not None:
                statements.append(stmt)
        return statements

    def declaration(self) -> Optional[stmt_module.Stmt]:
        try:
            if self.match(TokenType.FUN):
                return self.function("function")
            if self.match(TokenType.VAR):
                return self.var_declaration()
            return self.statement()
        except ParseError:
            self.synchronize()
            return None

    # kind is used to distinguish functions and methods
    def function(self, kind: str) -> stmt_module.Function:
        name = self.consume(TokenType.IDENTIFIER, f"Expect {kind} name.")
        self.consume(TokenType.LEFT_PAREN, f"Expect '(' after {kind} name.")
        params = []
        if not self.check(TokenType.RIGHT_PAREN):
            while True:
                if len(params) >= 255:
                    self.error(self.peek(), "Can't have more than 255 parameters.")
                params.append(
                    self.consume(TokenType.IDENTIFIER, "Expect parameter name.")
                )
                if not self.match(TokenType.COMMA):
                    break
        self.consume(TokenType.RIGHT_PAREN, "Expect ')' after parameters.")
        self.consume(TokenType.LEFT_BRACE, f"Expect '{{' before {kind} body.")
        body = self.block()
        return stmt_module.Function(name, params, body)

    def return_(self) -> stmt_module.Return:
        keyword = self.previous()
        value = None
        if not self.check(TokenType.SEMICOLON):
            # An expression is returned
            value = self.expression()

        self.consume(TokenType.SEMICOLON, "Expect ';' after return value.")
        return stmt_module.Return(keyword, value)

    def var_declaration(self) -> stmt_module.Var:
        name = self.consume(TokenType.IDENTIFIER, "Expect variable name.")
        initializer = None
        if self.match(TokenType.EQUAL):
            initializer = self.expression()
        self.consume(TokenType.SEMICOLON, "Expect ';' after variable declaration.")
        return stmt_module.Var(name, initializer)

    def statement(self) -> stmt_module.Stmt:
        if self.match(TokenType.FOR):
            return self.for_statement()
        if self.match(TokenType.IF):
            return self.if_statement()
        if self.match(TokenType.RETURN):
            return self.return_()
        if self.match(TokenType.WHILE):
            return self.while_statement()
        if self.match(TokenType.LEFT_BRACE):
            return stmt_module.Block(self.block())
        if self.match(TokenType.BREAK):
            return self.break_statement()
        if self.match(TokenType.CONTINUE):
            return self.continue_statement()
        return self.expression_statement()

    def for_statement(self):
        self.consume(TokenType.LEFT_PAREN, "Expect '(' after 'for'.")
        initializer = None
        if self.match(TokenType.SEMICOLON):
            initializer = None
        elif self.match(TokenType.VAR):
            initializer = self.var_declaration()
        else:
            initializer = self.expression_statement()

        condition = None
        if not self.check(TokenType.SEMICOLON):
            condition = self.expression()
        self.consume(TokenType.SEMICOLON, "Expect ';' after loop condition.")

        increment = None
        if not self.check(TokenType.RIGHT_PAREN):
            increment = self.expression()
        self.consume(TokenType.RIGHT_PAREN, "Expect ')' after for clauses.")

        self.current_loop_nesting_depth += 1
        body = self.statement()
        self.current_loop_nesting_depth -= 1

        return stmt_module.For(initializer, condition, increment, body)

    def if_statement(self):
        self.consume(TokenType.LEFT_PAREN, "Expect '(' after 'if'.")
        condition = self.expression()
        self.consume(TokenType.RIGHT_PAREN, "Expect ')' after if condition.")

        then_branch = self.statement()
        else_branch = None
        if self.match(TokenType.ELSE):
            else_branch = self.statement()

        return stmt_module.If(condition, then_branch, else_branch)

    def while_statement(self):
        self.consume(TokenType.LEFT_PAREN, "Expect '(' after 'while'.")
        condition = self.expression()
        self.consume(TokenType.RIGHT_PAREN, "Expect ')' after condition.")
        self.current_loop_nesting_depth += 1
        body = self.statement()
        self.current_loop_nesting_depth -= 1
        return stmt_module.While(condition, body)

    def break_statement(self):
        if self.current_loop_nesting_depth == 0:
            self.error(self.previous(), "break not in loop.")
        self.consume(TokenType.SEMICOLON, "Expect ';' after 'break'.")
        return stmt_module.Break()

    def continue_statement(self):
        if self.current_loop_nesting_depth == 0:
            self.error(self.previous(), "continue not in loop.")
        self.consume(TokenType.SEMICOLON, "Expect ';' after 'continue'.")
        return stmt_module.Continue()

    def block(self) -> List[stmt_module.Stmt]:
        statements = []
        while not self.check(TokenType.RIGHT_BRACE) and not self.is_at_end():
            statements.append(self.declaration())
        self.consume(TokenType.RIGHT_BRACE, "Expect '}' after block.")
        return statements

    def expression_statement(self):
        expr = self.expression()
        self.consume(TokenType.SEMICOLON, "Expect ';' after expression.")
        return stmt_module.Expression(expr)

    def expression(self) -> expr_module.Expr:
        return self.assignment()

    def assignment(self) -> expr_module.Expr:
        expr = self.or_()
        if self.match(TokenType.EQUAL):
            equals = self.previous()
            value = self.assignment()
            if isinstance(expr, expr_module.Variable):
                return expr_module.Assign(expr.name, value)
            self.error(equals, "Invalid assignment target.")
        return expr

    def or_(self) -> expr_module.Expr:
        expr = self.and_()
        while self.match(TokenType.OR):
            op = self.previous()
            right = self.and_()
            expr = expr_module.Logical(expr, op, right)
        return expr

    def and_(self) -> expr_module.Expr:
        expr = self.equality()
        while self.match(TokenType.AND):
            op = self.previous()
            right = self.equality()
            expr = expr_module.Logical(expr, op, right)
        return expr

    def equality(self) -> expr_module.Expr:
        expr = self.comparison()
        while self.match(TokenType.BANG_EQUAL, TokenType.EQUAL_EQUAL):
            op = self.previous()
            right = self.comparison()
            expr = expr_module.Binary(expr, op, right)
        return expr

    def comparison(self) -> expr_module.Expr:
        expr = self.term()
        while self.match(
            TokenType.GREATER,
            TokenType.GREATER_EQUAL,
            TokenType.LESS,
            TokenType.LESS_EQUAL,
        ):
            op = self.previous()
            right = self.term()
            expr = expr_module.Binary(expr, op, right)
        return expr

    def term(self) -> expr_module.Expr:
        expr = self.factor()
        while self.match(TokenType.MINUS, TokenType.PLUS):
            op = self.previous()
            right = self.factor()
            expr = expr_module.Binary(expr, op, right)
        return expr

    def factor(self) -> expr_module.Expr:
        expr = self.unary()
        while self.match(TokenType.SLASH, TokenType.STAR):
            op = self.previous()
            right = self.unary()
            expr = expr_module.Binary(expr, op, right)
        return expr

    def unary(self) -> expr_module.Expr:
        if self.match(TokenType.BANG, TokenType.MINUS):
            op = self.previous()
            right = self.unary()
            return expr_module.Unary(op, right)
        return self.call()

    def call(self) -> expr_module.Expr:
        expr = self.primary()
        while True:
            if self.match(TokenType.LEFT_PAREN):
                expr = self.finish_call(expr)
            else:
                break
        return expr

    def finish_call(self, callee: expr_module.Expr) -> expr_module.Call:
        arguments = []
        if not self.check(TokenType.RIGHT_PAREN):
            while True:
                if len(arguments) >= 255:
                    self.error(self.peek(), "Can't have more than 255 arguments.")
                arguments.append(self.expression())
                if not self.match(TokenType.COMMA):
                    break
        paren = self.consume(TokenType.RIGHT_PAREN, "Expect ')' after arguments.")
        return expr_module.Call(callee, paren, arguments)

    def primary(self) -> expr_module.Expr:
        if self.match(TokenType.FALSE):
            return expr_module.Literal(False)
        if self.match(TokenType.TRUE):
            return expr_module.Literal(True)
        if self.match(TokenType.NIL):
            return expr_module.Literal(None)
        if self.match(TokenType.NUMBER, TokenType.STRING):
            return expr_module.Literal(self.previous().literal)
        if self.match(TokenType.IDENTIFIER):
            return expr_module.Variable(self.previous())
        if self.match(TokenType.LEFT_PAREN):
            expr = self.expression()
            self.consume(TokenType.RIGHT_PAREN, "Expect ')' after expression.")
            return expr_module.Grouping(expr)
        raise self.error(self.peek(), "Expect expression.")

    def match(self, *types: TokenType) -> bool:
        for token_type in types:
            if self.check(token_type):
                self.advance()
                return True
        return False

    def check(self, token_type: TokenType) -> bool:
        if self.is_at_end():
            return False
        return self.peek().token_type == token_type

    def advance(self) -> Token:
        if not self.is_at_end():
            self.current += 1
        return self.previous()

    def is_at_end(self) -> bool:
        return self.peek().token_type == TokenType.EOF

    def peek(self) -> Token:
        return self.tokens[self.current]

    def previous(self) -> Token:
        return self.tokens[self.current - 1]

    def consume(self, token_type: TokenType, message: str) -> Token:
        if self.check(token_type):
            return self.advance()
        raise self.error(self.peek(), message)

    def error(self, token: Token, message: str) -> ParseError:
        from plox import lox

        lox.error(token.line, message)
        raise ParseError()

    def synchronize(self) -> None:
        self.advance()
        while not self.is_at_end():
            if self.previous().token_type == TokenType.SEMICOLON:
                return
            if self.peek().token_type in [
                TokenType.FUN,
                TokenType.VAR,
                TokenType.FOR,
                TokenType.IF,
                TokenType.WHILE,
                TokenType.PRINT,
            ]:
                return
            self.advance()
