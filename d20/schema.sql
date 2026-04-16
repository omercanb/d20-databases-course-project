drop table if exists User;
drop table if exists Owner;
drop table if exists Customer;
drop table if exists Store;
drop table if exists 'Table';
drop table if exists Game;
drop table if exists GameCopy;
drop table if exists Session;
drop table if exists SessionGameCopy;
drop table if exists GameDamage;
drop table if exists MarketPariticipant;
drop table if exists MarketParticipantInventory;
drop table if exists Orders;
drop table if exists MarketHistory;

-- CREATE TABLE post (
--   id INTEGER PRIMARY KEY AUTOINCREMENT,
--   author_id INTEGER NOT NULL,
--   created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
--   title TEXT NOT NULL,
--   body TEXT NOT NULL,
--   FOREIGN KEY (author_id) REFERENCES user (id)
-- );
--

create table User (
    id       integer primary key autoincrement,
    username      text not null unique,
    -- password is the password hash actually
    password text not null
    -- created_at    timestamp default current_timestamp
);

create table Store (
    id            integer primary key autoincrement,
    username      text not null unique,
    password text not null,
    name text not null unique
    -- address       text,
    -- phone_number  text,
    -- opening_hour  text,
    -- closing_hour  text,
    -- location      text
);

create table 'Table' (
    store_id integer not null,
    table_num integer not null,
    capacity integer,
    foreign key (store_id) references Store(id),
    primary key (store_id, table_num)
);

create table Game (
    id integer primary key autoincrement,
    name text not null unique
);

create table GameCopy (
    game_id integer not null,
    store_id integer not null,
    copy_num integer not null,
    foreign key (game_id) references Game(id),
    foreign key (store_id) references Store(id),
    primary key (game_id, store_id, copy_num)
);

create table Session (
    id integer primary key autoincrement,
    user_id integer not null,
    store_id integer not null,
    table_num integer not null,
    day text not null,
    start_time integer not null,
    end_time integer not null,
    foreign key (store_id, table_num) references 'Table'(store_id, table_num),
    foreign key (user_id) references User(id)
);

create table SessionGameCopy (
    session_id integer not null,
    game_id integer not null,
    store_id integer not null,
    copy_num integer not null,
    foreign key (session_id) references Session(id),
    foreign key (game_id, store_id, copy_num) references GameCopy(game_id, store_id, copy_num),
    primary key (session_id, game_id, store_id, copy_num)
);

create table GameDamage (
    session_id integer not null,
    game_id integer not null,
    store_id integer not null,
    copy_num integer not null,
    description text,
    foreign key (session_id) references Session(id),
    foreign key (game_id, store_id, copy_num) references GameCopy(game_id, store_id, copy_num),
    primary key (session_id, game_id, store_id, copy_num)
);


-- create table tier (
--     tier_id   integer primary key autoincrement,
--     tier_name text not null
-- );

-- Dynamic Price and Market Related Tables
-- The table for a 'user' in terms of the market portion of this program
-- Reserved cash is the cash the user has set aside in buy orders, so it could happen at any moment and be removed from the account
create table MarketPariticipant (
    id integer primary key autoincrement,
    -- Either customer id or store id is set
    customer_id integer,
    store_id integer,
    availiable_cash decimal(10, 2),
    reserved_cash decimal(10, 2),
    -- The below is like an xor operator checking that either customer id or store id is set
    check((customer_id is not null and store_id is null) or (customer_id is null and store_id is not null))
);

-- A many to many relation about the games that a market participant owns and has set aside to be used in the market
-- Logically this should be kept separate from the game copies table as that is a store specific thing, and it wouldn't make sense for 
-- stores to directly trade out of their own inventory if they hadn't set it aside.
-- This table also includes the inventory that is reserved: this means the user put out an order to sell this item, so it could be bought at any time
-- Unlike the game copy table, multiple game copies are stored in a single row, because we assume that different copies of the same game are identical
create table MarketParticipantInventory (
    participant_id integer not null,
    game_id integer not null,
    available_quantity integer not null,
    reserved_quantity integer not null,
    foreign key (participant_id) references MarketParticipant(id),
    foreign key (game_id) references Game(id),
    primary key (participant_id, game_id)
);

-- The order book
-- Contains trades that are waiting to happen
-- These consist of limit order (either buy or sell orders that are waiting to happen at a specified price)
-- A fill of an order means that a trade happened in the requested price range
-- A BUY order means the trade is waiting for a SELL order with an equal or lower price (Eq. BUY @ 10; SELL @ 5 is a match, SELL @ 12 is not)
-- The same is true for a SELL order in the opposite direction
-- Additionally a trade that happened is called a fill, and fills can be partial, so a trade could be SELL 5 CATAN @ 10 and only 2 could have been bought
create table Orders (
    id integer primary key,
    participant_id integer not null,
    game_id integer not null,
    order_type text check (order_type in ('LIMIT', 'MARKET')) not null,
    side text check (order_type in ('BUY', 'SELL')) not null,
    -- The constraint on price is because market orders should have no price (they execute at a specific price and that is in the history)
    -- And the price for a limit order can't be negative 
    price decimal(10, 2) check((order_type = 'LIMIT' and price > 0) or (order_type = 'MARKET' and price is null)),
    initial_quantity integer not null,
    filled_quantity integer not null,
    status text check (status in ('OPEN', 'PARTIAL', 'COMPLETED', 'CANCELLED')),
    created_at text not null -- TODO is there a default value for this in sqlite
);
 -- TODO create index on status for faster queries for open and partial

-- The history table
-- This needs to have every filled out trade
-- One buying and one selling trade is needed as we match them
-- The execution price is specified to determine which of the two prices the trade happened at
-- The quantity is also needed and an executed at
create table MarketHistory (
    buy_order_id integer not null,
    sell_order_id integer not null,
    buyer_id integer not null,
    seller_id integer not null,
    execution_price decimal(10, 2) not null,
    quantity integer not null,
    executed_at text not null,
    primary key (buy_order_id, sell_order_id),
    foreign key (buy_order_id) references Orders(id),
    foreign key (sell_order_id) references Orders(id),
    foreign key (buyer_id) references MarketPariticipant(id),
    foreign key (seller_id) references MarketPariticipant(id)
)
