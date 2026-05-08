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
                      players_per_match, entry_fee_points, sponsor_name,
                      start_date, end_date, prize_description, table_nums, min_loyalty_tier=None):
    """Create a tournament and assign the given tables to it."""
    db = get_db()
    row = _row(db.execute(
        """
        INSERT INTO Tournament
            (store_id, game_id, name, format, max_participants, players_per_match,
             entry_fee_points, sponsor_name, start_date, end_date, prize_description, min_loyalty_tier)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
        """,
        (store_id, game_id, name, fmt, max_participants, players_per_match,
         entry_fee_points, sponsor_name, start_date, end_date, prize_description, min_loyalty_tier),
    ))
    t_id = row["id"]
    for tnum in table_nums:
        db.execute(
            "INSERT INTO TournamentTable (tournament_id, store_id, table_num) VALUES (%s,%s,%s)",
            (t_id, store_id, tnum),
        )
    db.commit()
    return t_id


def update_tournament(tournament_id, store_id, name, max_participants, sponsor_name, start_date, end_date, prize_description, min_loyalty_tier=None):
    """Update editable tournament fields and sync related Session dates."""
    db = get_db()
    
    t = _row(db.execute("SELECT * FROM Tournament WHERE id=%s AND store_id=%s", (tournament_id, store_id)))
    if not t:
        raise ValueError("Tournament not found or not owned by this store.")

    db.execute(
        """
        UPDATE Tournament
        SET name = %s,
            max_participants = %s,
            sponsor_name = %s,
            start_date = %s,
            end_date = %s,
            prize_description = %s,
            min_loyalty_tier = %s
        WHERE id = %s AND store_id = %s
        """,
        (name, max_participants, sponsor_name, start_date, end_date, prize_description, min_loyalty_tier, tournament_id, store_id)
    )
    
    db.execute(
        """
        UPDATE Session
        SET day = TO_CHAR(%s::TIMESTAMP, 'YYYY-MM-DD'),
            start_time = EXTRACT(HOUR FROM %s::TIMESTAMP)::INTEGER,
            end_time = CASE 
                WHEN %s::TIMESTAMP IS NOT NULL AND EXTRACT(HOUR FROM %s::TIMESTAMP) > EXTRACT(HOUR FROM %s::TIMESTAMP)
                THEN EXTRACT(HOUR FROM %s::TIMESTAMP)::INTEGER
                ELSE EXTRACT(HOUR FROM %s::TIMESTAMP)::INTEGER + 4
            END
        WHERE is_tournament = TRUE AND tournament_id = %s
        """,
        (start_date, start_date, end_date, end_date, start_date, end_date, start_date, tournament_id)
    )

    db.commit()


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
        SELECT tp.*, u.username, u.tournament_wins
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


def register_participant(tournament_id, user_id, use_free_entry=False):
    """Insert into TournamentParticipant; the DB trigger handles all eligibility checks."""
    db = get_db()
    db.execute(
        "INSERT INTO TournamentParticipant (tournament_id, user_id, used_free_entry) VALUES (%s, %s, %s)",
        (tournament_id, user_id, use_free_entry),
    )
    db.commit()


def deregister_participant(tournament_id, user_id):
    """Delete from TournamentParticipant; the DB trigger handles refunds."""
    db = get_db()
    db.execute(
        "DELETE FROM TournamentParticipant WHERE tournament_id=%s AND user_id=%s",
        (tournament_id, user_id),
    )
    db.commit()


def get_user_tournament_eligibility(tournament_id, user_id):
    """Return dict with tier_code, free_entries_available, meets_tier_requirement."""
    db = get_db()
    t = _row(db.execute("SELECT store_id, min_loyalty_tier FROM Tournament WHERE id=%s", (tournament_id,)))
    if not t:
        return None
    store_id = t["store_id"]
    min_tier = t["min_loyalty_tier"]

    # Ensure user has a LoyaltyPoint record at this store (trigger does this on insert, but we need it before)
    db.execute(
        "INSERT INTO LoyaltyPoint (user_id, store_id, points, lifetime_points) VALUES (%s, %s, 0, 0) ON CONFLICT DO NOTHING",
        (user_id, store_id)
    )
    db.commit()

    lp = _row(db.execute("SELECT tier_code, used_free_tournament_entries FROM LoyaltyPoint WHERE user_id=%s AND store_id=%s", (user_id, store_id)))
    tier_code = lp["tier_code"] if lp else "Bronze"
    used_entries = lp["used_free_tournament_entries"] if lp else 0

    lt = _row(db.execute("SELECT min_points, free_tournament_entries FROM LoyaltyTier WHERE store_id=%s AND code=%s", (store_id, tier_code)))
    free_allowed = lt["free_tournament_entries"] if lt else 0
    free_entries_available = max(0, free_allowed - used_entries)

    meets_tier_requirement = True
    if min_tier:
        min_lt = _row(db.execute("SELECT min_points FROM LoyaltyTier WHERE store_id=%s AND code=%s", (store_id, min_tier)))
        user_lt = _row(db.execute("SELECT min_points FROM LoyaltyTier WHERE store_id=%s AND code=%s", (store_id, tier_code)))
        if min_lt and user_lt:
            meets_tier_requirement = user_lt["min_points"] >= min_lt["min_points"]

    return {
        "tier_code": tier_code,
        "free_entries_available": free_entries_available,
        "meets_tier_requirement": meets_tier_requirement
    }


# ---------------------------------------------------------------------------
# Bracket generation (application layer)
# ---------------------------------------------------------------------------

def _get_allocated_tables(tournament_id):
    db = get_db()
    return _rows(db.execute(
        "SELECT store_id, table_num FROM TournamentTable WHERE tournament_id=%s ORDER BY table_num",
        (tournament_id,),
    ))


def generate_single_elimination_bracket(tournament_id, seeded=False):
    """Generate a seeded-random single-elimination bracket and persist TournamentMatch rows."""
    db = get_db()
    participants = get_participants(tournament_id)
    tables = _get_allocated_tables(tournament_id)
    if not tables:
        raise ValueError("No tables have been assigned to this tournament.")
    if len(participants) < 2:
        raise ValueError("Need at least 2 participants to generate a bracket.")

    n = len(participants)
    # Pad to next power of 2
    size = 1
    while size < n:
        size *= 2

    if seeded:
        participants.sort(key=lambda p: p.get("tournament_wins", 0), reverse=True)
        players = [p["user_id"] for p in participants]
        while len(players) < size:
            players.append(None)

        # Standard bracket seeding (1 plays N, 2 plays N-1, etc.)
        slots = [0]
        for i in range(1, int(math.log2(size)) + 1):
            slots = [x for s in slots for x in (s, 2**i - 1 - s)]
        
        match_players = [players[slots[i]] for i in range(size)]
    else:
        random.shuffle(participants)
        match_players = [p["user_id"] for p in participants]
        while len(match_players) < size:
            match_players.append(None)

    total_rounds = int(math.log2(size))
    table_cycle = 0

    # ── Step 1: create all round-1 match rows (no winner yet) ──────────────
    round1_ids = []
    bye_match_ids = []          # track which round-1 matches are BYEs
    player_idx = 0
    for m in range(size // 2):
        p1 = match_players[player_idx]
        player_idx += 1
        p2 = match_players[player_idx]
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
    """Generate a full round-robin schedule for 1v1."""
    db = get_db()
    participants = get_participants(tournament_id)
    tables = _get_allocated_tables(tournament_id)
    if not tables:
        raise ValueError("No tables have been assigned to this tournament.")
    if len(participants) < 2:
        raise ValueError("Need at least 2 participants to generate a bracket.")

    players = [p["user_id"] for p in participants]
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
                continue
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
        players = [players[0]] + [players[-1]] + players[1:-1]

    db.commit()


def generate_ffa_single_elimination_bracket(tournament_id, players_per_match, seeded=False):
    """
    Single-elimination bracket where each match has `players_per_match` players.
    Winner of each match advances. No player1_id/player2_id — uses TournamentMatchParticipant.
    """
    db = get_db()
    participants = get_participants(tournament_id)
    tables = _get_allocated_tables(tournament_id)
    if not tables:
        raise ValueError("No tables assigned to this tournament.")
    K = players_per_match

    # Calculate number of matches per round
    curr = len(participants)
    round_matches = []
    while curr > 1:
        m = math.ceil(curr / K)
        round_matches.append(m)
        curr = m

    # Sort or shuffle participants
    if seeded:
        participants.sort(key=lambda p: p.get("tournament_wins", 0), reverse=True)
    else:
        random.shuffle(participants)
        
    current_items = [p["user_id"] for p in participants]
    
    table_cycle = 0
    all_rounds_match_ids = []
    
    for rnd_idx, num_matches in enumerate(round_matches):
        rnd = rnd_idx + 1
        num_items = len(current_items)
        
        # Capacities: "fill tables first" -> K, K, ..., remainder
        capacities = [K] * (num_matches - 1)
        remainder = num_items - (num_matches - 1) * K
        if remainder > 0:
            capacities.append(remainder)
            
        groups = [[] for _ in range(num_matches)]
        for i, item in enumerate(current_items):
            target = i % num_matches
            while len(groups[target]) >= capacities[target]:
                target = (target + 1) % num_matches
            groups[target].append(item)
            
        next_items = [] # these will be the match_ids for the current round
        
        for m_idx, group in enumerate(groups):
            t = tables[table_cycle % len(tables)]
            table_cycle += 1
            
            # Match is a bye if it only has 1 incoming item (player or previous match)
            is_bye = (len(group) == 1)
            
            row = _row(db.execute(
                """
                INSERT INTO TournamentMatch
                    (tournament_id, round_number, match_number, store_id, table_num, is_bye)
                VALUES (%s,%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (tournament_id, rnd, m_idx + 1, t["store_id"], t["table_num"], is_bye),
            ))
            mid = row["id"]
            next_items.append(mid)
            
            if rnd == 1:
                # Insert participants
                for uid in group:
                    db.execute(
                        "INSERT INTO TournamentMatchParticipant (match_id, user_id) VALUES (%s,%s)",
                        (mid, uid),
                    )
            else:
                # Wire next_match_id of the PREVIOUS round's matches
                for prev_mid in group:
                    db.execute(
                        "UPDATE TournamentMatch SET next_match_id=%s WHERE id=%s",
                        (mid, prev_mid),
                    )
                    
        all_rounds_match_ids.append(next_items)
        current_items = next_items

    # Auto-advance single-item byes (only one incoming item in the group)
    for round_match_ids in all_rounds_match_ids:
        for mid in round_match_ids:
            m = _row(db.execute("SELECT * FROM TournamentMatch WHERE id=%s", (mid,)))
            if m and m["is_bye"]:
                # For round 1, we immediately know the user_id of the single player
                parts = _rows(db.execute(
                    "SELECT user_id FROM TournamentMatchParticipant WHERE match_id=%s", (mid,)
                ))
                if parts:
                    winner_uid = parts[0]["user_id"]
                    db.execute(
                        "UPDATE TournamentMatch SET winner_id=%s, is_played=TRUE WHERE id=%s",
                        (winner_uid, mid),
                    )
                    # And copy them to the next match
                    if m["next_match_id"]:
                        db.execute(
                            "INSERT INTO TournamentMatchParticipant (match_id, user_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                            (m["next_match_id"], winner_uid),
                        )

    db.commit()


def generate_ffa_round_robin_bracket(tournament_id, players_per_match):
    """
    Round-robin FFA: each round randomly assigns all players to tables of K.
    Number of rounds = ceil((N-1) / (K-1)) to approximate full coverage.
    Uses TournamentMatchParticipant (no player1_id/player2_id).
    """
    db = get_db()
    participants = get_participants(tournament_id)
    tables = _get_allocated_tables(tournament_id)
    if not tables:
        raise ValueError("No tables assigned to this tournament.")
    K = players_per_match
    N = len(participants)
    players = [p["user_id"] for p in participants]

    # Number of rounds: enough that each player faces ~N-1 others
    num_rounds = max(2, math.ceil((N - 1) / (K - 1)))
    table_cycle = 0
    match_num = 0

    for rnd in range(1, num_rounds + 1):
        shuffled = players[:]
        random.shuffle(shuffled)
        # Pad to multiple of K
        while len(shuffled) % K != 0:
            shuffled.append(None)
        groups = [shuffled[i:i+K] for i in range(0, len(shuffled), K)]
        for group in groups:
            real = [u for u in group if u is not None]
            if len(real) < 2:
                continue
            match_num += 1
            t = tables[table_cycle % len(tables)]
            table_cycle += 1
            row = _row(db.execute(
                """
                INSERT INTO TournamentMatch
                    (tournament_id, round_number, match_number, store_id, table_num)
                VALUES (%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (tournament_id, rnd, match_num, t["store_id"], t["table_num"]),
            ))
            mid = row["id"]
            for uid in real:
                db.execute(
                    "INSERT INTO TournamentMatchParticipant (match_id, user_id) VALUES (%s,%s)",
                    (mid, uid),
                )
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
    """Record result for a 1v1 match. The DB trigger handles advancement."""
    db = get_db()
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


def record_ffa_match_result(match_id, participant_ranks, tournament_id, store_id):
    """
    Record results for a free-for-all match.
    participant_ranks: list of {user_id, score, rank_in_match} sorted by rank.
    The player with rank_in_match=1 becomes winner_id.
    For single elimination: winner advances to next match; all others get sessions deleted.
    """
    db = get_db()
    t = _row(db.execute(
        "SELECT store_id, format FROM Tournament WHERE id=%s", (tournament_id,)
    ))
    if not t or t["store_id"] != store_id:
        raise PermissionError("Not your tournament.")

    match = _row(db.execute(
        "SELECT * FROM TournamentMatch WHERE id=%s AND tournament_id=%s",
        (match_id, tournament_id),
    ))
    if not match:
        raise ValueError("Match not found.")

    winner = next((p for p in participant_ranks if p["rank_in_match"] == 1), None)
    if not winner:
        raise ValueError("No winner (rank 1) provided.")

    # Upsert TournamentMatchParticipant rows
    for p in participant_ranks:
        db.execute(
            """
            INSERT INTO TournamentMatchParticipant (match_id, user_id, score, rank_in_match)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT (match_id, user_id) DO UPDATE
              SET score=EXCLUDED.score, rank_in_match=EXCLUDED.rank_in_match
            """,
            (match_id, p["user_id"], p.get("score"), p["rank_in_match"]),
        )

    # Mark match played and set winner_id
    db.execute(
        "UPDATE TournamentMatch SET winner_id=%s, is_played=TRUE WHERE id=%s",
        (winner["user_id"], match_id),
    )

    # For single elimination: advance winner to next match participant slot
    if match["next_match_id"] and t["format"] == "single_elimination":
        db.execute(
            """
            INSERT INTO TournamentMatchParticipant (match_id, user_id)
            VALUES (%s, %s)
            ON CONFLICT (match_id, user_id) DO NOTHING
            """,
            (match["next_match_id"], winner["user_id"]),
        )
        
        # Auto-cascade if the next match is a bye
        next_m = _row(db.execute("SELECT is_bye FROM TournamentMatch WHERE id=%s", (match["next_match_id"],)))
        if next_m and next_m["is_bye"]:
            record_ffa_match_result(
                match["next_match_id"],
                [{"user_id": winner["user_id"], "rank_in_match": 1}],
                tournament_id,
                store_id
            )

    # Delete loser sessions (single elimination only) and winner if this is the final
    losers = [p["user_id"] for p in participant_ranks if p["rank_in_match"] != 1]
    if t["format"] == "single_elimination":
        for uid in losers:
            db.execute(
                "DELETE FROM Session WHERE user_id=%s AND is_tournament=TRUE AND tournament_id=%s",
                (uid, tournament_id),
            )
        # If final match (no next_match_id), also free the winner
        if not match["next_match_id"]:
            db.execute(
                "DELETE FROM Session WHERE user_id=%s AND is_tournament=TRUE AND tournament_id=%s",
                (winner["user_id"], tournament_id),
            )

    db.commit()


def get_match_participants(match_id):
    db = get_db()
    return _rows(db.execute(
        """
        SELECT tmp.*, u.username
        FROM TournamentMatchParticipant tmp
        JOIN "User" u ON u.id = tmp.user_id
        WHERE tmp.match_id = %s
        ORDER BY tmp.rank_in_match NULLS LAST, u.username
        """,
        (match_id,),
    ))


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
    """Return True if every non-bye match (1v1 and FFA) has a recorded winner."""
    db = get_db()
    # 1v1 matches: both players must be present and winner set
    row1 = db.execute(
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
    # FFA matches: player1_id IS NULL, must have >=2 participants and winner set
    row2 = db.execute(
        """
        SELECT COUNT(*) AS pending
        FROM TournamentMatch tm
        WHERE tm.tournament_id = %s
          AND tm.player1_id IS NULL
          AND tm.is_bye = FALSE
          AND tm.is_played = FALSE
          AND (SELECT COUNT(*) FROM TournamentMatchParticipant WHERE match_id = tm.id) >= 2
        """,
        (tournament_id,),
    ).fetchone()
    return (row1["pending"] + row2["pending"]) == 0


def compute_standings_single_elimination(tournament_id):
    """
    Auto-compute final standings for a single-elimination tournament.
    Works for both 1v1 (uses player1_id/player2_id) and FFA (uses TournamentMatchParticipant).
    """
    db = get_db()
    matches = _rows(db.execute(
        """
        SELECT tm.id, tm.round_number, tm.match_number,
               tm.player1_id, tm.player2_id, tm.winner_id,
               u1.username AS player1_name,
               u2.username AS player2_name,
               uw.username AS winner_name
        FROM TournamentMatch tm
        LEFT JOIN "User" u1 ON u1.id = tm.player1_id
        LEFT JOIN "User" u2 ON u2.id = tm.player2_id
        LEFT JOIN "User" uw ON uw.id = tm.winner_id
        WHERE tm.tournament_id = %s
          AND tm.is_bye = FALSE
          AND tm.winner_id IS NOT NULL
        ORDER BY tm.round_number DESC, tm.match_number
        """,
        (tournament_id,),
    ))

    if not matches:
        return []

    is_ffa = (matches[0]["player1_id"] is None)
    max_round = max(m["round_number"] for m in matches)
    standings = []
    placed_ids = set()
    place = 1

    if is_ffa:
        # Load per-match participants for all matches
        all_parts = {}
        for m in matches:
            parts = _rows(db.execute(
                """
                SELECT tmp.user_id, tmp.rank_in_match, u.username
                FROM TournamentMatchParticipant tmp
                JOIN "User" u ON u.id = tmp.user_id
                WHERE tmp.match_id = %s
                ORDER BY tmp.rank_in_match NULLS LAST
                """,
                (m["id"],),
            ))
            all_parts[m["id"]] = parts

        for rnd in range(max_round, 0, -1):
            rnd_matches = [m for m in matches if m["round_number"] == rnd]
            if not rnd_matches:
                continue
            if rnd == max_round:
                # Final: all participants ordered by rank_in_match
                m = rnd_matches[0]
                for p in all_parts.get(m["id"], []):
                    if p["user_id"] not in placed_ids:
                        standings.append({"user_id": p["user_id"], "username": p["username"], "place": place})
                        placed_ids.add(p["user_id"])
                        place += 1
            else:
                # Earlier rounds: only the losers (rank != 1) are eliminated here
                for m in rnd_matches:
                    losers = [p for p in all_parts.get(m["id"], []) if p["rank_in_match"] != 1]
                    for p in sorted(losers, key=lambda x: x["rank_in_match"] or 999):
                        if p["user_id"] not in placed_ids:
                            standings.append({"user_id": p["user_id"], "username": p["username"], "place": place})
                            placed_ids.add(p["user_id"])
                            place += 1
    else:
        # 1v1 path
        for rnd in range(max_round, 0, -1):
            rnd_matches = [m for m in matches if m["round_number"] == rnd]
            if not rnd_matches:
                continue
            if rnd == max_round:
                m = rnd_matches[0]
                winner_id  = m["winner_id"]
                loser_id   = m["player2_id"] if m["winner_id"] == m["player1_id"] else m["player1_id"]
                winner_name = m["winner_name"]
                loser_name  = m["player2_name"] if m["winner_id"] == m["player1_id"] else m["player1_name"]
                standings.append({"user_id": winner_id, "username": winner_name, "place": 1})
                standings.append({"user_id": loser_id,  "username": loser_name,  "place": 2})
                placed_ids.add(winner_id)
                placed_ids.add(loser_id)
                place = 3
            else:
                for m in rnd_matches:
                    loser_id   = m["player2_id"] if m["winner_id"] == m["player1_id"] else m["player1_id"]
                    loser_name = m["player2_name"] if m["winner_id"] == m["player1_id"] else m["player1_name"]
                    if loser_id and loser_id not in placed_ids:
                        standings.append({"user_id": loser_id, "username": loser_name, "place": place})
                        placed_ids.add(loser_id)
                place += len(rnd_matches)

    return sorted(standings, key=lambda x: x["place"])


def compute_standings_round_robin(tournament_id):
    """
    Auto-compute standings for round robin.
    For FFA (players_per_match > 2): rank by wins (rank_in_match=1) then score sum.
    For 1v1: rank by wins then point differential.
    """
    db = get_db()
    participants = get_participants(tournament_id)
    stats = {p["user_id"]: {"user_id": p["user_id"], "username": p["username"], "wins": 0, "diff": 0}
             for p in participants}

    t = _row(db.execute("SELECT players_per_match FROM Tournament WHERE id=%s", (tournament_id,)))
    is_ffa = t and t["players_per_match"] > 2

    if is_ffa:
        parts = _rows(db.execute(
            """
            SELECT tmp.user_id, tmp.rank_in_match, tmp.score
            FROM TournamentMatchParticipant tmp
            JOIN TournamentMatch tm ON tm.id = tmp.match_id
            WHERE tm.tournament_id = %s AND tm.winner_id IS NOT NULL
            """,
            (tournament_id,),
        ))
        for p in parts:
            if p["user_id"] in stats:
                if p["rank_in_match"] == 1:
                    stats[p["user_id"]]["wins"] += 1
                try:
                    stats[p["user_id"]]["diff"] += int(p["score"] or 0)
                except (ValueError, TypeError):
                    pass
    else:
        matches = _rows(db.execute(
            """
            SELECT player1_id, player2_id, winner_id, score_player1, score_player2
            FROM TournamentMatch
            WHERE tournament_id = %s AND winner_id IS NOT NULL
            """,
            (tournament_id,),
        ))
        for m in matches:
            w = m["winner_id"]
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
