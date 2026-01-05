"""Transaction data models."""

from datetime import datetime, date
from typing import Optional
from decimal import Decimal
from pydantic import BaseModel, Field, computed_field

from .enums import RowRole, ReviewStatus


class Transaction(BaseModel):
    """Represents a row in the Transactions tab.

    Attributes:
        Identity (protected - server writes):
            sf_account_id: SimpleFIN account ID (empty for MANUAL)
            sf_txn_id: SimpleFIN transaction ID (empty for MANUAL)
            txn_key: Unique key (sf_account_id:sf_txn_id or MANUAL:guid)
            row_role: Row type (BANK, SPLIT, MANUAL)

        Bank snapshot (protected - server writes):
            sf_date: Original transaction date from bank
            sf_amount: Original amount from bank (signed)
            sf_payee: Original payee from bank
            sf_memo: Original memo from bank
            sf_imported_at: First import timestamp
            sf_last_seen_at: Last sync timestamp where transaction was found

        Canonical (user editable):
            date: Effective transaction date (defaults to sf_date)
            accounting_month: Derived month for aggregation (e.g., "2024-01", computed from date)
            amount: Canonical amount (0 for BANK with splits, split amount for SPLIT)
            payee: Canonical payee name
            memo: Canonical memo/note
            category: Hierarchical account category (e.g., "Expenses:Groceries")
            tags: Space or comma-separated tags

        Review (protected - server writes):
            review_status: Computed review status
            review_notes: Human-readable notes about review status
            needs_attention: Boolean flag for filtering

        Display (protected - server writes):
            account_name: Human-readable account name (from Accounts tab)
            account_type: Account type (from Accounts tab)

        Sheet metadata:
            sheet_row_index: Row number for updates (not stored in sheet)
    """

    # Canonical (user-editable) - displayed first in sheet
    date: date
    accounting_month: Optional[str] = None  # Derived from date (e.g., "2024-01")
    amount: Decimal = Decimal("0")
    payee: str = ""
    memo: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[str] = None

    # Display (protected - computed from Accounts tab)
    account_name: Optional[str] = None
    account_type: Optional[str] = None

    # Identity (protected)
    sf_account_id: str = ""  # Empty for MANUAL rows
    sf_txn_id: Optional[str] = None
    txn_key: str
    row_role: RowRole

    # Bank snapshot (protected)
    sf_date: Optional[date] = None
    sf_amount: Optional[Decimal] = None
    sf_payee: Optional[str] = None
    sf_memo: Optional[str] = None
    sf_imported_at: Optional[datetime] = None
    sf_last_seen_at: Optional[datetime] = None

    # Review (protected)
    review_status: ReviewStatus = ReviewStatus.NEW
    review_notes: Optional[str] = None
    needs_attention: bool = False

    # Sheet metadata (not stored in sheet)
    sheet_row_index: Optional[int] = Field(default=None, exclude=True)


class TransactionGroup(BaseModel):
    """Group of transactions sharing the same txn_key.

    Used for analyzing splits and computing review status.

    Attributes:
        txn_key: Shared transaction key
        bank_row: The BANK row (if exists)
        split_rows: List of SPLIT rows
        manual_rows: List of MANUAL rows (typically 0 or 1)
    """

    txn_key: str
    bank_row: Optional[Transaction] = None
    split_rows: list[Transaction] = Field(default_factory=list)
    manual_rows: list[Transaction] = Field(default_factory=list)

    @computed_field
    @property
    def has_splits(self) -> bool:
        """Returns True if this group has split rows."""
        return len(self.split_rows) > 0

    @computed_field
    @property
    def split_sum(self) -> Decimal:
        """Sum of all split row amounts."""
        return sum((s.amount for s in self.split_rows), Decimal("0"))

    @computed_field
    @property
    def all_rows(self) -> list[Transaction]:
        """Returns all rows in the group."""
        rows = []
        if self.bank_row:
            rows.append(self.bank_row)
        rows.extend(self.split_rows)
        rows.extend(self.manual_rows)
        return rows
