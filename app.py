"""
ReLoop - Flask backend (REST API + serves the frontend).
Run:  python backend/app.py      then open http://127.0.0.1:5000
"""
import csv
import io
import os
import random
from datetime import timedelta
from functools import wraps

from flask import Flask, g, jsonify, request, send_from_directory, Response
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

import logic as L

FRONTEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
app = Flask(__name__, static_folder=FRONTEND, static_url_path="")
app.config["SECRET_KEY"] = os.environ.get("RELOOP_SECRET", "dev-secret-change-me")
DEMO_MODE = os.environ.get("RELOOP_DEMO", "1") == "1"   # fixed OTP 123456 for demo
DEMO_OTP = "123456"
signer = URLSafeTimedSerializer(app.config["SECRET_KEY"])
TOKEN_HOURS = 24 * 7
DEPARTMENTS = ["CSE", "ECE", "IT", "EEE", "Civil", "Other"]


# ---------------- helpers ----------------
def db():
    if "db" not in g:
        g.db = L.connect()
    return g.db


@app.teardown_appcontext
def close_db(_):
    conn = g.pop("db", None)
    if conn:
        conn.close()


def err(msg, code=400, **extra):
    return jsonify({"error": msg, **extra}), code


def auth(*roles):
    """Decorator: needs a valid token, and (optionally) one of the given roles."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            h = request.headers.get("Authorization", "")
            if not h.startswith("Bearer "):
                return err("login required", 401)
            try:
                data = signer.loads(h[7:], max_age=TOKEN_HOURS * 3600)
            except (BadSignature, SignatureExpired):
                return err("invalid or expired token", 401)
            user = L.one(db(), "SELECT * FROM users WHERE user_id=?", (data["uid"],))
            if not user:
                return err("user not found", 401)
            if roles and user["role"] not in roles:
                return err("you do not have permission for this", 403)
            g.user = user
            return fn(*a, **kw)
        return wrapper
    return deco


def public_user(u):
    return {k: u[k] for k in ("user_id", "name", "alias", "role", "identifier", "department", "hostel")}


def vendor_outlet_ids(user):
    if user["role"] == "admin":
        return [r["outlet_id"] for r in L.many(db(), "SELECT outlet_id FROM outlets WHERE institution_id=?",
                                               (user["institution_id"],))]
    return [r["outlet_id"] for r in L.many(db(), "SELECT outlet_id FROM outlets WHERE vendor_user_id=?",
                                           (user["user_id"],))]


# ---------------- pages ----------------
@app.route("/")
def index():
    return send_from_directory(FRONTEND, "index.html")


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "demo_mode": DEMO_MODE})


# ---------------- auth ----------------
@app.post("/api/auth/otp/request")
def otp_request():
    d = request.get_json(silent=True) or {}
    ident = (d.get("identifier") or "").strip()
    if len(ident) < 3:
        return err("enter your roll number, email or phone")
    conn = db()
    user = L.one(conn, "SELECT * FROM users WHERE identifier=?", (ident,))
    if not user:
        name = (d.get("name") or "").strip()
        if not name:
            return err("new_user", 404, message="New here? Please add your name to register.")
        inst = L.one(conn, "SELECT institution_id FROM institutions ORDER BY institution_id LIMIT 1")
        conn.execute("INSERT INTO users(institution_id,role,name,alias,identifier,department,hostel,created_at) "
                     "VALUES (?,?,?,?,?,?,?,?)",
                     (inst["institution_id"], "student", name, name.split()[0] + str(random.randint(10, 99)), ident,
                      d.get("department") or "Other", d.get("hostel") or "Day scholar", L.iso(L.now())))
    code = DEMO_OTP if DEMO_MODE else str(random.randint(100000, 999999))
    conn.execute("INSERT INTO otp_codes(identifier,code,expires_at) VALUES (?,?,?)",
                 (ident, code, L.iso(L.now() + timedelta(minutes=10))))
    conn.commit()
    res = {"message": "OTP sent"}
    if DEMO_MODE:
        res["demo_otp"] = code      # in real use this would be sent by SMS / email
    return jsonify(res)


@app.post("/api/auth/otp/verify")
def otp_verify():
    d = request.get_json(silent=True) or {}
    ident = (d.get("identifier") or "").strip()
    code = (d.get("otp") or "").strip()
    conn = db()
    row = L.one(conn, "SELECT * FROM otp_codes WHERE identifier=? AND code=? AND used=0 AND expires_at>? "
                      "ORDER BY otp_id DESC LIMIT 1", (ident, code, L.iso(L.now())))
    if not row:
        return err("wrong or expired OTP", 401)
    conn.execute("UPDATE otp_codes SET used=1 WHERE otp_id=?", (row["otp_id"],))
    conn.commit()
    user = L.one(conn, "SELECT * FROM users WHERE identifier=?", (ident,))
    token = signer.dumps({"uid": user["user_id"], "role": user["role"]})
    return jsonify({"token": token, "user": public_user(user)})


@app.get("/api/me")
@auth()
def me():
    conn, u = db(), g.user
    L.mark_overdue(conn)
    open_cups = L.many(conn, "SELECT t.txn_id, c.code, t.due_at, t.status FROM transactions t "
                             "JOIN containers c ON c.container_id=t.container_id "
                             "WHERE t.user_id=? AND t.status IN ('open','overdue')", (u["user_id"],))
    pending = L.one(conn, "SELECT COUNT(*) AS c FROM transactions WHERE user_id=? AND status='pending'",
                    (u["user_id"],))["c"]
    return jsonify({"user": public_user(u), "points": L.points_balance(conn, u["user_id"]),
                    "streak": L.streak_days(conn, u["user_id"]), "open_cups": open_cups,
                    "pending": pending, "points_today": L.points_today(conn, u["user_id"]),
                    "daily_cap": L.DAILY_POINT_CAP})


@app.get("/api/outlets")
@auth()
def outlets():
    rows = L.many(db(), "SELECT outlet_id,name,type,location FROM outlets WHERE institution_id=? ORDER BY name",
                  (g.user["institution_id"],))
    return jsonify(rows)


# ---------------- scanning (student side) ----------------
def finish_request(conn, txn_id, user_id):
    """Auto-approve trusted users, otherwise leave pending for the vendor."""
    if L.is_trusted(conn, user_id):
        res = L.approve_txn(conn, txn_id, None)
        res["auto_approved"] = True
    else:
        res = {"status": "pending", "message": "Waiting for the vendor to approve", "points": 0}
    conn.commit()
    res["txn_id"] = txn_id
    return res


def too_many_recent(conn, user_id):
    since = L.iso(L.now() - timedelta(hours=1))
    c = L.one(conn, "SELECT COUNT(*) AS c FROM transactions WHERE user_id=? AND created_at>?", (user_id, since))["c"]
    return c >= 8


@app.post("/api/scan/borrow")
@auth("student", "staff", "guest")
def scan_borrow():
    d = request.get_json(silent=True) or {}
    code = (d.get("container_code") or "").strip().upper()
    conn, u = db(), g.user
    L.mark_overdue(conn)
    c = L.one(conn, "SELECT * FROM containers WHERE code=?", (code,))
    if not c:
        return err("this QR code is not a ReLoop container", 404)
    if c["condition"] != "ok":
        return err("this container is %s" % c["condition"], 409)
    if c["wash_status"] != "ready":
        return err("this container is not ready (status: %s)" % c["wash_status"], 409)
    if L.one(conn, "SELECT 1 AS x FROM transactions WHERE container_id=? AND status IN ('pending','open','overdue')",
             (c["container_id"],)):
        return err("this container is already in use", 409)
    mine = L.one(conn, "SELECT COUNT(*) AS c FROM transactions WHERE user_id=? AND status IN ('open','overdue','pending') "
                       "AND action='borrow'", (u["user_id"],))["c"]
    if mine >= L.MAX_OPEN_BORROWS:
        return err("you already have %d cups out. Please return one first." % mine, 409)
    if L.one(conn, "SELECT 1 AS x FROM transactions WHERE user_id=? AND status='overdue'", (u["user_id"],)):
        return err("you have an overdue cup. Please return it first.", 409)
    if too_many_recent(conn, u["user_id"]):
        return err("too many scans in the last hour", 429)
    txn_id = L.create_txn(conn, u["user_id"], c["outlet_id"], "borrow", c["item_type_id"], c["container_id"])
    res = finish_request(conn, txn_id, u["user_id"])
    res["container"] = code
    return jsonify(res), 201


@app.post("/api/scan/refill")
@auth("student", "staff", "guest")
def scan_refill():
    d = request.get_json(silent=True) or {}
    action = d.get("action")
    conn, u = db(), g.user
    if action not in L.ACTION_ITEM:
        return err("action must be one of: " + ", ".join(L.ACTION_ITEM))
    o = L.one(conn, "SELECT * FROM outlets WHERE outlet_id=? AND institution_id=?",
              (d.get("outlet_id"), u["institution_id"]))
    if not o:
        return err("outlet not found", 404)
    if too_many_recent(conn, u["user_id"]):
        return err("too many scans in the last hour", 429)
    it = L.item_type_by_name(conn, L.ACTION_ITEM[action])
    txn_id = L.create_txn(conn, u["user_id"], o["outlet_id"], action, it["item_type_id"])
    res = finish_request(conn, txn_id, u["user_id"])
    return jsonify(res), 201


@app.post("/api/scan/return")
@auth("student", "staff", "guest")
def scan_return():
    d = request.get_json(silent=True) or {}
    code = (d.get("container_code") or "").strip().upper()
    conn, u = db(), g.user
    L.mark_overdue(conn)
    c = L.one(conn, "SELECT * FROM containers WHERE code=?", (code,))
    if not c:
        return err("this QR code is not a ReLoop container", 404)
    t = L.one(conn, "SELECT * FROM transactions WHERE container_id=? AND status IN ('open','overdue')",
              (c["container_id"],))
    if not t:
        return err("this container is not currently borrowed", 409)
    if t["user_id"] != u["user_id"]:
        return err("this container was borrowed by someone else", 403)
    out = d.get("outlet_id") or c["outlet_id"]
    if not L.one(conn, "SELECT 1 AS x FROM outlets WHERE outlet_id=? AND institution_id=?", (out, u["institution_id"])):
        return err("outlet not found", 404)
    res = L.return_container(conn, t, out)
    conn.commit()
    res["txn_id"] = t["txn_id"]
    res["status"] = "closed"
    return jsonify(res)


# ---------------- student data ----------------
@app.get("/api/transactions/me")
@auth()
def my_transactions():
    limit = min(int(request.args.get("limit", 20)), 100)
    rows = L.many(db(), "SELECT t.txn_id,t.action,t.status,t.created_at,t.due_at,t.returned_at,t.plastic_g,t.co2_g,"
                        "t.points_awarded,o.name AS outlet,c.code AS container FROM transactions t "
                        "JOIN outlets o ON o.outlet_id=t.outlet_id LEFT JOIN containers c ON c.container_id=t.container_id "
                        "WHERE t.user_id=? ORDER BY t.txn_id DESC LIMIT ?", (g.user["user_id"], limit))
    return jsonify(rows)


@app.get("/api/impact/me")
@auth()
def impact_me():
    conn, uid = db(), g.user["user_id"]
    tot = L.one(conn, "SELECT COUNT(*) AS items, COALESCE(SUM(plastic_g),0) AS plastic_g, COALESCE(SUM(co2_g),0) AS co2_g "
                      "FROM transactions WHERE user_id=? AND status='closed'", (uid,))
    days = []
    for i in range(6, -1, -1):
        day = (L.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        c = L.one(conn, "SELECT COUNT(*) AS c FROM transactions WHERE user_id=? AND status='closed' "
                        "AND substr(COALESCE(returned_at,created_at),1,10)=?", (uid, day))["c"]
        days.append({"date": day, "items": c})
    by_action = L.many(conn, "SELECT action, COUNT(*) AS n FROM transactions WHERE user_id=? AND status='closed' "
                             "GROUP BY action", (uid,))
    return jsonify({"items": tot["items"], "plastic_g": round(tot["plastic_g"], 1), "co2_g": round(tot["co2_g"], 1),
                    "last7": days, "by_action": by_action, "points": L.points_balance(conn, uid),
                    "streak": L.streak_days(conn, uid),
                    "bottles_equivalent": round(tot["plastic_g"] / 18.0, 1)})


@app.get("/api/leaderboard")
@auth()
def leaderboard():
    kind = request.args.get("type", "department")
    conn, u = db(), g.user
    inst = u["institution_id"]
    if kind in ("department", "hostel"):
        col = "department" if kind == "department" else "hostel"
        rows = L.many(conn, "SELECT u.%s AS name, COUNT(t.txn_id) AS items, COALESCE(SUM(t.co2_g),0) AS co2_g "
                            "FROM users u JOIN transactions t ON t.user_id=u.user_id AND t.status='closed' "
                            "WHERE u.institution_id=? AND u.role!='vendor' AND u.%s IS NOT NULL "
                            "GROUP BY u.%s ORDER BY items DESC LIMIT 10" % (col, col, col), (inst,))
    elif kind == "user":
        rows = L.many(conn, "SELECT u.user_id, COALESCE(u.alias,u.name) AS name, COUNT(t.txn_id) AS items, "
                            "COALESCE(SUM(t.co2_g),0) AS co2_g FROM users u JOIN transactions t ON t.user_id=u.user_id "
                            "AND t.status='closed' WHERE u.institution_id=? AND u.role IN ('student','staff') "
                            "GROUP BY u.user_id ORDER BY items DESC LIMIT 10", (inst,))
        for r in rows:
            r["me"] = r.pop("user_id") == u["user_id"]
    else:
        return err("type must be department, hostel or user")
    for i, r in enumerate(rows):
        r["rank"] = i + 1
        r["co2_g"] = round(r["co2_g"], 1)
    return jsonify(rows)


# ---------------- rewards ----------------
@app.get("/api/rewards")
@auth()
def rewards():
    rows = L.many(db(), "SELECT r.reward_id,r.title,r.points_cost,r.stock,o.name AS outlet FROM rewards r "
                        "LEFT JOIN outlets o ON o.outlet_id=r.outlet_id WHERE r.active=1 ORDER BY r.points_cost")
    return jsonify(rows)


@app.post("/api/rewards/<int:rid>/redeem")
@auth("student", "staff", "guest")
def redeem(rid):
    conn, u = db(), g.user
    r = L.one(conn, "SELECT * FROM rewards WHERE reward_id=? AND active=1", (rid,))
    if not r:
        return err("reward not found", 404)
    if r["stock"] <= 0:
        return err("this reward is out of stock", 409)
    bal = L.points_balance(conn, u["user_id"])
    if bal < r["points_cost"]:
        return err("not enough points (you have %d, need %d)" % (bal, r["points_cost"]), 409)
    code = "RL-" + "".join(random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
    conn.execute("UPDATE rewards SET stock=stock-1 WHERE reward_id=?", (rid,))
    conn.execute("INSERT INTO redemptions(user_id,reward_id,points_spent,voucher_code,created_at) VALUES (?,?,?,?,?)",
                 (u["user_id"], rid, r["points_cost"], code, L.iso(L.now())))
    conn.execute("INSERT INTO points_ledger(user_id,txn_id,points,reason,created_at) VALUES (?,?,?,?,?)",
                 (u["user_id"], None, -r["points_cost"], "redeemed: " + r["title"], L.iso(L.now())))
    conn.commit()
    return jsonify({"voucher_code": code, "points_left": bal - r["points_cost"], "title": r["title"]}), 201


@app.get("/api/redemptions/me")
@auth()
def my_redemptions():
    return jsonify(L.many(db(), "SELECT d.voucher_code,d.points_spent,d.created_at,r.title FROM redemptions d "
                                "JOIN rewards r ON r.reward_id=d.reward_id WHERE d.user_id=? ORDER BY d.redemption_id DESC",
                          (g.user["user_id"],)))


# ---------------- vendor ----------------
@app.get("/api/vendor/pending")
@auth("vendor", "admin")
def vendor_pending():
    ids = vendor_outlet_ids(g.user)
    if not ids:
        return jsonify([])
    q = ",".join("?" * len(ids))
    rows = L.many(db(), "SELECT t.txn_id,t.action,t.created_at,u.name AS user_name,u.identifier,o.name AS outlet,"
                        "c.code AS container FROM transactions t JOIN users u ON u.user_id=t.user_id "
                        "JOIN outlets o ON o.outlet_id=t.outlet_id LEFT JOIN containers c ON c.container_id=t.container_id "
                        "WHERE t.status='pending' AND t.outlet_id IN (%s) ORDER BY t.txn_id" % q, ids)
    return jsonify(rows)


@app.post("/api/vendor/approvals/<int:txn_id>")
@auth("vendor", "admin")
def vendor_decide(txn_id):
    d = request.get_json(silent=True) or {}
    conn = db()
    t = L.one(conn, "SELECT * FROM transactions WHERE txn_id=?", (txn_id,))
    if not t or t["outlet_id"] not in vendor_outlet_ids(g.user):
        return err("request not found", 404)
    if t["status"] != "pending":
        return err("this request was already handled", 409)
    if d.get("decision") == "approve":
        res = L.approve_txn(conn, txn_id, g.user["user_id"])
    elif d.get("decision") == "reject":
        L.reject_txn(conn, txn_id, g.user["user_id"])
        res = {"status": "rejected"}
    else:
        return err("decision must be approve or reject")
    conn.commit()
    return jsonify(res)


@app.post("/api/vendor/manual")
@auth("vendor", "admin")
def vendor_manual():
    """Vendor logs an action for a student who has no smartphone (by roll number)."""
    d = request.get_json(silent=True) or {}
    conn = db()
    user = L.one(conn, "SELECT * FROM users WHERE identifier=? AND role IN ('student','staff','guest')",
                 (d.get("identifier", "").strip(),))
    if not user:
        return err("no student with this roll number", 404)
    ids = vendor_outlet_ids(g.user)
    outlet = d.get("outlet_id") or (ids[0] if ids else None)
    if outlet not in ids:
        return err("outlet not found", 404)
    action = d.get("action")
    if action not in L.ACTION_ITEM:
        return err("action must be one of: " + ", ".join(L.ACTION_ITEM))
    it = L.item_type_by_name(conn, L.ACTION_ITEM[action])
    txn_id = L.create_txn(conn, user["user_id"], outlet, action, it["item_type_id"])
    res = L.approve_txn(conn, txn_id, g.user["user_id"])
    conn.commit()
    res["txn_id"] = txn_id
    return jsonify(res), 201


@app.get("/api/vendor/containers")
@auth("vendor", "admin")
def vendor_containers():
    ids = vendor_outlet_ids(g.user)
    if not ids:
        return jsonify([])
    q = ",".join("?" * len(ids))
    return jsonify(L.many(db(), "SELECT c.code,c.type,c.wash_status,c.condition,o.name AS outlet FROM containers c "
                                "JOIN outlets o ON o.outlet_id=c.outlet_id WHERE c.outlet_id IN (%s) ORDER BY c.code" % q, ids))


@app.post("/api/vendor/containers/wash")
@auth("vendor", "admin")
def vendor_wash():
    d = request.get_json(silent=True) or {}
    ids = vendor_outlet_ids(g.user)
    if not ids:
        return err("no outlet", 404)
    q = ",".join("?" * len(ids))
    conn = db()
    if d.get("all"):
        cur = conn.execute("UPDATE containers SET wash_status='ready' WHERE wash_status='dirty' AND outlet_id IN (%s)" % q, ids)
    else:
        codes = [c.upper() for c in d.get("codes", [])]
        if not codes:
            return err("send codes or all:true")
        cq = ",".join("?" * len(codes))
        cur = conn.execute("UPDATE containers SET wash_status='ready' WHERE wash_status='dirty' AND code IN (%s) "
                           "AND outlet_id IN (%s)" % (cq, q), codes + ids)
    conn.commit()
    return jsonify({"washed": cur.rowcount})


@app.get("/api/vendor/stats")
@auth("vendor", "admin")
def vendor_stats():
    conn = db()
    L.mark_overdue(conn)
    ids = vendor_outlet_ids(g.user)
    if not ids:
        return jsonify({})
    q = ",".join("?" * len(ids))
    today = L.now().strftime("%Y-%m-%d")
    saved = L.one(conn, "SELECT COUNT(*) AS c FROM transactions WHERE status='closed' AND outlet_id IN (%s) "
                        "AND substr(COALESCE(returned_at,created_at),1,10)=?" % q, ids + [today])["c"]
    pend = L.one(conn, "SELECT COUNT(*) AS c FROM transactions WHERE status='pending' AND outlet_id IN (%s)" % q, ids)["c"]
    status = L.many(conn, "SELECT wash_status, COUNT(*) AS n FROM containers WHERE outlet_id IN (%s) AND condition='ok' "
                          "GROUP BY wash_status" % q, ids)
    overdue = L.one(conn, "SELECT COUNT(*) AS c FROM transactions WHERE status='overdue' AND outlet_id IN (%s)" % q, ids)["c"]
    total = L.one(conn, "SELECT COUNT(*) AS c FROM transactions WHERE status='closed' AND outlet_id IN (%s)" % q, ids)["c"]
    return jsonify({"saved_today": saved, "pending": pend, "overdue": overdue, "total_saved": total,
                    "containers": {r["wash_status"]: r["n"] for r in status}})


# ---------------- admin ----------------
@app.get("/api/admin/dashboard")
@auth("admin")
def admin_dashboard():
    conn, inst = db(), g.user["institution_id"]
    L.mark_overdue(conn)
    base = "FROM transactions t JOIN users u ON u.user_id=t.user_id WHERE u.institution_id=? AND t.status='closed'"
    tot = L.one(conn, "SELECT COUNT(*) AS items, COALESCE(SUM(t.plastic_g),0) AS plastic_g, COALESCE(SUM(t.co2_g),0) AS co2_g "
                      + base, (inst,))
    since = L.iso(L.now() - timedelta(days=7))
    active = L.one(conn, "SELECT COUNT(DISTINCT t.user_id) AS c FROM transactions t JOIN users u ON u.user_id=t.user_id "
                         "WHERE u.institution_id=? AND t.created_at>?", (inst, since))["c"]
    students = L.one(conn, "SELECT COUNT(*) AS c FROM users WHERE institution_id=? AND role IN ('student','staff')", (inst,))["c"]
    per_day = []
    for i in range(13, -1, -1):
        day = (L.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        c = L.one(conn, "SELECT COUNT(*) AS c " + base + " AND substr(COALESCE(t.returned_at,t.created_at),1,10)=?",
                  (inst, day))["c"]
        per_day.append({"date": day, "items": c})
    by_outlet = L.many(conn, "SELECT o.name, COUNT(t.txn_id) AS items FROM outlets o LEFT JOIN transactions t "
                             "ON t.outlet_id=o.outlet_id AND t.status='closed' WHERE o.institution_id=? "
                             "GROUP BY o.outlet_id ORDER BY items DESC", (inst,))
    by_dept = L.many(conn, "SELECT u.department AS name, COUNT(t.txn_id) AS items " + base +
                           " GROUP BY u.department ORDER BY items DESC", (inst,))
    b = L.one(conn, "SELECT SUM(CASE WHEN t.status='closed' THEN 1 ELSE 0 END) AS closed, COUNT(*) AS total "
                    "FROM transactions t JOIN users u ON u.user_id=t.user_id WHERE u.institution_id=? "
                    "AND t.action='borrow' AND t.status IN ('open','overdue','closed')", (inst,))
    overdue = L.one(conn, "SELECT COUNT(*) AS c FROM transactions t JOIN users u ON u.user_id=t.user_id "
                          "WHERE u.institution_id=? AND t.status='overdue'", (inst,))["c"]
    return jsonify({"items": tot["items"], "plastic_g": round(tot["plastic_g"], 1), "co2_g": round(tot["co2_g"], 1),
                    "active_users_7d": active, "registered_users": students, "per_day": per_day,
                    "by_outlet": by_outlet, "by_department": by_dept, "overdue": overdue,
                    "return_rate": round(100 * (b["closed"] or 0) / b["total"], 1) if b["total"] else None})


@app.get("/api/admin/flags")
@auth("admin")
def admin_flags():
    since = L.iso(L.now() - timedelta(hours=1))
    rows = L.many(db(), "SELECT u.name,u.identifier,COUNT(*) AS scans_last_hour FROM transactions t "
                        "JOIN users u ON u.user_id=t.user_id WHERE u.institution_id=? AND t.created_at>? "
                        "GROUP BY u.user_id HAVING COUNT(*)>=6 ORDER BY scans_last_hour DESC",
                  (g.user["institution_id"], since))
    return jsonify(rows)


@app.get("/api/admin/outlets")
@auth("admin")
def admin_outlets():
    return jsonify(L.many(db(), "SELECT o.outlet_id,o.name,o.type,o.location,v.name AS vendor,"
                                "(SELECT COUNT(*) FROM containers c WHERE c.outlet_id=o.outlet_id) AS containers "
                                "FROM outlets o LEFT JOIN users v ON v.user_id=o.vendor_user_id "
                                "WHERE o.institution_id=? ORDER BY o.name", (g.user["institution_id"],)))


@app.post("/api/admin/outlets")
@auth("admin")
def admin_add_outlet():
    d = request.get_json(silent=True) or {}
    if not (d.get("name") or "").strip() or not (d.get("type") or "").strip():
        return err("name and type are required")
    vendor = None
    if d.get("vendor_identifier"):
        vendor = L.one(db(), "SELECT user_id FROM users WHERE identifier=? AND role='vendor'", (d["vendor_identifier"],))
        if not vendor:
            return err("vendor not found", 404)
    cur = db().execute("INSERT INTO outlets(institution_id,name,type,location,vendor_user_id) VALUES (?,?,?,?,?)",
                       (g.user["institution_id"], d["name"].strip(), d["type"].strip(), d.get("location"),
                        vendor["user_id"] if vendor else None))
    db().commit()
    return jsonify({"outlet_id": cur.lastrowid}), 201


@app.post("/api/admin/containers")
@auth("admin")
def admin_add_containers():
    d = request.get_json(silent=True) or {}
    conn = db()
    o = L.one(conn, "SELECT * FROM outlets WHERE outlet_id=? AND institution_id=?",
              (d.get("outlet_id"), g.user["institution_id"]))
    ctype = d.get("type", "cup")
    count = int(d.get("count", 0))
    if not o or ctype not in ("cup", "bottle") or not 1 <= count <= 200:
        return err("need a valid outlet_id, type (cup/bottle) and count (1-200)")
    name = "Tea or coffee cup (150 ml)" if ctype == "cup" else "Water bottle (500 ml)"
    it = L.item_type_by_name(conn, name)
    prefix = "CUP" if ctype == "cup" else "BTL"
    last = L.one(conn, "SELECT COUNT(*) AS c FROM containers WHERE code LIKE ?", (prefix + "-%",))["c"]
    codes = []
    for i in range(count):
        code = "%s-%03d" % (prefix, last + i + 1)
        conn.execute("INSERT INTO containers(outlet_id,code,type,material,item_type_id) VALUES (?,?,?,?,?)",
                     (o["outlet_id"], code, ctype, "steel" if ctype == "cup" else "food-grade PP", it["item_type_id"]))
        codes.append(code)
    conn.commit()
    return jsonify({"created": codes}), 201


@app.get("/api/admin/qr-list")
@auth("admin")
def admin_qr_list():
    conn, inst = db(), g.user["institution_id"]
    outs = L.many(conn, "SELECT outlet_id,name FROM outlets WHERE institution_id=?", (inst,))
    cons = L.many(conn, "SELECT c.code,c.type,o.name AS outlet FROM containers c JOIN outlets o ON o.outlet_id=c.outlet_id "
                        "WHERE o.institution_id=? ORDER BY c.code", (inst,))
    return jsonify({"outlets": [{"label": o["name"], "value": "RELOOP:OUTLET:%d" % o["outlet_id"]} for o in outs],
                    "containers": [{"label": c["code"], "sub": c["outlet"], "value": "RELOOP:" + c["code"]} for c in cons]})


@app.get("/api/admin/item-types")
@auth("admin")
def get_item_types():
    return jsonify(L.many(db(), "SELECT * FROM item_types ORDER BY item_type_id"))


@app.put("/api/admin/item-types/<int:iid>")
@auth("admin")
def put_item_type(iid):
    d = request.get_json(silent=True) or {}
    try:
        p, e, r = float(d["plastic_grams"]), float(d["emission_kg"]), float(d["reuse_footprint_kg"])
    except (KeyError, ValueError, TypeError):
        return err("plastic_grams, emission_kg and reuse_footprint_kg must be numbers")
    if min(p, e, r) < 0:
        return err("values cannot be negative")
    cur = db().execute("UPDATE item_types SET plastic_grams=?, emission_kg=?, reuse_footprint_kg=? WHERE item_type_id=?",
                       (p, e, r, iid))
    db().commit()
    if cur.rowcount == 0:
        return err("item type not found", 404)
    return jsonify({"updated": iid})


@app.post("/api/admin/rewards")
@auth("admin")
def admin_add_reward():
    d = request.get_json(silent=True) or {}
    try:
        cost, stock = int(d["points_cost"]), int(d["stock"])
    except (KeyError, ValueError, TypeError):
        return err("title, points_cost and stock are required")
    if not (d.get("title") or "").strip() or cost <= 0 or stock < 0:
        return err("invalid reward")
    cur = db().execute("INSERT INTO rewards(outlet_id,title,points_cost,stock) VALUES (?,?,?,?)",
                       (d.get("outlet_id"), d["title"].strip(), cost, stock))
    db().commit()
    return jsonify({"reward_id": cur.lastrowid}), 201


@app.get("/api/admin/report.csv")
@auth("admin")
def admin_report():
    rows = L.many(db(), "SELECT substr(COALESCE(t.returned_at,t.created_at),1,10) AS date, o.name AS outlet, t.action,"
                        "u.department, t.plastic_g, t.co2_g FROM transactions t JOIN users u ON u.user_id=t.user_id "
                        "JOIN outlets o ON o.outlet_id=t.outlet_id WHERE t.status='closed' AND u.institution_id=? "
                        "ORDER BY date", (g.user["institution_id"],))
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["date", "outlet", "action", "department", "plastic_g", "co2_g"])
    for r in rows:
        w.writerow([r["date"], r["outlet"], r["action"], r["department"], r["plastic_g"], r["co2_g"]])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=reloop_report.csv"})


# ---------------- start ----------------
def ensure_db():
    if not os.path.exists(L.DB_PATH):
        import seed
        seed.main()


ensure_db()   # creates and fills the database on first start (also when run with gunicorn)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
