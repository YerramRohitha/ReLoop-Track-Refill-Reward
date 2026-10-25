# ReLoop - Track. Refill. Reward.

**Team Innovatrix Nova** | Malla Reddy Engineering College for Women | Gigpoint Hackathon

ReLoop is a QR-based reusable cup and bottle system that tracks single-use plastic avoided on campus,
turns it into plastic and CO2 savings, and rewards students with points.

> All people, numbers and history in the database are **sample data** created by `seed.py`.
> The plastic weights and emission values are starting estimates and must be replaced with verified values.

---

## 1. Run it (quick start)

You need **Python 3.9 or newer**. Nothing else (the database is SQLite and is created automatically).

### Windows
```bat
cd reloop
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python backend\app.py
```
(or just double-click `run.bat`)

### Mac / Linux
```bash
cd reloop
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python backend/app.py
```
(or just run `./run.sh`)

Then open **http://127.0.0.1:5000** in the browser. On a phone on the same Wi-Fi, open `http://<your-computer-ip>:5000`.

To use another port: `PORT=8080 python backend/app.py` (Windows: `set PORT=8080` first).

## 2. Demo logins

| Role | Login (identifier) | What to try |
|---|---|---|
| Student | `student1` ... `student12` | Home, Scan, Impact, Leaderboard, Rewards |
| Vendor | `vendor1` (Tea Point + Library Cafe), `vendor2` (Canteen + Refill Point) | Approve requests, mark cups washed |
| Admin | `admin1` | Dashboard, outlets, QR codes, settings, CSV report |
| New user | any new roll number / email | Register with your name |

**OTP:** in demo mode the OTP is always `123456` (it is also filled in for you). In real use it would be sent by SMS/email.

### 3-minute demo flow
1. Login as **student11** (no history yet). Go to **Scan** > *Borrow cup* > code `CUP-012` > Confirm. You see "Request sent".
2. In a second browser window (or private window) login as **vendor1**. The request appears under **Approvals**. Tap **Approve**.
3. Back as student11: Home shows the cup with a due time. Tap **Return** > Confirm. You get points, plastic and CO2 saved.
4. Try *Refill bottle* with outlet "Water Refill Point". Open **Impact**, **Board** and **Rewards**.
5. Login as **admin1**: see the campus dashboard, QR codes page (print), and Settings (edit emission values, download CSV).

Students with 3 or more earlier actions are *trusted* and are approved automatically (to keep the counter fast).
New students need the vendor to tap Approve.

## 3. Reset the database
```bash
python backend/seed.py
```
This drops all tables, recreates them from `backend/schema.sql` and fills the sample data again.

## 4. Run the tests
```bash
python -m unittest tests.test_api -v
```
32 tests cover login, roles, borrow / approve / return, overdue and penalty, daily point cap, rewards, leaderboards and admin tools.
The last run is saved in `docs/API_TEST_RESULTS.txt`.

## 5. Project structure
```
reloop/
  backend/
    app.py                 Flask REST API (+ serves the frontend)
    logic.py               Business rules: points, impact, overdue, streaks
    seed.py                Creates the DB and sample data
    schema.sql             SQLite schema (used by the app)
    schema_postgres.sql    Same schema for PostgreSQL (optional)
  database/reloop.db       Ready-made SQLite database with sample data
  frontend/                index.html, style.css, app.js (plain JavaScript, no build step), manifest.json (PWA)
  tests/test_api.py        API tests
  docs/
    DATABASE_SETUP.md      Database documentation
    API_DOCUMENTATION.md   All API endpoints
    API_TEST_RESULTS.txt   Test output
    er_diagram.png         ER diagram
    screenshots/           Screenshots of the working screens
  requirements.txt, run.sh, run.bat
```

## 6. Tech stack used
- **Backend:** Python 3, Flask (REST API), token login with OTP
- **Database:** SQLite (PostgreSQL schema also provided)
- **Frontend:** HTML, CSS and plain JavaScript (mobile-first, installable as a PWA)
- **QR scanning:** the browser's built-in `BarcodeDetector` (Chrome / Android) or type the code
- **QR generation:** `qrcodejs` loaded from cdnjs on the admin QR page (needs internet)

## 7. Putting it online (for the live link)
Free options: **Render**, **Railway**, **PythonAnywhere**.

Render example (Web Service from your GitHub repo):
- Build command: `pip install -r requirements.txt gunicorn`
- Start command: `gunicorn --chdir backend -w 1 -b 0.0.0.0:$PORT app:app`
- Environment variables: `RELOOP_SECRET` = any long random text, and `RELOOP_DEMO` = `1` (keeps the fixed demo OTP).

The free tiers reset the SQLite file on restart, which is fine for a demo because the app re-creates the sample data automatically.
For real use, set `RELOOP_DEMO=0` and connect an SMS/email service for OTPs.

### Push to GitHub
```bash
git init
git add .
git commit -m "ReLoop - Innovatrix Nova"
git branch -M main
git remote add origin https://github.com/<your-username>/reloop.git
git push -u origin main
```

## 8. Settings you can change (backend/logic.py)
`BORROW_HOURS` (48), `PENALTY_AFTER_HOURS` (72), `DAILY_POINT_CAP` (30), `TRUSTED_AFTER` (3), `MAX_OPEN_BORROWS` (2) and the `POINTS` table.

## 9. Known limits (honest list)
- OTP is a fixed demo code; no real SMS/email is sent.
- Overdue status is checked when someone opens the app (no background scheduler yet), and reminders are not sent yet.
- Camera scanning needs a browser with `BarcodeDetector` (Chrome on Android/desktop). Other browsers can type the code.
- SQLite is fine for a demo and a single campus; move to PostgreSQL for many colleges.
- Impact numbers depend on the item catalogue values, which are estimates until verified.
