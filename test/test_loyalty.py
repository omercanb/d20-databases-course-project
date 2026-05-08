import pytest
from psycopg2 import errors

from d20.db import get_db
from d20.db.checkout import checkout_session
from d20.db.loyalty import (
    REDEMPTION_RATE,
    add_points,
    get_customer_loyalty_profile,
    get_loyalty_analytics,
    get_point_rule,
    get_store_loyalty_stats,
    get_user_points,
    redeem_points,
    update_store_loyalty_point_rules,
    update_store_loyalty_tiers,
)
from d20.db.tournament import register_participant
from d20.db.voucher import create_voucher
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


def test_checkout_awards_session_hour_loyalty_points_once(client, app):
    with app.app_context():
        db = get_db()
        store_id = create_store("checkout-loyalty-store", "Checkout Loyalty Store")
        db.execute(
            'INSERT INTO "Table" (store_id, table_num, capacity) VALUES (%s, 1, 4)',
            (store_id,),
        )
        session_id = db.execute(
            """
            INSERT INTO Session (user_id, store_id, table_num, day, start_time, end_time, checked_in)
            VALUES (1, %s, 1, '2099-01-01', 10, 12, TRUE)
            RETURNING id
            """,
            (store_id,),
        ).fetchone()["id"]
        db.commit()

    with client.session_transaction() as sess:
        sess["store_id"] = store_id

    response = client.post(f"/mystore/session/{session_id}/checkout")
    assert response.status_code == 302

    with app.app_context():
        row = get_loyalty_row(1, store_id)
        assert row["points"] == 10
        assert row["lifetime_points"] == 10
        assert row["tier_code"] == "Bronze"

    second_response = client.post(f"/mystore/session/{session_id}/checkout")
    assert second_response.status_code == 302

    with app.app_context():
        row = get_loyalty_row(1, store_id)
        assert row["points"] == 10
        assert row["lifetime_points"] == 10


def test_store_owner_cannot_checkout_before_customer_checkin(client, app):
    with app.app_context():
        db = get_db()
        store_id = create_store("pre-checkin-checkout-store", "Pre Checkin Store")
        db.execute(
            'INSERT INTO "Table" (store_id, table_num, capacity) VALUES (%s, 1, 4)',
            (store_id,),
        )
        session_id = db.execute(
            """
            INSERT INTO Session (user_id, store_id, table_num, day, start_time, end_time)
            VALUES (1, %s, 1, '2099-01-01', 10, 12)
            RETURNING id
            """,
            (store_id,),
        ).fetchone()["id"]
        db.commit()

    with client.session_transaction() as sess:
        sess["store_id"] = store_id

    get_response = client.get(
        f"/mystore/session/{session_id}/checkout",
        follow_redirects=True,
    )
    post_response = client.post(
        f"/mystore/session/{session_id}/checkout",
        follow_redirects=True,
    )

    assert get_response.status_code == 200
    assert post_response.status_code == 200
    assert "Customer must check in before checkout." in get_response.get_data(as_text=True)
    assert "Customer must check in before checkout." in post_response.get_data(as_text=True)

    with app.app_context():
        db = get_db()
        bill_count = db.execute(
            "SELECT COUNT(*) AS count FROM Bill WHERE session_id = %s",
            (session_id,),
        ).fetchone()["count"]
        session = db.execute(
            "SELECT checkout_status, checked_in FROM Session WHERE id = %s",
            (session_id,),
        ).fetchone()
        loyalty_row = get_loyalty_row(1, store_id)

        assert bill_count == 0
        assert session["checkout_status"] == "active"
        assert session["checked_in"] is False
        assert loyalty_row is None


def test_checkout_applies_current_tier_discount(app):
    with app.app_context():
        db = get_db()
        store_id = create_store("tier-discount-store", "Tier Discount Store")
        db.execute(
            'INSERT INTO "Table" (store_id, table_num, capacity) VALUES (%s, 1, 4)',
            (store_id,),
        )
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
                    "discount_percent": 10,
                    "reservation_advance_days": 0,
                    "free_tournament_entries": 0,
                },
                {
                    "code": "Gold",
                    "min_points": 1000,
                    "discount_percent": 20,
                    "reservation_advance_days": 0,
                    "free_tournament_entries": 1,
                },
            ],
        )
        add_points(1, store_id, 600)
        session_id = db.execute(
            """
            INSERT INTO Session (user_id, store_id, table_num, day, start_time, end_time)
            VALUES (1, %s, 1, '2099-01-01', 10, 12)
            RETURNING id
            """,
            (store_id,),
        ).fetchone()["id"]
        db.commit()

        bill = checkout_session(session_id, [])

        assert bill["table_fee"] == pytest.approx(10)
        assert bill["tier_discount"] == pytest.approx(1)
        assert bill["grand_total"] == pytest.approx(9)


def test_checkout_rejects_customer_voucher_from_another_store(app):
    with app.app_context():
        db = get_db()
        store_id = create_store("voucher-checkout-store", "Voucher Checkout Store")
        other_store_id = create_store("other-voucher-store", "Other Voucher Store")
        db.execute(
            'INSERT INTO "Table" (store_id, table_num, capacity) VALUES (%s, 1, 4)',
            (store_id,),
        )
        session_id = db.execute(
            """
            INSERT INTO Session (user_id, store_id, table_num, day, start_time, end_time)
            VALUES (1, %s, 1, '2099-01-01', 10, 12)
            RETURNING id
            """,
            (store_id,),
        ).fetchone()["id"]
        db.commit()

        voucher_id = create_voucher(
            other_store_id,
            "Wrong Store Credit",
            "Should not apply outside its store.",
            50,
            "any",
            5,
        )
        customer_voucher_id = db.execute(
            """
            INSERT INTO CustomerVoucher (user_id, store_id, voucher_id)
            VALUES (1, %s, %s)
            RETURNING id
            """,
            (other_store_id, voucher_id),
        ).fetchone()["id"]
        db.commit()

        with pytest.raises(ValueError, match="Voucher is not valid for this session"):
            checkout_session(session_id, [], customer_voucher_id)

        bill_count = db.execute(
            "SELECT COUNT(*) AS count FROM Bill WHERE session_id = %s",
            (session_id,),
        ).fetchone()["count"]
        customer_voucher = db.execute(
            "SELECT is_used, bill_id FROM CustomerVoucher WHERE id = %s",
            (customer_voucher_id,),
        ).fetchone()
        session = db.execute(
            "SELECT checkout_status FROM Session WHERE id = %s",
            (session_id,),
        ).fetchone()

        assert bill_count == 0
        assert customer_voucher["is_used"] is False
        assert customer_voucher["bill_id"] is None
        assert session["checkout_status"] == "active"


def test_checkout_rejects_food_voucher_when_bill_has_no_food(app):
    with app.app_context():
        db = get_db()
        store_id = create_store("food-voucher-store", "Food Voucher Store")
        db.execute(
            'INSERT INTO "Table" (store_id, table_num, capacity) VALUES (%s, 1, 4)',
            (store_id,),
        )
        session_id = db.execute(
            """
            INSERT INTO Session (user_id, store_id, table_num, day, start_time, end_time)
            VALUES (1, %s, 1, '2099-01-01', 10, 12)
            RETURNING id
            """,
            (store_id,),
        ).fetchone()["id"]
        db.commit()

        voucher_id = create_voucher(
            store_id,
            "Food Only Credit",
            "Only applies to food and drinks.",
            50,
            "food",
            5,
        )
        customer_voucher_id = db.execute(
            """
            INSERT INTO CustomerVoucher (user_id, store_id, voucher_id)
            VALUES (1, %s, %s)
            RETURNING id
            """,
            (store_id, voucher_id),
        ).fetchone()["id"]
        db.commit()

        with pytest.raises(ValueError, match="Voucher does not apply to this bill"):
            checkout_session(session_id, [], customer_voucher_id)

        bill_count = db.execute(
            "SELECT COUNT(*) AS count FROM Bill WHERE session_id = %s",
            (session_id,),
        ).fetchone()["count"]
        customer_voucher = db.execute(
            "SELECT is_used, bill_id FROM CustomerVoucher WHERE id = %s",
            (customer_voucher_id,),
        ).fetchone()

        assert bill_count == 0
        assert customer_voucher["is_used"] is False
        assert customer_voucher["bill_id"] is None


def test_store_owner_can_create_voucher(client, app):
    with app.app_context():
        store_id = create_store("owner-voucher-store", "Owner Voucher Store")

    with client.session_transaction() as sess:
        sess["store_id"] = store_id

    response = client.post(
        "/mystore/vouchers/add",
        data={
            "name": "Owner Food Credit",
            "description": "Created from the owner dashboard.",
            "point_cost": "75",
            "reward_type": "food",
            "reward_value": "7.50",
        },
    )

    assert response.status_code == 302
    with app.app_context():
        voucher = get_db().execute(
            """
            SELECT name, description, point_cost, reward_type, reward_value, is_active
            FROM LoyaltyVoucher
            WHERE store_id = %s AND name = %s
            """,
            (store_id, "Owner Food Credit"),
        ).fetchone()

        assert voucher is not None
        assert voucher["description"] == "Created from the owner dashboard."
        assert voucher["point_cost"] == 75
        assert voucher["reward_type"] == "food"
        assert voucher["reward_value"] == pytest.approx(7.50)
        assert voucher["is_active"] is True


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
              AND viewname IN (
                'store_top_loyalty_point_holders',
                'vw_loyalty_tier_distribution',
                'vw_loyalty_redemption_overview',
                'vw_loyalty_redemption_by_tier',
                'vw_loyalty_revenue_impact',
                'vw_loyalty_most_loyal'
              )
            ORDER BY viewname
            """
        ).fetchall()
        assert {row["viewname"] for row in views} == {
            "store_top_loyalty_point_holders",
            "vw_loyalty_tier_distribution",
            "vw_loyalty_redemption_overview",
            "vw_loyalty_redemption_by_tier",
            "vw_loyalty_revenue_impact",
            "vw_loyalty_most_loyal",
        }


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
        assert_check_constraint(exc_info, "loyaltyredemption_points_spent_nonzero")
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


def test_free_tournament_entry_is_used_before_points_are_deducted(app):
    with app.app_context():
        db = get_db()
        store_id = create_store("free-entry-store", "Free Entry Store")
        db.execute(
            'INSERT INTO "Table" (store_id, table_num, capacity) VALUES (%s, 1, 4)',
            (store_id,),
        )
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
                    "reservation_advance_days": 0,
                    "free_tournament_entries": 0,
                },
                {
                    "code": "Gold",
                    "min_points": 1000,
                    "discount_percent": 10,
                    "reservation_advance_days": 0,
                    "free_tournament_entries": 1,
                },
            ],
        )
        add_points(1, store_id, 1200)
        first_tournament_id = db.execute(
            """
            INSERT INTO Tournament
                (store_id, game_id, name, format, max_participants, players_per_match,
                 entry_fee_points, start_date, end_date)
            VALUES (%s, 1, 'Free Entry One', 'single_elimination', 8, 2, 100,
                    '2099-01-01 10:00', '2099-01-01 12:00')
            RETURNING id
            """,
            (store_id,),
        ).fetchone()["id"]
        second_tournament_id = db.execute(
            """
            INSERT INTO Tournament
                (store_id, game_id, name, format, max_participants, players_per_match,
                 entry_fee_points, start_date, end_date)
            VALUES (%s, 1, 'Paid Entry Two', 'single_elimination', 8, 2, 100,
                    '2099-01-02 10:00', '2099-01-02 12:00')
            RETURNING id
            """,
            (store_id,),
        ).fetchone()["id"]
        for tournament_id in (first_tournament_id, second_tournament_id):
            db.execute(
                "INSERT INTO TournamentTable (tournament_id, store_id, table_num) VALUES (%s, %s, 1)",
                (tournament_id, store_id),
            )
        db.commit()

        register_participant(first_tournament_id, 1)
        after_free = get_loyalty_row(1, store_id)
        first_participant = db.execute(
            """
            SELECT used_free_entry
            FROM TournamentParticipant
            WHERE tournament_id = %s AND user_id = 1
            """,
            (first_tournament_id,),
        ).fetchone()
        assert first_participant["used_free_entry"] is True
        assert after_free["points"] == 1200

        register_participant(second_tournament_id, 1)
        after_paid = get_loyalty_row(1, store_id)
        second_participant = db.execute(
            """
            SELECT used_free_entry
            FROM TournamentParticipant
            WHERE tournament_id = %s AND user_id = 1
            """,
            (second_tournament_id,),
        ).fetchone()
        used_free_entries = db.execute(
            """
            SELECT used_free_tournament_entries
            FROM LoyaltyPoint
            WHERE user_id = 1 AND store_id = %s
            """,
            (store_id,),
        ).fetchone()["used_free_tournament_entries"]

        assert second_participant["used_free_entry"] is False
        assert after_paid["points"] == 1100
        assert used_free_entries == 1


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


def test_owner_can_view_customer_loyalty_profile(client, app):
    with app.app_context():
        db = get_db()
        store_id = create_store("profile-loyalty-store", "Profile Loyalty Store")
        db.execute(
            'INSERT INTO "Table" (store_id, table_num, capacity) VALUES (%s, 1, 4)',
            (store_id,),
        )
        add_points(1, store_id, 250)
        session_id = db.execute(
            """
            INSERT INTO Session (user_id, store_id, table_num, day, start_time, end_time, checkout_status)
            VALUES (1, %s, 1, '2000-01-01', 10, 12, 'checked_out')
            RETURNING id
            """,
            (store_id,),
        ).fetchone()["id"]
        db.execute(
            """
            INSERT INTO Bill (session_id, table_fee, food_total, damage_fee, grand_total)
            VALUES (%s, 10, 0, 0, 10)
            """,
            (session_id,),
        )
        db.commit()

        profile = get_customer_loyalty_profile(1, store_id)
        assert profile["user"]["username"] == "test"
        assert profile["lifetime_points"] == 250
        assert profile["session_summary"]["checked_out_sessions"] == 1

    with client.session_transaction() as sess:
        sess["store_id"] = store_id

    response = client.get(f"/mystore/loyalty/customer/1")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "test Loyalty Profile" in body
    assert "Lifetime Points" in body
    assert "Recent Past Sessions" in body


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


def test_user_loyalty_policy_page_shows_store_specific_rules_and_tiers(client, app):
    with app.app_context():
        store_id = create_store("policy-store", "Policy Store")
        update_store_loyalty_point_rules(
            store_id,
            [
                {"action_code": "session_hour", "points_per_unit": 8},
                {"action_code": "food_dollar", "points_per_unit": 2},
                {"action_code": "game_rating", "points_per_unit": 12},
                {"action_code": "tournament_participation", "points_per_unit": 30},
            ],
        )
        update_store_loyalty_tiers(
            store_id,
            [
                {
                    "code": "Bronze",
                    "min_points": 0,
                    "discount_percent": 0,
                    "reservation_advance_days": 2,
                    "free_tournament_entries": 0,
                },
                {
                    "code": "Silver",
                    "min_points": 500,
                    "discount_percent": 7.5,
                    "reservation_advance_days": 10,
                    "free_tournament_entries": 1,
                },
                {
                    "code": "Gold",
                    "min_points": 900,
                    "discount_percent": 15,
                    "reservation_advance_days": 21,
                    "free_tournament_entries": 2,
                },
            ],
        )
        add_points(1, store_id, 900)

    with client.session_transaction() as sess:
        sess["user_id"] = 1

    response = client.get(f"/auth/loyalty/{store_id}/how-it-works")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Policy Store Loyalty Policy" in body
    assert "How It Works" in body
    assert "Table session hour" in body
    assert "8 pts" in body
    assert "$90.00" in body
    assert "Gold" in body
    assert "15%" in body
    assert "21" in body
    assert "2" in body


def test_user_loyalty_policy_page_returns_to_store_rewards_when_opened_there(client, app):
    with app.app_context():
        store_id = create_store("policy-return-store", "Policy Return Store")

    with client.session_transaction() as sess:
        sess["user_id"] = 1

    response = client.get(
        f"/auth/loyalty/{store_id}/how-it-works?next=/store/{store_id}/loyalty"
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Back to Loyalty Rewards" in body
    assert f'href="/store/{store_id}/loyalty"' in body
    assert "$0.00" in body


def test_store_loyalty_page_links_to_policy_page(client, app):
    with app.app_context():
        store_id = create_store("policy-link-store", "Policy Link Store")

    with client.session_transaction() as sess:
        sess["user_id"] = 1

    response = client.get(f"/store/{store_id}/loyalty")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "How It Works" in body
    assert f"/auth/loyalty/{store_id}/how-it-works" in body


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
        # seed_loyalty_program expects 8 users (indices 0-7)
        user_ids = [
            1, 2,
            create_user("seed-u3"), create_user("seed-u4"),
            create_user("seed-u5"), create_user("seed-u6"),
            create_user("seed-u7"), create_user("seed-u8"),
        ]
        store_ids = [
            create_store("seed-loyalty-store-1", "Seed Loyalty Store 1"),
            create_store("seed-loyalty-store-2", "Seed Loyalty Store 2"),
            create_store("seed-loyalty-store-3", "Seed Loyalty Store 3"),
        ]

        seed_loyalty_program(user_ids, store_ids)

        # store 0 uses tier_configs[0]: Silver≥300, Gold≥800
        # effective lifetime points (base + 45 extra from rules): Bronze×3, Silver×2, Gold×3
        stats = get_store_loyalty_stats(store_ids[0])
        distribution = {tier["code"]: tier["customer_count"] for tier in stats["tier_distribution"]}
        assert distribution == {"Bronze": 3, "Silver": 2, "Gold": 3}
        assert len(stats["top_customers"]) == 5
        assert [customer["store_rank"] for customer in stats["top_customers"]] == [1, 2, 3, 4, 5]
        assert stats["point_rule_map"]["session_hour"] == pytest.approx(6)
        assert stats["point_rule_map"]["tournament_participation"] == pytest.approx(25)

        db = get_db()
        # 6 (store0) + 7 (store1) + 6 (store2) = 19 applied redemptions total
        redemption_summary = db.execute(
            """
            SELECT COUNT(*) AS redemption_count,
                   COUNT(*) FILTER (WHERE bill_id IS NULL) AS unapplied_count
            FROM LoyaltyRedemption
            WHERE store_id = ANY(%s)
            """,
            (store_ids,),
        ).fetchone()
        assert redemption_summary["redemption_count"] == 19
        assert redemption_summary["unapplied_count"] == 0


# ── get_loyalty_analytics ─────────────────────────────────────────────────────

def test_analytics_returns_required_keys(app):
    with app.app_context():
        store_id = create_store()
        analytics = get_loyalty_analytics(store_id)
        for key in ("tier_distribution", "redemption_overview", "redemption_by_tier",
                    "revenue_impact", "most_loyal", "available_tiers"):
            assert key in analytics


def test_analytics_available_tiers_are_all_three(app):
    with app.app_context():
        store_id = create_store()
        analytics = get_loyalty_analytics(store_id)
        assert set(analytics["available_tiers"]) == {"Bronze", "Silver", "Gold"}


def test_analytics_tier_distribution_has_three_rows(app):
    with app.app_context():
        store_id = create_store()
        add_points(1, store_id, 10)
        analytics = get_loyalty_analytics(store_id)
        assert len(analytics["tier_distribution"]) == 3


def test_analytics_tier_distribution_columns(app):
    with app.app_context():
        store_id = create_store()
        add_points(1, store_id, 10)
        row = get_loyalty_analytics(store_id)["tier_distribution"][0]
        for col in ("tier", "threshold", "customer_count", "total_active_points",
                    "total_lifetime_points", "discount_percent", "pct_of_customers"):
            assert col in row


def test_analytics_tier_filter_limits_distribution(app):
    with app.app_context():
        store_id = create_store()
        add_points(1, store_id, 600)   # → Silver (default threshold 500)
        add_points(2, store_id, 50)    # → Bronze
        analytics = get_loyalty_analytics(store_id, tier_code="Silver")
        assert len(analytics["tier_distribution"]) == 1
        assert analytics["tier_distribution"][0]["tier"] == "Silver"


def test_analytics_tier_filter_limits_most_loyal(app):
    with app.app_context():
        store_id = create_store()
        add_points(1, store_id, 600)   # → Silver
        add_points(2, store_id, 50)    # → Bronze
        analytics = get_loyalty_analytics(store_id, tier_code="Silver")
        usernames = [c["username"] for c in analytics["most_loyal"]]
        assert "test" in usernames
        assert "other" not in usernames


def test_analytics_redemption_overview_zero_with_no_redemptions(app):
    with app.app_context():
        store_id = create_store()
        analytics = get_loyalty_analytics(store_id)
        r = analytics["redemption_overview"]
        assert r["total_redemptions"] == 0
        assert r["total_points_redeemed"] == 0


def test_analytics_redemption_overview_counts_after_redeem(app):
    with app.app_context():
        store_id = create_store()
        add_points(1, store_id, 500)
        redeem_points(1, store_id, 100, "Deal 1")
        redeem_points(1, store_id, 50, "Deal 2")
        analytics = get_loyalty_analytics(store_id)
        r = analytics["redemption_overview"]
        assert r["total_redemptions"] == 2
        assert r["total_points_redeemed"] == 150
        assert r["min_redemption"] == 50
        assert r["max_redemption"] == 100


def test_analytics_revenue_impact_zero_without_bills(app):
    with app.app_context():
        store_id = create_store()
        analytics = get_loyalty_analytics(store_id)
        assert analytics["revenue_impact"]["total_bills"] == 0


def test_analytics_most_loyal_contains_user_after_points(app):
    with app.app_context():
        store_id = create_store()
        add_points(1, store_id, 400)
        analytics = get_loyalty_analytics(store_id)
        usernames = [c["username"] for c in analytics["most_loyal"]]
        assert "test" in usernames


def test_analytics_most_loyal_columns(app):
    with app.app_context():
        store_id = create_store()
        add_points(1, store_id, 400)
        row = get_loyalty_analytics(store_id)["most_loyal"][0]
        for col in ("username", "tier_code", "current_points", "lifetime_points",
                    "points_spent", "redemption_count", "discount_value",
                    "session_count", "total_spent"):
            assert col in row


# ── Analytics routes ──────────────────────────────────────────────────────────

def test_analytics_page_requires_store_login(client, app):
    with app.app_context():
        store_id = create_store()
    resp = client.get("/mystore/loyalty/analytics")
    assert resp.status_code == 302
    assert "loginstore" in resp.headers["Location"]


def test_analytics_page_loads_with_store_session(client, app):
    with app.app_context():
        store_id = create_store()
    with client.session_transaction() as sess:
        sess["store_id"] = store_id
    resp = client.get("/mystore/loyalty/analytics")
    assert resp.status_code == 200
    assert b"Loyalty Statistics" in resp.data


def test_analytics_page_shows_tier_tables(client, app):
    with app.app_context():
        store_id = create_store()
        add_points(1, store_id, 600)
    with client.session_transaction() as sess:
        sess["store_id"] = store_id
    resp = client.get("/mystore/loyalty/analytics")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Points Distribution Across Tiers" in body
    assert "Redemption Overview" in body
    assert "Revenue Impact" in body
    assert "Most Loyal Customers" in body


def test_analytics_page_silver_tier_filter(client, app):
    with app.app_context():
        store_id = create_store()
        add_points(1, store_id, 600)
    with client.session_transaction() as sess:
        sess["store_id"] = store_id
    resp = client.get("/mystore/loyalty/analytics?tier=Silver")
    assert resp.status_code == 200


def test_analytics_page_invalid_tier_redirects_with_flash(client, app):
    with app.app_context():
        store_id = create_store()
    with client.session_transaction() as sess:
        sess["store_id"] = store_id
    resp = client.get("/mystore/loyalty/analytics?tier=Platinum", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Unknown loyalty tier" in resp.data
