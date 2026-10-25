-- ReLoop database schema (SQLite)
-- Created automatically by: python backend/seed.py

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS redemptions;
DROP TABLE IF EXISTS rewards;
DROP TABLE IF EXISTS points_ledger;
DROP TABLE IF EXISTS transactions;
DROP TABLE IF EXISTS containers;
DROP TABLE IF EXISTS item_types;
DROP TABLE IF EXISTS outlets;
DROP TABLE IF EXISTS otp_codes;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS institutions;

CREATE TABLE institutions (
    institution_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    city           TEXT
);

CREATE TABLE users (
    user_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    institution_id INTEGER NOT NULL REFERENCES institutions(institution_id),
    role           TEXT NOT NULL CHECK (role IN ('student','staff','guest','vendor','admin')),
    name           TEXT NOT NULL,
    alias          TEXT,
    identifier     TEXT NOT NULL UNIQUE,       -- roll number, email or phone
    department     TEXT,
    hostel         TEXT,
    created_at     TEXT NOT NULL
);

CREATE TABLE otp_codes (
    otp_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    identifier TEXT NOT NULL,
    code       TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE outlets (
    outlet_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    institution_id INTEGER NOT NULL REFERENCES institutions(institution_id),
    name           TEXT NOT NULL,
    type           TEXT NOT NULL,              -- tea stall, canteen, cafe, refill point
    location       TEXT,
    vendor_user_id INTEGER REFERENCES users(user_id)
);

CREATE TABLE item_types (
    item_type_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT NOT NULL UNIQUE,
    plastic_grams      REAL NOT NULL,          -- plastic in the disposable item
    emission_kg        REAL NOT NULL,          -- kg CO2e of the disposable item
    reuse_footprint_kg REAL NOT NULL DEFAULT 0 -- kg CO2e per reuse (washing etc.)
);

CREATE TABLE containers (
    container_id INTEGER PRIMARY KEY AUTOINCREMENT,
    outlet_id    INTEGER NOT NULL REFERENCES outlets(outlet_id),
    code         TEXT NOT NULL UNIQUE,         -- printed on the QR sticker
    type         TEXT NOT NULL CHECK (type IN ('cup','bottle')),
    material     TEXT,
    item_type_id INTEGER NOT NULL REFERENCES item_types(item_type_id),
    wash_status  TEXT NOT NULL DEFAULT 'ready' CHECK (wash_status IN ('ready','in_use','dirty')),
    condition    TEXT NOT NULL DEFAULT 'ok'    CHECK (condition IN ('ok','damaged','lost'))
);

CREATE TABLE transactions (
    txn_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL REFERENCES users(user_id),
    outlet_id        INTEGER NOT NULL REFERENCES outlets(outlet_id),
    container_id     INTEGER REFERENCES containers(container_id),
    item_type_id     INTEGER NOT NULL REFERENCES item_types(item_type_id),
    action           TEXT NOT NULL CHECK (action IN ('borrow','refill','byo_cup','byo_bag','no_lid')),
    status           TEXT NOT NULL CHECK (status IN ('pending','open','overdue','closed','rejected')),
    created_at       TEXT NOT NULL,
    approved_at      TEXT,
    approved_by      INTEGER REFERENCES users(user_id),
    due_at           TEXT,
    returned_at      TEXT,
    return_outlet_id INTEGER REFERENCES outlets(outlet_id),
    plastic_g        REAL NOT NULL DEFAULT 0,
    co2_g            REAL NOT NULL DEFAULT 0,
    points_awarded   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE points_ledger (
    ledger_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(user_id),
    txn_id     INTEGER REFERENCES transactions(txn_id),
    points     INTEGER NOT NULL,
    reason     TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE rewards (
    reward_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    outlet_id   INTEGER REFERENCES outlets(outlet_id),
    title       TEXT NOT NULL,
    points_cost INTEGER NOT NULL,
    stock       INTEGER NOT NULL DEFAULT 0,
    active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE redemptions (
    redemption_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(user_id),
    reward_id     INTEGER NOT NULL REFERENCES rewards(reward_id),
    points_spent  INTEGER NOT NULL,
    voucher_code  TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE INDEX idx_txn_user      ON transactions(user_id);
CREATE INDEX idx_txn_outlet    ON transactions(outlet_id);
CREATE INDEX idx_txn_container ON transactions(container_id);
CREATE INDEX idx_txn_status    ON transactions(status);
CREATE INDEX idx_txn_created   ON transactions(created_at);
CREATE INDEX idx_ledger_user   ON points_ledger(user_id);
CREATE INDEX idx_users_dept    ON users(department);
