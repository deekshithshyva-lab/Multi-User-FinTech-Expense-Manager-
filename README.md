# Multi-User FinTech Expense Manager

Flask + MySQL + pandas. Users upload bank CSV statements; transactions are parsed, auto-categorised by rules, and shown on a Chart.js dashboard with budget tracking.

## Project structure

```
expense_manager/
├── run.py                      # entrypoint  (flask --app run ...)
├── config.py                   # dev / testing / production settings
├── requirements.txt, .env.example, docker-compose.yml (MySQL 8)
├── app/
│   ├── __init__.py             # create_app() application factory
│   ├── extensions.py           # db, migrate, login_manager, csrf
│   ├── cli.py                  # flask init-db | parse-csv
│   ├── models/                 # DATABASE MODELS
│   │   ├── user.py             #   User (hashed password, Flask-Login)
│   │   ├── category.py         #   Category, CategoryRule (+ enums)
│   │   ├── transaction.py      #   Transaction (signed amount, dedupe fingerprint)
│   │   ├── budget.py           #   Budget (monthly limit per category)
│   │   └── import_batch.py     #   ImportBatch (upload history / undo)
│   ├── services/               # CSV PROCESSORS & BUSINESS LOGIC (no Flask imports)
│   │   ├── csv_parser.py       #   pandas bank-CSV parser            [done]
│   │   ├── seeding.py          #   default categories + starter rules [done]
│   │   ├── categorizer.py      #   rule engine                        [next]
│   │   ├── importer.py         #   parse -> categorise -> bulk insert [next]
│   │   └── analytics.py        #   monthly trend / category / budget queries [next]
│   ├── blueprints/             # BACKEND ROUTES                        [next]
│   │   ├── auth.py             #   register / login / logout
│   │   ├── uploads.py          #   CSV upload + import history
│   │   ├── transactions.py     #   list, edit category, delete
│   │   ├── budgets.py, rules.py
│   │   └── dashboard.py        #   page + JSON endpoints for charts
│   ├── templates/              # FRONTEND: Jinja + Tailwind + Chart.js [next]
│   └── static/
├── sample_data/                # two differently formatted sample statements
└── tests/                      # parser tests (14) + model tests
```

## Setup

```bash
# 1. Python env  (3.11+)
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # then set SECRET_KEY

# 2. MySQL: either Docker ...
docker compose up -d
# ... or your own MySQL 8 server:
#   CREATE DATABASE expense_manager CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
#   CREATE USER 'expense'@'localhost' IDENTIFIED BY 'expense';
#   GRANT ALL PRIVILEGES ON expense_manager.* TO 'expense'@'localhost';
# (adjust DATABASE_URL in .env to match)

# 3. Create tables
flask --app run init-db
#   or with migrations:  flask --app run db init && flask --app run db migrate -m "initial" && flask --app run db upgrade

# 4. Try the CSV parser right now (no DB needed)
flask --app run parse-csv sample_data/sample_statement.csv
flask --app run parse-csv sample_data/sample_statement_debit_credit.csv

# 5. Tests
pytest
```

## Data model

| Table | Purpose | Notes |
|---|---|---|
| `users` | accounts | scrypt-hashed passwords; every other table is keyed by `user_id` |
| `categories` | per-user categories | `kind` = expense / income / transfer (transfers are excluded from spending charts) |
| `category_rules` | auto-categorisation rules | pattern + match type + `priority` (lower runs first) |
| `transactions` | the ledger | **signed** amount (negative = expense); `fingerprint` unique per user |
| `budgets` | monthly limit per category | one row per (user, category) |
| `import_batches` | upload audit trail | counts, detected columns and date format |

Money is `NUMERIC(12,2)` / `Decimal`, never float.

## CSV parser (`app/services/csv_parser.py`)

`parse_bank_csv(file, dayfirst=None, invert_sign=False, column_map=None)` returns a `ParseResult`:
a DataFrame of valid rows (`row, date, description, amount, fingerprint`), plus `errors`, `warnings`, and what it detected (columns, delimiter, encoding, date format).

Handles: junk lines above the header; `, ; TAB |` delimiters; UTF-8 / BOM / UTF-16 / Windows-1252; a signed Amount column, separate Debit/Credit columns, or a DR/CR type column; amounts like `$1,234.56`, `(45.00)`, `45.00-`, `1.234,56`, `45.00 DR`; dates in DD/MM, MM/DD, ISO, `05 Jan 2026`, with times.

Design choices worth knowing:
- **Bad rows never sink an upload.** They come back with their line number and reason.
- **Idempotent imports.** The fingerprint is a hash of date + amount + description + an occurrence counter, so two identical coffees on one day stay separate, while re-uploading a file creates no duplicates (DB unique constraint on `user_id, fingerprint`).
- **Ambiguous dates** (every day <= 12) are read as MM/DD with a visible warning; pass `dayfirst=True` for DD/MM banks. Any day > 12 in the file resolves it automatically.
- **Credit-card exports** (purchases shown as positive) need `invert_sign=True`; the parser warns when every amount is positive.
- Python's `csv` module tokenises lines (so line numbers in errors are exact and ragged rows can't crash pandas); pandas handles the date and column work.

## Next steps

1. `categorizer.py` + `importer.py` (bulk insert, skip duplicates, create an ImportBatch)
2. Auth blueprint and templates (register / login / logout)
3. Upload page with preview and per-row error report
4. `analytics.py` + dashboard endpoints and templates (Tailwind + Chart.js: monthly trend, category breakdown, budget table)
5. Transactions list with inline category editing, rules and budgets pages
