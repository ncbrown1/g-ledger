"""Tests for zero balance handling throughout the system.

These tests ensure that Decimal("0") is properly handled in:
- Account serialization and parsing
- Balance history serialization and parsing
- Transaction serialization and parsing
- Reconciliation calculations
"""

from decimal import Decimal
from datetime import date, datetime

from gledger.models.account import Account
from gledger.models.balance_history import BalanceSnapshot
from gledger.models.enums import AccountType
from gledger.repositories.sheet_repo import SheetRepository
from unittest.mock import Mock


class TestZeroBalanceSerialization:
    """Test that zero balances are properly serialized to sheets."""

    def test_account_zero_balance_serialization(self):
        """Test that account with $0.00 balance serializes correctly."""
        repo = SheetRepository(Mock())

        account = Account(
            sf_account_id="ACC123",
            enabled=True,
            ignored=False,
            display_name="Test Account",
            account_type=AccountType.CHECKING,
            balance=Decimal("0"),
            available_balance=Decimal("0"),
            balance_date=datetime(2024, 1, 1),
            reconcile_date=date(2024, 1, 1),
        )

        row = repo._serialize_account(account)

        # Balance should be 0.0 (float), not empty string
        assert row[8] == 0.0, f"Expected 0.0, got {row[8]}"
        assert row[9] == 0.0, f"Expected 0.0, got {row[9]}"

    def test_account_none_balance_serialization(self):
        """Test that account with None balance serializes to empty string."""
        repo = SheetRepository(Mock())

        account = Account(
            sf_account_id="ACC123",
            enabled=True,
            ignored=False,
            display_name="Test Account",
            account_type=AccountType.CHECKING,
            balance=None,
            available_balance=None,
        )

        row = repo._serialize_account(account)

        # None should serialize to empty string
        assert row[8] == "", f"Expected empty string, got {row[8]}"
        assert row[9] == "", f"Expected empty string, got {row[9]}"

    def test_balance_snapshot_zero_balance_serialization(self):
        """Test that balance snapshot with $0.00 serializes correctly."""
        repo = SheetRepository(Mock())

        snapshot = BalanceSnapshot(
            sf_account_id="ACC123",
            account_name="Test Account",
            balance_date=date(2024, 1, 1),
            balance=Decimal("0"),
            available_balance=Decimal("0"),
            recorded_at=datetime(2024, 1, 1),
            source="simplefin",
            is_starting_balance=False,
        )

        row = repo._serialize_balance_snapshot(snapshot)

        # Balance should be 0.0 (float), not empty string
        assert row[4] == 0.0, f"Expected 0.0, got {row[4]}"
        assert row[5] == 0.0, f"Expected 0.0, got {row[5]}"


class TestZeroBalanceParsing:
    """Test that zero balances are properly parsed from sheets."""

    def test_account_zero_balance_parsing_from_float(self):
        """Test parsing account with numeric 0 from sheet."""
        repo = SheetRepository(Mock())

        # Simulate Google Sheets returning numeric 0
        row = [
            "ACC123",
            True,
            False,
            "institution",
            "org",
            "Test Account",
            "checking",
            "USD",
            0.0,  # balance as float
            0,  # available_balance as int
            "2024-01-01",
            "2024-01-01T00:00:00",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ]

        account = repo._parse_account_row(row, sheet_row_index=2)

        # Should parse as Decimal("0"), not None
        assert account.balance == Decimal("0"), f"Expected Decimal('0'), got {account.balance}"
        assert account.available_balance == Decimal(
            "0"
        ), f"Expected Decimal('0'), got {account.available_balance}"
        assert account.balance is not None, "Balance should not be None"

    def test_account_zero_balance_parsing_from_string(self):
        """Test parsing account with string "0" from sheet."""
        repo = SheetRepository(Mock())

        # Simulate Google Sheets returning string "0"
        row = [
            "ACC123",
            True,
            False,
            "institution",
            "org",
            "Test Account",
            "checking",
            "USD",
            "0",  # balance as string
            "0.00",  # available_balance as string
            "2024-01-01",
            "2024-01-01T00:00:00",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ]

        account = repo._parse_account_row(row, sheet_row_index=2)

        # Should parse as Decimal("0"), not None
        assert account.balance == Decimal("0")
        assert account.available_balance == Decimal("0")

    def test_account_empty_balance_parsing(self):
        """Test parsing account with empty balance from sheet."""
        repo = SheetRepository(Mock())

        # Simulate Google Sheets returning empty string
        row = [
            "ACC123",
            True,
            False,
            "institution",
            "org",
            "Test Account",
            "checking",
            "USD",
            "",  # balance as empty string
            "",  # available_balance as empty string
            "2024-01-01",
            "2024-01-01T00:00:00",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ]

        account = repo._parse_account_row(row, sheet_row_index=2)

        # Empty string should parse as None
        assert account.balance is None
        assert account.available_balance is None


class TestZeroBalanceReconciliation:
    """Test that zero balances work correctly in reconciliation."""

    def test_reconciliation_with_zero_starting_balance(self):
        """Test reconciliation calculation with $0.00 starting balance."""
        from gledger.models.balance_history import ReconciliationResult

        result = ReconciliationResult.compute(
            sf_account_id="ACC123",
            account_name="Test Account",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            starting_balance=Decimal("0"),
            ending_balance=Decimal("100"),
            transaction_sum=Decimal("100"),
            transaction_count=5,
        )

        # Should calculate correctly with zero starting balance
        assert result.starting_balance == Decimal("0")
        assert result.calculated_ending_balance == Decimal("100")
        assert result.discrepancy == Decimal("0")
        assert result.is_balanced is True

    def test_reconciliation_with_zero_ending_balance(self):
        """Test reconciliation calculation with $0.00 ending balance."""
        from gledger.models.balance_history import ReconciliationResult

        result = ReconciliationResult.compute(
            sf_account_id="ACC123",
            account_name="Test Account",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            starting_balance=Decimal("100"),
            ending_balance=Decimal("0"),
            transaction_sum=Decimal("-100"),
            transaction_count=5,
        )

        # Should calculate correctly with zero ending balance
        assert result.ending_balance == Decimal("0")
        assert result.calculated_ending_balance == Decimal("0")
        assert result.discrepancy == Decimal("0")
        assert result.is_balanced is True

    def test_suggest_starting_balance_returns_zero(self):
        """Test that suggest_starting_balance can return $0.00."""
        from gledger.services.reconciliation import ReconciliationService
        from gledger.models.transaction import Transaction
        from gledger.models.enums import RowRole, ReviewStatus

        mock_sheet_repo = Mock()

        # Mock transactions that sum to current balance
        mock_sheet_repo.read_transactions.return_value = [
            Transaction(
                sf_account_id="ACC123",
                txn_key="ACC123:TXN1",
                row_role=RowRole.BANK,
                date=date(2024, 1, 15),
                amount=Decimal("100"),
                payee="Test",
                memo="",
                category="Test",
                account_name="Test Account",
                review_status=ReviewStatus.OK,
                needs_attention=False,
            )
        ]

        service = ReconciliationService(mock_sheet_repo)

        account = Account(
            sf_account_id="ACC123",
            enabled=True,
            ignored=False,
            display_name="Test Account",
            account_type=AccountType.CHECKING,
            balance=Decimal("100"),  # Current balance = transaction sum, so starting = 0
        )

        suggested = service.suggest_starting_balance(account)

        # Should suggest $0.00, not None
        assert suggested is not None, "Should return a value, not None"
        assert suggested == Decimal("0"), f"Expected Decimal('0'), got {suggested}"


class TestZeroBalanceRoundTrip:
    """Test that zero balances survive round-trip through serialize/parse."""

    def test_account_zero_balance_round_trip(self):
        """Test account with $0.00 balance survives serialize -> parse."""
        repo = SheetRepository(Mock())

        original = Account(
            sf_account_id="ACC123",
            enabled=True,
            ignored=False,
            display_name="Test Account",
            account_type=AccountType.CHECKING,
            balance=Decimal("0"),
            available_balance=Decimal("0"),
            balance_date=datetime(2024, 1, 1),
        )

        # Serialize
        row = repo._serialize_account(original)

        # Parse back
        parsed = repo._parse_account_row(row, sheet_row_index=2)

        # Should be identical
        assert parsed.balance == Decimal("0")
        assert parsed.available_balance == Decimal("0")
        assert parsed.balance is not None
        assert parsed.available_balance is not None
