"""
Creates the database (schema.sql) and fills it with SAMPLE data for the demo.
Run:  python backend/seed.py
All people and numbers created here are sample data, not real results.
"""
import os
import random
from datetime import timedelta

import logic as L

HERE = os.path.dirname(os.path.abspath(__file__))

ITEM_TYPES = [  # name, plastic g, kg CO2e, reuse footprint kg  (starting estimates, editable by admin)
    ("Tea or coffee cup (150 ml)", 3, 0.020, 0.004),
    ("Water bottle (500 ml)", 18, 0.080, 0.006),
    ("Plastic carry bag", 5, 0.020, 0.003),
    ("Lid and straw", 2, 0.008, 0.000),
    ("Takeaway container with lid", 25, 0.100, 0.010),
]
ALIASES = ["GreenOwl", "EcoFox", "LeafyLily", "BlueBottle", "SunnySip", "CupHero",
           "RePourer", "PlasticFree", "TeaTurtle", "RiverRose", "MintyMe", "LoopLark"]
DEPTS = ["CSE", "ECE", "IT", "EEE", "Civil"]
HOSTELS = ["Block A", "Block B", "Block C", "Day scholar"]


def main(path=None):
    path = path or L.DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = L.connect(path)
    with open(os.path.join(HERE, "schema.sql")) as f:
        conn.executescript(f.read())
    rnd = random.Random(2026)
    t0 = L.iso(L.now())

    conn.execute("INSERT INTO institutions(name,city) VALUES (?,?)",
                 ("Malla Reddy Engineering College for Women", "Hyderabad"))
    inst = 1

    def user(role, name, ident, alias=None, dept=None, hostel=None):
        return conn.execute("INSERT INTO users(institution_id,role,name,alias,identifier,department,hostel,created_at) "
                            "VALUES (?,?,?,?,?,?,?,?)", (inst, role, name, alias, ident, dept, hostel, t0)).lastrowid

    admin = user("admin", "Campus Admin (sample)", "admin1")
    v1 = user("vendor", "Tea Point Vendor (sample)", "vendor1")
    v2 = user("vendor", "Canteen Vendor (sample)", "vendor2")
    students = []
    for i in range(12):
        students.append(user("student", "Sample Student %02d" % (i + 1), "student%d" % (i + 1), ALIASES[i],
                             DEPTS[i % len(DEPTS)], HOSTELS[i % len(HOSTELS)]))

    for name, typ, loc, vendor in [("Tea Point", "tea stall", "Near main gate", v1),
                                   ("Main Canteen", "canteen", "Ground floor, main block", v2),
                                   ("Library Cafe", "cafe", "Library building", v1),
                                   ("Water Refill Point", "refill point", "Corridor, block B", v2)]:
        conn.execute("INSERT INTO outlets(institution_id,name,type,location,vendor_user_id) VALUES (?,?,?,?,?)",
                     (inst, name, typ, loc, vendor))

    for n, p, e, r in ITEM_TYPES:
        conn.execute("INSERT INTO item_types(name,plastic_grams,emission_kg,reuse_footprint_kg) VALUES (?,?,?,?)", (n, p, e, r))
    cup_it, btl_it = 1, 2

    n = 0
    for outlet, count in [(1, 15), (2, 10)]:
        for _ in range(count):
            n += 1
            conn.execute("INSERT INTO containers(outlet_id,code,type,material,item_type_id) VALUES (?,?,?,?,?)",
                         (outlet, "CUP-%03d" % n, "cup", "steel", cup_it))
    for i in range(6):
        conn.execute("INSERT INTO containers(outlet_id,code,type,material,item_type_id) VALUES (?,?,?,?,?)",
                     (3, "BTL-%03d" % (i + 1), "bottle", "food-grade PP", btl_it))

    for outlet, title, cost, stock in [(1, "Rs. 10 off at Tea Point", 100, 50), (2, "Free coffee at Main Canteen", 250, 20),
                                       (None, "Stationery voucher (Rs. 20)", 300, 15),
                                       (None, "Reusable steel bottle", 600, 5)]:
        conn.execute("INSERT INTO rewards(outlet_id,title,points_cost,stock) VALUES (?,?,?,?)", (outlet, title, cost, stock))

    # ---- sample history for students 1..10 over the last 14 days ----
    actions = ["refill", "byo_cup", "byo_bag", "no_lid", "borrow"]
    item_for = {a: L.item_type_by_name(conn, L.ACTION_ITEM[a])["item_type_id"] for a in L.ACTION_ITEM}
    pts_day = {}
    for uid in students[:10]:
        habit = rnd.choice([0.5, 0.7, 0.9, 1.2, 1.6])  # how active this student is
        for back in range(14, 0, -1):
            day = L.now() - timedelta(days=back)
            for _ in range(int(habit * rnd.choice([0, 1, 1, 2, 2, 3]))):
                action = rnd.choice(actions)
                when = day.replace(hour=rnd.randint(8, 17), minute=rnd.randint(0, 59), second=0)
                outlet = rnd.choice([1, 1, 2, 3, 4]) if action != "borrow" else rnd.choice([1, 2])
                if action == "borrow":
                    cont = conn.execute("SELECT container_id FROM containers WHERE outlet_id=? ORDER BY RANDOM() LIMIT 1",
                                        (outlet,)).fetchone()[0]
                    item = cup_it
                    ret = when + timedelta(hours=rnd.randint(2, 30))
                    plastic, co2 = L.impact_for(conn, item)
                    pts = 10
                    cur = conn.execute(
                        "INSERT INTO transactions(user_id,outlet_id,container_id,item_type_id,action,status,created_at,"
                        "approved_at,approved_by,due_at,returned_at,return_outlet_id,plastic_g,co2_g,points_awarded) "
                        "VALUES (?,?,?,?,?,'closed',?,?,?,?,?,?,?,?,?)",
                        (uid, outlet, cont, item, action, L.iso(when), L.iso(when), v1, L.iso(when + timedelta(hours=48)),
                         L.iso(ret), outlet, plastic, co2, pts))
                    stamp = ret
                else:
                    item = item_for[action]
                    plastic, co2 = L.impact_for(conn, item)
                    pts = L.POINTS[action]
                    cur = conn.execute(
                        "INSERT INTO transactions(user_id,outlet_id,item_type_id,action,status,created_at,approved_at,"
                        "approved_by,returned_at,plastic_g,co2_g,points_awarded) VALUES (?,?,?,?,'closed',?,?,?,?,?,?,?)",
                        (uid, outlet, item, action, L.iso(when), L.iso(when), v1, L.iso(when), plastic, co2, pts))
                    stamp = when
                key = (uid, stamp.strftime("%Y-%m-%d"))
                room = max(0, L.DAILY_POINT_CAP - pts_day.get(key, 0))
                pts = min(pts, room)
                pts_day[key] = pts_day.get(key, 0) + pts
                conn.execute("UPDATE transactions SET points_awarded=? WHERE txn_id=?", (pts, cur.lastrowid))
                if pts:
                    conn.execute("INSERT INTO points_ledger(user_id,txn_id,points,reason,created_at) VALUES (?,?,?,?,?)",
                                 (uid, cur.lastrowid, pts, action, L.iso(stamp)))

    # ---- one open cup (student3) and one overdue-in-waiting cup (student4) so the demo has something to return ----
    for uid, cid, hrs in [(students[2], 1, 10), (students[3], 2, 60)]:
        when = L.now() - timedelta(hours=hrs)
        conn.execute("INSERT INTO transactions(user_id,outlet_id,container_id,item_type_id,action,status,created_at,"
                     "approved_at,approved_by,due_at) VALUES (?,?,?,?,'borrow','open',?,?,?,?)",
                     (uid, 1, cid, cup_it, L.iso(when), L.iso(when), v1, L.iso(when + timedelta(hours=48))))
        conn.execute("UPDATE containers SET wash_status='in_use' WHERE container_id=?", (cid,))
    conn.execute("UPDATE containers SET wash_status='dirty' WHERE container_id IN (3,4,5)")

    conn.commit()
    conn.close()
    print("Database created at", os.path.abspath(path))


if __name__ == "__main__":
    main()
