from pathlib import Path
import json
import subprocess
import time
import urllib.request
import urllib.error
from http.client import HTTPException
ROOT = Path.cwd()
PROJECT = "gameshelf-lab2-star" if ROOT.name == "lab2_zvezdochka" else "gameshelf-lab2"
REPORT = ROOT / "docs/checks"
REPORT.mkdir(parents=True, exist_ok=True)

class Transcript:
    def __init__(self, filename):
        self.path = REPORT / filename
        self.path.write_text("")
    def __call__(self, line=""):
        print(line, flush=True)
        with self.path.open("a") as f: f.write(str(line) + "\n")

def run(args, check=True):
    return subprocess.run(args, text=True, capture_output=True, check=check)

def compose(*args):
    return run(["docker", "compose", *args])

def inspect(cid):
    return json.loads(run(["docker", "inspect", cid]).stdout)[0]

def container(service):
    cid = compose("ps", "-a", "-q", service).stdout.strip()
    assert cid, "Container not found: " + service
    assert inspect(cid)["Config"]["Labels"]["com.docker.compose.project"] == PROJECT
    return cid

def http(path="/api/games", data=None):
    request = urllib.request.Request("http://frontend" + path, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()
    except (OSError, TimeoutError, HTTPException): return 0, "connection failed"

def wait_api(timeout=100):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, body = http()
        if status == 200: return body
        time.sleep(1)
    raise RuntimeError("API did not recover within " + str(timeout) + " seconds")

def sql(statement):
    return compose("exec", "-T", "db", "psql", "-U", "postgres", "-d", "games", "-Atc", statement).stdout.strip()
