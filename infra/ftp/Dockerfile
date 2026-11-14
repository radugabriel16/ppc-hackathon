FROM python:3.12.8-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir pyftpdlib==2.0.1 \
    && useradd --system --uid 10001 --create-home ftpuser \
    && mkdir /data \
    && chown 10001:10001 /data
COPY infra/ftp/server.py /app/server.py
USER 10001:10001
EXPOSE 2121 30000-30009
CMD ["python", "/app/server.py"]
