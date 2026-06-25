"""Unit tests for retrieval/clear_cache.py -- the embedding-cache CLI.

Covers the safe-by-default dry-run, the ``--apply`` deletion path, the
config/exit-code contract, and the edge cases (missing dir, unset cache_dir,
non-directory target). No model load or filesystem outside ``tmp_path``.
"""

import yaml

from retrieval import clear_cache


def _write_cfg(tmp_path, cache_dir):
    cfg = {"models": {"embeddings": {"model": "test-model", "cache_dir": cache_dir}}}
    p = tmp_path / "config.yaml"
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f)
    return str(p)


def _make_cache(tmp_path, name=".emb_cache"):
    cache = tmp_path / name
    cache.mkdir()
    (cache / "model.safetensors").write_bytes(b"x" * 2048)
    (cache / "sub").mkdir()
    (cache / "sub" / "config.json").write_text("{}", encoding="utf-8")
    return cache


def test_read_cache_dir_ok(tmp_path):
    cfg = _write_cfg(tmp_path, ".emb_cache")
    assert clear_cache.read_cache_dir(cfg) == ".emb_cache"


def test_read_cache_dir_unset_returns_empty(tmp_path):
    cfg = _write_cfg(tmp_path, "")
    assert clear_cache.read_cache_dir(cfg) == ""


def test_read_cache_dir_bad_config_raises(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("models: 123\n", encoding="utf-8")
    import pytest

    from utils.errors import ConfigError

    with pytest.raises(ConfigError):
        clear_cache.read_cache_dir(str(p))


def test_read_cache_dir_missing_file_raises(tmp_path):
    import pytest

    from utils.errors import ConfigError

    with pytest.raises(ConfigError):
        clear_cache.read_cache_dir(str(tmp_path / "nope.yaml"))


def test_dry_run_is_default_and_keeps_files(tmp_path):
    cache = _make_cache(tmp_path)
    cfg = _write_cfg(tmp_path, str(cache))
    rc = clear_cache.main(["--config", cfg])
    assert rc == clear_cache.EXIT_OK
    assert cache.exists()  # dry-run must not delete


def test_apply_removes_cache(tmp_path):
    cache = _make_cache(tmp_path)
    cfg = _write_cfg(tmp_path, str(cache))
    rc = clear_cache.main(["--config", cfg, "--apply"])
    assert rc == clear_cache.EXIT_OK
    assert not cache.exists()


def test_apply_when_absent_is_ok(tmp_path):
    cfg = _write_cfg(tmp_path, str(tmp_path / "does-not-exist"))
    rc = clear_cache.main(["--config", cfg, "--apply"])
    assert rc == clear_cache.EXIT_OK


def test_unset_cache_dir_noop(tmp_path):
    cfg = _write_cfg(tmp_path, "")
    rc = clear_cache.main(["--config", cfg, "--apply"])
    assert rc == clear_cache.EXIT_OK


def test_bad_config_exit_env(tmp_path):
    rc = clear_cache.main(["--config", str(tmp_path / "missing.yaml"), "--apply"])
    assert rc == clear_cache.EXIT_ENV


def test_non_directory_target_fails(tmp_path):
    target = tmp_path / "emb_cache_file"
    target.write_text("not a dir", encoding="utf-8")
    cfg = _write_cfg(tmp_path, str(target))
    rc = clear_cache.main(["--config", cfg, "--apply"])
    assert rc == clear_cache.EXIT_FAIL
    assert target.exists()  # left untouched


def test_dir_stats_counts_files_and_bytes(tmp_path):
    cache = _make_cache(tmp_path)
    files, total = clear_cache.dir_stats(cache)
    assert files == 2
    assert total == 2048 + len("{}")


def test_human_size_units():
    assert clear_cache.human_size(0) == "0.0 B"
    assert clear_cache.human_size(1536) == "1.5 KiB"
    assert clear_cache.human_size(5 * 1024 * 1024) == "5.0 MiB"
