FROM python:3.12.8-slim-bookworm AS builder

WORKDIR /build
COPY backend/requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt
COPY backend/pyproject.toml .
COPY backend/app ./app
COPY backend/filegrid_forecast ./filegrid_forecast
RUN /opt/venv/bin/pip install --no-cache-dir --no-deps .

FROM python:3.12.8-slim-bookworm

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app:/app/backend" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --system --uid 10001 --create-home app
COPY --from=builder /opt/venv /opt/venv
COPY backend /app/backend
COPY config /app/config
COPY fixtures /app/fixtures
COPY infra/init/create_bucket.py /app/infra/init/create_bucket.py
COPY infra/storage-db/init.sql /app/infra/storage-db/init.sql
WORKDIR /app/backend
USER 10001:10001

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
