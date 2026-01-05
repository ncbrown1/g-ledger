"""Enumerations for G-Ledger data models."""

from enum import Enum


class AccountType(str, Enum):
    """Account type classification."""

    CHECKING = "checking"
    SAVINGS = "savings"
    CREDIT = "credit"
    INVESTMENT = "investment"
    LOAN = "loan"


class ReconcileStatus(str, Enum):
    """Account reconciliation status."""

    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class RowRole(str, Enum):
    """Transaction row role."""

    BANK = "BANK"
    SPLIT = "SPLIT"
    MANUAL = "MANUAL"


class ReviewStatus(str, Enum):
    """Transaction review status for flagging issues."""

    OK = "OK"
    NEW = "NEW"
    SPLIT_MISMATCH = "SPLIT_MISMATCH"
    BANK_CHANGED = "BANK_CHANGED"
    MISSING_CATEGORY = "MISSING_CATEGORY"
    UNMATCHABLE = "UNMATCHABLE"
    INVALID = "INVALID"
