"""Tests for review engine."""

import pytest
from decimal import Decimal
from datetime import date

from gledger.models.transaction import Transaction, TransactionGroup
from gledger.models.category import Category
from gledger.models.enums import RowRole, ReviewStatus
from gledger.services.review_engine import ReviewEngine


class TestReviewEngine:
    """Test review engine functionality."""

    @pytest.fixture
    def categories(self):
        """Create test categories."""
        return [
            Category(category="Expenses:Groceries", active=True),
            Category(category="Expenses:Dining", active=True),
            Category(category="Income:Salary", active=True),
            Category(category="Assets:Cash", active=True),
        ]

    @pytest.fixture
    def review_engine(self, categories):
        """Create review engine with test categories."""
        return ReviewEngine(categories)

    def test_split_mismatch(self, review_engine):
        """Test split sum validation."""
        # Create BANK row
        bank_row = Transaction(
            sf_account_id="ACC123",
            sf_txn_id="TXN456",
            txn_key="ACC123:TXN456",
            row_role=RowRole.BANK,
            sf_date=date(2024, 1, 15),
            sf_amount=Decimal("-100.00"),
            sf_payee="Test Store",
            date=date(2024, 1, 15),
            amount=Decimal("0"),  # BANK row has 0 when splits exist
            payee="Test Store",
            category="Expenses:Groceries",
            review_status=ReviewStatus.NEW,
        )

        # Create SPLIT rows that don't sum correctly
        split1 = Transaction(
            sf_account_id="ACC123",
            sf_txn_id=None,
            txn_key="ACC123:TXN456",
            row_role=RowRole.SPLIT,
            date=date(2024, 1, 15),
            amount=Decimal("-60.00"),
            payee="Test Store",
            category="Expenses:Groceries",
            review_status=ReviewStatus.NEW,
        )

        split2 = Transaction(
            sf_account_id="ACC123",
            sf_txn_id=None,
            txn_key="ACC123:TXN456",
            row_role=RowRole.SPLIT,
            date=date(2024, 1, 15),
            amount=Decimal("-30.00"),  # Total -90, but should be -100
            payee="Test Store",
            category="Expenses:Dining",
            review_status=ReviewStatus.NEW,
        )

        group = TransactionGroup(
            txn_key="ACC123:TXN456", bank_row=bank_row, split_rows=[split1, split2]
        )

        status, notes, needs_attention = review_engine.compute_review_for_group(group)

        assert status == ReviewStatus.SPLIT_MISMATCH
        assert needs_attention is True
        assert "sum" in notes.lower()

    def test_split_valid(self, review_engine):
        """Test valid split sum."""
        # Create BANK row
        bank_row = Transaction(
            sf_account_id="ACC123",
            sf_txn_id="TXN456",
            txn_key="ACC123:TXN456",
            row_role=RowRole.BANK,
            sf_date=date(2024, 1, 15),
            sf_amount=Decimal("-100.00"),
            sf_payee="Test Store",
            date=date(2024, 1, 15),
            amount=Decimal("0"),
            payee="Test Store",
            category="Expenses:Groceries",
            review_status=ReviewStatus.NEW,
        )

        # Create SPLIT rows that sum correctly
        split1 = Transaction(
            sf_account_id="ACC123",
            sf_txn_id=None,
            txn_key="ACC123:TXN456",
            row_role=RowRole.SPLIT,
            date=date(2024, 1, 15),
            amount=Decimal("-60.00"),
            payee="Test Store",
            category="Expenses:Groceries",
            review_status=ReviewStatus.NEW,
        )

        split2 = Transaction(
            sf_account_id="ACC123",
            sf_txn_id=None,
            txn_key="ACC123:TXN456",
            row_role=RowRole.SPLIT,
            date=date(2024, 1, 15),
            amount=Decimal("-40.00"),  # Total -100, matches!
            payee="Test Store",
            category="Expenses:Dining",
            review_status=ReviewStatus.NEW,
        )

        group = TransactionGroup(
            txn_key="ACC123:TXN456", bank_row=bank_row, split_rows=[split1, split2]
        )

        status, notes, needs_attention = review_engine.compute_review_for_group(group)

        assert status == ReviewStatus.OK
        assert needs_attention is False

    def test_new_transaction(self, review_engine):
        """Test MISSING_CATEGORY status for uncategorized transaction."""
        bank_row = Transaction(
            sf_account_id="ACC123",
            sf_txn_id="TXN456",
            txn_key="ACC123:TXN456",
            row_role=RowRole.BANK,
            sf_date=date(2024, 1, 15),
            sf_amount=Decimal("-50.00"),
            sf_payee="Test Store",
            date=date(2024, 1, 15),
            amount=Decimal("-50.00"),
            payee="Test Store",
            category="Expenses:Uncategorized",  # Still default
            review_status=ReviewStatus.NEW,
        )

        group = TransactionGroup(txn_key="ACC123:TXN456", bank_row=bank_row)

        status, notes, needs_attention = review_engine.compute_review_for_group(group)

        assert status == ReviewStatus.MISSING_CATEGORY
        assert needs_attention is True
        assert "Uncategorized" in notes

    def test_properly_categorized_transaction(self, review_engine):
        """Test that properly categorized transactions return OK status."""
        bank_row = Transaction(
            sf_account_id="ACC123",
            sf_txn_id="TXN456",
            txn_key="ACC123:TXN456",
            row_role=RowRole.BANK,
            sf_date=date(2024, 1, 15),
            sf_amount=Decimal("-50.00"),
            sf_payee="Test Store",
            date=date(2024, 1, 15),
            amount=Decimal("-50.00"),
            payee="Test Store",
            category="Expenses:Groceries",  # Valid category
            review_status=ReviewStatus.OK,
        )

        group = TransactionGroup(txn_key="ACC123:TXN456", bank_row=bank_row)

        status, notes, needs_attention = review_engine.compute_review_for_group(group)

        # Should be OK because properly categorized
        assert status == ReviewStatus.OK
        assert needs_attention is False
