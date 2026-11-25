from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
import json
import subprocess
import sys
import threading
import time
import urllib.parse
sys.path.insert(0, str(Path.cwd().parent / "lab2/tools"))
from common import *

mode = sys.argv[1] if len(sys.argv) > 1 else "recovery"
assert mode in ("recovery", "limits")
log = Transcript(mode + ".txt")
log("LAB2 STAR / " + mode.upper() + " | " + datetime.now(timezone.utc).isoformat())
wait_api()

def recovery():
    log("[1] All services before failure")
    log(compose("ps").stdout)
    db = container("db")
    backend = container("backend")
    before = inspect(db)["RestartCount"]
    log("DB RestartCount before crash=" + str(before))
    status, body = http(data=urllib.parse.urlencode(dict(title="DB recovery " + str(int(time.time())), platform="PC", status="planned")).encode())
    assert status == 201
    game_id = json.loads(body)["id"]
    log("Saved game id=" + str(game_id))
    log("[2] Crash PostgreSQL process inside its container")
    log("$ docker compose exec -T --user postgres db pg_ctl -D /var/lib/postgresql/data stop -m immediate")
    started = time.monotonic()
    result = run(["docker", "exec", "--user", "postgres", db, "pg_ctl", "-D", "/var/lib/postgresql/data", "stop", "-m", "immediate"], check=False)
    log("exec exit=" + str(result.returncode))
    for _ in range(60):
        state = inspect(db)
        code, _body = http()
        log(f"t={time.monotonic()-started:.1f}s HTTP={code} DB={state['State']['Status']} restarts={state['RestartCount']}")
        if state["RestartCount"] > before and code == 200: break
        time.sleep(1)
    assert inspect(db)["RestartCount"] > before
    log("DB RestartCount after crash=" + str(inspect(db)["RestartCount"]))
    assert container("db") == db
    assert container("backend") == backend
    assert any(row["id"] == game_id for row in json.loads(wait_api()))
    log("[3] curl after automatic restart")
    response = run(["curl", "-sS", "-o", "/tmp/recovered.json", "-w", "%{http_code}", "http://frontend/api/games"]).stdout
    log("$ curl http://frontend/api/games -> " + response)
    assert response == "200"
    log("Same database container, higher RestartCount; backend was not restarted.")
    log("Saved game id=" + str(game_id) + " is still in the database.")
    log(compose("ps").stdout)
    (REPORT / "database-recovery.log").write_text(compose("logs", "--no-color", "--tail", "65", "db", "backend").stdout)
    log("PASS: automatic recovery without docker compose up/start.")

def cpu_stat():
    text = run(["docker", "exec", container("backend"), "cat", "/sys/fs/cgroup/cpu.stat"], check=False).stdout
    return dict((k, int(v)) for k, v in (row.split() for row in text.splitlines()) if len([k, v]) == 2)

def load(label, seconds=20, workers=16):
    log("Load: " + label + "; GET /api/games; workers=" + str(workers) + "; duration=" + str(seconds) + "s")
    stop = threading.Event()
    stats = []
    ids = [container(s) for s in ("frontend", "backend", "db")]
    def sample():
        while not stop.is_set():
            result = run(["docker", "stats", "--no-stream", "--format", "{{.Name}} CPU={{.CPUPerc}} MEM={{.MemUsage}}", *ids], check=False)
            stats.append(datetime.now(timezone.utc).isoformat() + "\n" + result.stdout)
            stop.wait(1)
    monitor = threading.Thread(target=sample)
    monitor.start()
    deadline = time.monotonic() + seconds
    started = time.monotonic()
    def worker():
        result = []
        while time.monotonic() < deadline:
            tick = time.monotonic()
            status, _ = http()
            result.append((status, time.monotonic() - tick))
            time.sleep(0.05)
        return result
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            rows = [row for group in pool.map(lambda _: worker(), range(workers)) for row in group]
    finally:
        stop.set(); monitor.join()
    counts = dict(Counter(str(row[0]) for row in rows))
    latency = sorted(row[1] for row in rows)
    summary = dict(requests=len(rows), statuses=counts, elapsed=round(time.monotonic()-started,2),
                   p95_seconds=round(latency[min(len(latency)-1,int(len(latency)*.95))],3))
    (REPORT / (label + "-stats.txt")).write_text("\n".join(stats))
    (REPORT / (label + "-load.json")).write_text(json.dumps(summary, indent=2))
    log(json.dumps(summary))
    if stats: log("Last docker stats sample:\n" + stats[-1])
    return summary

def limits():
    # Временные игры добавляем только в отдельную базу звёздочки и в конце удаляем.
    prefix = "LAB2_LOAD_"
    sql("DELETE FROM games WHERE starts_with(title, 'LAB2_LOAD_')")
    sql("INSERT INTO games(title,platform,status) SELECT 'LAB2_LOAD_' || n || repeat('x',95), repeat('P',55), 'planned' FROM generate_series(1,1500) n")
    summaries = {}
    try:
        log("[1] CPU too tight: 0.10 CPU, memory stays 384 MiB")
        cid = container("backend")
        run(["docker", "update", "--cpus", "0.10", cid])
        before = cpu_stat()
        summaries["cpu-tight"] = load("cpu-tight", seconds=20)
        after = cpu_stat()
        (REPORT / "cpu-throttling.json").write_text(json.dumps(dict(before=before,after=after), indent=2))
        delta = after["nr_throttled"] - before["nr_throttled"]
        log("cpu.stat nr_throttled delta=" + str(delta))
        log("cpu.stat throttled_usec delta=" + str(after["throttled_usec"] - before["throttled_usec"]))
        assert delta > 0, "No CPU throttling observed"
        log("[2] Memory too tight: compose.tight.yaml, 72 MiB, Java Xmx256m")
        log("$ docker compose -f compose.yaml -f compose.tight.yaml up -d --no-deps backend")
        compose("-f", "compose.yaml", "-f", "compose.tight.yaml", "up", "-d", "--no-deps", "backend")
        cid = container("backend")
        epoch = str(int(time.time()))
        # Не требуем healthy до нагрузки: лимит специально может ломать запуск.
        time.sleep(3)
        summaries["memory-tight"] = load("memory-tight", seconds=25)
        end = str(int(time.time()) + 1)
        events = run(["docker", "events", "--since", epoch, "--until", end,
                      "--filter", "container=" + cid, "--filter", "event=oom", "--format", "{{json .}}"])
        (REPORT / "oom-events.jsonl").write_text(events.stdout)
        state = inspect(cid)
        (REPORT / "tight-container.json").write_text(json.dumps(dict(State=state["State"], RestartCount=state["RestartCount"], HostConfig={k:state["HostConfig"][k] for k in ("Memory", "MemorySwap", "NanoCpus")}),indent=2))
        log("OOM events: " + str(len(events.stdout.splitlines())) + "; restarts=" + str(state["RestartCount"]))
        assert events.stdout.strip(), "OOM not observed; tune the experimental profile"
    finally:
        log("[3] Restore normal limits even if an experimental check fails")
        log("$ docker compose up -d --no-deps --force-recreate backend")
        compose("up", "-d", "--no-deps", "--force-recreate", "backend")
        wait_api()
    try:
        summaries["stable"] = load("stable", seconds=25)
        assert set(summaries["stable"]["statuses"]) == {"200"}
        state = inspect(container("backend"))
        assert state["RestartCount"] == 0
        log("Stable backend limits: 1.00 CPU, 384 MiB; restarts=0")
        log("[4] Actual limits for all three services")
        for service in ("frontend", "backend", "db"):
            h = inspect(container(service))["HostConfig"]
            log(service + ": CPU=" + str(h["NanoCpus"]/1e9) + "; memory=" + str(h["Memory"]//1024//1024) + " MiB")
        (REPORT / "load-summary.json").write_text(json.dumps(summaries, indent=2))
        log("PASS: CPU throttling and OOM observed; stable profile returned only HTTP 200.")
    finally:
        sql("DELETE FROM games WHERE starts_with(title, 'LAB2_LOAD_')")

if mode == "recovery": recovery()
else:
    try:
        limits()
    finally:
        sql("DELETE FROM games WHERE starts_with(title, 'LAB2_LOAD_')")
