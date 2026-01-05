"""Pytest configuration and fixtures."""

import pytest


@pytest.fixture
def sample_config():
    """Sample configuration for testing."""
    from pathlib import Path
    from gledger.config import Config

    return Config(
        sheet_id="test-sheet-id",
        service_account_key_path=Path("./test-key.json"),
        simplefin_token="test:token",
        simplefin_base_url="https://test.simplefin.org",
        window_days=30,
        snapshot_dir=Path("./test-snapshots"),
        log_level="DEBUG",
    )
