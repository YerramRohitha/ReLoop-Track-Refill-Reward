# ReLoop API Documentation

Base URL (local): `http://127.0.0.1:5000/api`
All requests and responses are JSON (except the CSV report).
Protected endpoints need the header `Authorization: Bearer <token>` (token comes from `/auth/otp/verify`, valid 7 days).

Common errors: `400` bad input, `401` not logged in, `403` wrong role, `404` not found, `409` rule conflict (for example cup already in use), `429` too many scans.
Error body: `{"error": "message"}`

## 1. Authentication

### POST /auth/otp/request
Request an OTP. New users must also send `name` (department and hostel optional) and are registered as students.
```json
{"identifier": "student1"}
```
Response `200`: `{"message": "OTP sent", "demo_otp": "123456"}` (`demo_otp` only in demo mode).
Unknown identifier without a name: `404 {"error": "new_user"}`.

### POST /auth/otp/verify
```json
{"identifier": "student1", "otp": "123456"}
```
Response `200`: `{"token": "...", "user": {"user_id": 4, "name": "...", "role": "student", ...}}`

### GET /me   (all roles)
Profile, points, streak, cups currently borrowed, pending requests, points earned today and the daily cap.

### GET /outlets   (all roles)
List of outlets of the user's college.

## 2. Student scanning  (roles: student, staff, guest)

### POST /scan/borrow
```json
{"container_code": "CUP-010"}
```
Creates a request. Trusted users are approved immediately (`status: "open"`, with `due_at`); others get `status: "pending"` until the vendor approves.
Errors: `404` unknown code, `409` container dirty / in use / damaged, user already has 2 cups out or an overdue cup, `429` more than 8 scans in an hour.

### POST /scan/refill
```json
{"outlet_id": 4, "action": "refill"}
```
`action` is one of `refill`, `byo_cup`, `byo_bag`, `no_lid`. Response has `status` (`closed` or `pending`), `points`, `plastic_g`, `co2_g`.

### POST /scan/return
```json
{"container_code": "CUP-010", "outlet_id": 2}
```
`outlet_id` is optional (defaults to the cup's own outlet). Only the borrower can return the cup.
Response: `{"status": "closed", "points": 10, "plastic_g": 3.0, "co2_g": 16.0, "late": false}`.
Points: +10 on time (+2 if returned at another outlet), 0 if late, -5 if returned after 72 hours. The daily cap (30) applies to positive points.

## 3. Student data

| Method | Endpoint | Description |
|---|---|---|
| GET | /transactions/me?limit=20 | Own history |
| GET | /impact/me | Items, plastic (g), CO2e (g), last 7 days, by action, points, streak |
| GET | /leaderboard?type=department\|hostel\|user | Top 10 by items avoided |
| GET | /rewards | Active rewards |
| POST | /rewards/{id}/redeem | Spend points, returns `voucher_code` (409 if not enough points or out of stock) |
| GET | /redemptions/me | Own vouchers |

## 4. Vendor  (roles: vendor, admin)

| Method | Endpoint | Description |
|---|---|---|
| GET | /vendor/pending | Requests waiting for approval at the vendor's outlets |
| POST | /vendor/approvals/{txn_id} | Body `{"decision": "approve"}` or `"reject"` |
| POST | /vendor/manual | Log an action by roll number: `{"identifier": "student12", "action": "refill"}` |
| GET | /vendor/containers | Cups and bottles with wash status |
| POST | /vendor/containers/wash | `{"all": true}` or `{"codes": ["CUP-003"]}` marks dirty containers as ready |
| GET | /vendor/stats | Saved today, pending, overdue, containers by status |

## 5. Admin  (role: admin)

| Method | Endpoint | Description |
|---|---|---|
| GET | /admin/dashboard | Totals, 14-day chart, by outlet, by department, active users, return rate, overdue |
| GET | /admin/flags | Users with 6 or more scans in the last hour |
| GET / POST | /admin/outlets | List / create outlet `{"name","type","location","vendor_identifier"}` |
| POST | /admin/containers | `{"outlet_id": 1, "type": "cup", "count": 10}` creates containers with new codes |
| GET | /admin/qr-list | Values for QR codes: `RELOOP:<code>` and `RELOOP:OUTLET:<id>` |
| GET / PUT | /admin/item-types[/{id}] | View / edit plastic and emission values |
| POST | /admin/rewards | `{"title","points_cost","stock"}` |
| GET | /admin/report.csv | All counted actions as CSV |

## 6. Example with curl
```bash
# login
curl -s -X POST localhost:5000/api/auth/otp/request -H "Content-Type: application/json" -d '{"identifier":"student1"}'
TOKEN=$(curl -s -X POST localhost:5000/api/auth/otp/verify -H "Content-Type: application/json" \
        -d '{"identifier":"student1","otp":"123456"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")

# my impact
curl -s localhost:5000/api/impact/me -H "Authorization: Bearer $TOKEN"

# refill a bottle
curl -s -X POST localhost:5000/api/scan/refill -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" -d '{"outlet_id":4,"action":"refill"}'
```

## 7. QR code contents
- Cup / bottle: `RELOOP:CUP-001`
- Outlet counter: `RELOOP:OUTLET:1`
The Scan screen reads these with the camera, or the code can be typed.
