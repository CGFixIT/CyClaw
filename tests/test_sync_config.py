"""Self-contained tests for sync.config (runnable under `pytest --noconftest`).

No dependence on tests/conftest.py fixtures: uses the builtin tmp_path fixture
and resets the utils.logger config cache between tests so the temp config.yaml
is re-read each time.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from sync.config import RcloneConfig, load_sync_config
from utils.errors import SyncConfigError
from utils.logger import reset_config_cache

# Repo's data/corpus tree -- the only place local_path is allowed to resolve to.
REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_ROOT = (REPO_ROOT / "data" / "corpus").resolve()


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_config_cache()
    yield
    reset_config_cache()


def _write_config(tmp_path: Path, sync_block: dict) -> str:
    cfg = {"logging": {"audit_file": str(tmp_path / "audit.jsonl")}, "sync": sync_block}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return str(path)


def _base_block(**overrides: object) -> dict:
    block = {
        "enabled": True,
        "local_path": "data/corpus",
        "remote_name": "dropbox_cyclaw",
        "remote_path": "CyClaw/corpus",
        "direction": "pull",
    }
    block.update(overrides)
    return block


def test_valid_load(tmp_path: Path) -> None:
    path = _write_config(tmp_path, _base_block())
    cfg = load_sync_config(path)
    assert isinstance(cfg, RcloneConfig)
    # Relative default resolves against repo root into the corpus tree.
    assert cfg.local_path == str(CORPUS_ROOT)
    assert os.path.isabs(cfg.local_path)
    assert cfg.remote == "dropbox_cyclaw:CyClaw/corpus"
    assert cfg.REINDEX_EXIT_CODE == 10
    assert cfg.filter_file is not None and cfg.filter_file.endswith("cyclaw_filters.txt")
    assert cfg.log_path.endswith("rclone_cyclaw.log")


def test_absolute_corpus_subdir_is_accepted(tmp_path: Path) -> None:
    abs_path = str(CORPUS_ROOT / "sub")
    cfg = load_sync_config(_write_config(tmp_path, _base_block(local_path=abs_path)))
    assert cfg.local_path == abs_path


def test_rejects_relative_escape(tmp_path: Path) -> None:
    path = _write_config(tmp_path, _base_block(local_path="data/corpus/../../etc"))
    with pytest.raises(SyncConfigError) as exc:
        load_sync_config(path)
    assert exc.value.code == "SYNC_CONFIG_INVALID"


def test_rejects_path_outside_corpus(tmp_path: Path) -> None:
    path = _write_config(tmp_path, _base_block(local_path="/tmp/not-corpus"))
    with pytest.raises(SyncConfigError):
        load_sync_config(path)


def test_rejects_repo_data_dir_not_under_corpus(tmp_path: Path) -> None:
    # data/ (parent of corpus) must be rejected -- it is not inside corpus.
    path = _write_config(tmp_path, _base_block(local_path="data"))
    with pytest.raises(SyncConfigError):
        load_sync_config(path)


def test_rejects_bad_direction(tmp_path: Path) -> None:
    path = _write_config(tmp_path, _base_block(direction="push"))
    with pytest.raises(SyncConfigError):
        load_sync_config(path)


def test_rejects_remote_name_with_metacharacters(tmp_path: Path) -> None:
    path = _write_config(tmp_path, _base_block(remote_name="bad name; rm -rf"))
    with pytest.raises(SyncConfigError):
        load_sync_config(path)


def test_rejects_leading_dash_remote_path(tmp_path: Path) -> None:
    path = _write_config(tmp_path, _base_block(remote_path="--config=evil"))
    with pytest.raises(SyncConfigError):
        load_sync_config(path)


def test_rejects_remote_path_with_shell_metachars(tmp_path: Path) -> None:
    path = _write_config(tmp_path, _base_block(remote_path="corpus; touch pwned"))
    with pytest.raises(SyncConfigError):
        load_sync_config(path)


def test_rejects_out_of_range_schedule_hour(tmp_path: Path) -> None:
    path = _write_config(tmp_path, _base_block(schedule_hour=24))
    with pytest.raises(SyncConfigError):
        load_sync_config(path)


def test_rejects_out_of_range_schedule_min(tmp_path: Path) -> None:
    path = _write_config(tmp_path, _base_block(schedule_min=60))
    with pytest.raises(SyncConfigError):
        load_sync_config(path)


def test_rejects_negative_max_delete(tmp_path: Path) -> None:
    path = _write_config(tmp_path, _base_block(max_delete=-1))
    with pytest.raises(SyncConfigError):
        load_sync_config(path)


def test_rejects_bad_conflict_resolve(tmp_path: Path) -> None:
    path = _write_config(tmp_path, _base_block(conflict_resolve="random"))
    with pytest.raises(SyncConfigError):
        load_sync_config(path)


def test_missing_block_raises(tmp_path: Path) -> None:
    cfg = {"logging": {"audit_file": str(tmp_path / "audit.jsonl")}}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    with pytest.raises(SyncConfigError):
        load_sync_config(str(path))


def test_unknown_keys_collected_not_fatal(tmp_path: Path) -> None:
    path = _write_config(tmp_path, _base_block(typo_field="oops", another="x"))
    cfg = load_sync_config(path)
    # "enabled" is not flagged; the genuine typos are.
    assert set(cfg._unknown_keys) == {"another", "typo_field"}  # type: ignore[attr-defined]


def test_is_windows_property(tmp_path: Path) -> None:
    cfg = load_sync_config(_write_config(tmp_path, _base_block()))
    assert isinstance(cfg.is_windows, bool)
