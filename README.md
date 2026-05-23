# Finance Tracker

A personal finance web app for tracking income, expenses, and investments in **CZK**. Built with Django, PostgreSQL (Supabase), and a dark UI served via WhiteNoise.

**Repository:** [github.com/petkov93/finance-tracker](https://github.com/petkov93/finance-tracker)

---

## Features

### Dashboard
- Overview of **balance**, total income, and total expenses (all time)
- Recent transactions with edit/delete
- Amounts in CZK

### Transactions
- Add **income** or **expense** entries
- Optional category and description
- Categories filtered by type (income vs expense) on the form

### Statistics
- Summary cards (net balance, income, expense counts)
- **Monthly bar chart** with configurable date range
- **Pie charts** for expenses and income by category

### Investments
- Separate view for **invested** vs **profit** amounts (CZK)
- Portfolio value (invested + profit)
- Same list/edit/delete flow as transactions

### Accounts
- Register, log in, log out
- Each user only sees their own data

### Admin
- Django admin at `/admin/` for categories, transactions, and investment entries

---

## Tech stack

| Layer | Technology |
|-------|------------|
| Backend | Django 5.x |
| Database | PostgreSQL (Supabase) or SQLite locally |
| Auth | Django built-in users |
| Static files | WhiteNoise |
| Production server | Gunicorn |
| Deploy | [Render](https://render.com) (`render.yaml`) |

---

## Project structure

```
finance-tracker/
├── config/                 # Django settings, URLs, WSGI
├── financetracker/         # Main app
│   ├── management/commands/
│   │   └── seed_categories.py   # Default categories (empty DB only)
│   ├── migrations/
│   ├── static/financetracker/css/
│   ├── templates/financetracker/
│   ├── models.py           # Category, Transaction, InvestmentEntry
│   ├── views.py
│   ├── forms.py
│   └── urls.py
├── manage.py
├── requirements.txt
├── render.yaml             # Render Blueprint
├── run.ps1                 # Local dev (Windows)
├── run.sh                  # Local dev (Linux/macOS)
├── .env.example            # Environment template (commit this)
└── .env                    # Your secrets (never commit)
```

---

## Local development

### Prerequisites
- Python 3.12+
- A [Supabase](https://supabase.com) project (recommended) or SQLite fallback if `SUPABASE_URL` is unset

### 1. Clone and install

```bash
git clone https://github.com/petkov93/finance-tracker.git
cd finance-tracker
python -m venv .venv
```

**Windows (PowerShell):**
```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Linux / macOS:**
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Environment variables

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

| Variable | Description |
|----------|-------------|
| `SUPABASE_URL` | PostgreSQL connection URI (Supabase → **Session pooler**) |
| `SECRET_KEY` | Django secret key (long random string) |
| `DJANGO_DEBUG` | `true` for local dev |

Optional locally: `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` (defaults work for `localhost`).

**Supabase URI tip:** If your password has special characters, paste the URI as-is; the app URL-encodes it automatically.

### 3. Run the app

**Windows:**
```powershell
.\run.ps1
```

**Linux / macOS:**
```bash
bash run.sh
```

This will:
1. Run database migrations
2. Seed **default categories** only if the category table is empty
3. Collect static files
4. Start the dev server at `http://127.0.0.1:8000`

### 4. Create a user

Open the app → **Sign up**, or use the admin:

```bash
python manage.py createsuperuser
```

Then visit `/admin/`.

---

## Default categories

On first run (empty database), these categories are created automatically:

| Income | Expense |
|--------|---------|
| Salary 💼 | Food 🍽️ |
| Freelance 💻 | Food at Work 🥪 |
| Other Income 💰 | Health 💊, Transport 🚗, Rent 🏠, … |

If **any** category already exists, seeding is skipped — your admin changes are never overwritten on restart.

To seed manually:
```bash
python manage.py seed_categories
```

---

## Database

- **Production / recommended:** PostgreSQL on Supabase (`SUPABASE_URL` in environment)
- **Local fallback:** SQLite (`db.sqlite3`) when `SUPABASE_URL` is not set

Migrations:
```bash
python manage.py migrate
```

---

## Deploy on Render

1. Push this repo to GitHub (already done if you cloned from [petkov93/finance-tracker](https://github.com/petkov93/finance-tracker)).
2. [Render](https://render.com) → **New** → **Blueprint** → connect the repo (uses `render.yaml`).
3. Set these **Environment** variables in the Render dashboard:

| Variable | Example |
|----------|---------|
| `SUPABASE_URL` | `postgresql://...` (session pooler) |
| `SECRET_KEY` | long random string |
| `DJANGO_DEBUG` | `false` |
| `ALLOWED_HOSTS` | `your-app.onrender.com` |
| `CSRF_TRUSTED_ORIGINS` | `https://your-app.onrender.com` |

4. Deploy. Render runs migrate, seed (if empty), collectstatic, and Gunicorn.

Health check: `GET /health/` → `{"status": "ok"}`

---

## Useful commands

```bash
python manage.py migrate
python manage.py seed_categories
python manage.py collectstatic --noinput
python manage.py createsuperuser
python manage.py runserver
python manage.py check --deploy   # production settings check
```

---

## Security notes

- Never commit `.env` — it is in `.gitignore`
- Use a strong `SECRET_KEY` in production
- Registration is open by default; restrict via admin or disable `register` URL if you deploy publicly

---

## License

Private / personal project. Use and modify as you like.
