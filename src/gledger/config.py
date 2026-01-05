"""Configuration management for G-Ledger."""

import os
import re
import json
import stat
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator
import yaml


class Config(BaseModel):
    """Application configuration.

    Attributes:
        sheet_id: Google Sheet ID (from URL)
        service_account_key_path: Path to service account JSON key file
        simplefin_token: SimpleFIN access token
        simplefin_base_url: SimpleFIN API base URL
        window_days: Number of days to fetch transactions (default 30)
        snapshot_dir: Directory for git-based snapshots
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
    """

    # Google Sheets
    sheet_id: str
    service_account_key_path: Path

    # SimpleFIN
    simplefin_token: str
    simplefin_base_url: str = "https://bridge.simplefin.org/simplefin"

    # Sync settings
    window_days: int = 30

    # Snapshot settings
    snapshot_dir: Path = Field(default_factory=lambda: Path.home() / "gledger-snapshots")

    # Logging
    log_level: str = "INFO"

    @field_validator("service_account_key_path", "snapshot_dir", mode="before")
    @classmethod
    def resolve_paths(cls, v):
        """Resolve paths to absolute paths."""
        if v:
            return Path(v).expanduser().resolve()
        return v

    @field_validator("window_days")
    @classmethod
    def validate_window_days(cls, v):
        """Ensure window_days is positive."""
        if v <= 0:
            raise ValueError("window_days must be positive")
        return v

    @field_validator("sheet_id")
    @classmethod
    def validate_sheet_id(cls, v):
        """Validate Google Sheet ID format."""
        if not v or not v.strip():
            raise ValueError("sheet_id cannot be empty")

        # Google Sheet IDs are alphanumeric with underscores/hyphens, typically 44 chars
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError(
                f"Invalid sheet_id format: {v}\n"
                "Sheet ID should be alphanumeric (found in Sheet URL)"
            )

        if len(v) < 20:
            raise ValueError(
                f"sheet_id seems too short: {v}\n"
                "Make sure you're using the Sheet ID, not the entire URL"
            )

        return v

    @field_validator("simplefin_base_url")
    @classmethod
    def validate_simplefin_url(cls, v):
        """Validate SimpleFIN URL format."""
        if not v.startswith("https://"):
            raise ValueError(
                f"SimpleFIN URL must use HTTPS: {v}\n"
                "For security, only HTTPS connections are allowed"
            )
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v):
        """Validate log level is recognized."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(
                f"Invalid log_level: {v}\n" f"Must be one of: {', '.join(valid_levels)}"
            )
        return v_upper

    @model_validator(mode="after")
    def validate_files_exist(self):
        """Validate that required files exist and have correct permissions."""
        # Check service account key file
        key_path = self.service_account_key_path
        if not key_path.exists():
            raise FileNotFoundError(
                f"Service account key file not found: {key_path}\n"
                "Create a service account in Google Cloud Console and download the key"
            )

        if not key_path.is_file():
            raise ValueError(f"Service account key path is not a file: {key_path}")

        # Check file permissions (warn if too permissive)
        file_stat = key_path.stat()
        if stat.S_IMODE(file_stat.st_mode) & 0o077:
            # File is readable by group or others
            import warnings

            warnings.warn(
                f"Service account key file has insecure permissions: {key_path}\n"
                f"Recommended: chmod 600 {key_path}",
                UserWarning,
            )

        # Validate it's valid JSON
        try:
            with open(key_path) as f:
                key_data = json.load(f)

            required_fields = ["type", "project_id", "private_key", "client_email"]
            missing = [f for f in required_fields if f not in key_data]
            if missing:
                raise ValueError(
                    f"Service account key file is missing required fields: {', '.join(missing)}"
                )

            if key_data.get("type") != "service_account":
                raise ValueError(
                    f"Service account key file has wrong type: {key_data.get('type')}\n"
                    "Expected: service_account"
                )

        except json.JSONDecodeError as e:
            raise ValueError(
                f"Service account key file is not valid JSON: {key_path}\n" f"Error: {e}"
            )

        return self

    @classmethod
    def find_config_path(cls, config_path: Optional[Path] = None) -> Path:
        """Find configuration file using search hierarchy.

        Search order:
        1. Explicit config_path argument (if provided)
        2. GLEDGER_CONFIG environment variable
        3. ~/.config/gledger/config.yaml (XDG standard location)
        4. ./config.yaml (current directory)

        Args:
            config_path: Optional explicit config path

        Returns:
            Path to configuration file

        Raises:
            FileNotFoundError: If no config file found in search hierarchy
        """
        # 1. Explicit path provided
        if config_path is not None:
            path = Path(config_path).expanduser().resolve()
            if path.exists():
                return path
            raise FileNotFoundError(
                f"Configuration file not found: {config_path}\n" f"Specified path does not exist"
            )

        # 2. Environment variable
        env_path = os.environ.get("GLEDGER_CONFIG")
        if env_path:
            path = Path(env_path).expanduser().resolve()
            if path.exists():
                return path
            raise FileNotFoundError(
                f"Configuration file not found: {env_path}\n"
                f"GLEDGER_CONFIG environment variable points to non-existent file"
            )

        # 3. XDG config directory (~/.config/gledger/config.yaml)
        xdg_path = Path.home() / ".config" / "gledger" / "config.yaml"
        if xdg_path.exists():
            return xdg_path

        # 4. Current directory (./config.yaml)
        local_path = Path("config.yaml").resolve()
        if local_path.exists():
            return local_path

        # No config found anywhere
        raise FileNotFoundError(
            "Configuration file not found. Searched:\n"
            f"  - GLEDGER_CONFIG environment variable\n"
            f"  - {xdg_path}\n"
            f"  - {local_path}\n"
            f"Create config.yaml in one of these locations or set GLEDGER_CONFIG"
        )

    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> "Config":
        """Load configuration from YAML file.

        Uses config path search hierarchy if no path specified.
        Relative paths in config are resolved relative to config file location.

        Args:
            config_path: Optional path to configuration file.
                        If None, searches standard locations.

        Returns:
            Config instance

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If config is invalid
        """
        resolved_path = cls.find_config_path(config_path)

        with open(resolved_path) as f:
            data = yaml.safe_load(f)

        # Apply environment variable overrides
        data = cls._apply_env_overrides(data)

        # Resolve relative paths relative to config file directory
        data = cls._resolve_relative_paths(data, resolved_path)

        return cls(**data)

    @classmethod
    def _resolve_relative_paths(cls, data: dict, config_path: Path) -> dict:
        """Resolve relative paths in config relative to config file location.

        Args:
            data: Config data dict
            config_path: Path to the config file

        Returns:
            Updated config data dict with resolved paths
        """
        config_dir = config_path.parent

        # List of fields that are file paths
        path_fields = ["service_account_key_path", "snapshot_dir"]

        for field in path_fields:
            if field in data and data[field]:
                path = Path(data[field]).expanduser()

                # If path is relative (not absolute), resolve relative to config dir
                if not path.is_absolute():
                    data[field] = str(config_dir / path)

        return data

    @classmethod
    def _apply_env_overrides(cls, data: dict) -> dict:
        """Apply environment variable overrides to config data.

        Environment variables:
            GLEDGER_SHEET_ID: Override sheet_id
            GLEDGER_SERVICE_ACCOUNT_KEY: Override service_account_key_path
            GLEDGER_SIMPLEFIN_TOKEN: Override simplefin_token
            GLEDGER_SNAPSHOT_DIR: Override snapshot_dir
            GLEDGER_LOG_LEVEL: Override log_level

        Args:
            data: Config data dict from YAML

        Returns:
            Updated config data dict
        """
        env_mappings = {
            "GLEDGER_SHEET_ID": "sheet_id",
            "GLEDGER_SERVICE_ACCOUNT_KEY": "service_account_key_path",
            "GLEDGER_SIMPLEFIN_TOKEN": "simplefin_token",
            "GLEDGER_SNAPSHOT_DIR": "snapshot_dir",
            "GLEDGER_LOG_LEVEL": "log_level",
        }

        for env_var, config_key in env_mappings.items():
            env_value = os.environ.get(env_var)
            if env_value:
                data[config_key] = env_value

        return data
