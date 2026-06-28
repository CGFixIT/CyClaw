"""Tests for agentic.cli -- subcommands, disabled no-op, exit codes."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agentic import cli
from utils.logger import reset_config_cache

REPO_ROOT = Path(__file__).resolve().parent.parent


def _write_config(tmp_path: Path, *, enabled: bool) -> str:
    cfg = {
        "logging": {"audit_file": str(tmp_path / "audit.jsonl"), "audit_fields": {}},
        "policy": {"prompt_filter": {"banned_patterns": ["ignore previous instructions"]},
                   "privacy": {}},
        "agentic": {
            "enabled": enabled,
            "repo": "CGFixIT/CyClaw",
            "mode": "read",
            "writes_enabled": False,
            "gh_min_version": "2.40.0",
            "registry_path": "data/agentic/skills_registry.json",
        },
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return str(path)


@pytest.fixture(autouse=True)
def _reset():
    reset_config_cache()
    yield
    reset_config_cache()


def test_status_runs(tmp_path, capsys):
    code = cli.main(["--config", _write_config(tmp_path, enabled=False), "status"])
    assert code == 0
    out = capsys.readouterr().out
    assert "CGFixIT/CyClaw" in out
    assert "registry_version" in out


def test_context_disabled_is_noop(tmp_path, capsys):
    # enabled=false -> clean exit 0 without ever touching gh.
    code = cli.main(["--config", _write_config(tmp_path, enabled=False), "context", "--repo"])
    assert code == 0
    assert "disabled" in capsys.readouterr().out.lower()


def test_bad_config_returns_env_exit(tmp_path):
    cfg = {"logging": {"audit_file": str(tmp_path / "a.jsonl")}}  # no agentic block
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    assert cli.main(["--config", str(path), "status"]) == 3


def test_apply_skill_requires_confirm(tmp_path):
    code = cli.main(["--config", _write_config(tmp_path, enabled=True),
                     "apply-skill", "--name", "x", "--desc", "d", "--body", "safe body",
                     "--reason", "r"])
    assert code == 4  # EXIT_REFUSED (no --confirm)


def test_propose_skill_runs(tmp_path, capsys):
    code = cli.main(["--config", _write_config(tmp_path, enabled=True),
                     "propose-skill", "--name", "x", "--desc", "d",
                     "--body", "a safe body", "--reason", "r"])
    assert code == 0
    assert "proposed" in capsys.readouterr().out


def test_propose_skill_disabled_is_noop(tmp_path, capsys):
    # enabled=false -> registry op is a clean no-op (matches context).
    code = cli.main(["--config", _write_config(tmp_path, enabled=False),
                     "propose-skill", "--name", "x", "--desc", "d",
                     "--body", "a safe body", "--reason", "r"])
    assert code == 0
    assert "disabled" in capsys.readouterr().out.lower()


def test_apply_skill_disabled_does_not_write(tmp_path, capsys):
    # The master switch must block the registry WRITE even with --confirm + reason
    # + a clean (injection-free) body. agentic.enabled=false means the layer is off,
    # so the registry JSON must never be created. registry_path is validated to live
    # under the repo data/ tree, so use a unique repo-relative path (the gate fires
    # before any SkillRegistry is constructed, so nothing is ever written there).
    rel = "data/agentic/_test_disabled_noop_registry.json"
    registry = REPO_ROOT / rel
    registry.unlink(missing_ok=True)  # defensive: never pre-exist
    cfg = {
        "logging": {"audit_file": str(tmp_path / "audit.jsonl"), "audit_fields": {}},
        "policy": {"prompt_filter": {"banned_patterns": ["ignore previous instructions"]},
                   "privacy": {}},
        "agentic": {
            "enabled": False, "repo": "CGFixIT/CyClaw", "mode": "read",
            "writes_enabled": False, "gh_min_version": "2.40.0",
            "registry_path": rel,
        },
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    try:
        code = cli.main(["--config", str(path), "apply-skill", "--name", "demo",
                         "--desc", "d", "--body", "a safe body", "--reason", "r", "--confirm"])
        assert code == 0
        assert "disabled" in capsys.readouterr().out.lower()
        assert not registry.exists()  # nothing was written while the layer is off
    finally:
        registry.unlink(missing_ok=True)


def test_unknown_subcommand_errors(tmp_path):
    with pytest.raises(SystemExit):
        cli.main(["--config", _write_config(tmp_path, enabled=True), "bogus"])
