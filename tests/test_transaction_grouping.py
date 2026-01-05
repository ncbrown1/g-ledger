"""Tests for transaction grouping logic."""

from decimal import Decimal
from datetime import date

from gledger.models.transaction import Transaction
from gledger.models.enums import RowRole, ReviewStatus
from gledger.services.review_engine import group_transactions_by_key


class TestTransactionGrouping:
    """Test transaction grouping by txn_key."""

    def test_group_bank_only(self):
        """Test grouping with only BANK row."""
        txns = [
            Transaction(
                sf_account_id="ACC123",
                sf_txn_id="TXN456",
                txn_key="ACC123:TXN456",
                row_role=RowRole.BANK,
                sf_date=date(2024, 1, 15),
                sf_amount=Decimal("-50.00"),
                date=date(2024, 1, 15),
                amount=Decimal("0"),
                payee="Test",
                review_status=ReviewStatus.NEW,
            )
        ]

        groups = group_transactions_by_key(txns)

        assert len(groups) == 1
        assert "ACC123:TXN456" in groups
        group = groups["ACC123:TXN456"]
        assert group.bank_row is not None
        assert len(group.split_rows) == 0
        assert group.has_splits is False

    def test_group_bank_with_splits(self):
        """Test grouping BANK row with SPLIT rows."""
        txns = [
            Transaction(
                sf_account_id="ACC123",
                sf_txn_id="TXN456",
                txn_key="ACC123:TXN456",
                row_role=RowRole.BANK,
                sf_date=date(2024, 1, 15),
                sf_amount=Decimal("-100.00"),
                date=date(2024, 1, 15),
                amount=Decimal("0"),
                payee="Test",
                review_status=ReviewStatus.NEW,
            ),
            Transaction(
                sf_account_id="ACC123",
                sf_txn_id=None,
                txn_key="ACC123:TXN456",
                row_role=RowRole.SPLIT,
                date=date(2024, 1, 15),
                amount=Decimal("-60.00"),
                payee="Test",
                category="Expenses:Groceries",
                review_status=ReviewStatus.NEW,
            ),
            Transaction(
                sf_account_id="ACC123",
                sf_txn_id=None,
                txn_key="ACC123:TXN456",
                row_role=RowRole.SPLIT,
                date=date(2024, 1, 15),
                amount=Decimal("-40.00"),
                payee="Test",
                category="Expenses:Dining",
                review_status=ReviewStatus.NEW,
            ),
        ]

        groups = group_transactions_by_key(txns)

        assert len(groups) == 1
        group = groups["ACC123:TXN456"]
        assert group.bank_row is not None
        assert len(group.split_rows) == 2
        assert group.has_splits is True
        assert group.split_sum == Decimal("-100.00")

    def test_group_multiple_keys(self):
        """Test grouping multiple transaction keys."""
        txns = [
            Transaction(
                sf_account_id="ACC123",
                sf_txn_id="TXN1",
                txn_key="ACC123:TXN1",
                row_role=RowRole.BANK,
                sf_date=date(2024, 1, 15),
                sf_amount=Decimal("-50.00"),
                date=date(2024, 1, 15),
                amount=Decimal("0"),
                payee="Test 1",
                review_status=ReviewStatus.NEW,
            ),
            Transaction(
                sf_account_id="ACC123",
                sf_txn_id="TXN2",
                txn_key="ACC123:TXN2",
                row_role=RowRole.BANK,
                sf_date=date(2024, 1, 16),
                sf_amount=Decimal("-75.00"),
                date=date(2024, 1, 16),
                amount=Decimal("0"),
                payee="Test 2",
                review_status=ReviewStatus.NEW,
            ),
        ]

        groups = group_transactions_by_key(txns)

        assert len(groups) == 2
        assert "ACC123:TXN1" in groups
        assert "ACC123:TXN2" in groups

    def test_group_manual_transaction(self):
        """Test grouping MANUAL transaction."""
        txns = [
            Transaction(
                sf_account_id="",
                sf_txn_id=None,
                txn_key="MANUAL:2024-01-15-cash",
                row_role=RowRole.MANUAL,
                date=date(2024, 1, 15),
                amount=Decimal("-25.00"),
                payee="Cash Purchase",
                category="Expenses:Dining",
                review_status=ReviewStatus.NEW,
            )
        ]

        groups = group_transactions_by_key(txns)

        assert len(groups) == 1
        assert "MANUAL:2024-01-15-cash" in groups
        group = groups["MANUAL:2024-01-15-cash"]
        assert group.bank_row is None
        assert len(group.manual_rows) == 1
