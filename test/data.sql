INSERT INTO "User" (username, password)
VALUES
  ('test', 'pbkdf2:sha256:50000$TCI4GzcX$0de171a4f4dac32e3364c7ddc7c14f3e2fa61f2d17574483f7ffbb431b4acb2f'),
  ('other', 'pbkdf2:sha256:50000$kJPKsz6N$d2d4784f1b030a9761f5ccaeeaca413f27f2ecb76d6168407af962ddce849f79');

INSERT INTO Game (name, symbol, genre, min_players, max_players, avg_duration, complexity_rating, description)
VALUES
  ('Test Game', 'TG', 'Strategy', 2, 4, 60, 3, 'A test game for testing.');

INSERT INTO MarketPariticipant (customer_id, availiable_cash, reserved_cash)
VALUES
  (1, 1000.00, 0.00),
  (2, 1000.00, 0.00);
