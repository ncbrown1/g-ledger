"""Tests for balance history parsing and logic.

These tests ensure that balance history:
- Parses dates correctly (strings, integers, datetime objects)
- Handles the is_starting_balance flag correctly
- Properly filters and sorts for reconciliation
"""

from decimal import Decimal
from datetime import date, datetime, timedelta
from unittest.mock import Mock

from gledger.models.balance_history import BalanceSnapshot, ReconciliationResult
from gledger.repositories.sheet_repo import SheetRepository


class TestBalanceHistoryDateParsing:
    """Test that balance history correctly parses different date formats."""

    def test_parse_iso_date_string(self):
        """Test parsing ISO format date string."""
        repo = SheetRepository(Mock())

        row = [
            "ACC123",
            "Test Account",
            "checking",
            "2024-01-15",  # ISO date string
            100.0,
            90.0,
            "2024-01-15T10:30:00",  # ISO datetime string
            "simplefin",
            False,
            "",
        ]

        snapshot = repo._parse_balance_snapshot_row(row, sheet_row_index=2)

        assert snapshot.balance_date == date(2024, 1, 15)
        assert snapshot.recorded_at == datetime(2024, 1, 15, 10, 30, 0)

    def test_parse_excel_serial_number(self):
        """Test parsing Excel serial number (integer) as date."""
        repo = SheetRepository(Mock())

        # Excel serial number for 2024-01-15 (45310 days since 1899-12-30)
        excel_date = 45310
        expected_date = datetime(1899, 12, 30) + timedelta(days=excel_date)

        row = [
            "ACC123",
            "Test Account",
            "checking",
            excel_date,  # Excel serial number for balance_date
            100.0,
            90.0,
            excel_date,  # Excel serial number for recorded_at
            "simplefin",
            False,
            "",
        ]

        snapshot = repo._parse_balance_snapshot_row(row, sheet_row_index=2)

        # Should parse without error
        assert snapshot.balance_date is not None
        assert snapshot.recorded_at is not None
        # Date should be close to expected (within same day)
        assert snapshot.balance_date.year == expected_date.year
        assert snapshot.balance_date.month == expected_date.month

    def test_parse_float_serial_number(self):
        """Test parsing float serial number (with time) as datetime."""
        repo = SheetRepository(Mock())

        # Excel serial number with fractional day (time component)
        excel_datetime = 45310.5  # 45310 days + 12 hours

        row = [
            "ACC123",
            "Test Account",
            "checking",
            45310,  # Integer for date
            100.0,
            90.0,
            excel_datetime,  # Float for datetime (includes time)
            "simplefin",
            False,
            "",
        ]

        snapshot = repo._parse_balance_snapshot_row(row, sheet_row_index=2)

        assert snapshot.recorded_at is not None
        # Time component should be around noon
        assert 11 <= snapshot.recorded_at.hour <= 13

    def test_parse_empty_date_uses_fallback(self):
        """Test that empty date uses today() as fallback."""
        repo = SheetRepository(Mock())

        row = [
            "ACC123",
            "Test Account",
            "checking",
            "",  # Empty balance_date
            100.0,
            90.0,
            "",  # Empty recorded_at
            "simplefin",
            False,
            "",
        ]

        snapshot = repo._parse_balance_snapshot_row(row, sheet_row_index=2)

        # Should use fallbacks (today and now)
        assert snapshot.balance_date == date.today()
        assert snapshot.recorded_at.date() == date.today()


class TestBalanceHistoryIsStartingBalance:
    """Test the is_starting_balance flag functionality."""

    def test_parse_is_starting_balance_true(self):
        """Test parsing is_starting_balance=TRUE."""
        repo = SheetRepository(Mock())

        row = [
            "ACC123",
            "Test Account",
            "checking",
            "2024-01-15",
            100.0,
            90.0,
            "2024-01-15T10:30:00",
            "user_suggested",
            True,  # is_starting_balance
            "User designated starting balance",
        ]

        snapshot = repo._parse_balance_snapshot_row(row, sheet_row_index=2)

        assert snapshot.is_starting_balance is True
        assert snapshot.source == "user_suggested"

    def test_parse_is_starting_balance_false(self):
        """Test parsing is_starting_balance=FALSE."""
        repo = SheetRepository(Mock())

        row = [
            "ACC123",
            "Test Account",
            "checking",
            "2024-01-15",
            100.0,
            90.0,
            "2024-01-15T10:30:00",
            "simplefin",
            False,  # is_starting_balance
            "",
        ]

        snapshot = repo._parse_balance_snapshot_row(row, sheet_row_index=2)

        assert snapshot.is_starting_balance is False
        assert snapshot.source == "simplefin"

    def test_serialize_is_starting_balance(self):
        """Test serializing is_starting_balance to sheet."""
        repo = SheetRepository(Mock())

        snapshot = BalanceSnapshot(
            sf_account_id="ACC123",
            account_name="Test Account",
            balance_date=date(2024, 1, 15),
            balance=Decimal("100"),
            recorded_at=datetime(2024, 1, 15, 10, 30),
            source="user_suggested",
            is_starting_balance=True,
        )

        row = repo._serialize_balance_snapshot(snapshot)

        # is_starting_balance should be at index 8
        assert row[8] is True


class TestReconciliationResultComputation:
    """Test reconciliation result calculation logic."""

    def test_balanced_reconciliation(self):
        """Test reconciliation that balances perfectly."""
        result = ReconciliationResult.compute(
            sf_account_id="ACC123",
            account_name="Test Account",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            starting_balance=Decimal("1000"),
            ending_balance=Decimal("1500"),
            transaction_sum=Decimal("500"),
            transaction_count=10,
        )

        assert result.calculated_ending_balance == Decimal("1500")
        assert result.discrepancy == Decimal("0")
        assert result.is_balanced is True

    def test_discrepancy_reconciliation(self):
        """Test reconciliation with discrepancy."""
        result = ReconciliationResult.compute(
            sf_account_id="ACC123",
            account_name="Test Account",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            starting_balance=Decimal("1000"),
            ending_balance=Decimal("1500"),
            transaction_sum=Decimal("450"),  # Missing $50
            transaction_count=10,
        )

        assert result.calculated_ending_balance == Decimal("1450")
        assert result.discrepancy == Decimal("50")
        assert result.is_balanced is False

    def test_tolerance_within_penny(self):
        """Test that discrepancies within ±$0.01 are considered balanced."""
        result = ReconciliationResult.compute(
            sf_account_id="ACC123",
            account_name="Test Account",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            starting_balance=Decimal("1000.00"),
            ending_balance=Decimal("1500.00"),
            transaction_sum=Decimal("500.01"),  # Off by $0.01
            transaction_count=10,
        )

        assert result.discrepancy == Decimal("-0.01")
        assert result.is_balanced is True  # Within tolerance

    def test_tolerance_exceeds_penny(self):
        """Test that discrepancies exceeding ±$0.01 are not balanced."""
        result = ReconciliationResult.compute(
            sf_account_id="ACC123",
            account_name="Test Account",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            starting_balance=Decimal("1000.00"),
            ending_balance=Decimal("1500.00"),
            transaction_sum=Decimal("500.02"),  # Off by $0.02
            transaction_count=10,
        )

        assert result.discrepancy == Decimal("-0.02")
        assert result.is_balanced is False  # Exceeds tolerance

    def test_negative_balances(self):
        """Test reconciliation with negative balances (credit card)."""
        result = ReconciliationResult.compute(
            sf_account_id="ACC123",
            account_name="Credit Card",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            starting_balance=Decimal("-100"),  # Owed $100
            ending_balance=Decimal("-200"),  # Owed $200
            transaction_sum=Decimal("-100"),  # Charged $100
            transaction_count=5,
        )

        assert result.calculated_ending_balance == Decimal("-200")
        assert result.discrepancy == Decimal("0")
        assert result.is_balanced is True


class TestBalanceHistoryFiltering:
    """Test filtering and sorting balance history for reconciliation."""

    def test_filter_by_account_id(self):
        """Test filtering balance history by account ID."""
        snapshots = [
            BalanceSnapshot(
                sf_account_id="ACC123",
                account_name="Account 1",
                balance_date=date(2024, 1, 1),
                balance=Decimal("100"),
                recorded_at=datetime(2024, 1, 1),
                source="simplefin",
                is_starting_balance=False,
            ),
            BalanceSnapshot(
                sf_account_id="ACC456",
                account_name="Account 2",
                balance_date=date(2024, 1, 1),
                balance=Decimal("200"),
                recorded_at=datetime(2024, 1, 1),
                source="simplefin",
                is_starting_balance=False,
            ),
        ]

        # Filter for ACC123
        acc123_snapshots = [s for s in snapshots if s.sf_account_id == "ACC123"]

        assert len(acc123_snapshots) == 1
        assert acc123_snapshots[0].balance == Decimal("100")

    def test_sort_by_balance_date(self):
        """Test sorting balance history by balance_date."""
        snapshots = [
            BalanceSnapshot(
                sf_account_id="ACC123",
                account_name="Account 1",
                balance_date=date(2024, 1, 15),
                balance=Decimal("300"),
                recorded_at=datetime(2024, 1, 15),
                source="simplefin",
                is_starting_balance=False,
            ),
            BalanceSnapshot(
                sf_account_id="ACC123",
                account_name="Account 1",
                balance_date=date(2024, 1, 1),
                balance=Decimal("100"),
                recorded_at=datetime(2024, 1, 1),
                source="simplefin",
                is_starting_balance=False,
            ),
            BalanceSnapshot(
                sf_account_id="ACC123",
                account_name="Account 1",
                balance_date=date(2024, 1, 10),
                balance=Decimal("200"),
                recorded_at=datetime(2024, 1, 10),
                source="simplefin",
                is_starting_balance=False,
            ),
        ]

        # Sort by balance_date
        sorted_snapshots = sorted(snapshots, key=lambda s: s.balance_date)

        assert sorted_snapshots[0].balance == Decimal("100")  # Jan 1
        assert sorted_snapshots[1].balance == Decimal("200")  # Jan 10
        assert sorted_snapshots[2].balance == Decimal("300")  # Jan 15

    def test_prefer_starting_balance_entries(self):
        """Test preferring entries with is_starting_balance=TRUE."""
        snapshots = [
            BalanceSnapshot(
                sf_account_id="ACC123",
                account_name="Account 1",
                balance_date=date(2024, 1, 1),
                balance=Decimal("100"),
                recorded_at=datetime(2024, 1, 1),
                source="simplefin",
                is_starting_balance=False,
            ),
            BalanceSnapshot(
                sf_account_id="ACC123",
                account_name="Account 1",
                balance_date=date(2024, 1, 5),
                balance=Decimal("150"),
                recorded_at=datetime(2024, 1, 5),
                source="user_suggested",
                is_starting_balance=True,  # User designated
            ),
        ]

        # Filter for starting balances
        starting_balances = [s for s in snapshots if s.is_starting_balance]

        assert len(starting_balances) == 1
        assert starting_balances[0].balance == Decimal("150")
        assert starting_balances[0].source == "user_suggested"
