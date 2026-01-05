"""Tests for reconciliation service logic.

These tests ensure that:
- suggest_starting_balance works correctly with various scenarios
- Zero balances are handled properly
- Transaction sums are calculated correctly
"""

from decimal import Decimal
from datetime import date
from unittest.mock import Mock

from gledger.models.account import Account
from gledger.models.transaction import Transaction
from gledger.models.enums import AccountType, RowRole, ReviewStatus
from gledger.services.reconciliation import ReconciliationService


class TestSuggestStartingBalance:
    """Test the suggest_starting_balance functionality."""

    def test_suggest_with_no_transactions_returns_current_balance(self):
        """Test that accounts without transactions suggest current balance."""
        mock_sheet_repo = Mock()
        mock_sheet_repo.read_transactions.return_value = []

        service = ReconciliationService(mock_sheet_repo)

        account = Account(
            sf_account_id="ACC123",
            enabled=True,
            ignored=False,
            display_name="Investment Account",
            account_type=AccountType.INVESTMENT,
            balance=Decimal("5000"),
        )

        suggested = service.suggest_starting_balance(account)

        assert suggested == Decimal("5000")

    def test_suggest_with_transactions_calculates_backwards(self):
        """Test that accounts with transactions calculate starting balance."""
        mock_sheet_repo = Mock()

        # Mock transactions that sum to $200
        mock_sheet_repo.read_transactions.return_value = [
            Transaction(
                sf_account_id="ACC123",
                txn_key="ACC123:TXN1",
                row_role=RowRole.BANK,
                date=date(2024, 1, 15),
                amount=Decimal("100"),
                payee="Deposit",
                memo="",
                category="Income",
                account_name="Checking",
                review_status=ReviewStatus.OK,
                needs_attention=False,
            ),
            Transaction(
                sf_account_id="ACC123",
                txn_key="ACC123:TXN2",
                row_role=RowRole.BANK,
                date=date(2024, 1, 20),
                amount=Decimal("100"),
                payee="Deposit",
                memo="",
                category="Income",
                account_name="Checking",
                review_status=ReviewStatus.OK,
                needs_attention=False,
            ),
        ]

        service = ReconciliationService(mock_sheet_repo)

        account = Account(
            sf_account_id="ACC123",
            enabled=True,
            ignored=False,
            display_name="Checking",
            account_type=AccountType.CHECKING,
            balance=Decimal("1200"),  # Current balance
        )

        suggested = service.suggest_starting_balance(account)

        # Starting balance = current (1200) - transactions (200) = 1000
        assert suggested == Decimal("1000")

    def test_suggest_returns_zero_when_appropriate(self):
        """Test that zero starting balance is returned when appropriate."""
        mock_sheet_repo = Mock()

        # Mock transactions that sum to current balance
        mock_sheet_repo.read_transactions.return_value = [
            Transaction(
                sf_account_id="ACC123",
                txn_key="ACC123:TXN1",
                row_role=RowRole.BANK,
                date=date(2024, 1, 15),
                amount=Decimal("500"),
                payee="Initial Deposit",
                memo="",
                category="Income",
                account_name="Checking",
                review_status=ReviewStatus.OK,
                needs_attention=False,
            ),
        ]

        service = ReconciliationService(mock_sheet_repo)

        account = Account(
            sf_account_id="ACC123",
            enabled=True,
            ignored=False,
            display_name="Checking",
            account_type=AccountType.CHECKING,
            balance=Decimal("500"),  # Current = transaction sum
        )

        suggested = service.suggest_starting_balance(account)

        # Starting balance should be 0
        assert suggested is not None, "Should return Decimal('0'), not None"
        assert suggested == Decimal("0")

    def test_suggest_returns_none_for_no_balance(self):
        """Test that None is returned when account has no balance."""
        mock_sheet_repo = Mock()
        mock_sheet_repo.read_transactions.return_value = []

        service = ReconciliationService(mock_sheet_repo)

        account = Account(
            sf_account_id="ACC123",
            enabled=True,
            ignored=False,
            display_name="Checking",
            account_type=AccountType.CHECKING,
            balance=None,  # No balance
        )

        suggested = service.suggest_starting_balance(account)

        assert suggested is None

    def test_suggest_ignores_other_account_transactions(self):
        """Test that only transactions for the account are included."""
        mock_sheet_repo = Mock()

        mock_sheet_repo.read_transactions.return_value = [
            Transaction(
                sf_account_id="ACC123",
                txn_key="ACC123:TXN1",
                row_role=RowRole.BANK,
                date=date(2024, 1, 15),
                amount=Decimal("100"),
                payee="Deposit",
                memo="",
                category="Income",
                account_name="Checking",
                review_status=ReviewStatus.OK,
                needs_attention=False,
            ),
            Transaction(
                sf_account_id="ACC456",  # Different account
                txn_key="ACC456:TXN1",
                row_role=RowRole.BANK,
                date=date(2024, 1, 15),
                amount=Decimal("500"),
                payee="Deposit",
                memo="",
                category="Income",
                account_name="Savings",
                review_status=ReviewStatus.OK,
                needs_attention=False,
            ),
        ]

        service = ReconciliationService(mock_sheet_repo)

        account = Account(
            sf_account_id="ACC123",
            enabled=True,
            ignored=False,
            display_name="Checking",
            account_type=AccountType.CHECKING,
            balance=Decimal("100"),
        )

        suggested = service.suggest_starting_balance(account)

        # Should only count the $100 transaction for ACC123
        assert suggested == Decimal("0")

    def test_suggest_handles_negative_balances(self):
        """Test suggesting starting balance for credit card (negative balances)."""
        mock_sheet_repo = Mock()

        mock_sheet_repo.read_transactions.return_value = [
            Transaction(
                sf_account_id="CC123",
                txn_key="CC123:TXN1",
                row_role=RowRole.BANK,
                date=date(2024, 1, 15),
                amount=Decimal("-50"),  # Charge
                payee="Store",
                memo="",
                category="Shopping",
                account_name="Credit Card",
                review_status=ReviewStatus.OK,
                needs_attention=False,
            ),
        ]

        service = ReconciliationService(mock_sheet_repo)

        account = Account(
            sf_account_id="CC123",
            enabled=True,
            ignored=False,
            display_name="Credit Card",
            account_type=AccountType.CREDIT,
            balance=Decimal("-50"),  # Owe $50
        )

        suggested = service.suggest_starting_balance(account)

        # Starting = current (-50) - transactions (-50) = 0
        assert suggested == Decimal("0")

    def test_suggest_handles_split_transactions(self):
        """Test that split transactions are properly summed."""
        mock_sheet_repo = Mock()

        mock_sheet_repo.read_transactions.return_value = [
            # BANK row with amount = 0
            Transaction(
                sf_account_id="ACC123",
                txn_key="ACC123:TXN1",
                row_role=RowRole.BANK,
                date=date(2024, 1, 15),
                amount=Decimal("0"),  # BANK row zeroed out
                payee="Store",
                memo="",
                category="",
                account_name="Checking",
                review_status=ReviewStatus.OK,
                needs_attention=False,
            ),
            # SPLIT row 1
            Transaction(
                sf_account_id="ACC123",
                txn_key="ACC123:TXN1",
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
            # SPLIT row 2
            Transaction(
                sf_account_id="ACC123",
                txn_key="ACC123:TXN1",
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

        service = ReconciliationService(mock_sheet_repo)

        account = Account(
            sf_account_id="ACC123",
            enabled=True,
            ignored=False,
            display_name="Checking",
            account_type=AccountType.CHECKING,
            balance=Decimal("900"),
        )

        suggested = service.suggest_starting_balance(account)

        # Should sum all rows: 0 + (-70) + (-30) = -100
        # Starting = 900 - (-100) = 1000
        assert suggested == Decimal("1000")


class TestTransactionSumCalculation:
    """Test transaction sum calculations used in reconciliation."""

    def test_sum_positive_transactions(self):
        """Test summing positive (income) transactions."""
        transactions = [
            Decimal("100"),
            Decimal("200"),
            Decimal("50"),
        ]

        total = sum(transactions)

        assert total == Decimal("350")

    def test_sum_negative_transactions(self):
        """Test summing negative (expense) transactions."""
        transactions = [
            Decimal("-50"),
            Decimal("-100"),
            Decimal("-25"),
        ]

        total = sum(transactions)

        assert total == Decimal("-175")

    def test_sum_mixed_transactions(self):
        """Test summing mixed positive and negative transactions."""
        transactions = [
            Decimal("1000"),  # Deposit
            Decimal("-50"),  # Expense
            Decimal("-100"),  # Expense
            Decimal("200"),  # Deposit
        ]

        total = sum(transactions)

        assert total == Decimal("1050")

    def test_sum_with_none_values(self):
        """Test summing transactions where some amounts might be None."""
        transactions = [
            Decimal("100") if True else Decimal("0"),
            Decimal("200") if True else Decimal("0"),
            Decimal("0"),  # Treat None as 0
        ]

        # Using generator expression like in the actual code
        total = sum((t or Decimal("0")) for t in transactions)

        assert total == Decimal("300")

    def test_decimal_precision(self):
        """Test that Decimal maintains precision in calculations."""
        transactions = [
            Decimal("10.01"),
            Decimal("20.02"),
            Decimal("30.03"),
        ]

        total = sum(transactions)

        # Should be exactly 60.06, not 60.059999... (float issue)
        assert total == Decimal("60.06")
        assert str(total) == "60.06"
