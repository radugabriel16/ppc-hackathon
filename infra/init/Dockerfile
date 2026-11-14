FROM alpine:3.21.0

RUN apk add --no-cache openssl=3.3.7-r2
COPY infra/init/init.sh /usr/local/bin/filegrid-init
ENTRYPOINT ["sh", "/usr/local/bin/filegrid-init"]
