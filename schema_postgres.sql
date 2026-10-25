-- ReLoop database schema (PostgreSQL version of schema.sql)
-- Optional: use this if you want PostgreSQL instead of SQLite.
--   createdb reloop
--   psql -d reloop -f backend/schema_postgres.sql
-- (The demo app itself runs on SQLite; this file is for moving to PostgreSQL later.)

DROP TABLE IF EXISTS redemptions, rewards, points_ledger, transactions, containers,
                     item_types, outlets, otp_codes, users, institutions CASCADE;

CREATE TABLE institutions (
    institution_id SERIAL PRIMARY KEY,
    name           TEXT NOT NULL,
    city           TEXT
);

CREATE TABLE users (
    user_id        SERIAL PRIMARY KEY,
    institution_id INT NOT NULL REFERENCES institutions(institution_id),
    role           TEXT NOT NULL CHECK (role IN ('student','staff','guest','vendor','admin')),
    name           TEXT NOT NULL,
    alias          TEXT,
    identifier     TEXT NOT NULL UNIQUE,
    department     TEXT,
    hostel         TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE otp_codes (
    otp_id     SERIAL PRIMARY KEY,
    identifier TEXT NOT NULL,
    code       TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    used       BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE outlets (
    outlet_id      SERIAL PRIMARY KEY,
    institution_id INT NOT NULL REFERENCES institutions(institution_id),
    name           TEXT NOT NULL,
    type           TEXT NOT NULL,
    location       TEXT,
    vendor_user_id INT REFERENCES users(user_id)
);

CREATE TABLE item_types (
    item_type_id       SERIAL PRIMARY KEY,
    name               TEXT NOT NULL UNIQUE,
    plastic_grams      NUMERIC(8,2) NOT NULL,
    emission_kg        NUMERIC(8,4) NOT NULL,
    reuse_footprint_kg NUMERIC(8,4) NOT NULL DEFAULT 0
);

CREATE TABLE containers (
    container_id SERIAL PRIMARY KEY,
    outlet_id    INT NOT NULL REFERENCES outlets(outlet_id),
    code         TEXT NOT NULL UNIQUE,
    type         TEXT NOT NULL CHECK (type IN ('cup','bottle')),
    material     TEXT,
    item_type_id INT NOT NULL REFERENCES item_types(item_type_id),
    wash_status  TEXT NOT NULL DEFAULT 'ready' CHECK (wash_status IN ('ready','in_use','dirty')),
    condition    TEXT NOT NULL DEFAULT 'ok' CHECK (condition IN ('ok','damaged','lost'))
);

CREATE TABLE transactions (
    txn_id           SERIAL PRIMARY KEY,
    user_id          INT NOT NULL REFERENCES users(user_id),
    outlet_id        INT NOT NULL REFERENCES outlets(outlet_id),
    container_id     INT REFERENCES containers(container_id),
    item_type_id     INT NOT NULL REFERENCES item_types(item_type_id),
    action           TEXT NOT NULL CHECK (action IN ('borrow','refill','byo_cup','byo_bag','no_lid')),
    status           TEXT NOT NULL CHECK (status IN ('pending','open','overdue','closed','rejected')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_at      TIMESTAMPTZ,
    approved_by      INT REFERENCES users(user_id),
    due_at           TIMESTAMPTZ,
    returned_at      TIMESTAMPTZ,
    return_outlet_id INT REFERENCES outlets(outlet_id),
    plastic_g        NUMERIC(8,2) NOT NULL DEFAULT 0,
    co2_g            NUMERIC(10,2) NOT NULL DEFAULT 0,
    points_awarded   INT NOT NULL DEFAULT 0
);

CREATE TABLE points_ledger (
    ledger_id  SERIAL PRIMARY KEY,
    user_id    INT NOT NULL REFERENCES users(user_id),
    txn_id     INT REFERENCES transactions(txn_id),
    points     INT NOT NULL,
    reason     TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE rewards (
    reward_id   SERIAL PRIMARY KEY,
    outlet_id   INT REFERENCES outlets(outlet_id),
    title       TEXT NOT NULL,
    points_cost INT NOT NULL,
    stock       INT NOT NULL DEFAULT 0,
    active      BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE redemptions (
    redemption_id SERIAL PRIMARY KEY,
    user_id       INT NOT NULL REFERENCES users(user_id),
    reward_id     INT NOT NULL REFERENCES rewards(reward_id),
    points_spent  INT NOT NULL,
    voucher_code  TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_txn_user      ON transactions(user_id);
CREATE INDEX idx_txn_outlet    ON transactions(outlet_id);
CREATE INDEX idx_txn_container ON transactions(container_id);
CREATE INDEX idx_txn_status    ON transactions(status);
CREATE INDEX idx_txn_created   ON transactions(created_at);
CREATE INDEX idx_ledger_user   ON points_ledger(user_id);
CREATE INDEX idx_users_dept    ON users(department);
