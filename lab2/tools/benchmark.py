from datetime import datetime, timezone
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import time
from common import Transcript, REPORT, run
log = Transcript("benchmark.txt")
log("LAB2 BUILD CACHE | " + datetime.now(timezone.utc).isoformat())
log(run(["docker", "version", "--format", "Docker server {{.Server.Version}} / {{.Server.Arch}}"]).stdout.strip())
results = {}
with tempfile.TemporaryDirectory(prefix="lab2-cache-") as temp:
    context = Path(temp)
    for name in ("pom.xml", "Dockerfile", "Dockerfile.bad", ".dockerignore"):
        shutil.copyfile(Path("backend") / name, context / name)
    shutil.copytree("backend/src", context / "src")
    source = next((context / "src").rglob("Main.java"))
    original = source.read_text()
    for label, dockerfile in (("bad", "Dockerfile.bad"), ("good", "Dockerfile")):
        source.write_text(original)
        cmd = ["docker", "build", "--progress=plain", "-f", str(context / dockerfile), "-t", "gameshelf-lab2-backend:" + label, str(context)]
        log("\n$ docker build -f backend/" + dockerfile + " -t gameshelf-lab2-backend:" + label + " backend")
        for phase in ("baseline", "one-line-change"):
            if phase == "one-line-change":
                # Меняем только копию в /tmp, исходники в репозитории не трогаем.
                source.write_text(original + "\n// Cache experiment: changed one comment.\n")
            target = REPORT / ("build-" + label + "-" + phase + ".log")
            started = time.perf_counter()
            with target.open("w") as output:
                subprocess.run(cmd, stdout=output, stderr=subprocess.STDOUT, check=True)
            elapsed = time.perf_counter() - started
            log(label + " / " + phase + ": " + f"{elapsed:.2f}" + " seconds")
            results[label + "_" + phase] = round(elapsed, 2)
        image = json.loads(run(["docker", "image", "inspect", "gameshelf-lab2-backend:" + label]).stdout)[0]
        results[label + "_size_bytes"] = image["Size"]
        log("Image size: " + str(image["Size"]) + " bytes / " + f"{image['Size']/1024/1024:.1f}" + " MiB")
        user = run(["docker", "run", "--rm", "--entrypoint", "whoami", "gameshelf-lab2-backend:" + label]).stdout.strip()
        log("Image runtime user: " + user)
        results[label + "_user"] = user
assert results["good_size_bytes"] < results["bad_size_bytes"]
log("\nPASS: good image is smaller; source files in the repository were not edited.")
(REPORT / "benchmark.json").write_text(json.dumps(results, indent=2))
