import io
from contextlib import redirect_stderr, redirect_stdout

from flask import g, jsonify, render_template, request
from plox.runner import LoxRunner

from d20.db.game import InvalidSymbolError
from d20.db.market.orders import get_orders_by_script
from d20.db.market.participant_inventory import get_participant_inventory
from d20.db.market.trading_scripts import (
    create_script,
    delete_script,
    get_script,
    get_scripts_by_owner,
    update_script,
)
from d20.routes.market import market_api

from . import bp, market_login_required


@bp.route("/algorithmic", methods=("GET",))
@market_login_required
def algorithmic():
    participant_id = g.market_participant["id"]
    inventory = get_participant_inventory(participant_id)
    scripts = get_scripts_by_owner(participant_id)

    return render_template(
        "market/algorithmic.html",
        active_tab="algorithmic",
        participant=g.market_participant,
        inventory=inventory,
        scripts=scripts,
    )


@bp.route("/algorithmic/run", methods=("POST",))
@market_login_required
def algorithmic_run():
    """Execute algorithmic trading code and return results as JSON."""
    code = request.json.get("code", "")
    script_id = request.json.get("script_id")
    participant_id = g.market_participant["id"]
    script = get_script(script_id)
    update_script(script_id, script["name"], code)

    output, err = run_plox_and_capture(code, script_id)
    if err:
        result = {
            "success": False,
            "output": output,
            "error": str(err),
        }
    else:
        result = {
            "success": True,
            "output": output,
            "error": None,
        }
    print(result)
    return jsonify(result)


def run_plox_and_capture(code, script_id):
    runner = LoxRunner()
    runner.add_builtin("get_price", market_api.GetPrice())
    runner.add_builtin("market_buy", market_api.MarketBuy(script_id))
    runner.add_builtin("market_sell", market_api.MarketSell(script_id))
    with redirect_stdout(io.StringIO()) as stdout:
        with redirect_stderr(io.StringIO()) as stderr:
            try:
                runner.run(code)
                output = stdout.getvalue()
                errors = stderr.getvalue()
                if errors:
                    return output, errors
                else:
                    return output, None
            except InvalidSymbolError as e:
                output = stdout.getvalue()
                return output, f"Symbol Error: {e}"
            except Exception as e:
                output = stdout.getvalue()
                raise e
                return output, f"Error: {e} Error Type: {type(e)}"


# def run_plox(code):
#     scanner = Scanner(source)
#     tokens = scanner.scan_tokens()
#
#     parser = Parser(tokens)
#     statements = parser.parse()
#
#     if had_error:
#         return
#
#     if print_tree:
#         for statement in statements:
#             AstPrinter().print_stmt(statement)
#
#     if had_error:
#         return
#
#     interpreter.interpret(statements)
