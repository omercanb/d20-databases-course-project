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
DROP TABLE IF EXISTS MarketPariticipant CASCADE;
DROP TABLE IF EXISTS Store CASCADE;
DROP TABLE IF EXISTS "User" CASCADE;

DROP FUNCTION IF EXISTS fn_set_game_copy_availability() CASCADE;
DROP FUNCTION IF EXISTS fn_update_dynamic_price_after_session() CASCADE;

CREATE TABLE "User" (
    id       SERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL
);

CREATE TABLE Store (
    id       SERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL,
    name     TEXT NOT NULL UNIQUE
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
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    store_id   INTEGER NOT NULL,
    table_num  INTEGER NOT NULL,
    day        TEXT NOT NULL,
    start_time INTEGER NOT NULL,
    end_time   INTEGER NOT NULL,
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

CREATE TABLE MarketPariticipant (
    id              SERIAL PRIMARY KEY,
    customer_id     INTEGER,
    store_id        INTEGER,
    availiable_cash NUMERIC(10, 2),
    reserved_cash   NUMERIC(10, 2),
    CHECK ((customer_id IS NOT NULL AND store_id IS NULL) OR (customer_id IS NULL AND store_id IS NOT NULL))
);

CREATE TABLE MarketParticipantInventory (
    participant_id     INTEGER NOT NULL,
    game_id            INTEGER NOT NULL,
    available_quantity INTEGER NOT NULL,
    reserved_quantity  INTEGER NOT NULL,
    FOREIGN KEY (participant_id) REFERENCES MarketPariticipant(id),
    FOREIGN KEY (game_id) REFERENCES Game(id),
    PRIMARY KEY (participant_id, game_id)
);

CREATE TABLE TradingScript (
    id       SERIAL PRIMARY KEY,
    name     TEXT NOT NULL,
    code     TEXT NOT NULL,
    owner_id INTEGER NOT NULL,
    FOREIGN KEY (owner_id) REFERENCES MarketPariticipant(id)
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
    FOREIGN KEY (buyer_id)      REFERENCES MarketPariticipant(id),
    FOREIGN KEY (seller_id)     REFERENCES MarketPariticipant(id)
);
