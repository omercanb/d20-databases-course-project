import random
from datetime import date

import click

from flaskr.db.game import create_game, create_game_copy
from flaskr.db.session import create_session
from flaskr.db.stores import create_store, create_table
from flaskr.db.user import create_user


def seed_stores():
    users = [("user1", "pass"), ("user2", "pass")]
    user_ids = []
    for username, password in users:
        user_id = create_user(username, password)
        user_ids.append(user_id)

    stores = [
        ("store1", "Big Boy Playhouse", "pass"),
        ("store2", "The Dawg Pen", "pass"),
        ("store3", "The Den", "pass"),
    ]

    store_ids = []
    for username, name, password in stores:
        store_id = create_store(username, name, password)
        store_ids.append(store_id)

    for store_id in store_ids:
        for _ in range(3):
            create_table(store_id, 5)

    # Create new games
    games = ["Freakopoly", "Secret Freak", "Freaknames"]
    game_ids = []
    for game in games:
        game_id = create_game(game)
        game_ids.append(game_id)

    # Add 1-3 copies of games to stores
    store_to_game_copy = {}
    for store_id in store_ids:
        store_to_game_copy[store_id] = []
        for game_id in game_ids:
            n = 1
            for _ in range(n):
                copy_num = create_game_copy(game_id, store_id)
                store_to_game_copy[store_id].append((game_id, copy_num))

    user = user_ids[0]
    store = store_ids[0]
    table_num = 1
    day = str(date.today())
    start = 10
    end = 15
    games_used = [copy_num for game_id, copy_num in store_to_game_copy[store][:1]]
    create_session(user, store, table_num, day, start, end, games_used)


@click.command("seed")
def seed_db_command():
    seed_stores()
    click.echo("Seeded database.")
