"""Self-contained tests for sync.filters (runnable under `pytest --noconftest`).

No dependence on tests/conftest.py fixtures: uses tmp_path and resets the
utils.logger config cache between tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sync.config import load_sync_config
from sync.filters import filter_summary, generate_filters, write_filter_file
from utils.logger import reset_config_cache

REPO_ROOT = Path(__file__).resolve().parent.parent
SOUL_RULE = "- data/personality/**"


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_config_cache()
    yield
    reset_config_cache()


def _load(tmp_path: Path, **overrides: object):
    block = {
        "enabled": True,
        "local_path": "data/corpus",
        "remote_name": "dropbox_cyclaw",
        "remote_path": "CyClaw/corpus",
        "direction": "pull",
    }
    block.update(overrides)
    cfg = {"logging": {"audit_file": str(tmp_path / "audit.jsonl")}, "sync": block}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return load_sync_config(str(path))


def test_soul_excluded_by_default(tmp_path: Path) -> None:
    text = generate_filters(_load(tmp_path))
    assert SOUL_RULE in text
    assert "WARNING" not in text


def test_hardened_categories_present(tmp_path: Path) -> None:
    text = generate_filters(_load(tmp_path))
    for rule in (
        "- *.gguf",
        "- index/**",
        "- .emb_cache/**",
        "- .chroma/**",
        "- logs/**",
        "- *.jsonl",
        "- *.db",
        "- *.db-wal",
        "- *.db-shm",
        "- .env",
        "- credentials*",
        "- .git/**",
        "- .gitignore",
        "- desktop.ini",
        "- .rclone-state/**",
    ):
        assert rule in text, f"missing hardened rule: {rule}"


def test_soul_dropped_with_warning_when_include_soul(tmp_path: Path) -> None:
    text = generate_filters(_load(tmp_path, include_soul=True))
    assert SOUL_RULE not in text
    assert "WARNING" in text
    assert "include_soul=true" in text
    # Other hardened rules survive.
    assert "- *.db" in text


def test_extra_excludes_appended_after_hardened_block(tmp_path: Path) -> None:
    text = generate_filters(_load(tmp_path, extra_excludes=["scratch/**", "- already/**"]))
    lines = text.splitlines()
    # Bare entry gets a leading "- "; entry with leading "- " is preserved.
    assert "- scratch/**" in lines
    assert "- already/**" in lines
    # Extras come after the hardened soul rule.
    assert lines.index("- scratch/**") > lines.index(SOUL_RULE)
    assert lines.index("- scratch/**") > lines.index("- *.gguf")


def test_bang_extra_exclude_is_neutralised(tmp_path: Path) -> None:
    # rclone's '!' rule clears the whole filter list built so far. A user extra
    # must never be able to wipe the hardened soul/secret/index exclusions, so a
    # '!' entry is dropped (as a comment) rather than emitted as a live rule.
    text = generate_filters(_load(tmp_path, extra_excludes=["!", "! reset"]))
    lines = text.splitlines()
    # No live (non-comment) line is a bare '!' reset.
    assert "!" not in [ln for ln in lines if not ln.startswith("#")]
    assert not any(ln.strip() == "!" for ln in lines if not ln.startswith("#"))
    # The hardened soul rule still precedes any extras and survives intact.
    assert SOUL_RULE in text
    assert any("IGNORED" in ln and "!" in ln for ln in lines)


def test_write_filter_file_is_atomic_no_tmp_left(tmp_path: Path) -> None:
    target = tmp_path / "state" / "cyclaw_filters.txt"
    cfg = _load(tmp_path, filter_file=str(target))
    write_filter_file(cfg)
    # The temp file used for the atomic replace must not linger.
    assert not (target.parent / f"{target.name}.tmp").exists()
    assert SOUL_RULE in target.read_text(encoding="utf-8")


def test_write_filter_file_returns_abs_path(tmp_path: Path) -> None:
    target = tmp_path / "state" / "cyclaw_filters.txt"
    cfg = _load(tmp_path, filter_file=str(target))
    written = write_filter_file(cfg)
    assert written == str(target.resolve())
    assert Path(written).is_file()
    assert SOUL_RULE in Path(written).read_text(encoding="utf-8")


def test_filter_summary_shape(tmp_path: Path) -> None:
    cfg = _load(tmp_path, extra_excludes=["scratch/**"])
    summary = filter_summary(cfg)
    assert set(summary) == {"soul_excluded", "include_soul", "total_rules", "filter_file", "extra_excludes"}
    assert summary["soul_excluded"] is True
    assert summary["include_soul"] is False
    assert isinstance(summary["total_rules"], int) and summary["total_rules"] > 0
    assert summary["extra_excludes"] == ["scratch/**"]


def test_filter_summary_soul_included(tmp_path: Path) -> None:
    summary = filter_summary(_load(tmp_path, include_soul=True))
    assert summary["soul_excluded"] is False
    assert summary["include_soul"] is True
