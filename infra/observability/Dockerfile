# Alloy's base image need not contain a shell or HTTP client. Supply one static
# healthcheck tool without downloading packages at container startup.
FROM busybox:1.37.0-musl AS healthcheck

FROM grafana/alloy:v1.8.3 AS alloy
COPY --from=healthcheck /bin/busybox /busybox/wget
