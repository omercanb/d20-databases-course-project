"""Tournament routes — store (admin) and customer (user) views."""
from datetime import datetime

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from d20.db.tournament import (
    all_matches_done,
    close_registration,
    complete_tournament,
    compute_standings_round_robin,
    compute_standings_single_elimination,
    create_tournament,
    generate_round_robin_bracket,
    generate_single_elimination_bracket,
    get_matches,
    get_open_tournaments,
    get_participants,
    get_results,
    get_store_games,
    get_store_tables,
    get_tournament,
    get_tournaments_for_store,
    is_registered,
    record_match_result,
    record_result,
    register_participant,
    report_participation_stats,
    report_popular_games,
    report_revenue,
    report_top_players,
)

bp = Blueprint("tournament", __name__)

# ── guard decorators (same pattern as the rest of the app) ──────────────────

def _user_required(view):
    import functools
    @functools.wraps(view)
    def wrapped(**kw):
        if g.user is None:
            return redirect(url_for("auth.login"))
        return view(**kw)
    return wrapped


def _store_required(view):
    import functools
    @functools.wraps(view)
    def wrapped(**kw):
        if g.store is None:
            return redirect(url_for("auth.loginstore"))
        return view(**kw)
    return wrapped


# ===========================================================================
# CUSTOMER VIEWS
# ===========================================================================

@bp.route("/tournaments")
def browse_tournaments():
    """Public listing of open tournaments with filters."""
    game_id   = request.args.get("game_id",  type=int)
    date_from = request.args.get("date_from") or None
    date_to   = request.args.get("date_to")   or None
    fmt       = request.args.get("format")    or None
    max_fee   = request.args.get("max_fee",   type=int)

    tournaments = get_open_tournaments(
        game_id=game_id,
        date_from=date_from,
        date_to=date_to,
        fmt=fmt,
        max_fee=max_fee,
    )
    # Distinct games for the filter dropdown
    from d20.db import get_db
    all_games = [dict(r) for r in get_db().execute(
        "SELECT DISTINCT g.id, g.name FROM Game g JOIN Tournament t ON t.game_id = g.id ORDER BY g.name"
    ).fetchall()]

    return render_template(
        "tournament/browse.html",
        tournaments=tournaments,
        all_games=all_games,
        selected_game_id=game_id,
        selected_date_from=date_from,
        selected_date_to=date_to,
        selected_format=fmt,
        selected_max_fee=max_fee,
    )


@bp.route("/tournaments/<int:tournament_id>")
def tournament_detail(tournament_id):
    """Public detail page for a tournament."""
    t = get_tournament(tournament_id)
    if not t:
        abort(404)
    participants = get_participants(tournament_id)
    matches      = get_matches(tournament_id)
    results      = get_results(tournament_id)
    registered   = False
    if g.user:
        registered = is_registered(tournament_id, g.user["id"])

    # Group matches by round
    rounds = {}
    for m in matches:
        rounds.setdefault(m["round_number"], []).append(m)

    return render_template(
        "tournament/detail.html",
        tournament=t,
        participants=participants,
        rounds=rounds,
        results=results,
        registered=registered,
    )


@bp.route("/tournaments/<int:tournament_id>/register", methods=("POST",))
@_user_required
def register_for_tournament(tournament_id):
    t = get_tournament(tournament_id)
    if not t:
        abort(404)
    try:
        register_participant(tournament_id, g.user["id"])
        flash("Successfully registered for the tournament!")
    except Exception as exc:
        flash(f"Registration failed: {exc}")
    return redirect(url_for("tournament.tournament_detail", tournament_id=tournament_id))


# ===========================================================================
# STORE-OWNER / ADMIN VIEWS
# ===========================================================================

@bp.route("/mystore/tournaments")
@_store_required
def my_store_tournaments():
    tournaments = get_tournaments_for_store(g.store["id"])
    return render_template(
        "tournament/mystore_tournaments.html",
        tournaments=tournaments,
    )


@bp.route("/mystore/tournaments/create", methods=("GET", "POST"))
@_store_required
def create_tournament_form():
    store_id = g.store["id"]
    games  = get_store_games(store_id)
    tables = get_store_tables(store_id)

    if request.method == "POST":
        name             = request.form.get("name", "").strip()
        game_id          = request.form.get("game_id", type=int)
        fmt              = request.form.get("format")
        max_participants = request.form.get("max_participants", type=int)
        entry_fee_points = request.form.get("entry_fee_points", 0, type=int)
        sponsor_name     = request.form.get("sponsor_name", "").strip() or None
        start_date       = request.form.get("start_date")
        end_date         = request.form.get("end_date") or None
        prize_description = request.form.get("prize_description", "").strip() or None
        table_nums       = request.form.getlist("table_nums", type=int)

        if not name or not game_id or not fmt or not max_participants or not start_date:
            flash("Name, game, format, max participants, and start date are required.")
        elif not table_nums:
            flash("Select at least one table for the tournament.")
        else:
            try:
                t_id = create_tournament(
                    store_id=store_id,
                    game_id=game_id,
                    name=name,
                    fmt=fmt,
                    max_participants=max_participants,
                    entry_fee_points=entry_fee_points,
                    sponsor_name=sponsor_name,
                    start_date=start_date,
                    end_date=end_date,
                    prize_description=prize_description,
                    table_nums=table_nums,
                )
                flash("Tournament created successfully!")
                return redirect(url_for("tournament.manage_tournament", tournament_id=t_id))
            except Exception as exc:
                flash(f"Error creating tournament: {exc}")

    return render_template(
        "tournament/create_tournament.html",
        games=games,
        tables=tables,
    )


@bp.route("/mystore/tournaments/<int:tournament_id>")
@_store_required
def manage_tournament(tournament_id):
    t = get_tournament(tournament_id)
    if not t or t["store_id"] != g.store["id"]:
        abort(403)
    participants = get_participants(tournament_id)
    matches      = get_matches(tournament_id)
    results      = get_results(tournament_id)
    matches_done = all_matches_done(tournament_id) if matches else False

    rounds = {}
    for m in matches:
        rounds.setdefault(m["round_number"], []).append(m)

    return render_template(
        "tournament/manage_tournament.html",
        tournament=t,
        participants=participants,
        rounds=rounds,
        results=results,
        matches_done=matches_done,
    )


@bp.route("/mystore/tournaments/<int:tournament_id>/close-registration", methods=("POST",))
@_store_required
def close_tournament_registration(tournament_id):
    t = get_tournament(tournament_id)
    if not t or t["store_id"] != g.store["id"]:
        abort(403)
    try:
        close_registration(tournament_id, g.store["id"])
        flash("Registration closed. You can now generate the bracket.")
    except Exception as exc:
        flash(f"Error: {exc}")
    return redirect(url_for("tournament.manage_tournament", tournament_id=tournament_id))


@bp.route("/mystore/tournaments/<int:tournament_id>/generate-bracket", methods=("POST",))
@_store_required
def generate_bracket(tournament_id):
    t = get_tournament(tournament_id)
    if not t or t["store_id"] != g.store["id"]:
        abort(403)
    try:
        if t["format"] == "single_elimination":
            generate_single_elimination_bracket(tournament_id)
        else:
            generate_round_robin_bracket(tournament_id)
        flash("Bracket generated successfully!")
    except Exception as exc:
        flash(f"Error generating bracket: {exc}")
    return redirect(url_for("tournament.manage_tournament", tournament_id=tournament_id))


@bp.route("/mystore/tournaments/<int:tournament_id>/match/<int:match_id>/result", methods=("POST",))
@_store_required
def record_result_route(tournament_id, match_id):
    t = get_tournament(tournament_id)
    if not t or t["store_id"] != g.store["id"]:
        abort(403)
    winner_id  = request.form.get("winner_id", type=int)
    score_p1   = request.form.get("score_player1", "").strip() or None
    score_p2   = request.form.get("score_player2", "").strip() or None
    if not winner_id:
        flash("Please select a winner.")
        return redirect(url_for("tournament.manage_tournament", tournament_id=tournament_id))
    try:
        record_match_result(match_id, winner_id, score_p1, score_p2, tournament_id, g.store["id"])
        flash("Result recorded and bracket advanced.")
    except Exception as exc:
        flash(f"Error recording result: {exc}")
    return redirect(url_for("tournament.manage_tournament", tournament_id=tournament_id))


@bp.route("/mystore/tournaments/<int:tournament_id>/results/award", methods=("POST",))
@_store_required
def award_prizes_auto(tournament_id):
    """Auto-compute standings then apply prize points from the form."""
    t = get_tournament(tournament_id)
    if not t or t["store_id"] != g.store["id"]:
        abort(403)

    # Compute ordered standings
    if t["format"] == "single_elimination":
        standings = compute_standings_single_elimination(tournament_id)
    else:
        standings = compute_standings_round_robin(tournament_id)

    if not standings:
        flash("No match results found to compute standings.")
        return redirect(url_for("tournament.manage_tournament", tournament_id=tournament_id))

    # Pull the points-per-place from the form (place_1_pts, place_2_pts, …)
    errors = []
    for s in standings:
        place = s["place"]
        pts = request.form.get(f"pts_{place}", 0, type=int)
        prize_text = request.form.get(f"prize_{place}", "").strip() or None
        try:
            record_result(tournament_id, s["user_id"], place, prize_text, pts, g.store["id"])
        except Exception as exc:
            errors.append(str(exc))

    if errors:
        flash("Some prizes could not be saved: " + "; ".join(errors))
    else:
        flash(f"Prizes awarded to {len(standings)} players based on auto-computed standings!")
    return redirect(url_for("tournament.manage_tournament", tournament_id=tournament_id))


@bp.route("/mystore/tournaments/<int:tournament_id>/complete", methods=("POST",))
@_store_required
def complete_tournament_route(tournament_id):
    t = get_tournament(tournament_id)
    if not t or t["store_id"] != g.store["id"]:
        abort(403)
    try:
        complete_tournament(tournament_id, g.store["id"])
        flash("Tournament marked as completed and archived.")
    except Exception as exc:
        flash(f"Error: {exc}")
    return redirect(url_for("tournament.manage_tournament", tournament_id=tournament_id))


# ===========================================================================
# REPORTS (store-owner only)
# ===========================================================================

@bp.route("/mystore/tournaments/reports")
@_store_required
def tournament_reports():
    return render_template(
        "tournament/reports.html",
        popular_games=report_popular_games(),
        participation_stats=report_participation_stats(),
        revenue=report_revenue(),
        top_players=report_top_players(),
    )
