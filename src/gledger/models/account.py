"""Account data model."""

from datetime import date, datetime
from typing import Optional
from decimal import Decimal
from pydantic import BaseModel, Field

from .enums import AccountType


class Account(BaseModel):
    """Represents a row in the Accounts tab.

    Attributes:
        Identity:
            sf_account_id: SimpleFIN account identifier (immutable)
            enabled: Whether account is enabled for transaction sync
            ignored: If TRUE, balance shown as 0.00 (hide from reports)

        Display:
            institution: Short institution domain (e.g., "www.ally.com")
            sf_org_name: Full institution name (e.g., "Ally Bank")
            display_name: User-friendly account name
            account_type: Type of account (checking, savings, cc, etc.)

        Configuration:
            currency: Currency code (default USD)

        Balance (from SimpleFIN):
            balance: Current balance
            available_balance: Available balance
            balance_date: Date balance was updated
            last_synced_at: When we last synced this account

        Reconciliation:
            reconcile_date: Date through which user has confirmed accuracy
            starting_balance: Computed from Balance History (most recent before reconcile_date)
            starting_balance_date: Date of the starting balance
            expected_balance: Calculated from starting_balance + transaction sum
            balance_discrepancy: Actual balance - expected balance
            reconciliation_status_text: Status text (OK, DISCREPANCY, NO_BALANCE_HISTORY, etc.)

        Notes:
            notes: Optional notes for user reference

        Internal:
            sheet_row_index: Sheet row number (1-based) for updates
    """

    # Identity
    sf_account_id: str
    enabled: bool = True
    ignored: bool = False  # If TRUE, show balance as 0.00

    # Metadata
    institution: Optional[str] = None  # Domain (e.g., "www.ally.com")
    sf_org_name: Optional[str] = None  # Full name (e.g., "Ally Bank")
    display_name: str
    account_type: AccountType
    currency: str = "USD"

    # Balance (synced from SimpleFIN)
    balance: Optional[Decimal] = None
    available_balance: Optional[Decimal] = None
    balance_date: Optional[datetime] = None
    last_synced_at: Optional[datetime] = None

    # Reconciliation
    reconcile_date: Optional[date] = None  # User-specified date of confirmed accuracy

    # Computed reconciliation fields (updated by sync)
    starting_balance: Optional[Decimal] = (
        None  # From Balance History (most recent before reconcile_date)
    )
    starting_balance_date: Optional[date] = None  # Date of starting balance from Balance History
    expected_balance: Optional[Decimal] = None  # Calculated from transactions
    balance_discrepancy: Optional[Decimal] = None  # actual - expected
    reconciliation_status_text: Optional[str] = None  # OK, DISCREPANCY, etc.

    # Notes
    notes: Optional[str] = None

    # Sheet metadata (not stored in sheet)
    sheet_row_index: Optional[int] = Field(default=None, exclude=True)
