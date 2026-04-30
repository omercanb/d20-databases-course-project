import random
from datetime import date

import click

from d20.db.game import create_game, create_game_copy
from d20.db.market.market_participant import (
    get_market_participant,
    get_market_participant_by_customer,
    increment_available_cash,
)
from d20.db.market.orders import create_order
from d20.db.market.participant_inventory import increment_available_quantity
from d20.db.session import create_session
from d20.db.stores import create_store, create_table
from d20.db.user import create_user


def seed_users():
    users = [("user1", "pass"), ("user2", "pass")]
    return [create_user(username, password) for username, password in users]


def seed_stores():
    stores = [
        ("store1", "Big Boy Playhouse", "pass"),
        ("store2", "The Dawg Pen", "pass"),
        ("store3", "The Den", "pass"),
    ]
    store_ids = [
        create_store(username, name, password) for username, name, password in stores
    ]
    for store_id in store_ids:
        for _ in range(3):
            create_table(store_id, 5)
    return store_ids


def seed_games():
    games = [
        {
            "name": "Freakopoly",
            "symbol": "FRKPOL",
            "publisher": "Freak Games",
            "genre": "Strategy",
            "min_players": 2,
            "max_players": 6,
            "avg_duration": 120,
            "complexity_rating": 3,
            "strategy_rating": 4,
            "luck_rating": 4,
            "interaction_rating": 5,
            "description": "A freaky twist on the classic property trading game.",
        },
        {
            "name": "Secret Freak",
            "symbol": "SCRTFRK",
            "publisher": "Freak Games",
            "genre": "Social Deduction",
            "min_players": 4,
            "max_players": 10,
            "avg_duration": 45,
            "complexity_rating": 2,
            "strategy_rating": 3,
            "luck_rating": 2,
            "interaction_rating": 5,
            "description": "Uncover the secret freak among your friends.",
        },
        {
            "name": "Freaknames",
            "symbol": "FRKNMS",
            "publisher": "Freak Games",
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
    return [
        create_game(
            g["name"], g["symbol"],
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


def seed_game_copies(store_ids, game_ids):
    store_to_game_copy = {}
    for store_id in store_ids:
        store_to_game_copy[store_id] = []
        for game_id in game_ids:
            copy_num = create_game_copy(game_id, store_id)
            store_to_game_copy[store_id].append((game_id, copy_num))
    return store_to_game_copy


def seed_session(user_ids, store_ids, store_to_game_copy):
    user1 = user_ids[0]
    store1 = store_ids[0]
    games_used = [copy_num for game_id, copy_num in store_to_game_copy[store1][:1]]
    create_session(user1, store1, 1, str(date.today()), 10, 15, games_used)


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


def seed_the_universe():
    user_ids = seed_users()
    store_ids = seed_stores()
    game_ids = seed_games()
    store_to_game_copy = seed_game_copies(store_ids, game_ids)
    seed_session(user_ids, store_ids, store_to_game_copy)
    seed_orders(user_ids, game_ids)


@click.command("seed")
def seed_db_command():
    seed_the_universe()
    click.echo("Seeded database.")
