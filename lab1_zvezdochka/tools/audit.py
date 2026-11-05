from datetime import datetime, timezone
from pathlib import Path
import json
import hashlib
import shlex
import subprocess
import time

# Один фиксированный сайт и короткий список: случайно запустить большой скан не получится.
TARGET = "https://www.teeworlds.com"
OUT = Path("/results")
OUT.mkdir(parents=True, exist_ok=True)
lines = []
records = []

def log(text=""):
    print(text, flush=True)
    lines.append(text)
    (OUT / "transcript.txt").write_text("\n".join(lines) + "\n")

def request(label, path, method="GET"):
    time.sleep(1)
    headers = OUT / (label + ".headers.txt")
    body = OUT / (label + ".body.txt")
    cmd = ["curl", "--silent", "--show-error", "--path-as-is", "--max-time", "15",
           "--connect-timeout", "8", "--max-filesize", "262144", "--request", method,
           "--user-agent", "Lab1-Educational-Check/1.0", "--dump-header", str(headers),
           "--output", str(body), "--write-out", "%{http_code}", TARGET + path]
    if method == "TRACE":
        cmd[1:1] = ["--header", "X-Lab-Canary: harmless-lab1-marker"]
    log("$ " + shlex.join(cmd))
    r = subprocess.run(cmd, text=True, capture_output=True)
    status = r.stdout.strip()
    log("status=" + status + " curl_exit=" + str(r.returncode))
    if r.stderr:
        log(r.stderr.strip())
    h = headers.read_text(errors="replace") if headers.exists() else ""
    for line in h.splitlines():
        if line.lower().startswith(("http/", "server:", "location:", "allow:", "content-type:")):
            log(line)
    content = body.read_text(errors="replace") if body.exists() else ""
    record = dict(label=label, path=path, method=method, status=status,
                  curl_exit=r.returncode, bytes=body.stat().st_size if body.exists() else 0,
                  trace_echo="X-Lab-Canary: harmless-lab1-marker".lower() in content.lower())
    records.append(record)
    log("")
    if status in ("429", "503"):
        raise SystemExit("Server asked to slow down or is unavailable; stopping.")
    return record

log("Teeworlds: small external nginx check")
log("UTC: " + datetime.now(timezone.utc).isoformat())
log("Target: " + TARGET)
log("No redirects followed; no passwords, writes or recursive scan. Sequential curl, ffuf 1 req/s.")
log("\n[0] Baseline and nonexistent page")
request("baseline", "/")
request("missing", "/lab1-not-a-real-page-20261104")
log("[1] Path traversal / alias boundary, public robots.txt only")
request("robots-control", "/robots.txt")
for label, path in [
    ("traversal-literal", "/images/../robots.txt"),
    ("traversal-encoded", "/images/%2e%2e/robots.txt"),
    ("alias-boundary", "/images../robots.txt"),
    ("alias-downloads", "/downloads../robots.txt"),
]:
    request(label, path)
log("[2] Small page enumeration with ffuf")
cmd = ["ffuf", "-u", TARGET + "/FUZZ", "-w", "tools/paths.txt", "-t", "1", "-rate", "1",
       "-timeout", "10", "-maxtime", "60", "-mc", "all", "-noninteractive", "-s",
       "-H", "User-Agent: Lab1-Educational-Check/1.0", "-of", "json", "-o", str(OUT / "ffuf.json")]
log("$ " + shlex.join(cmd))
r = subprocess.run(cmd, capture_output=True, text=True)
(OUT / "ffuf-console.txt").write_text(r.stdout + r.stderr)
ffuf_exit = r.returncode
log("ffuf_exit=" + str(ffuf_exit))
if (OUT / "ffuf.json").exists():
    data = json.loads((OUT / "ffuf.json").read_text())
    log("STATUS  BYTES  PATH")
    for row in data.get("results", []):
        log(f"{row['status']:<7} {row['length']:<6} {row['input']['FUZZ']}")
log("\n[3] TRACE method, harmless header without cookies or credentials")
r = request("trace", "/", "TRACE")
log("TRACE echoed canary: " + str(r["trace_echo"]))
log("\nFinished. Status codes alone do not prove a vulnerability; interpretation is in README.md.")
(OUT / "requests.json").write_text(json.dumps(records, indent=2))
# Сравнение с обычным robots.txt помогает не принять нормализацию за взлом.
hashes = []
for name in ("robots-control", "traversal-literal", "traversal-encoded"):
    digest = hashlib.sha256((OUT / (name + ".body.txt")).read_bytes()).hexdigest()
    hashes.append(name + " " + digest)
(OUT / "body-hashes.txt").write_text("\n".join(hashes) + "\n")
if any(r["curl_exit"] for r in records) or ffuf_exit:
    raise SystemExit("Some curl requests failed: inspect the transcript.")
