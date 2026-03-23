-- =============================================================================
-- Occhi di Falco – Database Schema v2.1
-- 888 Poker Tournament Tracking – Normalized 3NF
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. tournaments
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tournaments (
  tournament_id         TEXT    PRIMARY KEY,
  platform              TEXT    NOT NULL,              -- '888poker'
  start_time            TIMESTAMP NOT NULL,
  end_time              TIMESTAMP,
  buy_in                REAL    NOT NULL,
  prize_pool            REAL,
  buy_in_currency       TEXT    DEFAULT 'USD',
  format                TEXT,                          -- '6-max', 'full-ring', etc.
  game_type             TEXT    DEFAULT 'NLHE',        -- 'NLHE', 'PLO', etc.
  initial_stack         REAL    NOT NULL,
  blind_levels          TEXT,                          -- JSON stringified
  table_id              TEXT,
  your_starting_position TEXT,
  final_position        INTEGER,
  final_stack           REAL,
  roi                   REAL,                          -- (final_stack - buy_in) / buy_in
  duration_minutes      INTEGER,
  total_hands_played    INTEGER,
  notes                 TEXT,
  created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tournaments_platform_date
  ON tournaments(platform, start_time);

-- ---------------------------------------------------------------------------
-- 2. players_in_tournament
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS players_in_tournament (
  player_id             TEXT    PRIMARY KEY,
  tournament_id         TEXT    NOT NULL,
  seat_number           INTEGER NOT NULL,
  starting_position     TEXT,                          -- 'BTN', 'SB', 'BB', 'UTG', etc.
  starting_stack        REAL    NOT NULL,
  final_stack           REAL,
  finishing_position    INTEGER,
  payout                REAL,
  is_hero               INTEGER DEFAULT 0,             -- 1 = hero (you)
  status                TEXT,                          -- 'active', 'busted', 'cashed'
  bust_hand_number      INTEGER,
  notes                 TEXT,
  created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (tournament_id) REFERENCES tournaments(tournament_id),
  UNIQUE(tournament_id, seat_number)
);

CREATE INDEX IF NOT EXISTS idx_players_tournament
  ON players_in_tournament(tournament_id);
CREATE INDEX IF NOT EXISTS idx_players_is_hero
  ON players_in_tournament(is_hero);

-- ---------------------------------------------------------------------------
-- 3. hands
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hands (
  hand_id               TEXT    PRIMARY KEY,
  tournament_id         TEXT    NOT NULL,
  hand_number           INTEGER NOT NULL,
  timestamp             TIMESTAMP NOT NULL,
  button_position       TEXT,
  small_blind           REAL    NOT NULL,
  big_blind             REAL    NOT NULL,
  ante                  REAL    DEFAULT 0,
  starting_pot          REAL,
  hero_seat             TEXT,
  hero_cards            TEXT,                          -- 'As Kh' or NULL
  community_cards       TEXT,                          -- 'Ks7s2d' or NULL
  hand_stage            TEXT,                          -- 'preflop','flop','turn','river','showdown'
  final_pot             REAL,
  final_winner          TEXT,                          -- player_id
  hero_result           TEXT,                          -- 'win','loss','chop','fold','unknown'
  hero_profit           REAL,                          -- net chip change for hero
  hand_duration_seconds REAL,
  notes                 TEXT,
  raw_json              TEXT,                          -- raw extraction for debugging
  created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (tournament_id) REFERENCES tournaments(tournament_id),
  UNIQUE(tournament_id, hand_number)
);

CREATE INDEX IF NOT EXISTS idx_hands_tournament ON hands(tournament_id);
CREATE INDEX IF NOT EXISTS idx_hands_timestamp  ON hands(timestamp);
CREATE INDEX IF NOT EXISTS idx_hands_stage      ON hands(hand_stage);

-- ---------------------------------------------------------------------------
-- 4. hand_actions
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hand_actions (
  action_id             INTEGER PRIMARY KEY AUTOINCREMENT,
  hand_id               TEXT    NOT NULL,
  action_order          INTEGER NOT NULL,
  player_id             TEXT,
  action_type           TEXT    NOT NULL,              -- 'fold','check','call','raise','bet','allin'
  amount                REAL,
  street                TEXT,                          -- 'preflop','flop','turn','river'
  timestamp             TIMESTAMP,
  FOREIGN KEY (hand_id)   REFERENCES hands(hand_id),
  FOREIGN KEY (player_id) REFERENCES players_in_tournament(player_id)
);

CREATE INDEX IF NOT EXISTS idx_actions_hand   ON hand_actions(hand_id);
CREATE INDEX IF NOT EXISTS idx_actions_player ON hand_actions(player_id);

-- ---------------------------------------------------------------------------
-- 5. player_statistics
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS player_statistics (
  stat_id               INTEGER PRIMARY KEY AUTOINCREMENT,
  tournament_id         TEXT    NOT NULL,
  player_id             TEXT    NOT NULL,

  -- Frequency stats
  hands_played          INTEGER DEFAULT 0,
  hands_won             INTEGER DEFAULT 0,
  hands_folded          INTEGER DEFAULT 0,

  -- Aggression metrics
  vpip                  REAL,   -- Voluntarily Put In Pot %
  pfr                   REAL,   -- Pre-Flop Raise %
  aggression_factor     REAL,   -- (Bets + Raises) / Calls
  postflop_aggression   REAL,

  -- 3-bet stats
  three_bet_percentage  REAL,
  fold_to_three_bet     REAL,

  -- C-bet stats
  cbet_percentage       REAL,
  fold_to_cbet          REAL,

  -- Showdown stats
  showdown_percentage   REAL,
  win_at_showdown       REAL,

  -- Positional VPIP
  vpip_btn              REAL,
  vpip_sb               REAL,
  vpip_bb               REAL,
  vpip_utg              REAL,

  -- Sizing averages
  avg_open_raise_size   REAL,
  avg_3bet_size         REAL,
  avg_4bet_size         REAL,

  -- Fish detection
  fish_score            INTEGER,  -- 0-100 (0=nit, 100=fish)
  volatility            INTEGER,  -- looseness 0-100

  -- Win-rate
  total_profit          REAL,
  win_rate              REAL,     -- bb/100
  roi                   REAL,

  updated_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (tournament_id) REFERENCES tournaments(tournament_id),
  FOREIGN KEY (player_id)     REFERENCES players_in_tournament(player_id),
  UNIQUE(tournament_id, player_id)
);

CREATE INDEX IF NOT EXISTS idx_stats_tournament ON player_statistics(tournament_id);
CREATE INDEX IF NOT EXISTS idx_stats_fish_score ON player_statistics(fish_score);

-- ---------------------------------------------------------------------------
-- 6. bubble_tracking
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bubble_tracking (
  bubble_id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  tournament_id               TEXT    NOT NULL,
  hand_number                 INTEGER,
  timestamp                   TIMESTAMP,

  remaining_players           INTEGER,
  players_to_cash             INTEGER,
  bubble_factor               REAL,   -- Avg stack / Min stack to cash

  chip_leader_id              TEXT,
  chip_leader_stack           REAL,
  shortest_stack_player_id    TEXT,
  shortest_stack              REAL,
  stack_range                 REAL,   -- (Max - Min) / Avg

  your_chip_position          INTEGER,  -- 1=leader
  your_chip_percentage        REAL,     -- Your chips / Total chips
  icm_equity                  REAL,

  notes                       TEXT,
  FOREIGN KEY (tournament_id)            REFERENCES tournaments(tournament_id),
  FOREIGN KEY (chip_leader_id)           REFERENCES players_in_tournament(player_id),
  FOREIGN KEY (shortest_stack_player_id) REFERENCES players_in_tournament(player_id)
);

CREATE INDEX IF NOT EXISTS idx_bubble_tournament ON bubble_tracking(tournament_id);
CREATE INDEX IF NOT EXISTS idx_bubble_hand       ON bubble_tracking(hand_number);

-- ---------------------------------------------------------------------------
-- 7. blind_levels
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS blind_levels (
  level_id         INTEGER PRIMARY KEY AUTOINCREMENT,
  tournament_id    TEXT    NOT NULL,
  level_number     INTEGER,
  small_blind      REAL,
  big_blind        REAL,
  ante             REAL    DEFAULT 0,
  duration_minutes INTEGER,
  start_hand       INTEGER,
  end_hand         INTEGER,
  FOREIGN KEY (tournament_id) REFERENCES tournaments(tournament_id)
);

CREATE INDEX IF NOT EXISTS idx_blind_levels_tournament
  ON blind_levels(tournament_id);

-- ---------------------------------------------------------------------------
-- 8. session_metadata
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS session_metadata (
  session_id                    TEXT    PRIMARY KEY,
  tournament_id                 TEXT    NOT NULL UNIQUE,
  session_start                 TIMESTAMP,
  session_end                   TIMESTAMP,
  data_quality_score            REAL,   -- 0-100 (% OCR confidence avg)
  extraction_method             TEXT,   -- 'live_screen', 'video_replay'
  frames_processed              INTEGER,
  frames_with_errors            INTEGER,
  ocr_avg_confidence            REAL,
  table_detection_success_rate  REAL,
  notes                         TEXT,
  created_at                    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (tournament_id) REFERENCES tournaments(tournament_id)
);
