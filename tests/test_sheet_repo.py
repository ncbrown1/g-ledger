"""Tests for sheet repository serialization and parsing.

These tests ensure that:
- All data types are correctly serialized to sheet format
- All data types are correctly parsed from sheet format
- Edge cases (empty, None, zero) are handled correctly
- Date parsing handles multiple formats (string, int, datetime)
"""

from decimal import Decimal
from datetime import date, datetime
from unittest.mock import Mock

from gledger.models.account import Account
from gledger.models.transaction import Transaction
from gledger.models.enums import AccountType, RowRole, ReviewStatus
from gledger.repositories.sheet_repo import SheetRepository


class TestAccountSerialization:
    """Test account serialization to sheet format."""

    def test_serialize_complete_account(self):
        """Test serializing account with all fields populated."""
        repo = SheetRepository(Mock())

        account = Account(
            sf_account_id="ACC123",
            enabled=True,
            ignored=False,
            institution="bank.com",
            sf_org_name="Bank Name",
            display_name="My Checking",
            account_type=AccountType.CHECKING,
            currency="USD",
            balance=Decimal("1234.56"),
            available_balance=Decimal("1200.00"),
            balance_date=datetime(2024, 1, 15, 10, 30),
            last_synced_at=datetime(2024, 1, 15, 11, 0),
            reconcile_date=date(2024, 1, 1),
            starting_balance=Decimal("1000.00"),
            starting_balance_date=date(2024, 1, 1),
            expected_balance=Decimal("1234.56"),
            balance_discrepancy=Decimal("0.00"),
            reconciliation_status_text="OK",
            notes="Test account",
        )

        row = repo._serialize_account(account)

        assert row[0] == "ACC123"
        assert row[1] is True
        assert row[2] is False
        assert row[3] == "bank.com"
        assert row[4] == "Bank Name"
        assert row[5] == "My Checking"
        assert row[6] == "checking"
        assert row[7] == "USD"
        assert row[8] == 1234.56  # balance as float
        assert row[9] == 1200.00  # available_balance as float
        assert row[10] == "2024-01-15T10:30:00"  # balance_date ISO
        assert row[11] == "2024-01-15T11:00:00"  # last_synced_at ISO
        assert row[12] == "2024-01-01"  # reconcile_date ISO
        assert row[13] == 1000.00  # starting_balance as float
        assert row[14] == "2024-01-01"  # starting_balance_date ISO
        assert row[15] == 1234.56  # expected_balance as float
        assert row[16] == 0.00  # balance_discrepancy as float
        assert row[17] == "OK"
        assert row[18] == "Test account"

    def test_serialize_account_with_none_values(self):
        """Test serializing account with None/optional fields."""
        repo = SheetRepository(Mock())

        account = Account(
            sf_account_id="ACC123",
            enabled=True,
            ignored=False,
            display_name="Minimal Account",
            account_type=AccountType.CHECKING,
            # All optional fields are None
        )

        row = repo._serialize_account(account)

        assert row[0] == "ACC123"
        assert row[3] == ""  # institution
        assert row[8] == ""  # balance (None -> empty)
        assert row[9] == ""  # available_balance
        assert row[10] == ""  # balance_date
        assert row[12] == ""  # reconcile_date

    def test_serialize_ignored_account_shows_zero_balance(self):
        """Test that ignored accounts serialize with $0.00 balance."""
        repo = SheetRepository(Mock())

        account = Account(
            sf_account_id="ACC123",
            enabled=True,
            ignored=True,  # Ignored account
            display_name="Ignored Account",
            account_type=AccountType.CHECKING,
            balance=Decimal("5000"),  # Has balance but ignored
        )

        row = repo._serialize_account(account)

        # Balance should be 0.0, not 5000
        assert row[8] == 0.0
        assert row[9] == 0.0


class TestAccountParsing:
    """Test account parsing from sheet format."""

    def test_parse_complete_account_row(self):
        """Test parsing account with all fields."""
        repo = SheetRepository(Mock())

        row = [
            "ACC123",
            True,
            False,
            "bank.com",
            "Bank Name",
            "My Checking",
            "checking",
            "USD",
            1234.56,
            1200.00,
            "2024-01-15T10:30:00",
            "2024-01-15T11:00:00",
            "2024-01-01",
            1000.00,
            "2024-01-01",
            1234.56,
            0.00,
            "OK",
            "Test account",
        ]

        account = repo._parse_account_row(row, sheet_row_index=2)

        assert account.sf_account_id == "ACC123"
        assert account.enabled is True
        assert account.ignored is False
        assert account.institution == "bank.com"
        assert account.display_name == "My Checking"
        assert account.balance == Decimal("1234.56")
        assert account.reconcile_date == date(2024, 1, 1)
        assert account.starting_balance == Decimal("1000.00")

    def test_parse_row_with_empty_strings(self):
        """Test parsing row with empty string values."""
        repo = SheetRepository(Mock())

        row = [
            "ACC123",
            True,
            False,
            "",
            "",
            "Account",
            "checking",
            "USD",
            "",
            "",  # Empty balance fields
            "",
            "",  # Empty date fields
            "",  # Empty reconcile_date
            "",
            "",  # Empty starting balance fields
            "",
            "",
            "",
            "",
        ]

        account = repo._parse_account_row(row, sheet_row_index=2)

        assert account.balance is None
        assert account.available_balance is None
        assert account.balance_date is None
        assert account.reconcile_date is None
        assert account.starting_balance is None

    def test_parse_short_row_pads_with_empty(self):
        """Test that short rows are padded with empty strings."""
        repo = SheetRepository(Mock())

        # Row with only first 6 fields (through display_name)
        row = ["ACC123", True, False, "bank.com", "org", "Name"]

        account = repo._parse_account_row(row, sheet_row_index=2)

        # Should not raise error, should use defaults
        assert account.sf_account_id == "ACC123"
        assert account.display_name == "Name"
        assert account.balance is None


class TestTransactionSerialization:
    """Test transaction serialization to sheet format."""

    def test_serialize_bank_transaction(self):
        """Test serializing a BANK row transaction."""
        repo = SheetRepository(Mock())

        txn = Transaction(
            sf_account_id="ACC123",
            sf_txn_id="TXN456",
            txn_key="ACC123:TXN456",
            row_role=RowRole.BANK,
            date=date(2024, 1, 15),
            amount=Decimal("-50.00"),
            payee="Store",
            memo="Purchase",
            category="Shopping",
            tags="tag1 tag2",
            account_name="Checking",
            account_type="checking",
            review_status=ReviewStatus.OK,
            review_notes="",
            needs_attention=False,
            sf_date=date(2024, 1, 15),
            sf_amount=Decimal("-50.00"),
            sf_payee="Store Inc",
            sf_memo="POS Purchase",
            sf_imported_at=datetime(2024, 1, 16, 10, 0),
            sf_last_seen_at=datetime(2024, 1, 16, 10, 0),
        )

        row = repo._serialize_transaction(txn)

        assert row[0] == "2024-01-15"  # date
        assert row[1] == ""  # accounting_month (formula)
        assert row[2] == -50.00  # amount
        assert row[3] == "Store"  # payee
        assert row[4] == "Purchase"  # memo
        assert row[5] == "Shopping"  # category
        assert row[6] == "tag1 tag2"  # tags
        assert row[7] == "Checking"  # account_name
        assert row[8] == "checking"  # account_type
        assert row[9] == "OK"  # review_status
        assert row[10] == ""  # review_notes
        assert row[11] is False  # needs_attention
        assert row[12] == "BANK"  # row_role
        assert row[13] == "ACC123:TXN456"  # txn_key

    def test_serialize_transaction_with_zero_amount(self):
        """Test serializing transaction with $0.00 amount."""
        repo = SheetRepository(Mock())

        txn = Transaction(
            sf_account_id="ACC123",
            txn_key="ACC123:TXN456",
            row_role=RowRole.BANK,
            date=date(2024, 1, 15),
            amount=Decimal("0"),  # Zero amount
            payee="Store",
            memo="",
            category="",
            account_name="Checking",
            review_status=ReviewStatus.OK,
            needs_attention=False,
        )

        row = repo._serialize_transaction(txn)

        # Should be 0.0, not empty string
        assert row[2] == 0.0

    def test_serialize_transaction_with_none_sf_amount(self):
        """Test serializing transaction with None sf_amount (MANUAL row)."""
        repo = SheetRepository(Mock())

        txn = Transaction(
            sf_account_id="",
            txn_key="MANUAL:123",
            row_role=RowRole.MANUAL,
            date=date(2024, 1, 15),
            amount=Decimal("-25.00"),
            payee="Cash",
            memo="",
            category="Cash",
            account_name="Manual",
            review_status=ReviewStatus.OK,
            needs_attention=False,
            sf_amount=None,  # Manual row has no SimpleFIN amount
        )

        row = repo._serialize_transaction(txn)

        # sf_amount (index 16) should be empty string
        assert row[16] == ""


class TestDateParsing:
    """Test date parsing helper methods."""

    def test_parse_date_from_iso_string(self):
        """Test parsing ISO format date string."""
        repo = SheetRepository(Mock())

        result = repo._parse_date("2024-01-15")

        assert result == date(2024, 1, 15)

    def test_parse_date_from_excel_serial(self):
        """Test parsing Excel serial number."""
        repo = SheetRepository(Mock())

        # Excel serial 45310 = 2024-01-15 approximately
        result = repo._parse_date(45310)

        assert result is not None
        assert isinstance(result, date)

    def test_parse_date_from_datetime_object(self):
        """Test parsing datetime object extracts the date."""
        repo = SheetRepository(Mock())

        dt = datetime(2024, 1, 15, 10, 30)
        result = repo._parse_date(dt)

        # Should extract the date from datetime
        assert result == date(2024, 1, 15) or result.date() == date(2024, 1, 15)
        assert isinstance(result, (date, datetime))

    def test_parse_date_from_date_object(self):
        """Test parsing date object."""
        repo = SheetRepository(Mock())

        d = date(2024, 1, 15)
        result = repo._parse_date(d)

        assert result == date(2024, 1, 15)

    def test_parse_date_from_empty_string(self):
        """Test parsing empty string returns None."""
        repo = SheetRepository(Mock())

        result = repo._parse_date("")

        assert result is None

    def test_parse_datetime_from_iso_string(self):
        """Test parsing ISO datetime string."""
        repo = SheetRepository(Mock())

        result = repo._parse_datetime("2024-01-15T10:30:00")

        assert result == datetime(2024, 1, 15, 10, 30, 0)

    def test_parse_datetime_from_excel_serial(self):
        """Test parsing Excel serial number as datetime."""
        repo = SheetRepository(Mock())

        # Excel serial with time component
        result = repo._parse_datetime(45310.5)  # .5 = noon

        assert result is not None
        assert isinstance(result, datetime)
        # Time should be around noon
        assert 11 <= result.hour <= 13


class TestBoolParsing:
    """Test boolean parsing from various formats."""

    def test_parse_bool_true_values(self):
        """Test parsing various truthy values."""
        repo = SheetRepository(Mock())

        assert repo._parse_bool(True, default=False) is True
        assert repo._parse_bool("TRUE", default=False) is True
        assert repo._parse_bool("true", default=False) is True
        assert repo._parse_bool("yes", default=False) is True
        assert repo._parse_bool("1", default=False) is True
        assert repo._parse_bool(1, default=False) is True

    def test_parse_bool_false_values(self):
        """Test parsing various falsy values."""
        repo = SheetRepository(Mock())

        assert repo._parse_bool(False, default=True) is False
        assert repo._parse_bool("FALSE", default=True) is False
        assert repo._parse_bool("false", default=True) is False
        assert repo._parse_bool("no", default=True) is False
        assert repo._parse_bool("0", default=True) is False
        assert repo._parse_bool(0, default=True) is False

    def test_parse_bool_empty_uses_default(self):
        """Test parsing empty value uses default."""
        repo = SheetRepository(Mock())

        assert repo._parse_bool("", default=True) is True
        assert repo._parse_bool("", default=False) is False
        assert repo._parse_bool(None, default=True) is True
