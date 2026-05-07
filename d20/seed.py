import mimetypes
import os
import random
from datetime import date, datetime, timedelta
from io import BytesIO

import click
from werkzeug.datastructures import FileStorage

from d20.db import get_db
from d20.db.game import (
    create_game,
    create_game_copy,
    rate_game,
    refresh_game_similarities,
    update_game_image,
)
from d20.db.market.market_participant import (
    get_market_participant,
    get_market_participant_by_customer,
    increment_available_cash,
)
from d20.db.market.orders import create_order
from d20.db.market.participant_inventory import increment_available_quantity
from d20.db.menu import create_beverage, create_food, create_menu_item
from d20.db.session import create_session
from d20.db.stores import create_store, create_table
from d20.db.user import create_user
from d20.db.loyalty import (
    REDEMPTION_RATE,
    add_points,
    get_point_rule,
    update_store_loyalty_point_rules,
    update_store_loyalty_tiers,
)


def seed_users():
    users = [("user1", "pass"), ("user2", "pass"), ("user3", "pass")]
    return [create_user(username, password) for username, password in users]


def seed_stores():
    stores = [
        ("store1", "Big Boy Playhouse", "pass", "Ankara/Kızılay"),
        ("store2", "The Dawg Pen", "pass", "Ankara/Ümitköy"),
        ("store3", "The Den", "pass", "İstanbul/Şişli"),
    ]
    store_ids = [
        create_store(username, name, password, address)
        for username, name, password, address in stores
    ]
    for store_id in store_ids:
        for _ in range(3):
            create_table(store_id, 5)
    return store_ids


def create_filestorage_from_file(file_path):
    """Create a FileStorage object from a local file path."""
    with open(file_path, "rb") as f:
        file_bytes = f.read()

    file_stream = BytesIO(file_bytes)
    filename = file_path.split("/")[-1]  # Get filename
    mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

    return FileStorage(stream=file_stream, filename=filename, content_type=mime_type)


def seed_games():
    games = [
        {
            "name": "Monopoly",
            "symbol": "MONOPOL",
            "publisher": "Capitalist Games",
            "genre": "Strategy",
            "min_players": 2,
            "max_players": 6,
            "avg_duration": 120,
            "complexity_rating": 3,
            "strategy_rating": 4,
            "luck_rating": 4,
            "interaction_rating": 5,
            "description": "The classic property trading game.",
        },
        {
            "name": "Catan",
            "symbol": "CATAN",
            "publisher": "Catan Games",
            "genre": "Social Deduction",
            "min_players": 4,
            "max_players": 10,
            "avg_duration": 45,
            "complexity_rating": 2,
            "strategy_rating": 3,
            "luck_rating": 2,
            "interaction_rating": 5,
            "description": "Become the baron.",
        },
        {
            "name": "Codenames",
            "symbol": "CDNMS",
            "publisher": "Secret Games",
            "genre": "Party",
            "min_players": 2,
            "max_players": 8,
            "avg_duration": 30,
            "complexity_rating": 1,
            "strategy_rating": 2,
            "luck_rating": 1,
            "interaction_rating": 4,
            "description": "A hilarious party word game for all ages.",
        },
    ]
    ids = [
        create_game(
            g["name"],
            g["symbol"],
            publisher=g["publisher"],
            genre=g["genre"],
            min_players=g["min_players"],
            max_players=g["max_players"],
            avg_duration=g["avg_duration"],
            complexity_rating=g["complexity_rating"],
            strategy_rating=g["strategy_rating"],
            luck_rating=g["luck_rating"],
            interaction_rating=g["interaction_rating"],
            description=g["description"],
        )
        for g in games
    ]
    game_image_paths = [
        "./d20/static/monopoly.png",
        "./d20/static/catan.png",
        "./d20/static/codenames.png",
    ]
    for game_id, path in zip(ids, game_image_paths):
        update_game_image(game_id, create_filestorage_from_file(path))
    return ids


def seed_game_copies(store_ids, game_ids):
    store_to_game_copy = {}
    for store_id in store_ids:
        store_to_game_copy[store_id] = []
        for game_id in game_ids:
            copy_num = create_game_copy(game_id, store_id)
            store_to_game_copy[store_id].append((game_id, copy_num))
    return store_to_game_copy


def seed_ratings(user_ids, game_ids):
    reviews = [
        (user_ids[0], game_ids[0], 5, "Chaotic in the best way."),
        (user_ids[1], game_ids[0], 4, "Great for a longer game night."),
        (user_ids[0], game_ids[1], 4, "Gets everyone talking fast."),
        (user_ids[1], game_ids[1], 5, "Really fun with a big group."),
        (user_ids[0], game_ids[2], 3, "Light and quick party filler."),
        (user_ids[1], game_ids[2], 4, "Easy to teach and funny."),
    ]
    for user_id, game_id, rating, comment in reviews:
        rate_game(user_id, game_id, rating, comment)


def seed_session(user_ids, store_ids, store_to_game_copy):
    # Build varied daily demand over a couple days, centered around 2-4 sessions/day.
    # Capacity is respected by distributing sessions across stores/tables/timeslots/games.
    random.seed(20)
    daily_targets = [2, 3, 4]
    time_slots = [(9, 11), (11, 13), (13, 15), (15, 17), (17, 19)]

    for day_idx, target_count in enumerate(daily_targets, start=1):
        session_candidates = []
        for store_id in store_ids:
            # One unique game per table per timeslot avoids game copy conflicts.
            game_ids_for_store = [
                game_id for game_id, _ in store_to_game_copy[store_id]
            ]
            for start_time, end_time in time_slots:
                for table_num in (1, 2, 3):
                    game_id = game_ids_for_store[
                        (table_num - 1) % len(game_ids_for_store)
                    ]
                    user_id = user_ids[
                        (day_idx + table_num + start_time) % len(user_ids)
                    ]
                    session_candidates.append(
                        (user_id, store_id, table_num, start_time, end_time, game_id)
                    )

        random.shuffle(session_candidates)
        selected = session_candidates[:target_count]
        future_day = str(date.today() + timedelta(days=day_idx))
        for user_id, store_id, table_num, start_time, end_time, game_id in selected:
            create_session(
                user_id,
                store_id,
                table_num,
                future_day,
                start_time,
                end_time,
                [game_id],
            )


def seed_orders(user_ids, game_ids):
    # Have user1 put out one buy and sell order for game 1 and 2
    user1 = user_ids[0]
    user1_market = get_market_participant_by_customer(user1)["id"]
    increment_available_cash(user1_market, 100)
    game1 = game_ids[0]
    create_order(user1_market, game1, "LIMIT", "BUY", 20, 2)
    game2 = game_ids[1]
    increment_available_quantity(user1_market, game2, 3)
    create_order(user1_market, game2, "LIMIT", "SELL", 30, 3)
    # Have user1 match the sell order to buy a game
    user2 = user_ids[1]
    user2_market = get_market_participant_by_customer(user2)["id"]
    increment_available_cash(user2_market, 100)
    create_order(user2_market, game2, "MARKET", "BUY", None, 1)


def seed_menus(store_ids):
    for store_id in store_ids:
        # Food
        nachos_id = create_menu_item(
            store_id, "Nachos", 8.99, "Crispy nachos with cheese dip"
        )
        create_food(nachos_id, is_vegetarian=True, category="Snack")

        burger_id = create_menu_item(
            store_id, "Classic Burger", 12.50, "Beef burger with fries"
        )
        create_food(burger_id, is_vegetarian=False, category="Main")

        # Beverages
        cola_id = create_menu_item(store_id, "Cola", 2.99, "Cold fizzy drink")
        create_beverage(cola_id, size="Large", temperature="Cold")

        coffee_id = create_menu_item(store_id, "Black Coffee", 3.50, "Freshly brewed")
        create_beverage(coffee_id, size="Regular", temperature="Hot")


def seed_loyalty_program(user_ids, store_ids):
    """Create visible loyalty tier, points, top-holder, and redemption examples."""
    tier_configs = [
        [
            {"code": "Bronze", "min_points": 0, "discount_percent": 0, "reservation_advance_days": 3, "free_tournament_entries": 0},
            {"code": "Silver", "min_points": 300, "discount_percent": 5, "reservation_advance_days": 7, "free_tournament_entries": 0},
            {"code": "Gold", "min_points": 800, "discount_percent": 10, "reservation_advance_days": 14, "free_tournament_entries": 1},
        ],
        [
            {"code": "Bronze", "min_points": 0, "discount_percent": 0, "reservation_advance_days": 3, "free_tournament_entries": 0},
            {"code": "Silver", "min_points": 500, "discount_percent": 7, "reservation_advance_days": 10, "free_tournament_entries": 0},
            {"code": "Gold", "min_points": 1200, "discount_percent": 15, "reservation_advance_days": 21, "free_tournament_entries": 2},
        ],
        [
            {"code": "Bronze", "min_points": 0, "discount_percent": 0, "reservation_advance_days": 3, "free_tournament_entries": 0},
            {"code": "Silver", "min_points": 400, "discount_percent": 5, "reservation_advance_days": 7, "free_tournament_entries": 0},
            {"code": "Gold", "min_points": 900, "discount_percent": 12, "reservation_advance_days": 14, "free_tournament_entries": 1},
        ],
    ]
    rule_configs = [
        {"session_hour": 6, "food_dollar": 1.5, "game_rating": 8, "tournament_participation": 25},
        {"session_hour": 5, "food_dollar": 1, "game_rating": 5, "tournament_participation": 20},
        {"session_hour": 7, "food_dollar": 2, "game_rating": 10, "tournament_participation": 30},
    ]

    for index, store_id in enumerate(store_ids):
        update_store_loyalty_tiers(store_id, tier_configs[index % len(tier_configs)])
        update_store_loyalty_point_rules(
            store_id,
            [
                {"action_code": action_code, "points_per_unit": points_per_unit}
                for action_code, points_per_unit in rule_configs[index % len(rule_configs)].items()
            ],
        )

    sample_activity = [
        (user_ids[0], store_ids[0], 180),
        (user_ids[1], store_ids[0], 520),
        (user_ids[2], store_ids[0], 980),
        (user_ids[0], store_ids[1], 275),
        (user_ids[1], store_ids[1], 760),
        (user_ids[2], store_ids[1], 1325),
        (user_ids[0], store_ids[2], 410),
        (user_ids[1], store_ids[2], 930),
        (user_ids[2], store_ids[2], 125),
    ]
    for user_id, store_id, base_points in sample_activity:
        add_points(user_id, store_id, base_points)
        add_points(user_id, store_id, int(2 * get_point_rule(store_id, "session_hour")))
        add_points(user_id, store_id, int(get_point_rule(store_id, "game_rating")))
        add_points(user_id, store_id, int(get_point_rule(store_id, "tournament_participation")))

    applied_redemptions = [
        (user_ids[2], store_ids[0], 120, "Seeded food voucher redemption"),
        (user_ids[1], store_ids[1], 75, "Seeded table-fee discount redemption"),
    ]
    for index, (user_id, store_id, points_spent, description) in enumerate(applied_redemptions, start=1):
        _create_applied_loyalty_redemption(user_id, store_id, points_spent, description, index)


def _create_applied_loyalty_redemption(user_id, store_id, points_spent, description, index):
    db = get_db()
    discount = round(float(points_spent * REDEMPTION_RATE), 2)
    table_fee = 20.00
    grand_total = round(max(0.0, table_fee - discount), 2)
    day = date.today() - timedelta(days=30 + index)

    db.execute(
        """
        INSERT INTO "Table" (store_id, table_num, capacity)
        VALUES (%s, 1, 5)
        ON CONFLICT (store_id, table_num) DO NOTHING
        """,
        (store_id,),
    )
    session_id = db.execute(
        """
        INSERT INTO Session (user_id, store_id, table_num, day, start_time, end_time, checkout_status)
        VALUES (%s, %s, 1, %s, 10, 14, 'checked_out')
        RETURNING id
        """,
        (user_id, store_id, day),
    ).fetchone()["id"]
    bill_id = db.execute(
        """
        INSERT INTO Bill (session_id, table_fee, food_total, damage_fee, loyalty_discount, grand_total)
        VALUES (%s, %s, 0, 0, %s, %s)
        RETURNING id
        """,
        (session_id, table_fee, discount, grand_total),
    ).fetchone()["id"]
    updated = db.execute(
        """
        UPDATE LoyaltyPoint
        SET points = points - %s
        WHERE user_id = %s AND store_id = %s AND points >= %s
        RETURNING points
        """,
        (points_spent, user_id, store_id, points_spent),
    ).fetchone()
    if updated is None:
        raise RuntimeError("Seeded loyalty redemption exceeds the available point balance.")
    db.execute(
        """
        INSERT INTO LoyaltyRedemption (user_id, store_id, bill_id, points_spent, description)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (user_id, store_id, bill_id, points_spent, description),
    )
    db.commit()


def seed_historical_price_data(user_ids, game_ids):
    """Generate 14 days of historical price data for games."""
    user2_id = user_ids[1]
    user3_id = user_ids[2]

    user2_market = get_market_participant_by_customer(user2_id)["id"]
    user3_market = get_market_participant_by_customer(user3_id)["id"]

    # Generate price data for each game
    num_days = 14
    today = datetime.now()

    for game_id in game_ids:
        # Generate random starting price between $10 and $30
        starting_price = random.uniform(10, 30)
        prices = [starting_price]

        # Generate prices for each day with random walk
        current_price = starting_price
        for _ in range(num_days - 1):
            # Random price change between -2 and +2
            price_change = random.uniform(-2, 2)
            current_price = max(1, current_price + price_change)
            prices.append(current_price)

        # Reverse prices so oldest is first
        prices.reverse()

        # Add game to user2's inventory
        increment_available_quantity(user2_market, game_id, num_days)

        # Add sufficient cash to user3
        total_cost = sum(prices)
        increment_available_cash(user3_market, total_cost + 100)

        # Create orders for each day
        for day_offset in range(num_days):
            # Calculate timestamp for this day
            day_timestamp = (
                today - timedelta(days=num_days - 1 - day_offset)
            ).isoformat()
            price = prices[day_offset]

            # User 2 creates limit sell order
            sell_order_id, _, _ = create_order(
                user2_market,
                game_id,
                "LIMIT",
                "SELL",
                price,
                1,
                created_at=day_timestamp,
            )

            # User 3 creates market buy order to fill it
            create_order(
                user3_market,
                game_id,
                "MARKET",
                "BUY",
                None,
                1,
                created_at=day_timestamp,
            )


def seed_tournament_test(game_ids):
    """
    Creates a dedicated TournamentTest store, 7 tour users with varied loyalty,
    and registers them in two ready-to-bracket tournaments (round robin + FFA single elim).
    Uses direct DB inserts to bypass the eligibility trigger for seeding purposes.
    """
    db = get_db()

    # ── 1. Store ────────────────────────────────────────────────────────────
    ts_id = create_store("TournamentTest", "TournamentTest Arena", "pass", "Test/Venue")
    # Create 4 tables (capacity 8 so everyone fits)
    for _ in range(4):
        create_table(ts_id, 8)
    # Add game copies for Catan (game_ids[1])
    create_game_copy(game_ids[1], ts_id)

    # ── 2. Loyalty tiers for this store ─────────────────────────────────────
    update_store_loyalty_tiers(ts_id, [
        {"code": "Bronze", "min_points": 0,    "discount_percent": 0,  "reservation_advance_days": 3,  "free_tournament_entries": 0},
        {"code": "Silver", "min_points": 300,  "discount_percent": 5,  "reservation_advance_days": 7,  "free_tournament_entries": 0},
        {"code": "Gold",   "min_points": 800,  "discount_percent": 10, "reservation_advance_days": 14, "free_tournament_entries": 1},
    ])
    update_store_loyalty_point_rules(ts_id, [
        {"action_code": "session_hour",             "points_per_unit": 6},
        {"action_code": "food_dollar",              "points_per_unit": 1},
        {"action_code": "game_rating",              "points_per_unit": 8},
        {"action_code": "tournament_participation", "points_per_unit": 25},
    ])

    # ── 3. Tour users (tour1 … tour7) with varied loyalty ───────────────────
    tour_names = [f"tour{i}" for i in range(1, 8)]
    # Points to seed (0, 50, 150, 300, 500, 800, 1200) → Bronze×3, Silver×2, Gold×2
    loyalty_points = [0, 50, 150, 300, 500, 800, 1200]

    tour_ids = []
    for name in tour_names:
        uid = create_user(name, name)
        tour_ids.append(uid)

    # Ensure LoyaltyPoint rows exist and set the desired balances directly
    for uid, pts in zip(tour_ids, loyalty_points):
        db.execute(
            """
            INSERT INTO LoyaltyPoint (user_id, store_id, points, lifetime_points)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, store_id) DO UPDATE
              SET points = EXCLUDED.points,
                  lifetime_points = EXCLUDED.lifetime_points
            """,
            (uid, ts_id, pts, pts),
        )
    db.commit()

    # ── 4. Two tournaments ───────────────────────────────────────────────────
    start_rr  = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d %H:%M")
    end_rr    = (datetime.now() + timedelta(days=3, hours=6)).strftime("%Y-%m-%d %H:%M")
    start_se  = (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d %H:%M")
    end_se    = (datetime.now() + timedelta(days=10, hours=4)).strftime("%Y-%m-%d %H:%M")

    # Round-Robin  (1v1, all 7 players)
    rr = db.execute(
        """
        INSERT INTO Tournament
            (store_id, game_id, name, format, max_participants, players_per_match,
             entry_fee_points, start_date, end_date, prize_description)
        VALUES (%s,%s,%s,'round_robin',8,2, 0,%s,%s,'Top 3 win store credit')
        RETURNING id
        """,
        (ts_id, game_ids[1], "TournamentTest Round Robin", start_rr, end_rr),
    ).fetchone()["id"]

    # Single Elimination FFA (4 players per match, all 7 players)
    se = db.execute(
        """
        INSERT INTO Tournament
            (store_id, game_id, name, format, max_participants, players_per_match,
             entry_fee_points, start_date, end_date, prize_description)
        VALUES (%s,%s,%s,'single_elimination',8,4, 0,%s,%s,'Champion gets 500 pts')
        RETURNING id
        """,
        (ts_id, game_ids[1], "TournamentTest FFA Elimination", start_se, end_se),
    ).fetchone()["id"]

    # Assign tables to both tournaments
    tables = db.execute(
        "SELECT table_num FROM \"Table\" WHERE store_id=%s ORDER BY table_num", (ts_id,)
    ).fetchall()
    for t in tables:
        for tid in (rr, se):
            db.execute(
                "INSERT INTO TournamentTable (tournament_id, store_id, table_num) VALUES (%s,%s,%s)",
                (tid, ts_id, t["table_num"]),
            )

    # ── 5. Register all 7 users while registration is still open ────────────
    for uid in tour_ids:
        for tid in (rr, se):
            db.execute(
                """
                INSERT INTO TournamentParticipant (tournament_id, user_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (tid, uid),
            )
    db.commit()

    # ── 6. Close registration so tournaments are ready to bracket ───────────
    for tid in (rr, se):
        db.execute(
            "UPDATE Tournament SET registration_open=FALSE, status='registration_open' WHERE id=%s",
            (tid,),
        )
    db.commit()

    return ts_id, rr, se


def seed_the_universe():
    user_ids = seed_users()
    store_ids = seed_stores()
    game_ids = seed_games()
    seed_ratings(user_ids, game_ids)
    refresh_game_similarities()
    store_to_game_copy = seed_game_copies(store_ids, game_ids)
    seed_session(user_ids, store_ids, store_to_game_copy)
    seed_orders(user_ids, game_ids)
    seed_menus(store_ids)
    seed_loyalty_program(user_ids, store_ids)
    seed_historical_price_data(user_ids, game_ids)
    seed_tournament_test(game_ids)


@click.command("seed")
def seed_db_command():
    seed_the_universe()
    click.echo("Seeded database.")
