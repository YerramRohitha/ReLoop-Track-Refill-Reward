"""
ReLoop - business logic.
All the rules (points, impact, overdue, streaks) live here so the API
routes in app.py stay small and easy to read.
"""
import os
import sqlite3
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("RELOOP_DB", os.path.join(BASE_DIR, "..", "database", "reloop.db"))

# ---- settings (starting values, can be tuned) ----
BORROW_HOURS = 48          # cup must come back within this time
PENALTY_AFTER_HOURS = 72   # extra penalty after this time
DAILY_POINT_CAP = 30
TRUSTED_AFTER = 3          # user with 3 approved actions is auto-approved
MAX_OPEN_BORROWS = 2

POINTS = {
    "refill": 5,
    "byo_cup": 8,
    "byo_bag": 5,
    "no_lid": 2,
    "return_on_time": 10,
    "late_penalty": -5,
    "streak_bonus": 20,
}

# which disposable item each action replaces
ACTION_ITEM = {
    "refill": "Water bottle (500 ml)",
    "byo_cup": "Tea or coffee cup (150 ml)",
    "byo_bag": "Plastic carry bag",
    "no_lid": "Lid and straw",
}


def now():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def parse(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


# ---------------- database helpers ----------------
def connect(path=None):
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def one(conn, sql, args=()):
    r = conn.execute(sql, args).fetchone()
    return dict(r) if r else None


def many(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


# ---------------- impact ----------------
def impact_for(conn, item_type_id):
    """Plastic (g) and net CO2e (g) saved by avoiding one disposable item."""
    it = one(conn, "SELECT * FROM item_types WHERE item_type_id=?", (item_type_id,))
    plastic = it["plastic_grams"]
    co2 = max(0.0, (it["emission_kg"] - it["reuse_footprint_kg"]) * 1000)
    return round(plastic, 2), round(co2, 2)


def item_type_by_name(conn, name):
    return one(conn, "SELECT * FROM item_types WHERE name=?", (name,))


# ---------------- points ----------------
def points_balance(conn, user_id):
    r = one(conn, "SELECT COALESCE(SUM(points),0) AS p FROM points_ledger WHERE user_id=?", (user_id,))
    return r["p"]


def points_today(conn, user_id):
    day = now().strftime("%Y-%m-%d")
    r = one(conn, "SELECT COALESCE(SUM(points),0) AS p FROM points_ledger "
                  "WHERE user_id=? AND points>0 AND substr(created_at,1,10)=?", (user_id, day))
    return r["p"]


def add_points(conn, user_id, txn_id, points, reason, when=None):
    """Adds points to the ledger. Positive points respect the daily cap."""
    if points > 0:
        room = max(0, DAILY_POINT_CAP - points_today(conn, user_id))
        points = min(points, room)
    if points == 0:
        return 0
    conn.execute("INSERT INTO points_ledger(user_id,txn_id,points,reason,created_at) VALUES (?,?,?,?,?)",
                 (user_id, txn_id, points, reason, when or iso(now())))
    return points


def streak_days(conn, user_id):
    """Number of days in a row (ending today or yesterday) with at least one finished action."""
    rows = many(conn, "SELECT DISTINCT substr(COALESCE(returned_at, approved_at, created_at),1,10) AS d "
                      "FROM transactions WHERE user_id=? AND status='closed' ORDER BY d DESC", (user_id,))
    days = {r["d"] for r in rows}
    d = now().date()
    if d.strftime("%Y-%m-%d") not in days:
        d -= timedelta(days=1)
    n = 0
    while d.strftime("%Y-%m-%d") in days:
        n += 1
        d -= timedelta(days=1)
    return n


def streak_bonus(conn, user_id, txn_id):
    s = streak_days(conn, user_id)
    if s and s % 7 == 0:
        day = now().strftime("%Y-%m-%d")
        done = one(conn, "SELECT 1 AS x FROM points_ledger WHERE user_id=? AND reason='streak bonus' "
                         "AND substr(created_at,1,10)=?", (user_id, day))
        if not done:
            return add_points(conn, user_id, txn_id, POINTS["streak_bonus"], "streak bonus")
    return 0


# ---------------- overdue ----------------
def mark_overdue(conn):
    t = iso(now())
    conn.execute("UPDATE transactions SET status='overdue' WHERE status='open' AND due_at < ?", (t,))
    conn.commit()


# ---------------- trusted users ----------------
def is_trusted(conn, user_id):
    r = one(conn, "SELECT COUNT(*) AS c FROM transactions WHERE user_id=? AND status IN ('closed','open','overdue')",
            (user_id,))
    return r["c"] >= TRUSTED_AFTER


# ---------------- transaction flow ----------------
def create_txn(conn, user_id, outlet_id, action, item_type_id, container_id=None):
    cur = conn.execute(
        "INSERT INTO transactions(user_id,outlet_id,container_id,item_type_id,action,status,created_at) "
        "VALUES (?,?,?,?,?,'pending',?)",
        (user_id, outlet_id, container_id, item_type_id, action, iso(now())))
    return cur.lastrowid


def approve_txn(conn, txn_id, approver_id):
    """Vendor (or auto-approve) accepts a pending transaction."""
    t = one(conn, "SELECT * FROM transactions WHERE txn_id=?", (txn_id,))
    ts = now()
    if t["action"] == "borrow":
        due = ts + timedelta(hours=BORROW_HOURS)
        conn.execute("UPDATE transactions SET status='open', approved_at=?, approved_by=?, due_at=? WHERE txn_id=?",
                     (iso(ts), approver_id, iso(due), txn_id))
        conn.execute("UPDATE containers SET wash_status='in_use' WHERE container_id=?", (t["container_id"],))
        return {"status": "open", "due_at": iso(due), "points": 0, "plastic_g": 0, "co2_g": 0}
    # refill / byo_cup / byo_bag / no_lid are finished straight away
    plastic, co2 = impact_for(conn, t["item_type_id"])
    pts = add_points(conn, t["user_id"], txn_id, POINTS[t["action"]], t["action"])
    conn.execute("UPDATE transactions SET status='closed', approved_at=?, approved_by=?, returned_at=?, "
                 "plastic_g=?, co2_g=?, points_awarded=? WHERE txn_id=?",
                 (iso(ts), approver_id, iso(ts), plastic, co2, pts, txn_id))
    pts += streak_bonus(conn, t["user_id"], txn_id)
    conn.execute("UPDATE transactions SET points_awarded=? WHERE txn_id=?", (pts, txn_id))
    return {"status": "closed", "points": pts, "plastic_g": plastic, "co2_g": co2}


def reject_txn(conn, txn_id, approver_id):
    conn.execute("UPDATE transactions SET status='rejected', approved_at=?, approved_by=? WHERE txn_id=?",
                 (iso(now()), approver_id, txn_id))


def return_container(conn, txn, return_outlet_id):
    """User returns a borrowed cup / bottle."""
    ts = now()
    borrowed = parse(txn["approved_at"])
    hours = (ts - borrowed).total_seconds() / 3600
    plastic, co2 = impact_for(conn, txn["item_type_id"])
    if hours <= BORROW_HOURS:
        pts = add_points(conn, txn["user_id"], txn["txn_id"], POINTS["return_on_time"], "cup returned on time")
        if return_outlet_id != txn["outlet_id"]:
            pts += add_points(conn, txn["user_id"], txn["txn_id"], 2, "returned at another outlet")
    elif hours > PENALTY_AFTER_HOURS:
        pts = add_points(conn, txn["user_id"], txn["txn_id"], POINTS["late_penalty"], "late return penalty")
    else:
        pts = 0
    conn.execute("UPDATE transactions SET status='closed', returned_at=?, return_outlet_id=?, plastic_g=?, co2_g=?, "
                 "points_awarded=? WHERE txn_id=?", (iso(ts), return_outlet_id, plastic, co2, pts, txn["txn_id"]))
    conn.execute("UPDATE containers SET wash_status='dirty' WHERE container_id=?", (txn["container_id"],))
    bonus = streak_bonus(conn, txn["user_id"], txn["txn_id"])
    if bonus:
        pts += bonus
        conn.execute("UPDATE transactions SET points_awarded=? WHERE txn_id=?", (pts, txn["txn_id"]))
    return {"points": pts, "plastic_g": plastic, "co2_g": co2, "late": hours > BORROW_HOURS}
