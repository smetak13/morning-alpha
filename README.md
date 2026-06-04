# fin-news

MVP CLI for a personalized investment morning report.

The app reads `portfolio.yaml`, `watchlist.yaml`, `config.yaml`, fetches FMP news and market data, ranks news by portfolio/watchlist/thesis relevance, sends compact JSON to OpenAI, renders an HTML email with Jinja2, and can send it through Resend.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Fill `.env`:

- `FMP_API_KEY`
- `OPENAI_API_KEY`
- `DATABASE_URL` from Neon Console > Connect
- `NEON_AUTH_BASE_URL` from Neon Console after enabling Auth
- `RESEND_API_KEY`, `RESEND_FROM`, `RESEND_TO`

Edit:

- `portfolio.yaml`
- `watchlist.yaml`
- `config.yaml`

## Run

```powershell
python report.py --date latest --send-email
```

Generate files without sending:

```powershell
python report.py --date latest
```

Use deterministic fallback output without OpenAI:

```powershell
python report.py --date latest --skip-openai
```

Outputs are written to `out/context.json`, `out/report.json`, `out/usage.json`, and `out/report.html`. `out/usage.json` includes OpenAI input/output token counts and an estimated per-report cost from the pricing configured in `config.yaml`.

## API Server

The FastAPI server is separate from `report.py` and proxies auth requests to Neon Auth:

```powershell
python server.py
```

Available auth endpoints:

- `POST /register` with `email`, `password`, and optional `name`
- `POST /login` with `email`, `password`, and optional `remember_me`
- `POST /register` or `POST /login` with `provider="google"` and a Google `id_token`
- `POST /register/google/id-token` with a Google `id_token`
- `POST /login/google/id-token` with a Google `id_token`
- `GET /me` to read the current Neon Auth session and local `public.users` row
- `POST /logout`

By default the server listens on port `8000` and runs `alembic upgrade head` on startup. Set `API_RUN_MIGRATIONS_ON_STARTUP=false` to disable automatic migrations. `API_PUBLIC_URL` is sent as the fallback `Origin` header when CLI clients such as curl do not provide one.

On successful register, the server forwards Neon Auth session cookies to the client and creates `public.users.id` from Neon Auth's `user.id` if it does not already exist. Existing local user rows are not updated by register/login; login and `GET /me` only read the local row.

## Cron

Run on a VPS/VM with timezone set explicitly:

```cron
TZ=Europe/Prague
0 8 * * 1-5 cd /path/to/fin-news && . .venv/bin/activate && python report.py --date latest --send-email >> logs/report.log 2>&1
```

The script resolves `latest` to the latest completed regular US trading day using a built-in NYSE holiday calendar.

## Neon

Database access is configured through a standard Postgres connection string:

```powershell
python report.py --check-db
```

Use the pooled Neon connection string for normal app traffic and keep `sslmode=require` in `DATABASE_URL`.

Schema changes are managed with Alembic migrations:

```powershell
python -m alembic revision -m "describe change"
python -m alembic upgrade head
```

Alembic reads the same `DATABASE_URL` from `.env`. New migration files will be created under `migrations/versions/`.

Neon Auth is expected to be enabled in the Neon Console. This project currently has a Python CLI surface, so it only validates the auth environment now:

```powershell
python report.py --check-auth-config
```

For the later web UI, keep email/password enabled in Neon Auth and configure Google OAuth in Neon Console. The auth data will live in Neon's `neon_auth` schema; application tables can be added separately once their shape is decided.

## Guardrails

The prompt and email template explicitly prohibit direct buy, sell, hold, position sizing, and trading recommendations. The report only flags relevance, thesis impact, and topics for further review.
