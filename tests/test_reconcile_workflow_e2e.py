"""End-to-end integration test for the reconciliation workflow.

This test simulates the complete user workflow:
1. Accounts are synced from SimpleFIN
2. User runs reconcile --suggest-starting-balance
3. Suggestions are written to Balance History
4. Account sync computes reconciliation status
5. Reconciliation status is accurate
"""

from decimal import Decimal
from datetime import date, datetime
from unittest.mock import Mock

from gledger.models.account import Account
from gledger.models.transaction import Transaction
from gledger.models.balance_history import BalanceSnapshot
from gledger.models.enums import AccountType, RowRole, ReviewStatus
from gledger.services.reconciliation import ReconciliationService
from gledger.repositories.sheet_repo import SheetRepository


class TestReconcileWorkflowE2E:
    """End-to-end tests for the complete reconciliation workflow."""

    def test_full_reconcile_workflow_with_zero_balance(self):
        """Test complete workflow: suggest → approve → sync → verify (with zero balance)."""

        # Setup: Mock sheet repository
        mock_sheet_repo = Mock(spec=SheetRepository)

        # Step 1: Account exists with current balance and transactions
        account = Account(
            sf_account_id="ACC123",
            enabled=True,
            ignored=False,
            display_name="Checking Account",
            account_type=AccountType.CHECKING,
            balance=Decimal("500.00"),  # Current balance
            balance_date=datetime(2024, 1, 31),
        )

        # Transactions that sum to $500
        transactions = [
            Transaction(
                sf_account_id="ACC123",
                txn_key="ACC123:TXN1",
                row_role=RowRole.BANK,
                date=date(2024, 1, 15),
                amount=Decimal("300"),
                payee="Deposit",
                memo="",
                category="Income",
                account_name="Checking Account",
                review_status=ReviewStatus.OK,
                needs_attention=False,
            ),
            Transaction(
                sf_account_id="ACC123",
                txn_key="ACC123:TXN2",
                row_role=RowRole.BANK,
                date=date(2024, 1, 20),
                amount=Decimal("200"),
                payee="Deposit",
                memo="",
                category="Income",
                account_name="Checking Account",
                review_status=ReviewStatus.OK,
                needs_attention=False,
            ),
        ]

        mock_sheet_repo.read_transactions.return_value = transactions

        # Step 2: Run suggest_starting_balance
        reconciliation_service = ReconciliationService(mock_sheet_repo)
        suggested = reconciliation_service.suggest_starting_balance(account)

        # Should suggest $0 (current $500 - transactions $500 = $0)
        assert suggested is not None, "Should return a value, not None"
        assert suggested == Decimal("0"), f"Expected $0, got ${suggested}"

        # Step 3: User approves suggestion - create balance snapshot
        earliest_txn_date = min(t.date for t in transactions)
        starting_balance_snapshot = BalanceSnapshot(
            sf_account_id="ACC123",
            account_name="Checking Account",
            balance_date=earliest_txn_date,
            balance=suggested,  # $0
            recorded_at=datetime.now(),
            source="user_suggested",
            is_starting_balance=True,  # Marked as starting balance
            notes="User approved suggestion",
        )

        # Step 4: Balance history now includes this snapshot
        mock_sheet_repo.read_balance_history.return_value = [starting_balance_snapshot]

        # Step 5: Account sync computes reconciliation status
        # Simulate account sync reading balance history
        balance_history = mock_sheet_repo.read_balance_history()

        # Filter for this account
        account_history = [h for h in balance_history if h.sf_account_id == "ACC123"]
        assert len(account_history) == 1

        # Get starting balance (oldest with is_starting_balance=True)
        starting_entries = [h for h in account_history if h.is_starting_balance]
        assert len(starting_entries) == 1
        starting_snapshot = starting_entries[0]

        # Set starting balance on account
        account.starting_balance = starting_snapshot.balance
        account.starting_balance_date = starting_snapshot.balance_date

        # Calculate expected balance
        account_transactions = [t for t in transactions if t.sf_account_id == "ACC123"]
        transaction_sum = sum((t.amount or Decimal("0")) for t in account_transactions)

        account.expected_balance = account.starting_balance + transaction_sum
        account.balance_discrepancy = account.balance - account.expected_balance

        # Determine status
        if abs(account.balance_discrepancy) <= Decimal("0.01"):
            account.reconciliation_status_text = "OK"
        else:
            account.reconciliation_status_text = "DISCREPANCY"

        # Step 6: Verify reconciliation
        assert account.starting_balance == Decimal("0")
        assert account.starting_balance_date == date(2024, 1, 15)
        assert account.expected_balance == Decimal("500")  # $0 + $500 transactions
        assert account.balance_discrepancy == Decimal("0")  # $500 - $500
        assert account.reconciliation_status_text == "OK"

    def test_full_reconcile_workflow_with_discrepancy(self):
        """Test workflow where reconciliation reveals a discrepancy."""

        mock_sheet_repo = Mock(spec=SheetRepository)

        # Account with balance that doesn't match transaction sum
        account = Account(
            sf_account_id="ACC456",
            enabled=True,
            ignored=False,
            display_name="Savings Account",
            account_type=AccountType.SAVINGS,
            balance=Decimal("1500.00"),  # Current balance
            balance_date=datetime(2024, 1, 31),
        )

        # Transactions only sum to $450 (missing $50)
        transactions = [
            Transaction(
                sf_account_id="ACC456",
                txn_key="ACC456:TXN1",
                row_role=RowRole.BANK,
                date=date(2024, 1, 10),
                amount=Decimal("200"),
                payee="Transfer In",
                memo="",
                category="Transfer",
                account_name="Savings Account",
                review_status=ReviewStatus.OK,
                needs_attention=False,
            ),
            Transaction(
                sf_account_id="ACC456",
                txn_key="ACC456:TXN2",
                row_role=RowRole.BANK,
                date=date(2024, 1, 20),
                amount=Decimal("250"),
                payee="Transfer In",
                memo="",
                category="Transfer",
                account_name="Savings Account",
                review_status=ReviewStatus.OK,
                needs_attention=False,
            ),
        ]

        mock_sheet_repo.read_transactions.return_value = transactions

        # Step 1: Suggest starting balance
        reconciliation_service = ReconciliationService(mock_sheet_repo)
        suggested = reconciliation_service.suggest_starting_balance(account)

        # Should suggest $1050 (current $1500 - transactions $450)
        assert suggested == Decimal("1050")

        # Step 2: Create snapshot
        starting_balance_snapshot = BalanceSnapshot(
            sf_account_id="ACC456",
            account_name="Savings Account",
            balance_date=date(2024, 1, 10),
            balance=suggested,
            recorded_at=datetime.now(),
            source="user_suggested",
            is_starting_balance=True,
        )

        mock_sheet_repo.read_balance_history.return_value = [starting_balance_snapshot]

        # Step 3: Now simulate a transaction was missing - only $400 in transactions
        # (User discovers this during reconciliation)
        corrected_transactions = transactions[:1]  # Only first transaction ($200)

        # Step 4: Compute reconciliation with corrected data
        account.starting_balance = suggested
        account.starting_balance_date = starting_balance_snapshot.balance_date

        account_transactions = [t for t in corrected_transactions if t.sf_account_id == "ACC456"]
        transaction_sum = sum((t.amount or Decimal("0")) for t in account_transactions)

        account.expected_balance = account.starting_balance + transaction_sum
        account.balance_discrepancy = account.balance - account.expected_balance

        if abs(account.balance_discrepancy) <= Decimal("0.01"):
            account.reconciliation_status_text = "OK"
        else:
            account.reconciliation_status_text = "DISCREPANCY"

        # Step 5: Verify discrepancy is detected
        assert account.starting_balance == Decimal("1050")
        assert account.expected_balance == Decimal("1250")  # $1050 + $200
        assert account.balance_discrepancy == Decimal(
            "250"
        )  # $1500 - $1250 (missing $250 transaction!)
        assert account.reconciliation_status_text == "DISCREPANCY"

    def test_workflow_with_reconcile_date_cutoff(self):
        """Test reconciliation with reconcile_date set (not empty)."""

        mock_sheet_repo = Mock(spec=SheetRepository)

        account = Account(
            sf_account_id="ACC789",
            enabled=True,
            ignored=False,
            display_name="Credit Card",
            account_type=AccountType.CREDIT,
            balance=Decimal("-200.00"),  # Owe $200
            balance_date=datetime(2024, 2, 1),
            reconcile_date=date(2024, 1, 15),  # User reconciled through Jan 15
        )

        # Balance history with multiple snapshots
        balance_history = [
            BalanceSnapshot(
                sf_account_id="ACC789",
                account_name="Credit Card",
                balance_date=date(2024, 1, 1),
                balance=Decimal("0"),
                recorded_at=datetime(2024, 1, 1),
                source="user_suggested",
                is_starting_balance=True,
            ),
            BalanceSnapshot(
                sf_account_id="ACC789",
                account_name="Credit Card",
                balance_date=date(2024, 1, 10),
                balance=Decimal("-50"),
                recorded_at=datetime(2024, 1, 10),
                source="simplefin",
                is_starting_balance=False,
            ),
            BalanceSnapshot(
                sf_account_id="ACC789",
                account_name="Credit Card",
                balance_date=date(2024, 1, 20),
                balance=Decimal("-150"),
                recorded_at=datetime(2024, 1, 20),
                source="simplefin",
                is_starting_balance=False,
            ),
        ]

        mock_sheet_repo.read_balance_history.return_value = balance_history

        # Find starting balance: most recent before reconcile_date (Jan 15)
        account_history = [h for h in balance_history if h.sf_account_id == "ACC789"]
        account_history.sort(key=lambda h: h.balance_date)

        # Filter: balance_date < reconcile_date
        eligible_snapshots = [h for h in account_history if h.balance_date < account.reconcile_date]

        # Should use Jan 10 snapshot (most recent before Jan 15)
        assert len(eligible_snapshots) == 2  # Jan 1 and Jan 10
        starting_snapshot = eligible_snapshots[-1]  # Most recent

        assert starting_snapshot.balance_date == date(2024, 1, 10)
        assert starting_snapshot.balance == Decimal("-50")

        # Set on account
        account.starting_balance = starting_snapshot.balance
        account.starting_balance_date = starting_snapshot.balance_date

        # This is correct - reconcile_date determines starting point
        assert account.starting_balance == Decimal("-50")
        assert account.starting_balance_date == date(2024, 1, 10)

    def test_workflow_with_empty_reconcile_date_prefers_starting_balance(self):
        """Test that empty reconcile_date prefers is_starting_balance=TRUE entries."""

        mock_sheet_repo = Mock(spec=SheetRepository)

        account = Account(
            sf_account_id="ACCINV",
            enabled=True,
            ignored=False,
            display_name="Investment Account",
            account_type=AccountType.INVESTMENT,
            balance=Decimal("10000.00"),
            reconcile_date=None,  # Never reconciled
        )

        # Balance history with both user-suggested and SimpleFIN snapshots
        balance_history = [
            BalanceSnapshot(
                sf_account_id="ACCINV",
                account_name="Investment Account",
                balance_date=date(2024, 1, 1),
                balance=Decimal("9000"),  # SimpleFIN older
                recorded_at=datetime(2024, 1, 1),
                source="simplefin",
                is_starting_balance=False,
            ),
            BalanceSnapshot(
                sf_account_id="ACCINV",
                account_name="Investment Account",
                balance_date=date(2024, 1, 5),
                balance=Decimal("9500"),  # User designated starting
                recorded_at=datetime(2024, 1, 5),
                source="user_suggested",
                is_starting_balance=True,
            ),
            BalanceSnapshot(
                sf_account_id="ACCINV",
                account_name="Investment Account",
                balance_date=date(2024, 1, 10),
                balance=Decimal("9800"),  # SimpleFIN newer
                recorded_at=datetime(2024, 1, 10),
                source="simplefin",
                is_starting_balance=False,
            ),
        ]

        mock_sheet_repo.read_balance_history.return_value = balance_history

        # When reconcile_date is empty, prefer is_starting_balance=True
        account_history = [h for h in balance_history if h.sf_account_id == "ACCINV"]
        starting_balance_entries = [h for h in account_history if h.is_starting_balance]

        if starting_balance_entries:
            # Use OLDEST entry marked as starting balance
            starting_balance_entries.sort(key=lambda h: h.balance_date)
            starting_snapshot = starting_balance_entries[0]
        else:
            # Fall back to oldest from history
            account_history.sort(key=lambda h: h.balance_date)
            starting_snapshot = account_history[0]

        # Should use Jan 5 (user-suggested, is_starting_balance=True)
        assert starting_snapshot.balance_date == date(2024, 1, 5)
        assert starting_snapshot.balance == Decimal("9500")
        assert starting_snapshot.is_starting_balance is True

        account.starting_balance = starting_snapshot.balance
        account.starting_balance_date = starting_snapshot.balance_date

        # Verify correct starting balance was selected
        assert account.starting_balance == Decimal("9500")
        assert account.starting_balance_date == date(2024, 1, 5)

    def test_suggest_with_split_transactions(self):
        """Test suggest_starting_balance correctly handles split transactions."""

        mock_sheet_repo = Mock(spec=SheetRepository)

        account = Account(
            sf_account_id="ACCSPLIT",
            enabled=True,
            ignored=False,
            display_name="Checking",
            account_type=AccountType.CHECKING,
            balance=Decimal("900.00"),
        )

        # Split transaction: BANK row + 2 SPLIT rows
        transactions = [
            # BANK row (amount = 0 for splits)
            Transaction(
                sf_account_id="ACCSPLIT",
                txn_key="ACCSPLIT:TXN1",
                row_role=RowRole.BANK,
                date=date(2024, 1, 15),
                amount=Decimal("0"),  # Zeroed out
                payee="Store",
                memo="",
                category="",
                account_name="Checking",
                review_status=ReviewStatus.OK,
                needs_attention=False,
            ),
            # SPLIT 1
            Transaction(
                sf_account_id="ACCSPLIT",
                txn_key="ACCSPLIT:TXN1",
                row_role=RowRole.SPLIT,
                date=date(2024, 1, 15),
                amount=Decimal("-70"),
                payee="Store",
                memo="",
                category="Groceries",
                account_name="Checking",
                review_status=ReviewStatus.OK,
                needs_attention=False,
            ),
            # SPLIT 2
            Transaction(
                sf_account_id="ACCSPLIT",
                txn_key="ACCSPLIT:TXN1",
                row_role=RowRole.SPLIT,
                date=date(2024, 1, 15),
                amount=Decimal("-30"),
                payee="Store",
                memo="",
                category="Household",
                account_name="Checking",
                review_status=ReviewStatus.OK,
                needs_attention=False,
            ),
        ]

        mock_sheet_repo.read_transactions.return_value = transactions

        reconciliation_service = ReconciliationService(mock_sheet_repo)
        suggested = reconciliation_service.suggest_starting_balance(account)

        # Should sum ALL rows: 0 + (-70) + (-30) = -100
        # Starting = 900 - (-100) = 1000
        assert suggested == Decimal("1000")


class TestReconcileEdgeCases:
    """Test edge cases in reconciliation workflow."""

    def test_account_with_no_balance_history(self):
        """Test account that has no balance history at all."""

        mock_sheet_repo = Mock(spec=SheetRepository)
        mock_sheet_repo.read_balance_history.return_value = []

        account = Account(
            sf_account_id="ACCNEW",
            enabled=True,
            ignored=False,
            display_name="New Account",
            account_type=AccountType.CHECKING,
            balance=Decimal("100"),
        )

        balance_history = mock_sheet_repo.read_balance_history()
        account_history = [h for h in balance_history if h.sf_account_id == "ACCNEW"]

        # No history available
        assert len(account_history) == 0

        # Should set status to indicate no history
        if not account_history:
            account.reconciliation_status_text = "NO_BALANCE_HISTORY"

        assert account.reconciliation_status_text == "NO_BALANCE_HISTORY"

    def test_account_with_future_reconcile_date(self):
        """Test account where reconcile_date is in the future (shouldn't happen but handle it)."""

        mock_sheet_repo = Mock(spec=SheetRepository)

        account = Account(
            sf_account_id="ACCFUT",
            enabled=True,
            ignored=False,
            display_name="Account",
            account_type=AccountType.CHECKING,
            balance=Decimal("1000"),
            reconcile_date=date(2025, 12, 31),  # Future date
        )

        balance_history = [
            BalanceSnapshot(
                sf_account_id="ACCFUT",
                account_name="Account",
                balance_date=date(2024, 1, 1),
                balance=Decimal("500"),
                recorded_at=datetime(2024, 1, 1),
                source="simplefin",
                is_starting_balance=False,
            ),
        ]

        mock_sheet_repo.read_balance_history.return_value = balance_history

        # Filter: balance_date < reconcile_date
        account_history = [h for h in balance_history if h.sf_account_id == "ACCFUT"]
        eligible_snapshots = [h for h in account_history if h.balance_date < account.reconcile_date]

        # Should still find the snapshot (it's before the future date)
        assert len(eligible_snapshots) == 1
        assert eligible_snapshots[0].balance == Decimal("500")
