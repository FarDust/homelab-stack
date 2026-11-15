"""Render the canonical patch against a deployment-neutral historical fixture."""

import subprocess
from pathlib import Path


def function(text, name):
    start = text.index(name + "() {")
    return text[start : text.index("\n}\n", start) + 3]


def test_patch_changes_reporting_and_deadline_wiring_not_admission_or_removal_policy(tmp_path):
    package = Path(__file__).parents[2]
    repository = package.parents[1]
    fixture = Path(__file__).parent / "fixtures/legacy_gate.sh"
    original = fixture.read_text()
    target = tmp_path / "gate-lib.sh"
    target.write_text(original)
    patch = repository / "host-config/ci-job-reporting/gate-reporting.patch"
    subprocess.run(["git", "apply", "--unidiff-zero", str(patch)], cwd=tmp_path, capture_output=True, check=True)
    changed = target.read_text()
    assert "_lanes_gc_report() { lanes_report_stale_once; }" in changed
    assert "_lanes_gc_report_containers() { lanes_report_stale_once; }" in changed
    for name in ("lanes_gc_own_trees", "_lanes_gc_rm_root", "lanes_reap_job_containers", "lanes_sweep_job_dirs"):
        assert function(original, name) == function(changed, name)
    old_limits = [
        line
        for line in original.splitlines()
        if line.startswith(("LANES_START_", "LANES_ABORT_", "LANES_MAX_", "LANES_SHM_", "LANES_MIN_"))
    ]
    new_limits = [
        line
        for line in changed.splitlines()
        if line.startswith(("LANES_START_", "LANES_ABORT_", "LANES_MAX_", "LANES_SHM_", "LANES_MIN_"))
    ]
    assert old_limits == new_limits
    assert changed.count("LANES_REPORT_START_EPOCH=$(date +%s)") == 2
    assert changed.count("unset _LANES_REPORT_RUN_KEY _LANES_REPORT_RUN_RC") == 2
    assert "( lanes_gc_hook ) >/dev/null 2>&1" not in changed
    assert "gc reporting incomplete; inspect structured report outcome" in changed


def test_public_shim_is_thin_and_has_no_private_deployment_mapping():
    package = Path(__file__).parents[2]
    repository = package.parents[1]
    directory = repository / "host-config/ci-job-reporting"
    shim = (directory / "gc-report.sh").read_text()
    assert len(shim.splitlines()) < 40
    assert "NODE_RETENTION_REPORT_STARTED_EPOCH" in shim
    assert "NODE_RETENTION_REPORT_EXPECTED_SECONDS" in shim
    assert "NODE_RETENTION_REPORT_STALE_HOURS" in shim
    assert "rm " not in shim
    for source in directory.iterdir():
        if source.is_file():
            text = source.read_text()
            assert "/home/" not in text
            assert ".ts.net" not in text
            assert "ssh " not in text
