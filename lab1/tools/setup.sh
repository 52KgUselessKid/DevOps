#!/bin/sh
set -eu
# Ключ создаётся у каждого свой и остаётся в Docker volume, а не в репозитории.
if [ ! -s /tls/local.crt ] || [ ! -s /tls/local.key ] ||
   ! openssl x509 -in /tls/local.crt -noout -checkhost localhost >/dev/null 2>&1 ||
   ! openssl x509 -in /tls/local.crt -noout -checkend 86400 >/dev/null 2>&1; then
  openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
    -keyout /tls/local.key -out /tls/local.crt \
    -subj '/CN=localhost' \
    -addext 'subjectAltName=DNS:localhost,DNS:status.localhost' \
    -addext 'basicConstraints=critical,CA:TRUE' 2>/dev/null
  chmod 600 /tls/local.key
fi
htpasswd -nbm admin "$ADMIN_PASSWORD" > /auth/admin.htpasswd
chmod 644 /auth/admin.htpasswd
printf 'TLS certificate and admin password file are ready.\n'
