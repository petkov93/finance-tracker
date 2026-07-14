# Finance Tracker

A personal finance web app for tracking income, expenses, and investments. Transactions are stored in their **native currency**; the dashboard and statistics show amounts in each user's **default currency** via on-the-fly **display conversion**. Built with Django, PostgreSQL (Supabase), and a dark UI served via WhiteNoise.

**Repository:** [github.com/petkov93/finance-tracker](https://github.com/petkov93/finance-tracker)

---

## Features

### Dashboard
- Overview of **balance**, total income, and total expenses (all time), summed in your default currency
- Recent transactions with edit/delete
- When a transaction's native currency differs from your default, the converted amount is shown prominently with the original as a footnote

### Transactions
- Add **income** or **expense** entries in any [Frankfurter-supported](https://frankfurter.dev) currency
- Currency picker defaults to your profile default on new entries
- Optional category and description
- Categories filtered by type (income vs expense) on the form

### Statistics
- Summary cards (net balance, income, expense counts) after display conversion (historical rates for past dates, latest for today and future)
- **Monthly bar chart** with configurable date range
- **Pie charts** for expenses and income by category — all totals in your default currency

### Investments
- Separate view for **invested** vs **profit** amounts (**CZK only** — no currency picker or conversion)
- Portfolio value (**profit − invested**) — net gain or loss relative to capital put in
- Same list/edit/delete flow as transactions

### Currency converter
- Standalone calculator at `/converter/` using **latest** exchange rates only
- Default pair CZK → EUR; your last-used pair is remembered in the session
- Independent of your profile default currency and transaction display logic

### Accounts
- Register with a required **default currency** (pre-selected from browser locale when it maps confidently to a supported code)
- Change default currency later in **Settings**
- Log in, log out; each user only sees their own data

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
│   ├── models.py           # Category, Transaction, InvestmentEntry, UserProfile
│   ├── services/
│   │   ├── currency.py           # Frankfurter rates, convert, supported currencies
│   │   └── display_conversion.py # Batch display conversion for dashboard/statistics
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

## Multi-currency

### Data model

| Concept | Where it lives | Purpose |
|---------|----------------|---------|
| **Default currency** | `UserProfile.default_currency` (one per user) | Unit of account for dashboard and statistics |
| **Transaction currency** | `Transaction.currency` | Native currency the amount was actually paid or received in |
| **Display conversion** | Computed at read time (not stored) | Converts transaction amounts into the user's default currency for display and aggregation |

Existing users and transactions are migrated automatically: every user gets a profile with default **CZK**, and every existing transaction is backfilled as CZK. Users created via `createsuperuser` receive a lazy profile with CZK default on first login.

### Registration and settings

- **Registration** requires choosing a default currency from the Frankfurter-supported list. Client-side logic reads `navigator.language` and pre-selects the picker when the region maps unambiguously to a supported ISO code; otherwise the picker stays empty until the user chooses.
- **Settings** includes a section to update default currency. Dashboard and statistics re-render in the new currency on the next page load.

### Transaction entry

- Each transaction stores `amount` and `currency` together — the amount is always in that row's native currency.
- The currency picker on add/edit defaults to the user's profile default on new entries.
- Investments are unchanged: amounts remain CZK-only with no currency field.

### Display conversion behavior

Dashboard and statistics do **not** sum raw `amount` values across mixed currencies. Instead, the display-conversion layer batches unique `(from, to, transaction_date)` rate lookups, converts each row, then aggregates.

- **Same currency** as default: one formatted amount, no footnote.
- **Different currency**: primary amount in default currency; secondary footnote shows the original native amount.
- **Degraded mode**: if today's rate cannot be fetched (Frankfurter unavailable and no cache), converted totals are omitted, rows show native amounts, and a warning banner is shown. Past-date rates served from cache continue to work silently.

### Exchange-rate policy

Rates come from the [Frankfurter API](https://frankfurter.dev). The currency service (`financetracker/services/currency.py`) applies:

| Transaction date | Rate used |
|------------------|-----------|
| Past (`< today`) | Historical rate for that date |
| Today | Latest available rate |
| Future (`> today`) | Latest available rate (same as today) |
| Same `from`/`to` pair | `1` — no HTTP call |

**Weekends and holidays:** when Frankfurter has no published rate for the exact date, the service walks back up to seven days to the nearest prior published rate. No rate-date hint is shown in the UI.

**Converter page:** always uses latest rates only (`get_rate` without a date). It does not use transaction-date historical lookups.

### Caching

Django's cache backend stores fetched rates to limit API usage:

| Rate type | Cache key | TTL |
|-----------|-----------|-----|
| Latest / today | `currency_rate_{FROM}_{TO}` | 24 hours |
| Past date | `currency_rate_{FROM}_{TO}_{YYYY-MM-DD}` | ~10 years (effectively immutable) |
| Supported currency list | `currency_supported_currencies` | 24 hours |

Past rates are treated as immutable once cached. There is no database-backed rate table in this version.

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

### Tests

Tests use an in-memory SQLite database (no Supabase required):

```bash
python manage.py test
```

**Windows:** `.\test.ps1`  
**Linux / macOS:** `bash test.sh`

Install dev dependencies first for coverage (see below):

```bash
pip install -r requirements-dev.txt
```

### Coverage

Run tests with coverage measurement and a terminal report:

```bash
coverage run manage.py test
coverage report
```

**Windows:** `.\cover.ps1`  
**Linux / macOS:** `bash cover.sh`

Optional HTML report (open `htmlcov/index.html` in a browser):

```bash
coverage html
```

---

## Security notes

- Never commit `.env` — it is in `.gitignore`
- Use a strong `SECRET_KEY` in production
- Registration is open by default; restrict via admin or disable `register` URL if you deploy publicly

---

## License

MIT — see [LICENSE](LICENSE).
