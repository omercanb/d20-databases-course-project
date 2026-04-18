"""An Instanced Version of Lox.py"""

import sys

from plox.ast_printer import AstPrinter
from plox.interpreter import Interpreter
from plox.parser import Parser
from plox.scanner import Scanner
from plox.types.lox_callable import LoxCallable


class LoxRunner:
    def __init__(self):
        self.had_error = False
        self.had_runtime_error = False
        self.print_tree = False
        self.interpreter = Interpreter()

    def add_builtin(self, fn_name, fn: LoxCallable):
        self.interpreter.globals.define(fn_name, fn)

    # Used to add builtin functions to lox
    def get_interpreter(self):
        return self.interpreter

    def run(self, source: str) -> None:
        scanner = Scanner(source)
        tokens = scanner.scan_tokens()

        parser = Parser(tokens)
        statements = parser.parse()

        if self.had_error:
            return

        if self.print_tree:
            for statement in statements:
                AstPrinter().print_stmt(statement)

        if self.had_error:
            return

        self.interpreter.interpret(statements)

    def error(self, line: int, message: str) -> None:
        self.report(line, "", message)
        self.had_error = True

    def runtime_error(self, error) -> None:
        print(f"[line {error.token.line}] Error: {error.message}", file=sys.stderr)
        self.had_runtime_error = True

    def report(self, line: int, where: str, message: str) -> None:
        print(f"[line {line}] Error{where}: {message}", file=sys.stderr)
