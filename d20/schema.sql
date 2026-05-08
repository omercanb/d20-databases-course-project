DROP TABLE IF EXISTS TournamentMatchParticipant CASCADE;
DROP TABLE IF EXISTS TournamentResult CASCADE;
DROP TABLE IF EXISTS TournamentMatch CASCADE;
DROP TABLE IF EXISTS TournamentParticipant CASCADE;
DROP TABLE IF EXISTS TournamentTable CASCADE;
DROP TABLE IF EXISTS Tournament CASCADE;
DROP TABLE IF EXISTS CustomerVoucher CASCADE;
DROP TABLE IF EXISTS LoyaltyVoucher CASCADE;
DROP TABLE IF EXISTS Bill CASCADE;
DROP TABLE IF EXISTS LoyaltyRedemption CASCADE;
DROP TABLE IF EXISTS LoyaltyPoint CASCADE;
DROP TABLE IF EXISTS LoyaltyPointRule CASCADE;
DROP TABLE IF EXISTS LoyaltyTier CASCADE;
DROP TABLE IF EXISTS GameDamage CASCADE;
DROP TABLE IF EXISTS SessionGameCopy CASCADE;
DROP TABLE IF EXISTS DynamicGamePrice CASCADE;
DROP TABLE IF EXISTS Session CASCADE;
DROP TABLE IF EXISTS GameRating CASCADE;
DROP TABLE IF EXISTS GameCopy CASCADE;
DROP TABLE IF EXISTS GameSimilarity CASCADE;
DROP TABLE IF EXISTS Game CASCADE;
DROP TABLE IF EXISTS "Table" CASCADE;
DROP TABLE IF EXISTS TradingScript CASCADE;
DROP TABLE IF EXISTS MarketHistory CASCADE;
DROP TABLE IF EXISTS Orders CASCADE;
DROP TABLE IF EXISTS MarketParticipantInventory CASCADE;
DROP TABLE IF EXISTS MarketParticipant CASCADE;
DROP TABLE IF EXISTS SessionOrderItem CASCADE;
DROP TABLE IF EXISTS SessionOrder CASCADE;
DROP TABLE IF EXISTS Beverage CASCADE;
DROP TABLE IF EXISTS Food CASCADE;
DROP TABLE IF EXISTS MenuItem CASCADE;
DROP TABLE IF EXISTS Store CASCADE;
DROP TABLE IF EXISTS "User" CASCADE;

DROP FUNCTION IF EXISTS fn_set_game_copy_availability() CASCADE;
DROP FUNCTION IF EXISTS fn_update_dynamic_price_after_session() CASCADE;
DROP FUNCTION IF EXISTS fn_release_reserved_on_cancel() CASCADE;
DROP FUNCTION IF EXISTS fn_seed_default_loyalty_tiers() CASCADE;
DROP FUNCTION IF EXISTS fn_seed_default_loyalty_point_rules() CASCADE;
DROP FUNCTION IF EXISTS fn_recalculate_loyalty_tier() CASCADE;
DROP FUNCTION IF EXISTS fn_recalculate_store_loyalty_points() CASCADE;
DROP FUNCTION IF EXISTS fn_validate_loyalty_tier_threshold_order() CASCADE;
DROP FUNCTION IF EXISTS fn_register_tournament() CASCADE;
DROP FUNCTION IF EXISTS fn_advance_tournament_bracket() CASCADE;
DROP FUNCTION IF EXISTS fn_award_tournament_prizes() CASCADE;

CREATE TABLE "User" (
    id       SERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL,
    tournament_wins INTEGER NOT NULL DEFAULT 0,
    tournament_losses INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE Store (
    id       SERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL,
    name     TEXT NOT NULL UNIQUE,
    address  TEXT NOT NULL
);

CREATE TABLE "Table" (
    store_id  INTEGER NOT NULL,
    table_num INTEGER NOT NULL,
    capacity  INTEGER,
    FOREIGN KEY (store_id) REFERENCES Store(id),
    PRIMARY KEY (store_id, table_num)
);

CREATE TABLE Game (
    id                  SERIAL PRIMARY KEY,
    name                TEXT NOT NULL UNIQUE,
    publisher           TEXT,
    symbol              TEXT NOT NULL UNIQUE,
    genre               TEXT,
    min_players         INTEGER,
    max_players         INTEGER,
    avg_duration        INTEGER,
    complexity_rating   INTEGER,
    strategy_rating     INTEGER,
    luck_rating         INTEGER,
    interaction_rating  INTEGER,
    description         TEXT,
    image_url           TEXT DEFAULT NULL,
    avg_rating          DOUBLE PRECISION DEFAULT 0,
    base_price          NUMERIC(10, 2) DEFAULT 10.00
);

CREATE TABLE GameSimilarity (
    id1   INTEGER NOT NULL,
    id2   INTEGER NOT NULL,
    score DOUBLE PRECISION NOT NULL,
    FOREIGN KEY (id1) REFERENCES Game(id),
    FOREIGN KEY (id2) REFERENCES Game(id),
    PRIMARY KEY (id1, id2)
);

CREATE TABLE GameCopy (
    game_id      INTEGER NOT NULL,
    store_id     INTEGER NOT NULL,
    copy_num     INTEGER NOT NULL,
    condition    TEXT NOT NULL DEFAULT 'good'
                 CHECK (condition IN ('good', 'minor_wear', 'damaged', 'missing_pieces')),
    is_available BOOLEAN NOT NULL DEFAULT TRUE,
    FOREIGN KEY (game_id)  REFERENCES Game(id),
    FOREIGN KEY (store_id) REFERENCES Store(id),
    PRIMARY KEY (game_id, store_id, copy_num)
);

CREATE OR REPLACE FUNCTION fn_set_game_copy_availability()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE GameCopy
    SET is_available = CASE
        WHEN NEW.condition IN ('damaged', 'missing_pieces') THEN FALSE
        ELSE TRUE
    END
    WHERE game_id  = NEW.game_id
      AND store_id = NEW.store_id
      AND copy_num = NEW.copy_num;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER set_game_copy_availability_after_insert
AFTER INSERT ON GameCopy
FOR EACH ROW EXECUTE FUNCTION fn_set_game_copy_availability();

CREATE TRIGGER set_game_copy_availability_after_condition_update
AFTER UPDATE OF condition ON GameCopy
FOR EACH ROW EXECUTE FUNCTION fn_set_game_copy_availability();

CREATE TABLE GameRating (
    user_id INTEGER NOT NULL,
    game_id INTEGER NOT NULL,
    rating  INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
    PRIMARY KEY (user_id, game_id),
    FOREIGN KEY (user_id) REFERENCES "User"(id),
    FOREIGN KEY (game_id) REFERENCES Game(id)
);

CREATE TABLE Session (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL,
    store_id        INTEGER NOT NULL,
    table_num       INTEGER NOT NULL,
    day             TEXT NOT NULL,
    start_time      INTEGER NOT NULL,
    end_time        INTEGER NOT NULL,
    checkout_status TEXT NOT NULL DEFAULT 'active' CHECK (checkout_status IN ('active', 'checked_out')),
    is_tournament   BOOLEAN NOT NULL DEFAULT FALSE,
    tournament_id   INTEGER,  -- set after Tournament table is created; FK added via ALTER TABLE below
    checked_in      BOOLEAN NOT NULL DEFAULT FALSE,
    FOREIGN KEY (store_id, table_num) REFERENCES "Table"(store_id, table_num),
    FOREIGN KEY (user_id) REFERENCES "User"(id)
);

CREATE TABLE SessionGameCopy (
    session_id INTEGER NOT NULL,
    game_id    INTEGER NOT NULL,
    store_id   INTEGER NOT NULL,
    copy_num   INTEGER NOT NULL,
    FOREIGN KEY (session_id) REFERENCES Session(id) ON DELETE CASCADE,
    FOREIGN KEY (game_id, store_id, copy_num) REFERENCES GameCopy(game_id, store_id, copy_num),
    PRIMARY KEY (session_id, game_id, store_id, copy_num)
);

CREATE TABLE DynamicGamePrice (
    game_id INTEGER NOT NULL,
    time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    price   NUMERIC(10, 2) NOT NULL,
    FOREIGN KEY (game_id) REFERENCES Game(id)
);

CREATE OR REPLACE FUNCTION fn_update_dynamic_price_after_session()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO DynamicGamePrice (game_id, price)
    SELECT
        NEW.game_id,
        (SELECT base_price FROM Game WHERE id = NEW.game_id) *
        (1.0 + (
            SELECT COUNT(*) FROM SessionGameCopy WHERE game_id = NEW.game_id
        ) * 0.05) *
        (1.0 + (
            1.0 / GREATEST(1, (SELECT COUNT(*) FROM GameCopy WHERE game_id = NEW.game_id))
        ) * 0.5) *
        (1.0 + (
            COALESCE((SELECT AVG(rating) FROM GameRating WHERE game_id = NEW.game_id), 3.0) - 3.0
        ) * 0.1);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_dynamic_price_after_session
AFTER INSERT ON SessionGameCopy
FOR EACH ROW EXECUTE FUNCTION fn_update_dynamic_price_after_session();

CREATE TABLE GameDamage (
    session_id  INTEGER NOT NULL,
    game_id     INTEGER NOT NULL,
    store_id    INTEGER NOT NULL,
    copy_num    INTEGER NOT NULL,
    description TEXT,
    FOREIGN KEY (session_id) REFERENCES Session(id) ON DELETE CASCADE,
    FOREIGN KEY (game_id, store_id, copy_num) REFERENCES GameCopy(game_id, store_id, copy_num),
    PRIMARY KEY (session_id, game_id, store_id, copy_num)
);

CREATE TABLE Bill (
    id              SERIAL PRIMARY KEY,
    session_id      INTEGER NOT NULL UNIQUE REFERENCES Session(id) ON DELETE CASCADE,
    table_fee       NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    food_total      NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    damage_fee      NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    loyalty_discount NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    tier_discount   NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    voucher_discount NUMERIC(10,2) NOT NULL DEFAULT 0.00,
    grand_total     NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    generated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE LoyaltyVoucher (
    id           SERIAL PRIMARY KEY,
    store_id     INTEGER NOT NULL REFERENCES Store(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    description  TEXT,
    point_cost   INTEGER NOT NULL CHECK (point_cost > 0),
    reward_type  TEXT NOT NULL CHECK (reward_type IN ('food', 'session', 'any')),
    reward_value NUMERIC(10, 2) NOT NULL CHECK (reward_value > 0),
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (store_id, name)
);

CREATE TABLE CustomerVoucher (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES "User"(id) ON DELETE CASCADE,
    store_id   INTEGER NOT NULL REFERENCES Store(id) ON DELETE CASCADE,
    voucher_id INTEGER NOT NULL REFERENCES LoyaltyVoucher(id) ON DELETE CASCADE,
    is_used    BOOLEAN NOT NULL DEFAULT FALSE,
    bill_id    INTEGER REFERENCES Bill(id),
    issued_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    used_at    TIMESTAMP
);

CREATE TABLE MarketParticipant (
    id              SERIAL PRIMARY KEY,
    customer_id     INTEGER,
    store_id        INTEGER,
    available_cash NUMERIC(10, 2),
    reserved_cash   NUMERIC(10, 2),
    CHECK ((customer_id IS NOT NULL AND store_id IS NULL) OR (customer_id IS NULL AND store_id IS NOT NULL))
);

CREATE TABLE MarketParticipantInventory (
    participant_id     INTEGER NOT NULL,
    game_id            INTEGER NOT NULL,
    available_quantity INTEGER NOT NULL,
    reserved_quantity  INTEGER NOT NULL,
    FOREIGN KEY (participant_id) REFERENCES MarketParticipant(id),
    FOREIGN KEY (game_id) REFERENCES Game(id),
    PRIMARY KEY (participant_id, game_id)
);

CREATE TABLE TradingScript (
    id       SERIAL PRIMARY KEY,
    name     TEXT NOT NULL,
    code     TEXT NOT NULL,
    owner_id INTEGER NOT NULL,
    FOREIGN KEY (owner_id) REFERENCES MarketParticipant(id)
);

CREATE TABLE Orders (
    id               SERIAL PRIMARY KEY,
    participant_id   INTEGER NOT NULL,
    game_id          INTEGER NOT NULL,
    game_symbol      TEXT NOT NULL,
    order_type       TEXT NOT NULL CHECK (order_type IN ('LIMIT', 'MARKET')),
    side             TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    price            NUMERIC(10, 2) CHECK ((order_type = 'LIMIT' AND price > 0) OR (order_type = 'MARKET' AND price IS NULL)),
    initial_quantity INTEGER NOT NULL,
    filled_quantity  INTEGER NOT NULL,
    status           TEXT CHECK (status IN ('OPEN', 'PARTIAL', 'COMPLETED', 'CANCELLED')),
    created_at       TEXT NOT NULL,
    script_id        INTEGER DEFAULT NULL,
    FOREIGN KEY (script_id) REFERENCES TradingScript(id)
);

CREATE OR REPLACE FUNCTION fn_release_reserved_on_cancel()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'CANCELLED' AND OLD.status != 'CANCELLED' THEN
        IF NEW.side = 'SELL' THEN
            UPDATE MarketParticipantInventory
            SET reserved_quantity = reserved_quantity - (NEW.initial_quantity - NEW.filled_quantity),
                available_quantity = available_quantity + (NEW.initial_quantity - NEW.filled_quantity)
            WHERE participant_id = NEW.participant_id AND game_id = NEW.game_id;
        ELSIF NEW.side = 'BUY' AND NEW.order_type = 'LIMIT' THEN
            UPDATE MarketParticipant
            SET reserved_cash = reserved_cash - (NEW.initial_quantity - NEW.filled_quantity) * NEW.price,
                available_cash = available_cash + (NEW.initial_quantity - NEW.filled_quantity) * NEW.price
            WHERE id = NEW.participant_id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER release_reserved_on_cancel
AFTER UPDATE ON Orders
FOR EACH ROW EXECUTE FUNCTION fn_release_reserved_on_cancel();

CREATE TABLE MarketHistory (
    buy_order_id    INTEGER NOT NULL,
    sell_order_id   INTEGER NOT NULL,
    buyer_id        INTEGER NOT NULL,
    seller_id       INTEGER NOT NULL,
    game_symbol     TEXT NOT NULL,
    execution_price NUMERIC(10, 2) NOT NULL,
    quantity        INTEGER NOT NULL,
    executed_at     TEXT NOT NULL,
    PRIMARY KEY (buy_order_id, sell_order_id),
    FOREIGN KEY (buy_order_id)  REFERENCES Orders(id),
    FOREIGN KEY (sell_order_id) REFERENCES Orders(id),
    FOREIGN KEY (buyer_id)      REFERENCES MarketParticipant(id),
    FOREIGN KEY (seller_id)     REFERENCES MarketParticipant(id)
);

CREATE TABLE MenuItem (
    id SERIAL PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES Store(id),
    name TEXT NOT NULL,
    price NUMERIC(10, 2) NOT NULL,
    description TEXT,
    is_available BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE Food (
    item_id INTEGER PRIMARY KEY REFERENCES MenuItem(id),
    is_vegetarian BOOLEAN NOT NULL DEFAULT FALSE,
    allergens TEXT,
    category TEXT
);

CREATE TABLE Beverage (
    item_id INTEGER PRIMARY KEY REFERENCES MenuItem(id),
    size TEXT,
    temperature TEXT
);

CREATE TABLE SessionOrder (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES Session(id) ON DELETE CASCADE,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'cancelled')),
    total_amount NUMERIC(10, 2) DEFAULT 0.00
);

CREATE TABLE SessionOrderItem (
    order_id INTEGER NOT NULL REFERENCES SessionOrder(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES MenuItem(id),
    quantity INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (order_id, item_id)
);

CREATE TABLE LoyaltyTier (
    store_id                 INTEGER NOT NULL REFERENCES Store(id) ON DELETE CASCADE,
    code                     TEXT NOT NULL,
    min_points               INTEGER NOT NULL,
    discount_percent         NUMERIC(5, 2) NOT NULL DEFAULT 0,
    reservation_advance_days INTEGER NOT NULL DEFAULT 0,
    free_tournament_entries  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (store_id, code),
    CONSTRAINT loyaltytier_valid_code CHECK (code IN ('Bronze', 'Silver', 'Gold')),
    CONSTRAINT loyaltytier_min_points_nonnegative CHECK (min_points >= 0),
    CONSTRAINT loyaltytier_discount_percent_range CHECK (discount_percent >= 0 AND discount_percent <= 100),
    CONSTRAINT loyaltytier_reservation_advance_days_nonnegative CHECK (reservation_advance_days >= 0),
    CONSTRAINT loyaltytier_free_tournament_entries_nonnegative CHECK (free_tournament_entries >= 0),
    CONSTRAINT loyaltytier_store_min_points_unique UNIQUE (store_id, min_points) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE OR REPLACE FUNCTION fn_seed_default_loyalty_tiers()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO LoyaltyTier (store_id, code, min_points, discount_percent, reservation_advance_days, free_tournament_entries)
    VALUES
        (NEW.id, 'Bronze', 0, 0, 3, 0),
        (NEW.id, 'Silver', 500, 0, 7, 0),
        (NEW.id, 'Gold', 1000, 0, 14, 0);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER seed_default_loyalty_tiers_after_store_insert
AFTER INSERT ON Store
FOR EACH ROW EXECUTE FUNCTION fn_seed_default_loyalty_tiers();

CREATE TABLE LoyaltyPointRule (
    store_id        INTEGER NOT NULL REFERENCES Store(id) ON DELETE CASCADE,
    action_code     TEXT NOT NULL,
    points_per_unit NUMERIC(10, 2) NOT NULL,
    PRIMARY KEY (store_id, action_code),
    CONSTRAINT loyaltypointrule_valid_action CHECK (
        action_code IN ('session_hour', 'food_dollar', 'game_rating', 'tournament_participation')
    ),
    CONSTRAINT loyaltypointrule_points_nonnegative CHECK (points_per_unit >= 0)
);

CREATE OR REPLACE FUNCTION fn_seed_default_loyalty_point_rules()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO LoyaltyPointRule (store_id, action_code, points_per_unit)
    VALUES
        (NEW.id, 'session_hour', 5),
        (NEW.id, 'food_dollar', 1),
        (NEW.id, 'game_rating', 5),
        (NEW.id, 'tournament_participation', 20);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER seed_default_loyalty_point_rules_after_store_insert
AFTER INSERT ON Store
FOR EACH ROW EXECUTE FUNCTION fn_seed_default_loyalty_point_rules();

CREATE TABLE LoyaltyPoint (
    id                           SERIAL PRIMARY KEY,
    user_id                      INTEGER NOT NULL REFERENCES "User"(id) ON DELETE CASCADE,
    store_id                     INTEGER NOT NULL REFERENCES Store(id) ON DELETE CASCADE,
    points                       INTEGER NOT NULL DEFAULT 0,
    lifetime_points              INTEGER NOT NULL DEFAULT 0,
    used_free_tournament_entries INTEGER NOT NULL DEFAULT 0,
    tier_code                    TEXT NOT NULL DEFAULT 'Bronze',
    updated_at                   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, store_id),
    CONSTRAINT loyaltypoint_points_nonnegative CHECK (points >= 0),
    CONSTRAINT loyaltypoint_lifetime_points_nonnegative CHECK (lifetime_points >= 0),
    CONSTRAINT loyaltypoint_lifetime_not_less_than_balance CHECK (lifetime_points >= points),
    CONSTRAINT loyaltypoint_used_free_entries_nonnegative CHECK (used_free_tournament_entries >= 0),
    FOREIGN KEY (store_id, tier_code) REFERENCES LoyaltyTier(store_id, code)
);

CREATE TABLE LoyaltyRedemption (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES "User"(id) ON DELETE CASCADE,
    store_id     INTEGER NOT NULL REFERENCES Store(id) ON DELETE CASCADE,
    bill_id      INTEGER REFERENCES Bill(id) ON DELETE SET NULL,
    points_spent INTEGER NOT NULL,
    redeemed_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    description  TEXT,
    CONSTRAINT loyaltyredemption_points_spent_nonzero CHECK (points_spent <> 0)
);

CREATE OR REPLACE FUNCTION fn_recalculate_loyalty_tier()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.points < 0 OR NEW.lifetime_points < 0 THEN
        RETURN NEW;
    END IF;

    SELECT code
    INTO NEW.tier_code
    FROM LoyaltyTier
    WHERE store_id = NEW.store_id
      AND min_points <= NEW.lifetime_points
    ORDER BY min_points DESC
    LIMIT 1;

    IF NEW.tier_code IS NULL THEN
        RAISE EXCEPTION 'No loyalty tier configured for store % and % lifetime points', NEW.store_id, NEW.lifetime_points;
    END IF;

    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER recalculate_loyalty_tier_before_insert
BEFORE INSERT ON LoyaltyPoint
FOR EACH ROW EXECUTE FUNCTION fn_recalculate_loyalty_tier();

CREATE TRIGGER recalculate_loyalty_tier_before_lifetime_points_update
BEFORE UPDATE OF lifetime_points ON LoyaltyPoint
FOR EACH ROW EXECUTE FUNCTION fn_recalculate_loyalty_tier();

CREATE OR REPLACE FUNCTION fn_recalculate_store_loyalty_points()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE LoyaltyPoint
    SET lifetime_points = lifetime_points
    WHERE store_id = NEW.store_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER recalculate_store_loyalty_points_after_tier_update
AFTER UPDATE OF min_points ON LoyaltyTier
FOR EACH ROW EXECUTE FUNCTION fn_recalculate_store_loyalty_points();

CREATE OR REPLACE FUNCTION fn_validate_loyalty_tier_threshold_order()
RETURNS TRIGGER AS $$
DECLARE
    bronze_points INTEGER;
    silver_points INTEGER;
    gold_points INTEGER;
BEGIN
    SELECT min_points INTO bronze_points
    FROM LoyaltyTier
    WHERE store_id = NEW.store_id AND code = 'Bronze';

    SELECT min_points INTO silver_points
    FROM LoyaltyTier
    WHERE store_id = NEW.store_id AND code = 'Silver';

    SELECT min_points INTO gold_points
    FROM LoyaltyTier
    WHERE store_id = NEW.store_id AND code = 'Gold';

    IF bronze_points IS NOT NULL
       AND silver_points IS NOT NULL
       AND gold_points IS NOT NULL
       AND NOT (bronze_points < silver_points AND silver_points < gold_points) THEN
        RAISE EXCEPTION 'Loyalty tier thresholds must satisfy Bronze < Silver < Gold for store %', NEW.store_id
            USING ERRCODE = '23514',
                  CONSTRAINT = 'loyaltytier_threshold_order';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER validate_loyalty_tier_threshold_order_after_insert_update
AFTER INSERT OR UPDATE OF min_points ON LoyaltyTier
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_validate_loyalty_tier_threshold_order();

CREATE INDEX idx_loyalty_point_user_store ON LoyaltyPoint(user_id, store_id);
CREATE INDEX idx_loyalty_point_store_tier ON LoyaltyPoint(store_id, tier_code);

CREATE VIEW store_top_loyalty_point_holders AS
SELECT *
FROM (
    SELECT
        lp.store_id,
        lp.user_id,
        u.username,
        lp.tier_code,
        lp.points AS current_points,
        lp.lifetime_points,
        COALESCE(SUM(lr.points_spent), 0) AS redeemed_points,
        ROW_NUMBER() OVER (
            PARTITION BY lp.store_id
            ORDER BY lp.lifetime_points DESC,
                     lp.points DESC,
                     u.username ASC
        ) AS store_rank
    FROM LoyaltyPoint lp
    JOIN "User" u ON u.id = lp.user_id
    LEFT JOIN LoyaltyRedemption lr
      ON lr.user_id = lp.user_id
     AND lr.store_id = lp.store_id
    GROUP BY lp.store_id, lp.user_id, u.username, lp.tier_code, lp.points, lp.lifetime_points
) ranked
WHERE store_rank <= 5;

CREATE VIEW historical_game_price AS
SELECT
    o.game_id,
    mh.executed_at::TIMESTAMP AS timestamp,
    mh.execution_price AS price
FROM MarketHistory mh
JOIN Orders o ON mh.buy_order_id = o.id;

-- =============================================================
-- TOURNAMENT TABLES
-- =============================================================

CREATE TABLE Tournament (
    id                   SERIAL PRIMARY KEY,
    store_id             INTEGER NOT NULL REFERENCES Store(id) ON DELETE CASCADE,
    game_id              INTEGER NOT NULL REFERENCES Game(id),
    name                 TEXT NOT NULL,
    format               TEXT NOT NULL CHECK (format IN ('single_elimination', 'round_robin')),
    max_participants     INTEGER NOT NULL CHECK (max_participants >= 2),
    players_per_match    INTEGER NOT NULL DEFAULT 2 CHECK (players_per_match >= 2),
    entry_fee_points     INTEGER NOT NULL DEFAULT 0 CHECK (entry_fee_points >= 0),
    sponsor_name         TEXT,
    min_loyalty_tier     TEXT DEFAULT NULL CHECK (min_loyalty_tier IS NULL OR min_loyalty_tier IN ('Bronze', 'Silver', 'Gold')),
    registration_open    BOOLEAN NOT NULL DEFAULT TRUE,
    status               TEXT NOT NULL DEFAULT 'registration_open'
                         CHECK (status IN ('registration_open', 'in_progress', 'completed')),
    start_date           TIMESTAMP NOT NULL,
    end_date             TIMESTAMP,
    prize_description    TEXT,
    created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Wire the Session.tournament_id FK now that Tournament exists
ALTER TABLE Session
    ADD CONSTRAINT session_tournament_id_fk
    FOREIGN KEY (tournament_id) REFERENCES Tournament(id) ON DELETE SET NULL;

-- Tables allocated to a tournament by the store owner
CREATE TABLE TournamentTable (
    tournament_id INTEGER NOT NULL REFERENCES Tournament(id) ON DELETE CASCADE,
    store_id      INTEGER NOT NULL,
    table_num     INTEGER NOT NULL,
    FOREIGN KEY (store_id, table_num) REFERENCES "Table"(store_id, table_num),
    PRIMARY KEY (tournament_id, store_id, table_num)
);

-- Registered participants
CREATE TABLE TournamentParticipant (
    tournament_id    INTEGER NOT NULL REFERENCES Tournament(id) ON DELETE CASCADE,
    user_id          INTEGER NOT NULL REFERENCES "User"(id) ON DELETE CASCADE,
    registered_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    used_free_entry  BOOLEAN NOT NULL DEFAULT FALSE,
    session_id       INTEGER REFERENCES Session(id) ON DELETE SET NULL,
    PRIMARY KEY (tournament_id, user_id)
);

-- Individual matches within a tournament
CREATE TABLE TournamentMatch (
    id             SERIAL PRIMARY KEY,
    tournament_id  INTEGER NOT NULL REFERENCES Tournament(id) ON DELETE CASCADE,
    round_number   INTEGER NOT NULL CHECK (round_number >= 1),
    match_number   INTEGER NOT NULL,  -- position within the round
    player1_id     INTEGER REFERENCES "User"(id) ON DELETE SET NULL,
    player2_id     INTEGER REFERENCES "User"(id) ON DELETE SET NULL,
    winner_id      INTEGER REFERENCES "User"(id) ON DELETE SET NULL,
    score_player1  TEXT,
    score_player2  TEXT,
    is_bye         BOOLEAN NOT NULL DEFAULT FALSE,  -- true when player2 is absent (single elim)
    is_played      BOOLEAN NOT NULL DEFAULT FALSE,
    next_match_id  INTEGER REFERENCES TournamentMatch(id) ON DELETE SET NULL,
    store_id       INTEGER,
    table_num      INTEGER,
    FOREIGN KEY (store_id, table_num) REFERENCES "Table"(store_id, table_num),
    UNIQUE (tournament_id, round_number, match_number)
);

-- Final standings / prizes per tournament
CREATE TABLE TournamentResult (
    id              SERIAL PRIMARY KEY,
    tournament_id   INTEGER NOT NULL REFERENCES Tournament(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES "User"(id) ON DELETE CASCADE,
    place           INTEGER NOT NULL CHECK (place >= 1),
    prize_text      TEXT,
    points_awarded  INTEGER NOT NULL DEFAULT 0 CHECK (points_awarded >= 0),
    awarded_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tournament_id, user_id)
    -- No UNIQUE on place: tied places (e.g. shared 3rd) are allowed
);

-- Per-match participant details (used for FFA and optionally 1v1)
CREATE TABLE TournamentMatchParticipant (
    match_id        INTEGER NOT NULL REFERENCES TournamentMatch(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES "User"(id),
    score           TEXT,               -- raw score (points, time, etc.)
    rank_in_match   INTEGER CHECK (rank_in_match >= 1),  -- 1 = winner
    PRIMARY KEY (match_id, user_id)
);

-- =============================================================
-- TRIGGER: REGISTRATION ELIGIBILITY
-- Fires BEFORE INSERT on TournamentParticipant.
-- Checks: tournament open, capacity, no overlap, and handles
-- free entry OR point deduction (normal points only).
-- =============================================================
CREATE OR REPLACE FUNCTION fn_register_tournament()
RETURNS TRIGGER AS $$
DECLARE
    v_tournament        Tournament%ROWTYPE;
    v_current_count     INTEGER;
    v_lp                LoyaltyPoint%ROWTYPE;
    v_free_allowed      INTEGER;
    v_overlap           INTEGER;
    v_table_store_id    INTEGER;
    v_table_num         INTEGER;
    v_session_id        INTEGER;
    v_session_day       TEXT;
    v_start_hour        INTEGER;
    v_end_hour          INTEGER;
BEGIN
    -- 1. Load tournament
    SELECT * INTO v_tournament FROM Tournament WHERE id = NEW.tournament_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'This tournament does not exist.';
    END IF;

    -- 2. Registration must be open
    IF v_tournament.status <> 'registration_open' THEN
        RAISE EXCEPTION 'Registration for this tournament is currently closed.';
    END IF;

    -- 3. Capacity check
    SELECT COUNT(*) INTO v_current_count
    FROM TournamentParticipant
    WHERE tournament_id = NEW.tournament_id;
    IF v_current_count >= v_tournament.max_participants THEN
        RAISE EXCEPTION 'This tournament is already full.';
    END IF;

    -- 4. Overlap check: user must not be in another active tournament at the same store
    --    whose date range actually conflicts with this one.
    SELECT COUNT(*) INTO v_overlap
    FROM TournamentParticipant tp
    JOIN Tournament t ON t.id = tp.tournament_id
    WHERE tp.user_id = NEW.user_id
      AND t.store_id = v_tournament.store_id
      AND t.status <> 'completed'
      AND t.id <> NEW.tournament_id
      AND (
          t.start_date < COALESCE(v_tournament.end_date, v_tournament.start_date + INTERVAL '8 hours')
          AND COALESCE(t.end_date, t.start_date + INTERVAL '8 hours') > v_tournament.start_date
      );
    IF v_overlap > 0 THEN
        RAISE EXCEPTION 'You are already registered for another tournament during this time at this store.';
    END IF;

    -- 5. Auto-create loyalty record if the user has never visited this store.
    --    This allows new users to enter free (or 0-fee) tournaments without error.
    INSERT INTO LoyaltyPoint (user_id, store_id, points, lifetime_points)
    VALUES (NEW.user_id, v_tournament.store_id, 0, 0)
    ON CONFLICT (user_id, store_id) DO NOTHING;

    SELECT * INTO v_lp
    FROM LoyaltyPoint
    WHERE user_id = NEW.user_id AND store_id = v_tournament.store_id;

    -- 6. Loyalty tier gate
    IF v_tournament.min_loyalty_tier IS NOT NULL THEN
        IF v_lp.tier_code NOT IN (
            SELECT code FROM LoyaltyTier
            WHERE store_id = v_tournament.store_id
              AND min_points >= (
                  SELECT min_points FROM LoyaltyTier
                  WHERE store_id = v_tournament.store_id AND code = v_tournament.min_loyalty_tier
              )
        ) THEN
            RAISE EXCEPTION 'This tournament requires % tier or higher to enter.', v_tournament.min_loyalty_tier;
        END IF;
    END IF;

    -- 7. Determine entry payment
    SELECT lt.free_tournament_entries INTO v_free_allowed
    FROM LoyaltyTier lt
    WHERE lt.store_id = v_tournament.store_id AND lt.code = v_lp.tier_code;

    IF NEW.used_free_entry THEN
        IF v_lp.used_free_tournament_entries >= v_free_allowed THEN
            RAISE EXCEPTION 'You have no free tournament entries remaining at this tier.';
        END IF;
        UPDATE LoyaltyPoint
        SET used_free_tournament_entries = used_free_tournament_entries + 1
        WHERE user_id = NEW.user_id AND store_id = v_tournament.store_id;
    ELSE
        -- Deduct entry fee from normal points only (lifetime_points unchanged)
        IF v_lp.points < v_tournament.entry_fee_points THEN
            RAISE EXCEPTION 'You do not have enough loyalty points to enter this tournament (Entry Fee: % pts, Your Balance: % pts).',
                v_tournament.entry_fee_points, v_lp.points;
        END IF;
        IF v_tournament.entry_fee_points > 0 THEN
            UPDATE LoyaltyPoint
            SET points = points - v_tournament.entry_fee_points
            WHERE user_id = NEW.user_id AND store_id = v_tournament.store_id;

            INSERT INTO LoyaltyRedemption (user_id, store_id, points_spent, description)
            VALUES (NEW.user_id, v_tournament.store_id, v_tournament.entry_fee_points,
                    'Tournament entry fee for tournament ID ' || NEW.tournament_id);
        END IF;
    END IF;

    -- 7. Allocate a session on the first allocated tournament table.
    --    All registrants share the same placeholder table; per-match table
    --    assignments happen later during bracket generation.
    SELECT tt.store_id, tt.table_num
    INTO v_table_store_id, v_table_num
    FROM TournamentTable tt
    WHERE tt.tournament_id = NEW.tournament_id
    ORDER BY tt.table_num
    LIMIT 1;

    IF v_table_store_id IS NULL THEN
        RAISE EXCEPTION 'No tables have been allocated to tournament %', NEW.tournament_id;
    END IF;

    -- Day label derived from the tournament start_date
    v_session_day    := TO_CHAR(v_tournament.start_date, 'YYYY-MM-DD');
    v_start_hour     := EXTRACT(HOUR FROM v_tournament.start_date)::INTEGER;
    IF v_tournament.end_date IS NOT NULL
       AND EXTRACT(HOUR FROM v_tournament.end_date) > v_start_hour THEN
        v_end_hour := EXTRACT(HOUR FROM v_tournament.end_date)::INTEGER;
    ELSE
        v_end_hour := v_start_hour + 4;
    END IF;

    INSERT INTO Session (
        user_id, store_id, table_num, day,
        start_time, end_time, checkout_status, is_tournament, tournament_id
    )
    VALUES (
        NEW.user_id,
        v_table_store_id,
        v_table_num,
        v_session_day,
        v_start_hour,
        v_end_hour,
        'active',
        TRUE,
        NEW.tournament_id
    )
    RETURNING id INTO v_session_id;

    NEW.session_id := v_session_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER register_tournament_before_insert
BEFORE INSERT ON TournamentParticipant
FOR EACH ROW EXECUTE FUNCTION fn_register_tournament();

-- =============================================================
-- TRIGGER: DEREGISTRATION
-- Fires BEFORE DELETE ON TournamentParticipant.
-- Checks: tournament open, refunds points or free entries.
-- =============================================================
CREATE OR REPLACE FUNCTION fn_deregister_tournament()
RETURNS TRIGGER AS $$
DECLARE
    v_tournament Tournament%ROWTYPE;
BEGIN
    SELECT * INTO v_tournament FROM Tournament WHERE id = OLD.tournament_id;

    IF v_tournament.status <> 'registration_open' THEN
        RAISE EXCEPTION 'Cannot deregister: tournament registration is closed or already started.';
    END IF;

    IF OLD.used_free_entry THEN
        UPDATE LoyaltyPoint
        SET used_free_tournament_entries = GREATEST(used_free_tournament_entries - 1, 0)
        WHERE user_id = OLD.user_id AND store_id = v_tournament.store_id;
    ELSIF v_tournament.entry_fee_points > 0 THEN
        UPDATE LoyaltyPoint
        SET points = points + v_tournament.entry_fee_points
        WHERE user_id = OLD.user_id AND store_id = v_tournament.store_id;

        INSERT INTO LoyaltyRedemption (user_id, store_id, points_spent, description)
        VALUES (OLD.user_id, v_tournament.store_id, -v_tournament.entry_fee_points,
                'Refund for deregistering from tournament ID ' || OLD.tournament_id);
    END IF;

    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER deregister_tournament_before_delete
BEFORE DELETE ON TournamentParticipant
FOR EACH ROW EXECUTE FUNCTION fn_deregister_tournament();

-- =============================================================
-- TRIGGER: ADVANCE BRACKET ON MATCH RESULT
-- Fires AFTER UPDATE OF winner_id ON TournamentMatch.
-- Advances the winner to next_match_id and updates global stats.
-- =============================================================
CREATE OR REPLACE FUNCTION fn_advance_tournament_bracket()
RETURNS TRIGGER AS $$
DECLARE
    v_loser_id INTEGER;
BEGIN
    -- Only act when a winner is newly recorded
    IF NEW.winner_id IS NULL OR NEW.winner_id = OLD.winner_id THEN
        RETURN NEW;
    END IF;

    -- FFA matches (player1_id IS NULL) are handled entirely in the application layer
    IF NEW.player1_id IS NULL THEN
        RETURN NEW;
    END IF;

    -- Mark match as played
    UPDATE TournamentMatch SET is_played = TRUE WHERE id = NEW.id;

    -- Determine loser
    IF NEW.player1_id = NEW.winner_id THEN
        v_loser_id := NEW.player2_id;
    ELSE
        v_loser_id := NEW.player1_id;
    END IF;

    -- Update global win/loss counters on User
    UPDATE "User" SET tournament_wins   = tournament_wins   + 1 WHERE id = NEW.winner_id;
    IF v_loser_id IS NOT NULL THEN
        UPDATE "User" SET tournament_losses = tournament_losses + 1 WHERE id = v_loser_id;
    END IF;

    -- Advance winner into the next match slot (single elimination)
    IF NEW.next_match_id IS NOT NULL THEN
        UPDATE TournamentMatch
        SET player1_id = CASE WHEN player1_id IS NULL THEN NEW.winner_id ELSE player1_id END,
            player2_id = CASE WHEN player1_id IS NOT NULL AND player2_id IS NULL THEN NEW.winner_id ELSE player2_id END
        WHERE id = NEW.next_match_id;
    END IF;

    -- Delete the eliminated player's tournament session
    IF v_loser_id IS NOT NULL THEN
        DELETE FROM Session
        WHERE user_id = v_loser_id
          AND is_tournament = TRUE
          AND tournament_id = NEW.tournament_id;
    END IF;

    -- If this is the final match (no next_match_id), also free the winner's session
    IF NEW.next_match_id IS NULL THEN
        DELETE FROM Session
        WHERE user_id = NEW.winner_id
          AND is_tournament = TRUE
          AND tournament_id = NEW.tournament_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER advance_tournament_bracket_after_winner_set
AFTER UPDATE OF winner_id ON TournamentMatch
FOR EACH ROW EXECUTE FUNCTION fn_advance_tournament_bracket();

-- =============================================================
-- TRIGGER: AWARD PRIZES ON TOURNAMENT RESULT INSERT
-- Fires AFTER INSERT on TournamentResult.
-- Awards loyalty points (points + lifetime_points) to finishers.
-- =============================================================
CREATE OR REPLACE FUNCTION fn_award_tournament_prizes()
RETURNS TRIGGER AS $$
DECLARE
    v_store_id INTEGER;
BEGIN
    SELECT store_id INTO v_store_id FROM Tournament WHERE id = NEW.tournament_id;

    IF NEW.points_awarded > 0 THEN
        -- Add to both spendable points AND lifetime points
        UPDATE LoyaltyPoint
        SET points          = points          + NEW.points_awarded,
            lifetime_points = lifetime_points + NEW.points_awarded
        WHERE user_id = NEW.user_id AND store_id = v_store_id;

        -- Log as a redemption-like credit (negative spend = award)
        INSERT INTO LoyaltyRedemption (user_id, store_id, points_spent, description)
        VALUES (NEW.user_id, v_store_id, -NEW.points_awarded,
                'Tournament prize: place ' || NEW.place || ' in tournament ID ' || NEW.tournament_id);
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER award_tournament_prizes_after_result_insert
AFTER INSERT ON TournamentResult
FOR EACH ROW EXECUTE FUNCTION fn_award_tournament_prizes();

-- =============================================================
-- REPORTING VIEWS
-- =============================================================

-- Most popular tournament games
CREATE VIEW vw_popular_tournament_games AS
SELECT
    g.id   AS game_id,
    g.name AS game_name,
    COUNT(DISTINCT t.id) AS total_tournaments,
    COUNT(tp.user_id)    AS total_participants
FROM Tournament t
JOIN Game g ON g.id = t.game_id
LEFT JOIN TournamentParticipant tp ON tp.tournament_id = t.id
GROUP BY g.id, g.name
ORDER BY total_tournaments DESC, total_participants DESC;

-- Average participation and format breakdown per store
CREATE VIEW vw_tournament_participation_stats AS
SELECT
    t.store_id,
    s.name AS store_name,
    t.format,
    COUNT(DISTINCT t.id)                                         AS num_tournaments,
    ROUND(AVG(participant_counts.cnt), 2)                        AS avg_participants
FROM Tournament t
JOIN Store s ON s.id = t.store_id
LEFT JOIN (
    SELECT tournament_id, COUNT(*) AS cnt
    FROM TournamentParticipant
    GROUP BY tournament_id
) participant_counts ON participant_counts.tournament_id = t.id
GROUP BY t.store_id, s.name, t.format
ORDER BY t.store_id, t.format;

-- Revenue from entry fees per tournament and store
CREATE VIEW vw_tournament_revenue AS
SELECT
    t.id         AS tournament_id,
    t.name       AS tournament_name,
    t.store_id,
    s.name       AS store_name,
    t.entry_fee_points,
    COUNT(tp.user_id)                                       AS total_registrations,
    COUNT(tp.user_id) FILTER (WHERE NOT tp.used_free_entry) AS paid_registrations,
    COUNT(tp.user_id) FILTER (WHERE tp.used_free_entry)     AS free_registrations,
    (COUNT(tp.user_id) FILTER (WHERE NOT tp.used_free_entry)) * t.entry_fee_points AS total_points_collected
FROM Tournament t
JOIN Store s ON s.id = t.store_id
LEFT JOIN TournamentParticipant tp ON tp.tournament_id = t.id
GROUP BY t.id, t.name, t.store_id, s.name, t.entry_fee_points
ORDER BY total_points_collected DESC;

-- Top-ranked players across all tournaments (global)
CREATE VIEW vw_top_tournament_players AS
SELECT
    u.id       AS user_id,
    u.username,
    u.tournament_wins,
    u.tournament_losses,
    (u.tournament_wins + u.tournament_losses) AS total_matches,
    CASE
        WHEN (u.tournament_wins + u.tournament_losses) = 0 THEN 0
        ELSE ROUND(
            u.tournament_wins::NUMERIC / (u.tournament_wins + u.tournament_losses) * 100, 2
        )
    END AS win_rate_pct,
    COALESCE((
        SELECT SUM(tr.points_awarded)
        FROM TournamentResult tr
        WHERE tr.user_id = u.id
    ), 0) AS total_prize_points,
    COALESCE((
        SELECT MIN(tr.place)
        FROM TournamentResult tr
        WHERE tr.user_id = u.id
    ), NULL) AS best_finish
FROM "User" u
WHERE u.tournament_wins > 0 OR u.tournament_losses > 0
ORDER BY u.tournament_wins DESC, win_rate_pct DESC;

CREATE VIEW vw_loyalty_tier_distribution AS
SELECT
    lt.store_id,
    lt.code AS tier,
    lt.min_points AS threshold,
    lt.discount_percent,
    COUNT(lp.id) AS customer_count,
    COALESCE(SUM(lp.points), 0) AS total_active_points,
    COALESCE(SUM(lp.lifetime_points), 0) AS total_lifetime_points,
    MIN(lp.lifetime_points) AS min_lifetime,
    MAX(lp.lifetime_points) AS max_lifetime,
    ROUND(AVG(lp.lifetime_points), 1) AS avg_lifetime,
    ROUND(
        100.0 * COUNT(lp.id)
        / NULLIF((SELECT COUNT(*) FROM LoyaltyPoint lp2 WHERE lp2.store_id = lt.store_id), 0),
    1) AS pct_of_customers
FROM LoyaltyTier lt
LEFT JOIN LoyaltyPoint lp
    ON lp.tier_code = lt.code AND lp.store_id = lt.store_id
GROUP BY lt.store_id, lt.code, lt.min_points, lt.discount_percent
ORDER BY lt.min_points ASC;

CREATE VIEW vw_loyalty_redemption_overview AS
SELECT
    lr.store_id,
    COUNT(*) AS total_redemptions,
    COALESCE(SUM(lr.points_spent), 0) AS total_points_redeemed,
    ROUND(AVG(lr.points_spent), 1) AS avg_per_redemption,
    MIN(lr.points_spent) AS min_redemption,
    MAX(lr.points_spent) AS max_redemption,
    ROUND(
        100.0 * SUM(lr.points_spent)
        / NULLIF((SELECT SUM(lp.lifetime_points) FROM LoyaltyPoint lp WHERE lp.store_id = lr.store_id), 0),
    1) AS redemption_rate_pct
FROM LoyaltyRedemption lr
GROUP BY lr.store_id;

CREATE VIEW vw_loyalty_redemption_by_tier AS
SELECT
    lp.store_id,
    lp.tier_code AS tier,
    COUNT(lr.id) AS redemption_count,
    COALESCE(SUM(lr.points_spent), 0) AS total_redeemed,
    ROUND(AVG(lr.points_spent), 1) AS avg_redeemed,
    MIN(lr.points_spent) AS min_redeemed,
    MAX(lr.points_spent) AS max_redeemed
FROM LoyaltyPoint lp
LEFT JOIN LoyaltyRedemption lr
    ON lr.user_id = lp.user_id AND lr.store_id = lp.store_id
GROUP BY lp.store_id, lp.tier_code
ORDER BY total_redeemed DESC;

CREATE VIEW vw_loyalty_revenue_impact AS
SELECT
    s.store_id,
    COUNT(b.id) AS total_bills,
    SUM(b.grand_total + b.loyalty_discount + b.tier_discount + b.voucher_discount) AS gross_revenue,
    SUM(b.loyalty_discount + b.tier_discount + b.voucher_discount) AS total_discount,
    SUM(b.grand_total) AS net_revenue,
    ROUND(AVG(b.loyalty_discount + b.tier_discount + b.voucher_discount), 2) AS avg_discount,
    MAX(b.loyalty_discount + b.tier_discount + b.voucher_discount) AS max_discount,
    MIN(CASE WHEN b.loyalty_discount + b.tier_discount + b.voucher_discount > 0 THEN b.loyalty_discount + b.tier_discount + b.voucher_discount END) AS min_discount_nonzero,
    COUNT(CASE WHEN b.loyalty_discount + b.tier_discount + b.voucher_discount > 0 THEN 1 END) AS bills_with_discount,
    ROUND(
        100.0 * SUM(b.loyalty_discount + b.tier_discount + b.voucher_discount)
        / NULLIF(SUM(b.grand_total + b.loyalty_discount + b.tier_discount + b.voucher_discount), 0),
    1) AS discount_pct
FROM Bill b
JOIN Session s ON b.session_id = s.id
GROUP BY s.store_id;

CREATE VIEW vw_loyalty_most_loyal AS
SELECT
    lp.store_id,
    lp.user_id,
    u.username,
    lp.tier_code,
    lp.points AS current_points,
    lp.lifetime_points,
    lp.lifetime_points - lp.points AS points_spent,
    COALESCE(r_stats.redemption_count, 0) AS redemption_count,
    ROUND(COALESCE(r_stats.discount_value, 0), 2) AS discount_value,
    COALESCE(s_stats.session_count, 0) AS session_count,
    ROUND(COALESCE(s_stats.total_spent, 0), 2) AS total_spent
FROM LoyaltyPoint lp
JOIN "User" u ON lp.user_id = u.id
LEFT JOIN (
    SELECT user_id, store_id,
           COUNT(*) AS redemption_count,
           SUM(points_spent) * 0.10 AS discount_value
    FROM LoyaltyRedemption
    GROUP BY user_id, store_id
) r_stats ON r_stats.user_id = lp.user_id
          AND r_stats.store_id = lp.store_id
LEFT JOIN (
    SELECT s.user_id, s.store_id,
           COUNT(*) AS session_count,
           SUM(b.grand_total) AS total_spent
    FROM Session s
    JOIN Bill b ON b.session_id = s.id
    WHERE s.checkout_status = 'checked_out'
    GROUP BY s.user_id, s.store_id
) s_stats ON s_stats.user_id = lp.user_id
          AND s_stats.store_id = lp.store_id
ORDER BY lp.lifetime_points DESC;
