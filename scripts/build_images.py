import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPS = ["validate", "revenue", "quantity", "report"]

for app in APPS:
    print(f"Building miniflow-{app}:1 ...")
    result = subprocess.run(
        ["docker", "build", "-t", f"miniflow-{app}:1", str(ROOT / "apps" / app)]
    )
    if result.returncode != 0:
        sys.exit(f"Build failed for {app}")
print("All images built.")