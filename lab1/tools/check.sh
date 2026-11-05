#!/bin/sh
set -eu
set -o pipefail

CURL='curl'
request() {
    method=$1 host=$2 path=$3 expected=$4
    shift 4
    scheme=https port=443
    case "$method" in HEAD) scheme=http; port=80 ;; esac
    if [ "$method" = HEAD ]; then
        printf '+ curl -I %s://%s%s\n' "$scheme" "$host" "$path"
    else
        printf '+ curl -X %s %s://%s%s\n' "$method" "$scheme" "$host" "$path"
    fi
    # --connect-to меняет только адрес соединения, Host и TLS SNI остаются настоящими.
    if [ "$method" = HEAD ]; then
        code=$($CURL --noproxy '*' -sS -I --connect-timeout 2 --max-time 8 \
            --connect-to "$host:$port:nginx:$port" -D "$tmp/headers" \
            -o "$tmp/body" -w '%{http_code}' "$scheme://$host$path" "$@")
    else
        code=$($CURL --noproxy '*' -sS --cacert /tls/local.crt --connect-timeout 2 --max-time 8 \
            --connect-to "$host:$port:nginx:$port" -X "$method" -D "$tmp/headers" \
            -o "$tmp/body" -w '%{http_code}' "$scheme://$host$path" "$@")
    fi
    backend=$(awk 'tolower($1)=="x-backend-id:" {gsub("\r", "", $2); print $2}' "$tmp/headers")
    printf '  HTTP %s; X-Backend-Id=%s\n' "$code" "${backend:--}"
    [ "$code" = "$expected" ] || { printf 'FAIL: expected HTTP %s\n' "$expected"; return 1; }
}
contains() { grep -Fq "$1" "$tmp/body" || { echo "FAIL: body does not contain $1"; return 1; }; }
restore() {
    if [ "${stopped:-0}" = 1 ]; then
        echo 'Restoring backend1 after interrupted check...'
        docker start "$backend_container" >/dev/null
    fi
    rm -rf "$tmp"
}
main() {
    tmp=$(mktemp -d)
    stopped=0
    trap restore EXIT
    trap 'exit 130' INT TERM
    printf 'LAB1 CHECKS | %s\n' "$(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    echo 'HTTPS requests use --cacert /tls/local.crt and --connect-to (see check.sh).'
    echo 'Displayed curl commands omit these repeated options and form/auth arguments.'

    printf '\n%s\n' '[1] HTTP -> HTTPS'
    request HEAD localhost / 301
    grep -qi '^Location: https://localhost/' "$tmp/headers"
    echo '  Location: https://localhost/'

    printf '\n%s\n' '[2] Frontend is served directly by nginx'
    request GET localhost / 200
    contains 'Полка с играми'
    [ -z "$backend" ]
    grep -qi '^X-Proxy: nginx' "$tmp/headers"

    printf '\n%s\n' '[3] Round robin: both Java instances answer'
    : > "$tmp/ids"
    for n in 1 2 3 4 5 6; do
        request GET localhost /api/games 200
        printf '%s\n' "$backend" >> "$tmp/ids"
        sleep 0.2
    done
    grep -qx backend-1 "$tmp/ids"
    grep -qx backend-2 "$tmp/ids"

    printf '\n%s\n' '[4] Write to PostgreSQL through the proxy'
    title="Lab1 check $(date +%s)"
    request POST localhost /api/games 201 \
        --data-urlencode "title=$title" --data-urlencode platform=PC --data-urlencode status=planned
    cat "$tmp/body"; printf '\n'
    sleep 0.3
    request GET localhost /api/games 200
    contains "$title"

    printf '\n%s\n' '[5] alias /docs/'
    request GET localhost /docs/ 200
    contains DOCS_ALIAS

    printf '\n%s\n' '[6] Basic Auth: missing, wrong and correct password'
    request GET localhost /admin 401
    grep -qi '^WWW-Authenticate: Basic' "$tmp/headers"
    request GET localhost /admin/ 401
    request GET localhost /admin 401 -u admin:wrong_password
    request GET localhost /admin 200 -u "admin:$ADMIN_PASSWORD"
    contains ADMIN_OK

    printf '\n%s\n' '[7] Virtual hosts do not leak each other'
    request GET status.localhost / 200
    contains STATUS_PROJECT
    if grep -Fq 'Полка с играми' "$tmp/body"; then echo 'FAIL: wrong site'; return 1; fi
    request GET status.localhost /api/games 404
    contains STATUS_404
    [ -z "$backend" ]
    request GET status.localhost /admin 404
    request HEAD foreign.localhost / 404
    request GET localhost / 404 -H 'Host: foreign.localhost'
    if grep -Fq 'Полка с играми' "$tmp/body"; then echo 'FAIL: unknown Host leaked frontend'; return 1; fi

    printf '\n%s\n' '[8] Unknown TLS SNI is rejected'
    if $CURL --noproxy '*' -ksS --max-time 5 \
        --connect-to foreign.localhost:443:nginx:443 https://foreign.localhost/ >"$tmp/foreign" 2>"$tmp/tls-error"; then
        echo 'FAIL: unknown TLS name was accepted'; return 1
    fi
    echo '  TLS handshake rejected for foreign.localhost (even with -k).'

    printf '\n%s\n' '[9] Custom 404'
    request GET localhost /this-page-does-not-exist 404
    contains GAME_SHELF_404

    printf '\n%s\n' '[10] Rate limit: 60 parallel API requests'
    sleep 2
    mkdir "$tmp/flood"
    for n in $(seq 1 60); do
        ($CURL --noproxy '*' -sS --cacert /tls/local.crt --max-time 10 \
            --connect-to localhost:443:nginx:443 -o /dev/null \
            -w '%{http_code}\n' https://localhost/api/games > "$tmp/flood/$n") &
    done
    wait
    cat "$tmp"/flood/* > "$tmp/codes"
    sort "$tmp/codes" | uniq -c
    grep -qx 429 "$tmp/codes"
    if grep -Ev '^(200|429)$' "$tmp/codes"; then echo 'FAIL: unexpected flood result'; return 1; fi
    sleep 2

    printf '\n%s\n' '[11] MAIN CHECK: stop backend1, frontend and API must stay alive'
    backend_container=$(docker ps -q --filter label=com.docker.compose.project=gameshelf-lab1 \
        --filter label=com.docker.compose.service=backend1)
    [ -n "$backend_container" ]
    stopped=1
    printf '+ docker stop --time 3 %s\n' "$backend_container"
    docker stop --time 3 "$backend_container" >/dev/null
    echo '  backend1 is stopped. No nginx reload is performed.'
    request GET localhost / 200
    for n in 1 2 3 4 5 6; do
        request GET localhost /api/games 200
        [ "$backend" = backend-2 ]
        contains "$title"
        sleep 0.2
    done
    echo '  PASS: saved data is still available; all six responses came from backend-2.'

    printf '\n%s\n' '[12] Restore backend1 and verify that both instances return'
    docker start "$backend_container" >/dev/null
    stopped=0
    ready=0
    for n in $(seq 1 40); do
        if [ "$(docker inspect -f '{{.State.Health.Status}}' "$backend_container")" = healthy ]; then ready=1; break; fi
        sleep 1
    done
    [ "$ready" = 1 ]
    # Дадим истечь fail_timeout, после этого nginx снова пробует восстановленный сервер.
    sleep 6
    : > "$tmp/restored"
    for n in 1 2 3 4 5 6; do
        request GET localhost /api/games 200
        printf '%s\n' "$backend" >> "$tmp/restored"
        sleep 0.2
    done
    grep -qx backend-1 "$tmp/restored"
    grep -qx backend-2 "$tmp/restored"
    printf '\n%s\n' 'ALL CHECKS PASSED. Both backends are running again.'
}
mkdir -p /reports
main 2>&1 | tee /reports/check-output.txt
