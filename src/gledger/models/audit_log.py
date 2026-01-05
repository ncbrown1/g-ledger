"""Audit log data model for tracking sync execution history."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class AuditLogEntry(BaseModel):
    """Audit log entry for sync execution history.

    Tracks execution of sync and accounts-sync commands with diagnostic information.

    Attributes:
        timestamp: When the sync was executed
        command: Command name (sync or accounts-sync)
        hostname: Server/hostname where sync was executed
        status: SUCCESS or FAILED
        new_count: Number of new items (transactions or accounts)
        updated_count: Number of updated items
        unchanged_count: Number of unchanged items
        needs_attention_count: Number of items needing attention (review flagged or reconciliation failures)
        duration_seconds: How long the sync took
        error_type: Type of exception if failed (e.g., HttpError, ValueError)
        error_message: Brief error description if failed
        notes: Optional additional notes
        sheet_row_index: Row number in sheet (for updates)
    """

    # Execution metadata
    timestamp: datetime
    command: str  # "sync" or "accounts-sync"
    hostname: str
    status: str  # "SUCCESS" or "FAILED"

    # Counts
    new_count: int = 0
    updated_count: int = 0
    unchanged_count: int = 0
    needs_attention_count: int = 0

    # Diagnostics
    duration_seconds: Optional[float] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    notes: Optional[str] = None

    # Sheet metadata (not stored in sheet)
    sheet_row_index: Optional[int] = Field(default=None, exclude=True)
