"""Tests for ZettelForge configuration loader."""
import os
import pytest
import tempfile
from pathlib import Path

from zettelforge.config import (
    ZettelForgeConfig,
    get_config,
    reload_config,
    _apply_env,
    _apply_yaml,
    _load_yaml,
)


class TestDefaults:
    def test_default_config(self):
        cfg = ZettelForgeConfig()
        assert cfg.typedb.host == "localhost"
        assert cfg.typedb.port == 1729
        assert cfg.typedb.database == "zettelforge"
        assert cfg.backend == "typedb"
        assert cfg.embedding.dimensions == 768
        assert cfg.retrieval.default_k == 10
        assert cfg.extraction.max_facts == 5
        assert cfg.synthesis.tier_filter == ["A", "B"]

    def test_storage_default(self):
        cfg = ZettelForgeConfig()
        assert cfg.storage.data_dir == "~/.amem"

    def test_cache_defaults(self):
        cfg = ZettelForgeConfig()
        assert cfg.cache.ttl_seconds == 300
        assert cfg.cache.max_entries == 1024


class TestEnvOverrides:
    def test_typedb_host_override(self):
        cfg = ZettelForgeConfig()
        os.environ["TYPEDB_HOST"] = "db.example.com"
        try:
            _apply_env(cfg)
            assert cfg.typedb.host == "db.example.com"
        finally:
            del os.environ["TYPEDB_HOST"]

    def test_typedb_port_override(self):
        cfg = ZettelForgeConfig()
        os.environ["TYPEDB_PORT"] = "2729"
        try:
            _apply_env(cfg)
            assert cfg.typedb.port == 2729
        finally:
            del os.environ["TYPEDB_PORT"]

    def test_backend_override(self):
        cfg = ZettelForgeConfig()
        os.environ["ZETTELFORGE_BACKEND"] = "jsonl"
        try:
            _apply_env(cfg)
            assert cfg.backend == "jsonl"
        finally:
            del os.environ["ZETTELFORGE_BACKEND"]

    def test_embedding_url_override(self):
        cfg = ZettelForgeConfig()
        os.environ["AMEM_EMBEDDING_URL"] = "http://gpu-box:11434"
        try:
            _apply_env(cfg)
            assert cfg.embedding.url == "http://gpu-box:11434"
        finally:
            del os.environ["AMEM_EMBEDDING_URL"]

    def test_data_dir_override(self):
        cfg = ZettelForgeConfig()
        os.environ["AMEM_DATA_DIR"] = "/data/zettelforge"
        try:
            _apply_env(cfg)
            assert cfg.storage.data_dir == "/data/zettelforge"
        finally:
            del os.environ["AMEM_DATA_DIR"]


class TestYamlOverrides:
    def test_apply_yaml_typedb(self):
        cfg = ZettelForgeConfig()
        data = {"typedb": {"host": "typedb.internal", "port": 3729}}
        _apply_yaml(cfg, data)
        assert cfg.typedb.host == "typedb.internal"
        assert cfg.typedb.port == 3729
        assert cfg.typedb.database == "zettelforge"  # unchanged

    def test_apply_yaml_backend(self):
        cfg = ZettelForgeConfig()
        _apply_yaml(cfg, {"backend": "jsonl"})
        assert cfg.backend == "jsonl"

    def test_apply_yaml_retrieval(self):
        cfg = ZettelForgeConfig()
        _apply_yaml(cfg, {"retrieval": {"default_k": 20, "entity_boost": 3.0}})
        assert cfg.retrieval.default_k == 20
        assert cfg.retrieval.entity_boost == 3.0

    def test_apply_yaml_ignores_unknown_keys(self):
        cfg = ZettelForgeConfig()
        _apply_yaml(cfg, {"typedb": {"nonexistent_key": "value"}})
        assert not hasattr(cfg.typedb, "nonexistent_key")

    def test_load_yaml_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("typedb:\n  host: from-file\n  port: 9999\nbackend: jsonl\n")
            f.flush()
            data = _load_yaml(Path(f.name))
        os.unlink(f.name)
        assert data.get("typedb", {}).get("host") == "from-file"
        assert data.get("backend") == "jsonl"


class TestPriorityOrder:
    def test_env_overrides_yaml(self):
        """Environment variables should beat config file values."""
        cfg = ZettelForgeConfig()
        _apply_yaml(cfg, {"typedb": {"host": "from-yaml"}})
        assert cfg.typedb.host == "from-yaml"

        os.environ["TYPEDB_HOST"] = "from-env"
        try:
            _apply_env(cfg)
            assert cfg.typedb.host == "from-env"
        finally:
            del os.environ["TYPEDB_HOST"]


class TestSingleton:
    def test_get_config_returns_same_instance(self):
        cfg1 = get_config()
        cfg2 = get_config()
        assert cfg1 is cfg2

    def test_reload_creates_new_instance(self):
        cfg1 = get_config()
        cfg2 = reload_config()
        assert cfg1 is not cfg2
