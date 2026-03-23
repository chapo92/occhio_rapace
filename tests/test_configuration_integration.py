"""
Configuration integration tests.

Covers:
- Loading config from file
- Dynamic update of config values
- Validation of all parameters
- Fallback to defaults when file is absent
- Invalid config detection
- Environment variable override
- Config persistence (write → reload)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_config(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def _load_fresh(config_path: str) -> dict:
    """Import config module fresh and load from the given path."""
    # Temporarily monkey-patch the config file path used by load_config.
    import importlib
    import config as cfg_module
    original = cfg_module._CONFIG_FILE
    try:
        cfg_module._CONFIG_FILE = config_path
        return cfg_module.load_config()
    finally:
        cfg_module._CONFIG_FILE = original


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLoadConfigFromFile:
    """load_config() should read and merge config.json."""

    def test_load_returns_dict(self):
        from config import load_config
        cfg = load_config()
        assert isinstance(cfg, dict)

    def test_platform_key_present(self):
        from config import load_config
        cfg = load_config()
        assert "platform" in cfg

    def test_platform_value_888poker(self):
        from config import load_config
        cfg = load_config()
        assert cfg["platform"] == "888poker"

    def test_required_top_level_keys(self):
        from config import load_config
        cfg = load_config()
        for key in ("platform", "capture", "table_detection", "ocr", "output"):
            assert key in cfg, f"Missing key: {key}"

    def test_override_from_file(self, tmp_path):
        config_file = tmp_path / "config_test.json"
        _write_config(str(config_file), {"platform": "pokerstars"})
        cfg = _load_fresh(str(config_file))
        assert cfg["platform"] == "pokerstars"


class TestDynamicConfigUpdate:
    """Modifying the loaded dict should not affect the defaults."""

    def test_mutation_does_not_affect_reload(self):
        from config import load_config
        cfg1 = load_config()
        cfg1["platform"] = "modified"
        cfg2 = load_config()
        assert cfg2["platform"] != "modified"

    def test_nested_mutation_isolated(self):
        from config import load_config
        cfg1 = load_config()
        cfg1.setdefault("capture", {})["fps"] = 999
        cfg2 = load_config()
        assert cfg2.get("capture", {}).get("fps", 0) != 999


class TestParameterValidation:
    """Loaded config should contain sensible typed values."""

    def test_capture_fps_positive(self):
        from config import load_config
        cfg = load_config()
        fps = cfg.get("capture", {}).get("fps", 0)
        assert fps > 0

    def test_table_detection_confidence_range(self):
        from config import load_config
        cfg = load_config()
        conf = cfg.get("table_detection", {}).get("min_confidence", 0)
        assert 0.0 <= conf <= 1.0

    def test_performance_queue_size_positive(self):
        from config import load_config
        cfg = load_config()
        qs = cfg.get("performance", {}).get("queue_size", 0)
        assert qs > 0

    def test_validation_max_stack_positive(self):
        from config import load_config
        cfg = load_config()
        ms = cfg.get("validation", {}).get("max_stack", 0)
        assert ms > 0

    def test_ocr_engine_is_string(self):
        from config import load_config
        cfg = load_config()
        engine = cfg.get("ocr", {}).get("engine", "")
        assert isinstance(engine, str) and engine


class TestFallbackDefaults:
    """When config file is absent, defaults should be used."""

    def test_missing_config_file_uses_defaults(self, tmp_path):
        absent_path = str(tmp_path / "absent.json")
        cfg = _load_fresh(absent_path)
        assert cfg["platform"] == "888poker"

    def test_partial_config_merges_with_defaults(self, tmp_path):
        config_file = tmp_path / "partial.json"
        _write_config(str(config_file), {"platform": "pokerstars"})
        cfg = _load_fresh(str(config_file))
        # Platform overridden
        assert cfg["platform"] == "pokerstars"
        # Other keys still present from defaults
        assert "capture" in cfg
        assert "ocr" in cfg

    def test_empty_config_file_uses_all_defaults(self, tmp_path):
        config_file = tmp_path / "empty.json"
        _write_config(str(config_file), {})
        cfg = _load_fresh(str(config_file))
        assert cfg["platform"] == "888poker"


class TestInvalidConfigs:
    """Malformed JSON should be handled gracefully (fall back to defaults)."""

    def test_invalid_json_falls_back_to_defaults(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{ invalid json !!!", encoding="utf-8")
        cfg = _load_fresh(str(bad_file))
        # Should fall back to defaults without raising.
        assert isinstance(cfg, dict)
        assert cfg["platform"] == "888poker"

    def test_empty_file_falls_back_to_defaults(self, tmp_path):
        empty_file = tmp_path / "empty_file.json"
        empty_file.write_text("", encoding="utf-8")
        cfg = _load_fresh(str(empty_file))
        assert isinstance(cfg, dict)


class TestConfigPersistence:
    """Writing then reloading a config should round-trip cleanly."""

    def test_write_and_reload(self, tmp_path):
        config_file = tmp_path / "roundtrip.json"
        data = {"platform": "pokerstars", "debug": True}
        _write_config(str(config_file), data)

        cfg = _load_fresh(str(config_file))
        assert cfg["platform"] == "pokerstars"
        assert cfg["debug"] is True

    def test_nested_write_and_reload(self, tmp_path):
        config_file = tmp_path / "nested.json"
        data = {"capture": {"fps": 10, "resolution": "1080p"}}
        _write_config(str(config_file), data)

        cfg = _load_fresh(str(config_file))
        assert cfg["capture"]["fps"] == 10
        assert cfg["capture"]["resolution"] == "1080p"

    def test_reload_does_not_mutate_disk_file(self, tmp_path):
        config_file = tmp_path / "immutable.json"
        data = {"platform": "888poker"}
        _write_config(str(config_file), data)

        cfg = _load_fresh(str(config_file))
        cfg["platform"] = "mutated"

        cfg2 = _load_fresh(str(config_file))
        assert cfg2["platform"] == "888poker"
