"""
API tests for ReLoop.  Run:  python -m unittest tests.test_api -v
Each test class uses a fresh temporary database filled with the sample data.
"""
import os
import sys
import tempfile
import unittest
from datetime import timedelta

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "backend"))

_tmp = tempfile.mkdtemp()
os.environ["RELOOP_DB"] = os.path.join(_tmp, "test.db")

import logic as L   # noqa: E402
import seed         # noqa: E402
import app as appmod  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        L.DB_PATH = os.path.join(tempfile.mkdtemp(), "test.db")   # fresh database for every test
        seed.main(L.DB_PATH)
        self.c = appmod.app.test_client()

    def login(self, ident):
        self.c.post("/api/auth/otp/request", json={"identifier": ident})
        r = self.c.post("/api/auth/otp/verify", json={"identifier": ident, "otp": "123456"})
        self.assertEqual(r.status_code, 200)
        return {"Authorization": "Bearer " + r.json["token"]}

    def sql(self, q, a=()):
        conn = L.connect()
        r = conn.execute(q, a)
        conn.commit()
        rows = [dict(x) for x in r.fetchall()] if r.description else []
        conn.close()
        return rows


class TestAuth(Base):
    def test_01_health(self):
        self.assertEqual(self.c.get("/api/health").json["status"], "ok")

    def test_02_login_existing_user(self):
        h = self.login("student1")
        self.assertEqual(self.c.get("/api/me", headers=h).json["user"]["identifier"], "student1")

    def test_03_new_user_registration(self):
        r = self.c.post("/api/auth/otp/request", json={"identifier": "newgirl@college.edu"})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json["error"], "new_user")
        r = self.c.post("/api/auth/otp/request", json={"identifier": "newgirl@college.edu", "name": "New Girl", "department": "CSE"})
        self.assertEqual(r.status_code, 200)
        h = self.login("newgirl@college.edu")
        self.assertEqual(self.c.get("/api/me", headers=h).json["user"]["role"], "student")

    def test_04_wrong_otp_rejected(self):
        self.c.post("/api/auth/otp/request", json={"identifier": "student1"})
        r = self.c.post("/api/auth/otp/verify", json={"identifier": "student1", "otp": "000000"})
        self.assertEqual(r.status_code, 401)

    def test_05_no_token_blocked(self):
        self.assertEqual(self.c.get("/api/me").status_code, 401)
        self.assertEqual(self.c.get("/api/me", headers={"Authorization": "Bearer fake"}).status_code, 401)

    def test_06_role_permissions(self):
        s = self.login("student1")
        v = self.login("vendor1")
        self.assertEqual(self.c.get("/api/admin/dashboard", headers=s).status_code, 403)
        self.assertEqual(self.c.get("/api/vendor/pending", headers=s).status_code, 403)
        self.assertEqual(self.c.get("/api/admin/dashboard", headers=v).status_code, 403)


class TestScanFlow(Base):
    def test_01_new_student_borrow_needs_vendor_approval(self):
        s, v = self.login("student11"), self.login("vendor1")
        r = self.c.post("/api/scan/borrow", headers=s, json={"container_code": "CUP-010"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json["status"], "pending")
        pend = self.c.get("/api/vendor/pending", headers=v).json
        self.assertEqual(len(pend), 1)
        res = self.c.post("/api/vendor/approvals/%d" % pend[0]["txn_id"], headers=v, json={"decision": "approve"})
        self.assertEqual(res.json["status"], "open")
        self.assertIn("due_at", res.json)

    def test_02_full_borrow_return_awards_points_and_impact(self):
        s, v = self.login("student11"), self.login("vendor1")
        self.c.post("/api/scan/borrow", headers=s, json={"container_code": "CUP-010"})
        tid = self.c.get("/api/vendor/pending", headers=v).json[0]["txn_id"]
        self.c.post("/api/vendor/approvals/%d" % tid, headers=v, json={"decision": "approve"})
        before = self.c.get("/api/me", headers=s).json["points"]
        r = self.c.post("/api/scan/return", headers=s, json={"container_code": "CUP-010"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json["points"], 10)
        self.assertEqual(r.json["plastic_g"], 3.0)
        self.assertEqual(r.json["co2_g"], 16.0)       # (0.020 - 0.004) kg = 16 g
        self.assertEqual(self.c.get("/api/me", headers=s).json["points"], before + 10)
        self.assertEqual(self.sql("SELECT wash_status FROM containers WHERE code='CUP-010'")[0]["wash_status"], "dirty")

    def test_03_dirty_cup_cannot_be_borrowed_until_washed(self):
        s, v = self.login("student11"), self.login("vendor1")
        r = self.c.post("/api/scan/borrow", headers=s, json={"container_code": "CUP-003"})   # seeded as dirty
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.c.post("/api/vendor/containers/wash", headers=v, json={"all": True}).json["washed"], 3)
        self.assertEqual(self.c.post("/api/scan/borrow", headers=s, json={"container_code": "CUP-003"}).status_code, 201)

    def test_04_same_cup_cannot_be_taken_twice(self):
        a, b = self.login("student11"), self.login("student12")
        self.assertEqual(self.c.post("/api/scan/borrow", headers=a, json={"container_code": "CUP-010"}).status_code, 201)
        self.assertEqual(self.c.post("/api/scan/borrow", headers=b, json={"container_code": "CUP-010"}).status_code, 409)

    def test_05_unknown_qr(self):
        s = self.login("student11")
        self.assertEqual(self.c.post("/api/scan/borrow", headers=s, json={"container_code": "NOPE-1"}).status_code, 404)

    def test_06_vendor_reject(self):
        s, v = self.login("student11"), self.login("vendor1")
        self.c.post("/api/scan/borrow", headers=s, json={"container_code": "CUP-011"})
        tid = self.c.get("/api/vendor/pending", headers=v).json[0]["txn_id"]
        self.assertEqual(self.c.post("/api/vendor/approvals/%d" % tid, headers=v, json={"decision": "reject"}).json["status"], "rejected")
        self.assertEqual(self.c.post("/api/vendor/approvals/%d" % tid, headers=v, json={"decision": "approve"}).status_code, 409)

    def test_07_trusted_student_is_auto_approved_refill(self):
        s = self.login("student1")     # has history in the sample data
        r = self.c.post("/api/scan/refill", headers=s, json={"outlet_id": 4, "action": "refill"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json["status"], "closed")
        self.assertTrue(r.json["auto_approved"])
        self.assertEqual(r.json["plastic_g"], 18.0)

    def test_08_bad_action_and_outlet(self):
        s = self.login("student1")
        self.assertEqual(self.c.post("/api/scan/refill", headers=s, json={"outlet_id": 4, "action": "fly"}).status_code, 400)
        self.assertEqual(self.c.post("/api/scan/refill", headers=s, json={"outlet_id": 999, "action": "refill"}).status_code, 404)

    def test_09_cannot_return_someone_elses_cup(self):
        s = self.login("student1")
        self.assertEqual(self.c.post("/api/scan/return", headers=s, json={"container_code": "CUP-001"}).status_code, 403)

    def test_10_borrower_returns_open_cup(self):
        s = self.login("student3")     # seeded with CUP-001 borrowed 10 hours ago
        me = self.c.get("/api/me", headers=s).json
        self.assertEqual(me["open_cups"][0]["code"], "CUP-001")
        r = self.c.post("/api/scan/return", headers=s, json={"container_code": "CUP-001", "outlet_id": 2})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json["points"], 12)         # 10 on time + 2 for another outlet (if under daily cap)

    def test_11_overdue_detected_and_penalty(self):
        s = self.login("student4")     # CUP-002 borrowed 60 h ago -> overdue
        me = self.c.get("/api/me", headers=s).json
        self.assertEqual(me["open_cups"][0]["status"], "overdue")
        self.sql("UPDATE transactions SET approved_at=? WHERE container_id=2 AND status='overdue'",
                 (L.iso(L.now() - timedelta(hours=80)),))
        r = self.c.post("/api/scan/return", headers=s, json={"container_code": "CUP-002"})
        self.assertEqual(r.json["points"], -5)
        self.assertTrue(r.json["late"])

    def test_12_overdue_user_cannot_borrow_again(self):
        s = self.login("student4")
        self.c.get("/api/me", headers=s)
        r = self.c.post("/api/scan/borrow", headers=s, json={"container_code": "CUP-012"})
        self.assertEqual(r.status_code, 409)

    def test_13_daily_point_cap(self):
        s = self.login("student1")
        self.sql("DELETE FROM points_ledger WHERE user_id=4")
        self.sql("DELETE FROM transactions WHERE user_id=4 AND created_at > ?", (L.iso(L.now() - timedelta(days=1)),))
        got = 0
        for _ in range(7):
            r = self.c.post("/api/scan/refill", headers=s, json={"outlet_id": 4, "action": "byo_cup"})
            self.assertEqual(r.status_code, 201)
            got += r.json["points"]
        self.assertLessEqual(got, L.DAILY_POINT_CAP)
        self.assertEqual(self.c.get("/api/me", headers=s).json["points_today"], L.DAILY_POINT_CAP)

    def test_14_too_many_scans_blocked(self):
        s = self.login("student1")
        codes = []
        for _ in range(12):
            codes.append(self.c.post("/api/scan/refill", headers=s, json={"outlet_id": 4, "action": "no_lid"}).status_code)
        self.assertIn(429, codes)

    def test_15_vendor_manual_entry_by_roll_number(self):
        v = self.login("vendor1")
        r = self.c.post("/api/vendor/manual", headers=v, json={"identifier": "student12", "action": "refill"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json["status"], "closed")
        self.assertEqual(self.c.post("/api/vendor/manual", headers=v, json={"identifier": "nobody", "action": "refill"}).status_code, 404)


class TestDataEndpoints(Base):
    def test_01_impact_me(self):
        s = self.login("student1")
        r = self.c.get("/api/impact/me", headers=s).json
        self.assertGreater(r["items"], 0)
        self.assertEqual(len(r["last7"]), 7)
        self.assertGreater(r["plastic_g"], 0)

    def test_02_leaderboards(self):
        s = self.login("student1")
        for kind in ("department", "hostel", "user"):
            r = self.c.get("/api/leaderboard?type=" + kind, headers=s)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json[0]["rank"], 1)
            self.assertTrue(all(r.json[i]["items"] >= r.json[i + 1]["items"] for i in range(len(r.json) - 1)))
        self.assertEqual(self.c.get("/api/leaderboard?type=bad", headers=s).status_code, 400)

    def test_03_redeem_not_enough_points(self):
        s = self.login("student12")      # no history, 0 points
        r = self.c.post("/api/rewards/4/redeem", headers=s)
        self.assertEqual(r.status_code, 409)

    def test_04_redeem_success_reduces_points_and_stock(self):
        s = self.login("student1")
        self.sql("INSERT INTO points_ledger(user_id,points,reason,created_at) VALUES (4,500,'test top-up',?)", (L.iso(L.now() - timedelta(days=3)),))
        before = self.c.get("/api/me", headers=s).json["points"]
        r = self.c.post("/api/rewards/1/redeem", headers=s)
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.json["voucher_code"].startswith("RL-"))
        self.assertEqual(self.c.get("/api/me", headers=s).json["points"], before - 100)
        self.assertEqual(self.sql("SELECT stock FROM rewards WHERE reward_id=1")[0]["stock"], 49)
        self.assertEqual(len(self.c.get("/api/redemptions/me", headers=s).json), 1)

    def test_05_vendor_stats_and_containers(self):
        v = self.login("vendor1")
        st = self.c.get("/api/vendor/stats", headers=v).json
        self.assertIn("containers", st)
        self.assertGreater(len(self.c.get("/api/vendor/containers", headers=v).json), 0)


class TestAdmin(Base):
    def test_01_dashboard(self):
        a = self.login("admin1")
        r = self.c.get("/api/admin/dashboard", headers=a).json
        self.assertGreater(r["items"], 0)
        self.assertEqual(len(r["per_day"]), 14)
        self.assertGreater(len(r["by_department"]), 0)

    def test_02_add_outlet_and_containers_and_qr_list(self):
        a = self.login("admin1")
        r = self.c.post("/api/admin/outlets", headers=a, json={"name": "Hostel Mess", "type": "mess", "vendor_identifier": "vendor2"})
        self.assertEqual(r.status_code, 201)
        oid = r.json["outlet_id"]
        r = self.c.post("/api/admin/containers", headers=a, json={"outlet_id": oid, "type": "cup", "count": 3})
        self.assertEqual(len(r.json["created"]), 3)
        qr = self.c.get("/api/admin/qr-list", headers=a).json
        self.assertTrue(any(c["value"] == "RELOOP:" + r.json["created"][0] for c in qr["containers"]))
        self.assertEqual(self.c.post("/api/admin/outlets", headers=a, json={"name": ""}).status_code, 400)

    def test_03_edit_item_type_changes_impact(self):
        a, s = self.login("admin1"), self.login("student1")
        self.assertEqual(self.c.put("/api/admin/item-types/2", headers=a,
                                    json={"plastic_grams": 20, "emission_kg": 0.1, "reuse_footprint_kg": 0.01}).status_code, 200)
        r = self.c.post("/api/scan/refill", headers=s, json={"outlet_id": 4, "action": "refill"})
        self.assertEqual(r.json["plastic_g"], 20.0)
        self.assertEqual(r.json["co2_g"], 90.0)
        self.assertEqual(self.c.put("/api/admin/item-types/2", headers=a, json={"plastic_grams": "x"}).status_code, 400)

    def test_04_report_csv(self):
        a = self.login("admin1")
        r = self.c.get("/api/admin/report.csv", headers=a)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_data(as_text=True).startswith("date,outlet,action,department,plastic_g,co2_g"))

    def test_05_flags(self):
        a, s = self.login("admin1"), self.login("student1")
        self.sql("DELETE FROM points_ledger WHERE user_id=4")
        self.sql("DELETE FROM transactions WHERE user_id=4 AND created_at > ?", (L.iso(L.now() - timedelta(days=1)),))
        for _ in range(7):
            self.c.post("/api/scan/refill", headers=s, json={"outlet_id": 4, "action": "no_lid"})
        flags = self.c.get("/api/admin/flags", headers=a).json
        self.assertTrue(any(f["identifier"] == "student1" for f in flags))

    def test_06_add_reward(self):
        a = self.login("admin1")
        r = self.c.post("/api/admin/rewards", headers=a, json={"title": "Free sticker", "points_cost": 50, "stock": 10})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.c.post("/api/admin/rewards", headers=a, json={"title": "", "points_cost": 0, "stock": 1}).status_code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
