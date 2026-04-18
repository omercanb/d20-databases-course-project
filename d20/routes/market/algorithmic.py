import io
from contextlib import redirect_stderr, redirect_stdout

from flask import g, jsonify, render_template, request
from plox.lox import run

from d20.db.market.participant_inventory import get_participant_inventory

from . import bp, market_login_required


@bp.route("/algorithmic", methods=("GET",))
@market_login_required
def algorithmic():
    participant_id = g.market_participant["id"]
    inventory = get_participant_inventory(participant_id)

    return render_template(
        "market/algorithmic.html",
        active_tab="algorithmic",
        participant=g.market_participant,
        inventory=inventory,
    )


@bp.route("/algorithmic/run", methods=("POST",))
@market_login_required
def algorithmic_run():
    """Execute algorithmic trading code and return results as JSON."""
    code = request.json.get("code", "")
    participant_id = g.market_participant["id"]

    # TODO: Implement actual language execution here
    # For now, return a placeholder response
    output, err = run_plox(code)
    if err:
        result = {
            "success": False,
            "output": None,
            "error": str(err),
        }
    else:
        result = {
            "success": True,
            "output": output,
            "error": None,
        }
    return jsonify(result)


def run_plox(code):
    try:
        with redirect_stdout(io.StringIO()) as stdout:
            with redirect_stderr(io.StringIO()) as stderr:
                run(code)
        output = stdout.getvalue()
        errors = stderr.getvalue()
        if errors:
            return None, errors
        else:
            return output, None
    except Exception as e:
        return None, e
