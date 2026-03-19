# BizMonitor API v2 — Production Ready

FastAPI + PostgreSQL + JWT Auth + Role-Based Access Control

---

## Role Permissions

| Action                        | Employee | Manager | Admin |
|-------------------------------|----------|---------|-------|
| Log sales / expenses          | ✅       | ✅      | ✅    |
| Update stock                  | ✅       | ✅      | ✅    |
| View own entries only         | ✅       | —       | —     |
| View ALL entries + dashboards | ❌       | ✅      | ✅    |
| Delete entries                | ❌       | ✅      | ✅    |
| Add inventory products        | ❌       | ✅      | ✅    |
| View stock audit logs         | ❌       | ✅      | ✅    |
| Manage users                  | ❌       | ❌      | ✅    |
| Delete products               | ❌       | ❌      | ✅    |

---

## Local Setup

```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate        # Mac/Linux
venv\Scripts\activate           # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy and fill in environment variables
cp .env.example .env
# Edit .env — set DATABASE_URL, SECRET_KEY, etc.

# 4. Start local PostgreSQL (or use SQLite for testing)
# For SQLite testing, change DATABASE_URL in .env to:
# DATABASE_URL=sqlite:///./bizmonitor.db
# and add connect_args={"check_same_thread": False} in database.py

# 5. Create first admin account (only works on empty database)
# Option A — via /setup endpoint (see API docs)
# Option B — run seed script
python seed.py

# 6. Start server
uvicorn main:app --reload
```

Docs: http://localhost:8000/docs

---

## Deploy to Render (Free)

### Step 1 — Push to GitHub
```bash
git init
git add .
git commit -m "BizMonitor API v2"
git remote add origin https://github.com/yourname/bizmonitor-api.git
git push -u origin main
```

### Step 2 — Deploy on Render
1. Go to https://render.com → New → Blueprint
2. Connect your GitHub repo
3. Render reads `render.yaml` automatically
4. This creates:
   - A **Web Service** running FastAPI
   - A **PostgreSQL database** (free 90-day trial, then ~$7/mo)
   - Auto-injects `DATABASE_URL` and generates `SECRET_KEY`

### Step 3 — First run setup
After deploy, visit:
```
https://your-api.onrender.com/setup
```
POST with:
```json
{
  "email": "admin@yourcompany.com",
  "full_name": "Your Name",
  "password": "StrongPassword123!",
  "role": "admin"
}
```
This creates your admin account. The `/setup` endpoint is permanently disabled after first use.

### Step 4 — Update ALLOWED_ORIGINS
In Render dashboard → Environment → set:
```
ALLOWED_ORIGINS=https://your-frontend-url.com
```

---

## Authentication Flow

```
POST /auth/login
  body: { username: "email@example.com", password: "..." }
  returns: { access_token: "...", token_type: "bearer", user: {...} }

All other requests:
  Header: Authorization: Bearer <access_token>
```

---

## Key API Endpoints

| Method | Endpoint | Role Required | Description |
|--------|----------|--------------|-------------|
| POST | /auth/login | Public | Get JWT token |
| GET | /auth/me | Any | Current user info |
| POST | /setup | Public (once) | Create first admin |
| GET | /users | Admin | List all users |
| POST | /users | Admin | Create user |
| GET | /sales | Employee+ | List sales |
| POST | /sales | Employee+ | Log a sale |
| GET | /expenses | Employee+ | List expenses |
| POST | /expenses | Employee+ | Record expense |
| GET | /inventory | Employee+ | List inventory |
| PATCH | /inventory/{sku}/stock | Employee+ | Update stock |
| GET | /inventory/{sku}/movements | Manager+ | Audit log |
| GET | /summary | Manager+ | KPI summary |

Full interactive docs at: `https://your-api.onrender.com/docs`

---

## Connect the Frontend

In `bizmonitor-frontend.jsx`, update the API constant and add auth:

```js
const API = "https://your-api.onrender.com";

// On login, store the token:
localStorage.setItem("token", data.access_token);

// On every API call, send the token:
headers: { "Authorization": `Bearer ${localStorage.getItem("token")}` }
```

---

## File Structure

```
bizmonitor-v2/
├── main.py          # All API routes with role guards
├── auth.py          # JWT creation, password hashing, role dependencies  
├── config.py        # Environment variable management
├── database.py      # PostgreSQL connection pool
├── models.py        # SQLAlchemy tables (users, sales, expenses, inventory, audit log)
├── schemas.py       # Pydantic validation for all requests/responses
├── crud.py          # All database operations
├── seed.py          # Demo data + test user accounts
├── render.yaml      # One-click Render deployment
├── .env.example     # Environment variable template
├── .gitignore       # Keeps secrets out of git
└── requirements.txt
```

---

## Upgrading Later

**Add email verification:** integrate SendGrid or Resend for email confirmation on signup.
**Add refresh tokens:** extend `auth.py` with a `/auth/refresh` endpoint.
**Add rate limiting:** use `slowapi` library to prevent brute-force attacks.
**Move to paid PostgreSQL:** just update `DATABASE_URL` — no code changes needed.
