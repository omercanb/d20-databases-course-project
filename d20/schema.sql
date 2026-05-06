DROP TABLE IF EXISTS Bill CASCADE;
DROP TABLE IF EXISTS LoyaltyRedemption CASCADE;
DROP TABLE IF EXISTS LoyaltyPoint CASCADE;
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

CREATE TABLE "User" (
    id       SERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL
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
    FOREIGN KEY (store_id, table_num) REFERENCES "Table"(store_id, table_num),
    FOREIGN KEY (user_id) REFERENCES "User"(id)
);

CREATE TABLE SessionGameCopy (
    session_id INTEGER NOT NULL,
    game_id    INTEGER NOT NULL,
    store_id   INTEGER NOT NULL,
    copy_num   INTEGER NOT NULL,
    FOREIGN KEY (session_id) REFERENCES Session(id),
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
    FOREIGN KEY (session_id) REFERENCES Session(id),
    FOREIGN KEY (game_id, store_id, copy_num) REFERENCES GameCopy(game_id, store_id, copy_num),
    PRIMARY KEY (session_id, game_id, store_id, copy_num)
);

CREATE TABLE Bill (
    id              SERIAL PRIMARY KEY,
    session_id      INTEGER NOT NULL UNIQUE REFERENCES Session(id),
    table_fee       NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    food_total      NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    damage_fee      NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    loyalty_discount NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    grand_total     NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    generated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    session_id INTEGER NOT NULL REFERENCES Session(id),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'cancelled')),
    total_amount NUMERIC(10, 2) DEFAULT 0.00
);

CREATE TABLE SessionOrderItem (
    order_id INTEGER NOT NULL REFERENCES SessionOrder(id),
    item_id INTEGER NOT NULL REFERENCES MenuItem(id),
    quantity INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (order_id, item_id)
);

CREATE TABLE LoyaltyPoint (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES "User"(id) ON DELETE CASCADE,
    store_id    INTEGER NOT NULL REFERENCES Store(id) ON DELETE CASCADE,
    points      INTEGER NOT NULL DEFAULT 0,
    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, store_id)
);

CREATE TABLE LoyaltyRedemption (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES "User"(id) ON DELETE CASCADE,
    store_id     INTEGER NOT NULL REFERENCES Store(id) ON DELETE CASCADE,
    bill_id      INTEGER REFERENCES Bill(id) ON DELETE SET NULL,
    points_spent INTEGER NOT NULL,
    redeemed_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    description  TEXT
);

CREATE INDEX idx_loyalty_point_user_store ON LoyaltyPoint(user_id, store_id);

CREATE VIEW historical_game_price AS
SELECT
    o.game_id,
    mh.executed_at::TIMESTAMP AS timestamp,
    mh.execution_price AS price
FROM MarketHistory mh
JOIN Orders o ON mh.buy_order_id = o.id;
