from datetime import datetime, timezone
import json
import time
import urllib.parse
from common import *
log = Transcript("check-output.txt")
log("LAB2 CHECKS | " + datetime.now(timezone.utc).isoformat())
log(compose("ps").stdout)
log("[1] Non-root user")
user = compose("exec", "-T", "backend", "whoami").stdout.strip()
log("$ docker compose exec -T backend whoami\n" + user)
assert user == "shelf"
log("[2] Save a game and read it through nginx")
name = "Hollow Knight lab2 " + str(int(time.time()))
status, body = http(data=urllib.parse.urlencode(dict(title=name, platform="PC", status="planned")).encode())
assert status == 201, (status, body)
game_id = json.loads(body)["id"]
log("POST /api/games -> 201; id=" + str(game_id))
assert any(row["id"] == game_id for row in json.loads(wait_api()))
log("[3] Remove and recreate database container, keep named volume")
old = container("db")
log("$ docker rm -f " + old[:12])
run(["docker", "rm", "-f", old])
log("$ docker compose up -d db")
log(compose("up", "-d", "db").stderr.strip())
new = container("db")
assert old != new
assert any(row["id"] == game_id for row in json.loads(wait_api()))
log("Old container: " + old[:12] + "; new: " + new[:12])
log("GET /api/games -> 200; SAME id=" + str(game_id) + " survived")
log("Volume: " + next(m["Name"] for m in inspect(new)["Mounts"] if m["Type"] == "volume"))
log("[4] Frontend cannot connect directly to PostgreSQL")
ip = inspect(new)["NetworkSettings"]["Networks"][PROJECT + "_data"]["IPAddress"]
for host in ("db", ip):
    log("$ docker compose exec -T frontend nc -z -w 2 " + host + " 5432")
    result = run(["docker", "compose", "exec", "-T", "frontend", "nc", "-z", "-w", "2", host, "5432"], check=False)
    log("exit=" + str(result.returncode) + "; " + (result.stderr.strip() or "connection blocked"))
    assert result.returncode != 0
assert http()[0] == 200
log("Frontend -> backend -> PostgreSQL: HTTP 200")
log("\nALL CHECKS PASSED. Database and games are still present.")
