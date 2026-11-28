import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import docker
import pytest

from miniflow.docker_executor import DockerJobExecutor
from miniflow.models import JobState
from miniflow.parser import load_workflow
from miniflow.scheduler import Scheduler

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "data" / "sample" / "orders.csv"
IMAGES = [f"miniflow-{a}:1" for a in ("validate", "revenue", "quantity", "report")]


def images_built() -> bool:
    try:
        client = docker.from_env()
        for image in IMAGES:
            client.images.get(image)
        return True
    except Exception:
        return False


needs_images = pytest.mark.skipif(
    not images_built(), reason="Docker not running or images not built "
                               "(run: sh scripts/build_images.sh)")


def run_app(name: str, workspace: Path) -> subprocess.CompletedProcess:
    """Run one app directly on the host: fast, no Docker."""
    return subprocess.run(
        [sys.executable, str(ROOT / "apps" / name / "app.py")],
        env={**os.environ, "WORKSPACE": str(workspace)},
        capture_output=True, text=True,
    )


@pytest.fixture
def ws(tmp_path):
    shutil.copy(SAMPLE, tmp_path / "orders.csv")
    return tmp_path


# ---------- each app alone (no Docker) ----------

def test_validate_accepts_sample(ws):
    r = run_app("validate", ws)
    assert r.returncode == 0
    assert (ws / "validated.csv").exists()


def test_validate_rejects_negative_quantity(ws):
    (ws / "orders.csv").write_text(
        "order_id,product,quantity,price\n1001,Laptop,-2,50000\n")
    r = run_app("validate", ws)
    assert r.returncode == 1
    assert "quantity must be positive" in r.stderr
    assert not (ws / "validated.csv").exists()


def test_validate_rejects_duplicate_order_id(ws):
    (ws / "orders.csv").write_text(
        "order_id,product,quantity,price\n1001,Laptop,1,100\n1001,Mouse,1,10\n")
    assert run_app("validate", ws).returncode == 1


def test_validate_rejects_wrong_columns(ws):
    (ws / "orders.csv").write_text("id,item\n1,x\n")
    assert run_app("validate", ws).returncode == 1


def test_validate_fails_when_input_missing(tmp_path):
    assert run_app("validate", tmp_path).returncode == 1


def test_revenue_matches_hand_calculation(ws):
    run_app("validate", ws)
    assert run_app("revenue", ws).returncode == 0
    data = json.loads((ws / "revenue.json").read_text())
    assert data["total"] == 198_500
    assert data["orders"]["1001"] == 100_000
    assert data["orders"]["1004"] == 5_000


def test_quantity_matches_hand_calculation(ws):
    run_app("validate", ws)
    run_app("quantity", ws)
    data = json.loads((ws / "quantity.json").read_text())
    assert data["products"] == {"Laptop": 3, "Keyboard": 5, "Monitor": 3, "Mouse": 10}
    assert data["total_units"] == 21


def test_report_combines_both_results(ws):
    for app in ("validate", "revenue", "quantity", "report"):
        assert run_app(app, ws).returncode == 0
    text = (ws / "report.txt").read_text()
    assert "198,500" in text and "Laptop" in text


def test_report_fails_without_inputs(ws):
    assert run_app("report", ws).returncode == 1


def test_apps_are_idempotent(ws):
    """Running the whole chain twice gives identical output."""
    def chain():
        for app in ("validate", "revenue", "quantity", "report"):
            run_app(app, ws)
        return (ws / "report.txt").read_text()
    assert chain() == chain()


# ---------- engine stays generic ----------

def test_engine_has_no_business_logic():
    for f in (ROOT / "miniflow").glob("*.py"):
        text = f.read_text().lower()
        for word in ("revenue", "invoice", "laptop", "orders.csv"):
            assert word not in text, f"{word!r} found in {f.name}"


# ---------- whole workflow through MiniFlow + real Docker ----------

def run_workflow(workspace: Path) -> Scheduler:
    wf = load_workflow("workflows/orders.yaml")
    s = Scheduler.from_workflow(wf)
    s.run(DockerJobExecutor(workspace=str(workspace)))
    return s


@needs_images
def test_full_workflow_succeeds(ws):
    s = run_workflow(ws)
    assert all(state == JobState.SUCCESS for state in s.state.values())
    assert json.loads((ws / "revenue.json").read_text())["total"] == 198_500
    assert "198,500" in s.results["report"].stdout


@needs_images
def test_dependency_order_on_real_workflow(ws):
    t = run_workflow(ws).timeline
    assert t["validate"].end <= t["revenue"].start
    assert t["validate"].end <= t["quantity"].start
    assert max(t["revenue"].end, t["quantity"].end) <= t["report"].start


@needs_images
def test_bad_data_blocks_everything_downstream(ws):
    (ws / "orders.csv").write_text(
        "order_id,product,quantity,price\n1001,Laptop,-2,50000\n")
    s = run_workflow(ws)
    assert s.state["validate"] == JobState.FAILED
    for job in ("revenue", "quantity", "report"):
        assert s.state[job] == JobState.SKIPPED
    assert not (ws / "revenue.json").exists()


@needs_images
def test_missing_input_file_fails_validate(tmp_path):
    s = run_workflow(tmp_path)
    assert s.state["validate"] == JobState.FAILED
    assert s.state["report"] == JobState.SKIPPED


@needs_images
def test_rerun_gives_same_result(ws):
    run_workflow(ws)
    first = (ws / "report.txt").read_text()
    run_workflow(ws)
    assert (ws / "report.txt").read_text() == first