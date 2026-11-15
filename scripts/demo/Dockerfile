FROM docker:27.3.1-cli AS docker
FROM grafana/k6:0.55.0 AS k6
FROM python:3.12.8-slim-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl jq postgresql-client ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir requests==2.32.3 awscli==1.35.12
COPY --from=docker /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose
COPY --from=k6 /usr/bin/k6 /usr/local/bin/k6
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /tmp
COPY entrypoint.sh /usr/local/bin/demo-entrypoint
ENTRYPOINT ["/usr/local/bin/demo-entrypoint"]
