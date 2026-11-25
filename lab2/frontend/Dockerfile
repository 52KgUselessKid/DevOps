FROM nginx:1.28-alpine@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236
# netcat нужен только для наглядной проверки сетевой изоляции в этой лабе.
RUN apk add --no-cache netcat-openbsd
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY web /usr/share/nginx/html
HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=6 CMD wget -q -O /dev/null http://127.0.0.1/health || exit 1
