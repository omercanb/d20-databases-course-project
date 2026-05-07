"""Tournament database access layer."""
import math
import random

from d20.db import get_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rows(cursor):
    return [dict(r) for r in cursor.fetchall()]

def _row(cursor):
    r = cursor.fetchone()
    return dict(r) if r else None


# ---------------------------------------------------------------------------
# Store / owner helpers
# ---------------------------------------------------------------------------

def get_store_games(store_id):
    db = get_db()
    return _rows(db.execute(
        """
        SELECT DISTINCT g.id, g.name
        FROM Game g
        JOIN GameCopy gc ON gc.game_id = g.id
        WHERE gc.store_id = %s
        ORDER BY g.name
        """,
        (store_id,),
    ))

def get_store_tables(store_id):
    db = get_db()
    return _rows(db.execute(
        'SELECT store_id, table_num, capacity FROM "Table" WHERE store_id = %s ORDER BY table_num',
        (store_id,),
    ))


# ---------------------------------------------------------------------------
# Tournament CRUD
# ---------------------------------------------------------------------------

def create_tournament(store_id, game_id, name, fmt, max_participants,
                      entry_fee_points, sponsor_name, start_date, end_date,
                      prize_description, table_nums):
    """Create a tournament and assign the given tables to it."""
    db = get_db()
    row = _row(db.execute(
        """
        INSERT INTO Tournament
            (store_id, game_id, name, format, max_participants, entry_fee_points,
             sponsor_name, start_date, end_date, prize_description)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
        """,
        (store_id, game_id, name, fmt, max_participants, entry_fee_points,
         sponsor_name, start_date, end_date, prize_description),
    ))
    t_id = row["id"]
    for tnum in table_nums:
        db.execute(
            "INSERT INTO TournamentTable (tournament_id, store_id, table_num) VALUES (%s,%s,%s)",
            (t_id, store_id, tnum),
        )
    db.commit()
    return t_id


def get_tournament(tournament_id):
    db = get_db()
    return _row(db.execute(
        """
        SELECT t.*, g.name AS game_name, s.name AS store_name
        FROM Tournament t
        JOIN Game g ON g.id = t.game_id
        JOIN Store s ON s.id = t.store_id
        WHERE t.id = %s
        """,
        (tournament_id,),
    ))


def get_tournaments_for_store(store_id):
    db = get_db()
    return _rows(db.execute(
        """
        SELECT t.*, g.name AS game_name,
               (SELECT COUNT(*) FROM TournamentParticipant tp WHERE tp.tournament_id = t.id) AS participant_count
        FROM Tournament t
        JOIN Game g ON g.id = t.game_id
        WHERE t.store_id = %s
        ORDER BY t.start_date DESC
        """,
        (store_id,),
    ))


def get_open_tournaments(game_id=None, date_from=None, date_to=None,
                          fmt=None, max_fee=None, store_id=None):
    """Browse open tournaments with optional filters."""
    db = get_db()
    clauses = ["t.status = 'registration_open'"]
    params = []
    if store_id:
        clauses.append("t.store_id = %s"); params.append(store_id)
    if game_id:
        clauses.append("t.game_id = %s"); params.append(game_id)
    if date_from:
        clauses.append("t.start_date >= %s"); params.append(date_from)
    if date_to:
        clauses.append("t.start_date <= %s"); params.append(date_to)
    if fmt:
        clauses.append("t.format = %s"); params.append(fmt)
    if max_fee is not None:
        clauses.append("t.entry_fee_points <= %s"); params.append(max_fee)

    where = " AND ".join(clauses)
    return _rows(db.execute(
        f"""
        SELECT t.*, g.name AS game_name, s.name AS store_name,
               (SELECT COUNT(*) FROM TournamentParticipant tp WHERE tp.tournament_id = t.id) AS participant_count
        FROM Tournament t
        JOIN Game g ON g.id = t.game_id
        JOIN Store s ON s.id = t.store_id
        WHERE {where}
        ORDER BY t.start_date ASC
        """,
        params,
    ))


def close_registration(tournament_id, store_id):
    db = get_db()
    db.execute(
        """
        UPDATE Tournament
        SET registration_open = FALSE, status = 'in_progress'
        WHERE id = %s AND store_id = %s
        """,
        (tournament_id, store_id),
    )
    db.commit()


def complete_tournament(tournament_id, store_id):
    """Mark tournament completed and remove all remaining tournament sessions."""
    db = get_db()
    db.execute(
        "UPDATE Tournament SET status = 'completed' WHERE id = %s AND store_id = %s",
        (tournament_id, store_id),
    )
    # Clean up tournament sessions for all remaining participants
    db.execute(
        """
        DELETE FROM Session
        WHERE is_tournament = TRUE AND tournament_id = %s
        """,
        (tournament_id,),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Participants
# ---------------------------------------------------------------------------

def get_participants(tournament_id):
    db = get_db()
    return _rows(db.execute(
        """
        SELECT tp.*, u.username
        FROM TournamentParticipant tp
        JOIN "User" u ON u.id = tp.user_id
        WHERE tp.tournament_id = %s
        ORDER BY tp.registered_at
        """,
        (tournament_id,),
    ))


def is_registered(tournament_id, user_id):
    db = get_db()
    r = db.execute(
        "SELECT 1 FROM TournamentParticipant WHERE tournament_id=%s AND user_id=%s",
        (tournament_id, user_id),
    ).fetchone()
    return r is not None


def register_participant(tournament_id, user_id):
    """Insert into TournamentParticipant; the DB trigger handles all eligibility checks."""
    db = get_db()
    db.execute(
        "INSERT INTO TournamentParticipant (tournament_id, user_id) VALUES (%s, %s)",
        (tournament_id, user_id),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Bracket generation (application layer)
# ---------------------------------------------------------------------------

def _get_allocated_tables(tournament_id):
    db = get_db()
    return _rows(db.execute(
        "SELECT store_id, table_num FROM TournamentTable WHERE tournament_id=%s ORDER BY table_num",
        (tournament_id,),
    ))


def generate_single_elimination_bracket(tournament_id):
    """Generate a seeded-random single-elimination bracket and persist TournamentMatch rows."""
    db = get_db()
    participants = get_participants(tournament_id)
    tables = _get_allocated_tables(tournament_id)
    if not tables:
        raise ValueError("No tables have been assigned to this tournament.")
    if len(participants) < 2:
        raise ValueError("Need at least 2 participants to generate a bracket.")

    random.shuffle(participants)
    n = len(participants)
    # Pad to next power of 2
    size = 1
    while size < n:
        size *= 2

    total_rounds = int(math.log2(size))
    table_cycle = 0

    # ── Step 1: create all round-1 match rows (no winner yet) ──────────────
    round1_ids = []
    bye_match_ids = []          # track which round-1 matches are BYEs
    player_idx = 0
    for m in range(size // 2):
        p1 = participants[player_idx]["user_id"] if player_idx < n else None
        player_idx += 1
        p2 = participants[player_idx]["user_id"] if player_idx < n else None
        player_idx += 1

        is_bye = (p2 is None)
        t = tables[table_cycle % len(tables)]
        table_cycle += 1

        row = _row(db.execute(
            """
            INSERT INTO TournamentMatch
                (tournament_id, round_number, match_number, player1_id, player2_id,
                 is_bye, store_id, table_num)
            VALUES (%s,1,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (tournament_id, m + 1, p1, p2, is_bye, t["store_id"], t["table_num"]),
        ))
        mid = row["id"]
        round1_ids.append(mid)
        if is_bye and p1 is not None:
            bye_match_ids.append((mid, p1))

    # ── Step 2: create subsequent rounds and wire next_match_id ────────────
    prev_round_ids = round1_ids
    for rnd in range(2, total_rounds + 1):
        matches_in_round = size // (2 ** rnd)
        current_round_ids = []
        for m in range(matches_in_round):
            t = tables[table_cycle % len(tables)]
            table_cycle += 1
            row = _row(db.execute(
                """
                INSERT INTO TournamentMatch
                    (tournament_id, round_number, match_number, store_id, table_num)
                VALUES (%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (tournament_id, rnd, m + 1, t["store_id"], t["table_num"]),
            ))
            current_round_ids.append(row["id"])
        # Wire next_match_id for every match in the previous round
        for i, prev_id in enumerate(prev_round_ids):
            next_id = current_round_ids[i // 2]
            db.execute(
                "UPDATE TournamentMatch SET next_match_id=%s WHERE id=%s",
                (next_id, prev_id),
            )
        prev_round_ids = current_round_ids

    # ── Step 3: NOW auto-advance BYE winners (next_match_id is wired) ──────
    # The DB trigger fn_advance_tournament_bracket will fire and fill in
    # the correct slot in the next round match.
    for mid, winner_id in bye_match_ids:
        db.execute(
            "UPDATE TournamentMatch SET winner_id=%s, is_played=TRUE WHERE id=%s",
            (winner_id, mid),
        )

    db.commit()


def generate_round_robin_bracket(tournament_id):
    """Generate a full round-robin schedule."""
    db = get_db()
    participants = get_participants(tournament_id)
    tables = _get_allocated_tables(tournament_id)
    if not tables:
        raise ValueError("No tables have been assigned to this tournament.")
    if len(participants) < 2:
        raise ValueError("Need at least 2 participants to generate a bracket.")

    players = [p["user_id"] for p in participants]
    # Add dummy for odd count (bye)
    if len(players) % 2 == 1:
        players.append(None)

    n = len(players)
    rounds = n - 1
    table_cycle = 0
    match_num = 0

    for rnd in range(rounds):
        half = n // 2
        pairs = [(players[i], players[n - 1 - i]) for i in range(half)]
        for p1, p2 in pairs:
            if p1 is None or p2 is None:
                continue  # skip bye rounds
            match_num += 1
            t = tables[table_cycle % len(tables)]
            table_cycle += 1
            db.execute(
                """
                INSERT INTO TournamentMatch
                    (tournament_id, round_number, match_number, player1_id, player2_id,
                     store_id, table_num)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                """,
                (tournament_id, rnd + 1, match_num, p1, p2, t["store_id"], t["table_num"]),
            )
        # Rotate players keeping index 0 fixed
        players = [players[0]] + [players[-1]] + players[1:-1]

    db.commit()


# ---------------------------------------------------------------------------
# Matches
# ---------------------------------------------------------------------------

def get_matches(tournament_id):
    db = get_db()
    return _rows(db.execute(
        """
        SELECT tm.*,
               u1.username AS player1_name,
               u2.username AS player2_name,
               uw.username AS winner_name
        FROM TournamentMatch tm
        LEFT JOIN "User" u1 ON u1.id = tm.player1_id
        LEFT JOIN "User" u2 ON u2.id = tm.player2_id
        LEFT JOIN "User" uw ON uw.id = tm.winner_id
        WHERE tm.tournament_id = %s
        ORDER BY tm.round_number, tm.match_number
        """,
        (tournament_id,),
    ))


def record_match_result(match_id, winner_id, score_p1, score_p2, tournament_id, store_id):
    db = get_db()
    # Verify ownership
    t = _row(db.execute("SELECT store_id FROM Tournament WHERE id=%s", (tournament_id,)))
    if not t or t["store_id"] != store_id:
        raise PermissionError("Not your tournament.")
    db.execute(
        """
        UPDATE TournamentMatch
        SET winner_id=%s, score_player1=%s, score_player2=%s
        WHERE id=%s AND tournament_id=%s
        """,
        (winner_id, score_p1, score_p2, match_id, tournament_id),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

def get_results(tournament_id):
    db = get_db()
    return _rows(db.execute(
        """
        SELECT tr.*, u.username
        FROM TournamentResult tr
        JOIN "User" u ON u.id = tr.user_id
        WHERE tr.tournament_id = %s
        ORDER BY tr.place
        """,
        (tournament_id,),
    ))


def record_result(tournament_id, user_id, place, prize_text, points_awarded, store_id):
    db = get_db()
    t = _row(db.execute("SELECT store_id FROM Tournament WHERE id=%s", (tournament_id,)))
    if not t or t["store_id"] != store_id:
        raise PermissionError("Not your tournament.")
    db.execute(
        """
        INSERT INTO TournamentResult
            (tournament_id, user_id, place, prize_text, points_awarded)
        VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT (tournament_id, user_id) DO UPDATE
        SET place=EXCLUDED.place, prize_text=EXCLUDED.prize_text, points_awarded=EXCLUDED.points_awarded
        """,
        (tournament_id, user_id, place, prize_text, points_awarded),
    )
    db.commit()


def all_matches_done(tournament_id):
    """Return True if every match (that has both players) has a recorded winner."""
    db = get_db()
    row = db.execute(
        """
        SELECT COUNT(*) AS pending
        FROM TournamentMatch
        WHERE tournament_id = %s
          AND player1_id IS NOT NULL
          AND player2_id IS NOT NULL
          AND is_bye = FALSE
          AND (winner_id IS NULL OR is_played = FALSE)
        """,
        (tournament_id,),
    ).fetchone()
    return row["pending"] == 0


def compute_standings_single_elimination(tournament_id):
    """
    Auto-compute final standings for a single-elimination tournament.
    Returns list of {user_id, username, place} sorted by place.
    1st  = winner of the final match
    2nd  = loser of the final match
    3rd+ = losers from semi-finals, quarter-finals, etc.
    """
    db = get_db()
    matches = _rows(db.execute(
        """
        SELECT tm.*, u1.username AS player1_name, u2.username AS player2_name,
               uw.username AS winner_name
        FROM TournamentMatch tm
        LEFT JOIN "User" u1 ON u1.id = tm.player1_id
        LEFT JOIN "User" u2 ON u2.id = tm.player2_id
        LEFT JOIN "User" uw ON uw.id = tm.winner_id
        WHERE tm.tournament_id = %s AND tm.is_bye = FALSE AND tm.player1_id IS NOT NULL
        ORDER BY tm.round_number DESC, tm.match_number
        """,
        (tournament_id,),
    ))

    max_round = max((m["round_number"] for m in matches), default=0)
    # place starts at 1 for the champion
    place = 1
    standings = []
    for rnd in range(max_round, 0, -1):
        rnd_matches = [m for m in matches if m["round_number"] == rnd]
        for m in rnd_matches:
            loser_id = m["player1_id"] if m["winner_id"] == m["player2_id"] else m["player2_id"]
            loser_name = m["player1_name"] if m["winner_id"] == m["player2_id"] else m["player2_name"]
            if rnd == max_round:
                # Final: winner is 1st, loser is 2nd
                standings.append({"user_id": m["winner_id"], "username": m["winner_name"], "place": 1})
                standings.append({"user_id": loser_id, "username": loser_name, "place": 2})
                place = 3
            else:
                standings.append({"user_id": loser_id, "username": loser_name, "place": place})
                place += 1
    return standings


def compute_standings_round_robin(tournament_id):
    """
    Auto-compute standings for round robin: rank by wins, then by point differential.
    """
    db = get_db()
    matches = _rows(db.execute(
        """
        SELECT player1_id, player2_id, winner_id, score_player1, score_player2
        FROM TournamentMatch
        WHERE tournament_id = %s AND winner_id IS NOT NULL
        """,
        (tournament_id,),
    ))
    participants = get_participants(tournament_id)
    stats = {p["user_id"]: {"user_id": p["user_id"], "username": p["username"], "wins": 0, "diff": 0} for p in participants}

    for m in matches:
        w, l = m["winner_id"], (m["player2_id"] if m["winner_id"] == m["player1_id"] else m["player1_id"])
        if w in stats:
            stats[w]["wins"] += 1
        try:
            s1 = int(m["score_player1"] or 0)
            s2 = int(m["score_player2"] or 0)
            if m["winner_id"] == m["player1_id"]:
                if m["player1_id"] in stats: stats[m["player1_id"]]["diff"] += s1 - s2
                if m["player2_id"] in stats: stats[m["player2_id"]]["diff"] += s2 - s1
            else:
                if m["player2_id"] in stats: stats[m["player2_id"]]["diff"] += s2 - s1
                if m["player1_id"] in stats: stats[m["player1_id"]]["diff"] += s1 - s2
        except (ValueError, TypeError):
            pass

    ranked = sorted(stats.values(), key=lambda x: (-x["wins"], -x["diff"]))
    return [{"user_id": r["user_id"], "username": r["username"], "place": i + 1} for i, r in enumerate(ranked)]


# ---------------------------------------------------------------------------
# Reports (query the views)
# ---------------------------------------------------------------------------

def report_popular_games():
    return _rows(get_db().execute("SELECT * FROM vw_popular_tournament_games"))

def report_participation_stats():
    return _rows(get_db().execute("SELECT * FROM vw_tournament_participation_stats"))

def report_revenue():
    return _rows(get_db().execute("SELECT * FROM vw_tournament_revenue"))

def report_top_players():
    return _rows(get_db().execute("SELECT * FROM vw_top_tournament_players"))
