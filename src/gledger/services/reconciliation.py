"""Reconciliation service for account balance validation."""

from datetime import date
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel

from ..models.account import Account
from ..models.balance_history import BalanceSnapshot, ReconciliationResult
from ..repositories.sheet_repo import SheetRepository
from ..utils.logging import get_logger

logger = get_logger(__name__)


class ReconciliationReport(BaseModel):
    """Overall reconciliation report for all accounts."""

    total_accounts: int = 0
    reconciled_count: int = 0
    discrepancy_count: int = 0
    no_starting_balance_count: int = 0
    results: list[ReconciliationResult] = []


class ReconciliationService:
    """Service for account balance reconciliation.

    Validates that:
        starting_balance + transaction_sum = current_balance

    Identifies discrepancies and provides reconciliation reports.
    """

    def __init__(self, sheet_repo: SheetRepository):
        """Initialize reconciliation service.

        Args:
            sheet_repo: Sheet repository
        """
        self.sheet_repo = sheet_repo
        logger.info("Initialized ReconciliationService")

    def reconcile_all_accounts(
        self, start_date: Optional[date] = None, end_date: Optional[date] = None
    ) -> ReconciliationReport:
        """Reconcile all accounts.

        Args:
            start_date: Start of reconciliation period (default: starting_balance_date)
            end_date: End of reconciliation period (default: today)

        Returns:
            ReconciliationReport with results for all accounts
        """
        logger.info("Starting reconciliation for all accounts...")

        # Read all accounts (excluding ignored)
        all_accounts = self.sheet_repo.read_accounts(enabled_only=False)
        accounts = [a for a in all_accounts if not a.ignored]

        report = ReconciliationReport(total_accounts=len(accounts))

        for account in accounts:
            try:
                result = self.reconcile_account(account, start_date, end_date)
                report.results.append(result)

                if result.is_balanced:
                    report.reconciled_count += 1
                else:
                    report.discrepancy_count += 1

            except ValueError as e:
                # No starting balance or other validation error
                logger.warning(f"Cannot reconcile {account.display_name}: {e}")
                report.no_starting_balance_count += 1

        logger.info(
            f"Reconciliation complete: {report.reconciled_count} OK, "
            f"{report.discrepancy_count} discrepancies, "
            f"{report.no_starting_balance_count} missing starting balance"
        )
        return report

    def reconcile_account(
        self, account: Account, start_date: Optional[date] = None, end_date: Optional[date] = None
    ) -> ReconciliationResult:
        """Reconcile a single account.

        Args:
            account: Account to reconcile
            start_date: Start of period (default: starting_balance_date)
            end_date: End of period (default: today)

        Returns:
            ReconciliationResult

        Raises:
            ValueError: If account lacks required data for reconciliation
        """
        # Validate account has required fields
        if account.starting_balance is None:
            raise ValueError(f"Account {account.display_name} has no starting balance")

        if account.starting_balance_date is None:
            raise ValueError(f"Account {account.display_name} has no starting balance date")

        if account.balance is None:
            raise ValueError(f"Account {account.display_name} has no current balance")

        # Use starting_balance_date as start if not specified
        if start_date is None:
            start_date = account.starting_balance_date

        # Use today as end if not specified
        if end_date is None:
            end_date = date.today()

        # Read transactions for this account (match by sf_account_id)
        all_transactions = self.sheet_repo.read_transactions()
        account_transactions = [
            t
            for t in all_transactions
            if hasattr(t, "sf_account_id") and t.sf_account_id == account.sf_account_id
        ]

        # Filter to relevant date range
        relevant_txns = [
            t for t in account_transactions if t.date and start_date <= t.date <= end_date
        ]

        # Sum transaction amounts
        transaction_sum = sum((t.amount or Decimal("0")) for t in relevant_txns)
        transaction_count = len(relevant_txns)

        # Get ending balance
        ending_balance = account.balance

        # Compute reconciliation result
        result = ReconciliationResult.compute(
            sf_account_id=account.sf_account_id,
            account_name=account.display_name,
            start_date=start_date,
            end_date=end_date,
            starting_balance=account.starting_balance,
            ending_balance=ending_balance,
            transaction_sum=transaction_sum,
            transaction_count=transaction_count,
            tolerance=Decimal("0.01"),
        )

        logger.debug(
            f"Reconciled {account.display_name}: "
            f"starting={result.starting_balance}, "
            f"txn_sum={result.transaction_sum}, "
            f"ending={result.ending_balance}, "
            f"discrepancy={result.discrepancy}, "
            f"balanced={result.is_balanced}"
        )

        return result

    def get_balance_history(
        self,
        sf_account_id: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[BalanceSnapshot]:
        """Get balance history for account(s).

        Args:
            sf_account_id: Optional account ID filter
            start_date: Optional start date filter
            end_date: Optional end date filter

        Returns:
            List of BalanceSnapshot objects
        """
        return self.sheet_repo.read_balance_history(
            sf_account_id=sf_account_id, start_date=start_date, end_date=end_date
        )

    def suggest_starting_balance(self, account: Account) -> Optional[Decimal]:
        """Suggest a starting balance for an account.

        Strategy:
        - If account has transactions: work backwards from current balance
        - If no transactions but has current balance: use current balance as starting balance
        - Otherwise: cannot suggest

        Args:
            account: Account to analyze

        Returns:
            Suggested starting balance, or None if cannot determine
        """
        # Check if account has current balance
        if account.balance is None:
            logger.warning(
                f"Cannot suggest starting balance for {account.display_name}: no current balance"
            )
            return None

        # Read all transactions for this account (match by sf_account_id)
        all_transactions = self.sheet_repo.read_transactions()
        account_transactions = [
            t
            for t in all_transactions
            if hasattr(t, "sf_account_id")
            and t.sf_account_id == account.sf_account_id
            and t.date is not None
        ]

        if not account_transactions:
            # No transactions - use current balance as starting balance
            # (common for investment accounts where transactions aren't tracked)
            logger.info(
                f"Suggested starting balance for {account.display_name}: ${account.balance:.2f} "
                f"(no transactions, using current balance)"
            )
            return account.balance

        # Has transactions - work backwards from current balance
        # Sort by date
        account_transactions.sort(key=lambda t: t.date)

        # Sum all transactions
        total_sum = sum((t.amount or Decimal("0")) for t in account_transactions)

        # Starting balance = current balance - transaction sum
        suggested = account.balance - total_sum

        logger.info(
            f"Suggested starting balance for {account.display_name}: ${suggested:.2f} "
            f"(based on current balance ${account.balance:.2f} - "
            f"transaction sum ${total_sum:.2f})"
        )

        return suggested
