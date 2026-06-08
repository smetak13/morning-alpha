FROM node:20-bookworm-slim AS frontend-builder

WORKDIR /app

COPY frontend/package*.json ./frontend/
RUN cd frontend && npm ci --no-audit --no-fund

COPY assets ./assets
COPY frontend ./frontend
RUN cd frontend && npm run build


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    API_HOST=0.0.0.0 \
    API_PORT=8000

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini config.yaml database.py neon_auth.py report.py report_scheduler.py server.py sync_stocks.py ./
COPY migrations ./migrations
COPY templates ./templates
COPY assets ./assets
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

EXPOSE 8000

CMD ["python", "server.py"]
