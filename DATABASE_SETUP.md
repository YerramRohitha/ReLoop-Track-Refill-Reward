# Database Design and Setup

## Overview
ReLoop uses **SQLite** (one file: `database/reloop.db`). No server needs to be installed.
The same design is available for **PostgreSQL** in `backend/schema_postgres.sql`.

ER diagram: `docs/er_diagram.png`

## Tables
| Table | Purpose | Key columns |
|---|---|---|
| institutions | A college (tenant) | institution_id, name, city |
| users | Students, staff, guests, vendors, admins | user_id, institution_id, role, identifier (unique), department, hostel |
| otp_codes | One-time passwords for login | identifier, code, expires_at, used |
| outlets | Tea stall, canteen, cafe, refill point | outlet_id, institution_id, vendor_user_id |
| item_types | Disposable items replaced, with plastic weight and emission values | plastic_grams, emission_kg, reuse_footprint_kg |
| containers | Every tagged reusable cup / bottle (one QR each) | code (unique), outlet_id, wash_status, condition |
| transactions | Every action: borrow, refill, own cup, own bag, no lid | action, status, due_at, plastic_g, co2_g, points_awarded |
| points_ledger | Every point gained or lost (balance = sum) | user_id, txn_id, points, reason |
| rewards | What points can be spent on | title, points_cost, stock |
| redemptions | Vouchers students have redeemed | user_id, reward_id, voucher_code |

## Relationships (all one-to-many)
- institutions -> users, outlets
- users (vendor) -> outlets; users -> transactions, points_ledger, redemptions
- outlets -> containers, transactions, rewards
- containers -> transactions; item_types -> containers, transactions
- transactions -> points_ledger; rewards -> redemptions

## Rules enforced by the database
- `CHECK` constraints on `role`, `action`, `status`, `wash_status`, `condition`
- `UNIQUE` on `users.identifier`, `containers.code`, `item_types.name`
- `FOREIGN KEY` constraints (enabled with `PRAGMA foreign_keys = ON`)
- Indexes on user, outlet, container, status and created date for fast dashboards

Transaction status flow: `pending -> open -> (overdue) -> closed` for borrowed cups,
`pending -> closed` for refill / own cup / own bag / no lid, or `pending -> rejected`.

## Setup steps
### SQLite (default, used by the app)
```bash
python backend/seed.py        # creates database/reloop.db from backend/schema.sql and adds sample data
```
The app also does this automatically on first start if the file is missing.
Use another file with `RELOOP_DB=/path/to/file.db`.

To look inside the database you can use *DB Browser for SQLite* (free) or:
```bash
python - <<'PY'
import sqlite3
c = sqlite3.connect("database/reloop.db")
for r in c.execute("select name, role from users limit 5"): print(r)
PY
```

### PostgreSQL (optional)
```bash
createdb reloop
psql -d reloop -f backend/schema_postgres.sql
```
The Flask code in this project talks to SQLite directly; to switch to PostgreSQL the `connect()` helper in
`backend/logic.py` and the `?` placeholders (use `%s` with psycopg2) would be changed.

## Sample data created by seed.py
- 1 institution, 1 admin, 2 vendors, 12 students (sample names, departments and hostels)
- 4 outlets, 31 containers (25 cups, 6 bottles), 5 item types, 4 rewards
- 14 days of sample history for 10 students, one open cup and one cup that is about to be overdue

## Impact calculation
```
plastic saved (g) = plastic_grams of the disposable item replaced
CO2e saved (g)    = (emission_kg - reuse_footprint_kg) x 1000
```
Values in `item_types` are starting estimates and can be edited by the admin (Settings screen or `PUT /api/admin/item-types/<id>`).
