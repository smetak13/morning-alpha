# fin-news

MVP CLI for a personalized investment morning report.

The app reads `portfolio.yaml`, `watchlist.yaml`, `config.yaml`, fetches FMP news and market data, ranks news by portfolio/watchlist/thesis relevance, sends compact JSON to OpenAI, renders an HTML email with Jinja2, and can send it through SMTP.

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
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TO`

For Gmail SMTP use port `465` with `SMTP_USE_SSL=true` and an app password. The script also accepts the aliases from the other project: `SMTP_SERVER`, `SMTP_SENDER`, and `SMTP_PWD`.

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

Outputs are written to `out/context.json`, `out/report.json`, and `out/report.html`.

## Cron

Run on a VPS/VM with timezone set explicitly:

```cron
TZ=Europe/Prague
0 8 * * 1-5 cd /path/to/fin-news && . .venv/bin/activate && python report.py --date latest --send-email >> logs/report.log 2>&1
```

The script resolves `latest` to the latest completed regular US trading day using a built-in NYSE holiday calendar.

## Guardrails

The prompt and email template explicitly prohibit direct buy, sell, hold, position sizing, and trading recommendations. The report only flags relevance, thesis impact, and topics for further review.
