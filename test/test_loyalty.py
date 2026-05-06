import pytest
from psycopg2 import errors

from d20.db import get_db
from d20.db.loyalty import (
    add_points,
    get_point_rule,
    get_store_loyalty_stats,
    redeem_points,
    update_store_loyalty_point_rules,
    update_store_loyalty_tiers,
)
from d20.seed import seed_loyalty_program


def create_store(username="loyalty-store", name="Loyalty Store"):
    db = get_db()
    row = db.execute(
        """
        INSERT INTO Store (username, password, name, address)
        VALUES (%s, 'test', %s, 'Test Address')
        RETURNING id
        """,
        (username, name),
    ).fetchone()
    db.commit()
    return row["id"]


def create_user(username):
    db = get_db()
    row = db.execute(
        """
        INSERT INTO "User" (username, password)
        VALUES (%s, 'test')
        RETURNING id
        """,
        (username,),
    ).fetchone()
    db.commit()
    return row["id"]


def get_loyalty_row(user_id, store_id):
    db = get_db()
    return db.execute(
        """
        SELECT points, lifetime_points, tier_code
        FROM LoyaltyPoint
        WHERE user_id = %s AND store_id = %s
        """,
        (user_id, store_id),
    ).fetchone()


def assert_check_constraint(exc_info, constraint_name):
    assert exc_info.value.diag.constraint_name == constraint_name


def test_loyalty_tier_recalculates_when_points_cross_thresholds(app):
    with app.app_context():
        store_id = create_store()

        add_points(1, store_id, 499)
        row = get_loyalty_row(1, store_id)
        assert row["points"] == 499
        assert row["lifetime_points"] == 499
        assert row["tier_code"] == "Bronze"

        add_points(1, store_id, 1)
        row = get_loyalty_row(1, store_id)
        assert row["points"] == 500
        assert row["lifetime_points"] == 500
        assert row["tier_code"] == "Silver"

        add_points(1, store_id, 500)
        row = get_loyalty_row(1, store_id)
        assert row["points"] == 1000
        assert row["lifetime_points"] == 1000
        assert row["tier_code"] == "Gold"


def test_redemption_decreases_balance_without_downgrading_lifetime_tier(app):
    with app.app_context():
        store_id = create_store()

        add_points(1, store_id, 1000)
        discount = redeem_points(1, store_id, 600, "Test redemption")

        row = get_loyalty_row(1, store_id)
        assert discount == pytest.approx(60.0)
        assert row["points"] == 400
        assert row["lifetime_points"] == 1000
        assert row["tier_code"] == "Gold"


def test_loyalty_points_cannot_go_negative_in_sql(app):
    with app.app_context():
        store_id = create_store()
        add_points(1, store_id, 10)

        db = get_db()
        with pytest.raises(errors.CheckViolation) as exc_info:
            db.execute(
                """
                UPDATE LoyaltyPoint
                SET points = -1
                WHERE user_id = %s AND store_id = %s
                """,
                (1, store_id),
            )
            db.commit()
        assert_check_constraint(exc_info, "loyaltypoint_points_nonnegative")
        db.rollback()


def test_loyalty_lifetime_points_cannot_go_below_current_balance(app):
    with app.app_context():
        store_id = create_store()
        add_points(1, store_id, 10)

        db = get_db()
        with pytest.raises(errors.CheckViolation) as exc_info:
            db.execute(
                """
                UPDATE LoyaltyPoint
                SET lifetime_points = 9
                WHERE user_id = %s AND store_id = %s
                """,
                (1, store_id),
            )
            db.commit()
        assert_check_constraint(exc_info, "loyaltypoint_lifetime_not_less_than_balance")
        db.rollback()


def test_store_loyalty_stats_groups_customers_by_tier(app):
    with app.app_context():
        store_id = create_store()
        add_points(1, store_id, 100)
        add_points(2, store_id, 700)

        stats = get_store_loyalty_stats(store_id)
        distribution = {tier["code"]: tier["customer_count"] for tier in stats["tier_distribution"]}
        assert distribution["Bronze"] == 1
        assert distribution["Silver"] == 1
        assert distribution["Gold"] == 0

        silver_stats = get_store_loyalty_stats(store_id, "Silver")
        assert [customer["username"] for customer in silver_stats["customers"]] == ["other"]


def test_new_store_gets_default_loyalty_tiers_from_sql_trigger(app):
    with app.app_context():
        store_id = create_store()
        db = get_db()

        rows = db.execute(
            """
            SELECT code, min_points, discount_percent, reservation_advance_days, free_tournament_entries
            FROM LoyaltyTier
            WHERE store_id = %s
            ORDER BY min_points
            """,
            (store_id,),
        ).fetchall()

        assert [row["code"] for row in rows] == ["Bronze", "Silver", "Gold"]
        assert [row["min_points"] for row in rows] == [0, 500, 1000]
        assert all(row["discount_percent"] == 0 for row in rows)


def test_store_specific_tier_threshold_update_recalculates_existing_customers(app):
    with app.app_context():
        store_id = create_store()
        other_store_id = create_store("other-loyalty-store", "Other Loyalty Store")
        add_points(1, store_id, 600)
        add_points(1, other_store_id, 600)

        update_store_loyalty_tiers(
            store_id,
            [
                {
                    "code": "Bronze",
                    "min_points": 0,
                    "discount_percent": 0,
                    "reservation_advance_days": 0,
                    "free_tournament_entries": 0,
                },
                {
                    "code": "Silver",
                    "min_points": 700,
                    "discount_percent": 5,
                    "reservation_advance_days": 2,
                    "free_tournament_entries": 0,
                },
                {
                    "code": "Gold",
                    "min_points": 1200,
                    "discount_percent": 10,
                    "reservation_advance_days": 7,
                    "free_tournament_entries": 1,
                },
            ],
        )

        assert get_loyalty_row(1, store_id)["tier_code"] == "Bronze"
        assert get_loyalty_row(1, other_store_id)["tier_code"] == "Silver"

        stats = get_store_loyalty_stats(store_id)
        silver = next(tier for tier in stats["tiers"] if tier["code"] == "Silver")
        assert silver["min_points"] == 700
        assert silver["discount_percent"] == pytest.approx(5)
        assert silver["reservation_advance_days"] == 2


def test_tier_threshold_update_uses_lifetime_points_not_current_balance(app):
    with app.app_context():
        store_id = create_store()
        add_points(1, store_id, 1000)
        redeem_points(1, store_id, 600, "Spend down balance")

        update_store_loyalty_tiers(
            store_id,
            [
                {
                    "code": "Bronze",
                    "min_points": 0,
                    "discount_percent": 0,
                    "reservation_advance_days": 0,
                    "free_tournament_entries": 0,
                },
                {
                    "code": "Silver",
                    "min_points": 500,
                    "discount_percent": 5,
                    "reservation_advance_days": 2,
                    "free_tournament_entries": 0,
                },
                {
                    "code": "Gold",
                    "min_points": 900,
                    "discount_percent": 10,
                    "reservation_advance_days": 7,
                    "free_tournament_entries": 1,
                },
            ],
        )

        row = get_loyalty_row(1, store_id)
        assert row["points"] == 400
        assert row["lifetime_points"] == 1000
        assert row["tier_code"] == "Gold"


def test_loyalty_sql_functions_triggers_and_views_exist(app):
    with app.app_context():
        db = get_db()

        functions = db.execute(
            """
            SELECT proname
            FROM pg_proc
            WHERE proname IN (
                'fn_seed_default_loyalty_tiers',
                'fn_seed_default_loyalty_point_rules',
                'fn_recalculate_loyalty_tier',
                'fn_recalculate_store_loyalty_points',
                'fn_validate_loyalty_tier_threshold_order'
            )
            """
        ).fetchall()
        assert {row["proname"] for row in functions} == {
            "fn_seed_default_loyalty_tiers",
            "fn_seed_default_loyalty_point_rules",
            "fn_recalculate_loyalty_tier",
            "fn_recalculate_store_loyalty_points",
            "fn_validate_loyalty_tier_threshold_order",
        }

        triggers = db.execute(
            """
            SELECT tgname
            FROM pg_trigger
            WHERE NOT tgisinternal
              AND tgname IN (
                'seed_default_loyalty_tiers_after_store_insert',
                'seed_default_loyalty_point_rules_after_store_insert',
                'recalculate_loyalty_tier_before_insert',
                'recalculate_loyalty_tier_before_lifetime_points_update',
                'recalculate_store_loyalty_points_after_tier_update',
                'validate_loyalty_tier_threshold_order_after_insert_update'
              )
            """
        ).fetchall()
        assert {row["tgname"] for row in triggers} == {
            "seed_default_loyalty_tiers_after_store_insert",
            "seed_default_loyalty_point_rules_after_store_insert",
            "recalculate_loyalty_tier_before_insert",
            "recalculate_loyalty_tier_before_lifetime_points_update",
            "recalculate_store_loyalty_points_after_tier_update",
            "validate_loyalty_tier_threshold_order_after_insert_update",
        }

        views = db.execute(
            """
            SELECT viewname
            FROM pg_views
            WHERE schemaname = 'public'
              AND viewname = 'store_top_loyalty_point_holders'
            """
        ).fetchall()
        assert [row["viewname"] for row in views] == ["store_top_loyalty_point_holders"]


def test_store_top_loyalty_point_holders_view_ranks_top_five_by_lifetime_points(app):
    with app.app_context():
        store_id = create_store()
        user_ids = [1, 2]
        user_ids.extend(create_user(f"loyalty-view-user-{index}") for index in range(3, 8))

        for user_id, points in zip(user_ids, [100, 200, 300, 400, 500, 600, 700]):
            add_points(user_id, store_id, points)
        redeem_points(user_ids[-1], store_id, 250, "Keep lifetime rank high")

        db = get_db()
        rows = db.execute(
            """
            SELECT username, current_points, redeemed_points, lifetime_points, store_rank
            FROM store_top_loyalty_point_holders
            WHERE store_id = %s
            ORDER BY store_rank
            """,
            (store_id,),
        ).fetchall()

        assert len(rows) == 5
        assert [row["lifetime_points"] for row in rows] == [700, 600, 500, 400, 300]
        assert rows[0]["current_points"] == 450
        assert rows[0]["redeemed_points"] == 250
        assert get_loyalty_row(user_ids[-1], store_id)["tier_code"] == "Silver"
        assert [row["store_rank"] for row in rows] == [1, 2, 3, 4, 5]

        stats = get_store_loyalty_stats(store_id)
        assert [customer["lifetime_points"] for customer in stats["top_customers"]] == [700, 600, 500, 400, 300]


@pytest.mark.parametrize(
    ("sql", "params", "constraint_name"),
    [
        (
            "UPDATE LoyaltyTier SET code = 'Platinum' WHERE store_id = %s AND code = 'Gold'",
            (),
            "loyaltytier_valid_code",
        ),
        (
            "UPDATE LoyaltyTier SET min_points = -1 WHERE store_id = %s AND code = 'Silver'",
            (),
            "loyaltytier_min_points_nonnegative",
        ),
        (
            "UPDATE LoyaltyTier SET discount_percent = 101 WHERE store_id = %s AND code = 'Silver'",
            (),
            "loyaltytier_discount_percent_range",
        ),
        (
            "UPDATE LoyaltyTier SET reservation_advance_days = -1 WHERE store_id = %s AND code = 'Silver'",
            (),
            "loyaltytier_reservation_advance_days_nonnegative",
        ),
        (
            "UPDATE LoyaltyTier SET free_tournament_entries = -1 WHERE store_id = %s AND code = 'Gold'",
            (),
            "loyaltytier_free_tournament_entries_nonnegative",
        ),
    ],
)
def test_loyalty_tier_named_constraints_are_enforced(app, sql, params, constraint_name):
    with app.app_context():
        store_id = create_store()
        db = get_db()

        with pytest.raises(errors.CheckViolation) as exc_info:
            db.execute(sql, (store_id, *params))
            db.commit()
        assert_check_constraint(exc_info, constraint_name)
        db.rollback()


def test_loyalty_tier_threshold_order_constraint_rejects_gold_below_silver(app):
    with app.app_context():
        store_id = create_store()
        db = get_db()

        with pytest.raises(errors.CheckViolation) as exc_info:
            db.execute(
                """
                UPDATE LoyaltyTier
                SET min_points = %s
                WHERE store_id = %s AND code = 'Gold'
                """,
                (400, store_id),
            )
            db.commit()
        assert_check_constraint(exc_info, "loyaltytier_threshold_order")
        db.rollback()


def test_loyalty_tier_threshold_order_constraint_rejects_silver_below_bronze(app):
    with app.app_context():
        store_id = create_store()
        db = get_db()

        with pytest.raises(errors.CheckViolation) as exc_info:
            db.execute(
                """
                UPDATE LoyaltyTier
                SET min_points = %s
                WHERE store_id = %s AND code = 'Bronze'
                """,
                (100, store_id),
            )
            db.execute(
                """
                UPDATE LoyaltyTier
                SET min_points = %s
                WHERE store_id = %s AND code = 'Silver'
                """,
                (50, store_id),
            )
            db.commit()
        assert_check_constraint(exc_info, "loyaltytier_threshold_order")
        db.rollback()


def test_loyalty_redemption_points_spent_constraint_is_named(app):
    with app.app_context():
        store_id = create_store()
        db = get_db()

        with pytest.raises(errors.CheckViolation) as exc_info:
            db.execute(
                """
                INSERT INTO LoyaltyRedemption (user_id, store_id, points_spent, description)
                VALUES (%s, %s, %s, %s)
                """,
                (1, store_id, 0, "Invalid redemption"),
            )
            db.commit()
        assert_check_constraint(exc_info, "loyaltyredemption_points_spent_positive")
        db.rollback()


@pytest.mark.parametrize(
    ("sql", "constraint_name"),
    [
        (
            "UPDATE LoyaltyPointRule SET action_code = 'unknown_action' WHERE store_id = %s AND action_code = 'game_rating'",
            "loyaltypointrule_valid_action",
        ),
        (
            "UPDATE LoyaltyPointRule SET points_per_unit = -1 WHERE store_id = %s AND action_code = 'game_rating'",
            "loyaltypointrule_points_nonnegative",
        ),
    ],
)
def test_loyalty_point_rule_named_constraints_are_enforced(app, sql, constraint_name):
    with app.app_context():
        store_id = create_store()
        db = get_db()

        with pytest.raises(errors.CheckViolation) as exc_info:
            db.execute(sql, (store_id,))
            db.commit()
        assert_check_constraint(exc_info, constraint_name)
        db.rollback()


def test_redeem_points_rejects_insufficient_balance_without_deducting(app):
    with app.app_context():
        store_id = create_store()
        add_points(1, store_id, 25)

        with pytest.raises(ValueError, match="Insufficient points balance"):
            redeem_points(1, store_id, 30, "Too many points")

        db = get_db()
        assert get_loyalty_row(1, store_id)["points"] == 25
        redemptions = db.execute(
            """
            SELECT COUNT(*) AS count
            FROM LoyaltyRedemption
            WHERE user_id = %s AND store_id = %s
            """,
            (1, store_id),
        ).fetchone()
        assert redemptions["count"] == 0


def test_owner_can_update_store_loyalty_tier_settings(client, app):
    with app.app_context():
        store_id = create_store()

    with client.session_transaction() as sess:
        sess["store_id"] = store_id

    response = client.post(
        "/mystore/loyalty/tiers",
        data={
            "Bronze_min_points": "0",
            "Bronze_discount_percent": "0",
            "Bronze_reservation_advance_days": "0",
            "Bronze_free_tournament_entries": "0",
            "Silver_min_points": "800",
            "Silver_discount_percent": "5",
            "Silver_reservation_advance_days": "3",
            "Silver_free_tournament_entries": "0",
            "Gold_min_points": "1500",
            "Gold_discount_percent": "15",
            "Gold_reservation_advance_days": "10",
            "Gold_free_tournament_entries": "2",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        stats = get_store_loyalty_stats(store_id)
        silver = next(tier for tier in stats["tiers"] if tier["code"] == "Silver")
        gold = next(tier for tier in stats["tiers"] if tier["code"] == "Gold")
        assert silver["min_points"] == 800
        assert silver["discount_percent"] == pytest.approx(5)
        assert silver["reservation_advance_days"] == 3
        assert gold["min_points"] == 1500
        assert gold["discount_percent"] == pytest.approx(15)
        assert gold["free_tournament_entries"] == 2


def test_owner_loyalty_policy_editors_are_hidden_behind_buttons(client, app):
    with app.app_context():
        store_id = create_store()

    with client.session_transaction() as sess:
        sess["store_id"] = store_id

    response = client.get("/mystore/loyalty")
    assert response.status_code == 200
    body = response.get_data(as_text=True)

    assert "Edit Tier Settings" in body
    assert "Edit Reward Policy" in body
    assert 'class="collapse" id="tierSettingsEditor"' in body
    assert 'class="collapse" id="rewardPolicyEditor"' in body
    assert 'data-bs-target="#tierSettingsEditor"' in body
    assert 'data-bs-target="#rewardPolicyEditor"' in body


def test_new_store_gets_default_loyalty_point_rules_from_sql_trigger(app):
    with app.app_context():
        store_id = create_store()
        db = get_db()

        rows = db.execute(
            """
            SELECT action_code, points_per_unit
            FROM LoyaltyPointRule
            WHERE store_id = %s
            ORDER BY action_code
            """,
            (store_id,),
        ).fetchall()
        rules = {row["action_code"]: row["points_per_unit"] for row in rows}
        assert rules == {
            "food_dollar": 1,
            "game_rating": 5,
            "session_hour": 5,
            "tournament_participation": 20,
        }


def test_store_specific_point_rule_update_changes_earning_values(app):
    with app.app_context():
        store_id = create_store()
        other_store_id = create_store("other-rule-store", "Other Rule Store")

        update_store_loyalty_point_rules(
            store_id,
            [
                {"action_code": "session_hour", "points_per_unit": 8},
                {"action_code": "food_dollar", "points_per_unit": 2},
                {"action_code": "game_rating", "points_per_unit": 12},
                {"action_code": "tournament_participation", "points_per_unit": 30},
            ],
        )

        assert get_point_rule(store_id, "session_hour") == pytest.approx(8)
        assert get_point_rule(store_id, "food_dollar") == pytest.approx(2)
        assert get_point_rule(store_id, "game_rating") == pytest.approx(12)
        assert get_point_rule(store_id, "tournament_participation") == pytest.approx(30)
        assert get_point_rule(other_store_id, "game_rating") == pytest.approx(5)


def test_owner_can_update_store_loyalty_point_rules(client, app):
    with app.app_context():
        store_id = create_store()

    with client.session_transaction() as sess:
        sess["store_id"] = store_id

    response = client.post(
        "/mystore/loyalty/point-rules",
        data={
            "session_hour": "9",
            "food_dollar": "2.5",
            "game_rating": "11",
            "tournament_participation": "40",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        assert get_point_rule(store_id, "session_hour") == pytest.approx(9)
        assert get_point_rule(store_id, "food_dollar") == pytest.approx(2.5)
        assert get_point_rule(store_id, "game_rating") == pytest.approx(11)
        assert get_point_rule(store_id, "tournament_participation") == pytest.approx(40)


def test_seed_loyalty_program_creates_visible_tiers_top_holders_and_applied_redemptions(app):
    with app.app_context():
        user_ids = [1, 2, create_user("seed-loyalty-user")]
        store_ids = [
            create_store("seed-loyalty-store-1", "Seed Loyalty Store 1"),
            create_store("seed-loyalty-store-2", "Seed Loyalty Store 2"),
            create_store("seed-loyalty-store-3", "Seed Loyalty Store 3"),
        ]

        seed_loyalty_program(user_ids, store_ids)

        stats = get_store_loyalty_stats(store_ids[0])
        distribution = {tier["code"]: tier["customer_count"] for tier in stats["tier_distribution"]}
        assert distribution == {"Bronze": 1, "Silver": 1, "Gold": 1}
        assert [customer["store_rank"] for customer in stats["top_customers"]] == [1, 2, 3]
        assert stats["point_rule_map"]["session_hour"] == pytest.approx(6)
        assert stats["point_rule_map"]["tournament_participation"] == pytest.approx(25)

        db = get_db()
        redemption_summary = db.execute(
            """
            SELECT COUNT(*) AS redemption_count,
                   COUNT(*) FILTER (WHERE bill_id IS NULL) AS unapplied_count
            FROM LoyaltyRedemption
            WHERE store_id = ANY(%s)
            """,
            (store_ids,),
        ).fetchone()
        assert redemption_summary["redemption_count"] == 2
        assert redemption_summary["unapplied_count"] == 0
