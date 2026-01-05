"""Balance history data models for reconciliation."""

from datetime import datetime, date
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel


class BalanceSnapshot(BaseModel):
    """Represents a balance snapshot for an account at a specific point in time.

    Used for reconciliation - validates that transaction sums match balance changes.

    Attributes:
        sf_account_id: SimpleFIN account ID
        account_name: Human-readable account name (for reference)
        account_type: Account type (checking, savings, credit, etc.)
        balance_date: Date of the balance snapshot
        balance: Account balance at this date
        available_balance: Available balance (if different from balance)
        recorded_at: Timestamp when this snapshot was recorded
        source: How this balance was obtained (simplefin, manual, user_suggested)
        is_starting_balance: True if designated as a starting balance for reconciliation
        notes: Optional notes about this balance snapshot
        sheet_row_index: Row number in sheet (for updates)
    """

    # Account identification
    sf_account_id: str
    account_name: str
    account_type: Optional[str] = None

    # Balance data
    balance_date: date
    balance: Decimal
    available_balance: Optional[Decimal] = None

    # Metadata
    recorded_at: datetime
    source: str = "simplefin"  # simplefin, manual, user_suggested
    is_starting_balance: bool = False  # True if this is designated as a starting balance
    notes: Optional[str] = None

    # Sheet metadata (not stored in sheet)
    sheet_row_index: Optional[int] = None


class ReconciliationResult(BaseModel):
    """Result of a reconciliation check for an account.

    Compares starting balance + transaction sum vs ending balance.

    Attributes:
        sf_account_id: SimpleFIN account ID
        account_name: Human-readable account name
        start_date: Start of reconciliation period
        end_date: End of reconciliation period
        starting_balance: Balance at start of period
        ending_balance: Balance at end of period
        transaction_sum: Sum of all transactions in period
        calculated_ending_balance: starting_balance + transaction_sum
        discrepancy: Difference between actual and calculated ending balance
        is_balanced: True if discrepancy is within tolerance (±$0.01)
        transaction_count: Number of transactions in period
    """

    sf_account_id: str
    account_name: str
    start_date: date
    end_date: date

    # Balance data
    starting_balance: Decimal
    ending_balance: Decimal

    # Transaction data
    transaction_sum: Decimal
    transaction_count: int

    # Reconciliation result
    calculated_ending_balance: Decimal
    discrepancy: Decimal
    is_balanced: bool

    @classmethod
    def compute(
        cls,
        sf_account_id: str,
        account_name: str,
        start_date: date,
        end_date: date,
        starting_balance: Decimal,
        ending_balance: Decimal,
        transaction_sum: Decimal,
        transaction_count: int,
        tolerance: Decimal = Decimal("0.01"),
    ) -> "ReconciliationResult":
        """Compute reconciliation result.

        Args:
            sf_account_id: Account ID
            account_name: Account name
            start_date: Period start
            end_date: Period end
            starting_balance: Balance at start
            ending_balance: Balance at end
            transaction_sum: Sum of transactions
            transaction_count: Number of transactions
            tolerance: Acceptable discrepancy (default ±$0.01)

        Returns:
            ReconciliationResult
        """
        calculated_ending = starting_balance + transaction_sum
        discrepancy = ending_balance - calculated_ending
        is_balanced = abs(discrepancy) <= tolerance

        return cls(
            sf_account_id=sf_account_id,
            account_name=account_name,
            start_date=start_date,
            end_date=end_date,
            starting_balance=starting_balance,
            ending_balance=ending_balance,
            transaction_sum=transaction_sum,
            transaction_count=transaction_count,
            calculated_ending_balance=calculated_ending,
            discrepancy=discrepancy,
            is_balanced=is_balanced,
        )
