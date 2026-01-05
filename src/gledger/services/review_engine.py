"""Review engine for computing transaction review status."""

from decimal import Decimal
from typing import Optional

from ..models.transaction import Transaction, TransactionGroup
from ..models.category import Category
from ..models.enums import ReviewStatus, RowRole
from ..utils.validation import is_amount_equal
from ..utils.logging import get_logger

logger = get_logger(__name__)


class ReviewEngine:
    """Computes review status for transaction groups.

    Validates splits, checks for missing categories, detects bank changes,
    and respects reconciled status.
    """

    def __init__(self, categories: list[Category]):
        """Initialize review engine.

        Args:
            categories: List of valid categories
        """
        self.valid_categories = {cat.category for cat in categories if cat.active}
        logger.debug(f"Initialized ReviewEngine with {len(self.valid_categories)} valid categories")

    def compute_review_for_group(
        self, group: TransactionGroup, import_data: Optional[dict] = None
    ) -> tuple[ReviewStatus, Optional[str], bool]:
        """Compute review status for a transaction group.

        Args:
            group: TransactionGroup to review
            import_data: Optional dict with sf_* fields from latest import
                        (to detect bank changes)

        Returns:
            Tuple of (review_status, review_notes, needs_attention)

        Logic:
        1. Check for INVALID (missing required fields)
        2. Check for SPLIT_MISMATCH (split sum != sf_amount)
        3. Check for BANK_CHANGED (sf_* fields changed)
        4. Check for MISSING_CATEGORY
        5. Otherwise: OK

        Note: Reconciliation is handled separately via account reconcile_date comparison.
        """
        # Check for INVALID (missing required fields)
        invalid_status = self._check_invalid(group)
        if invalid_status:
            return invalid_status

        # For MANUAL rows, different logic
        if group.manual_rows:
            # Manual transactions don't have bank data
            return self._review_manual_group(group)

        # BANK row logic
        if not group.bank_row:
            # No bank row but has splits? Invalid
            if group.split_rows:
                return (ReviewStatus.INVALID, "Split rows exist without BANK row", True)
            return ReviewStatus.OK, None, False

        bank_row = group.bank_row

        # Check for SPLIT_MISMATCH
        if group.has_splits:
            mismatch_status = self._check_split_mismatch(group)
            if mismatch_status:
                return mismatch_status

        # Check for BANK_CHANGED
        if import_data:
            changed_status = self._check_bank_changed(bank_row, import_data)
            if changed_status:
                return changed_status

        # Check for MISSING_CATEGORY
        missing_cat_status = self._check_missing_category(group)
        if missing_cat_status:
            return missing_cat_status

        # All checks passed
        return ReviewStatus.OK, None, False

    def _check_invalid(self, group: TransactionGroup) -> Optional[tuple[ReviewStatus, str, bool]]:
        """Check if group has invalid/missing required fields.

        Returns:
            (ReviewStatus.INVALID, notes, True) if invalid, else None
        """
        issues = []

        # Check each row
        for row in group.all_rows:
            if row.row_role == RowRole.BANK:
                # BANK row must have date, payee
                if not row.date:
                    issues.append("BANK row missing date")
                if not row.payee:
                    issues.append("BANK row missing payee")
                # If no splits, must have category
                if not group.has_splits and not row.category:
                    issues.append("BANK row missing category (no splits)")

            elif row.row_role == RowRole.SPLIT:
                # SPLIT row must have category and amount
                if not row.category:
                    issues.append("SPLIT row missing category")
                if row.amount == Decimal("0"):
                    issues.append("SPLIT row has zero amount")

            elif row.row_role == RowRole.MANUAL:
                # MANUAL row must have date, amount, category
                if not row.date:
                    issues.append("MANUAL row missing date")
                if not row.category:
                    issues.append("MANUAL row missing category")
                if row.amount == Decimal("0"):
                    issues.append("MANUAL row has zero amount")

        if issues:
            notes = "; ".join(issues)
            return ReviewStatus.INVALID, notes, True

        return None

    def _check_split_mismatch(
        self, group: TransactionGroup
    ) -> Optional[tuple[ReviewStatus, str, bool]]:
        """Check if split amounts sum to bank amount.

        Args:
            group: TransactionGroup with splits

        Returns:
            (ReviewStatus.SPLIT_MISMATCH, notes, True) if mismatch, else None
        """
        if not group.has_splits or not group.bank_row:
            return None

        sf_amount = group.bank_row.sf_amount
        if sf_amount is None:
            return ReviewStatus.INVALID, "BANK row missing sf_amount", True

        split_sum = group.split_sum

        if not is_amount_equal(split_sum, sf_amount):
            notes = f"Split sum {split_sum} != bank amount {sf_amount}"
            return ReviewStatus.SPLIT_MISMATCH, notes, True

        return None

    def _check_bank_changed(
        self, bank_row: Transaction, import_data: dict
    ) -> Optional[tuple[ReviewStatus, str, bool]]:
        """Check if bank snapshot fields changed from import.

        Args:
            bank_row: BANK row to check
            import_data: Dict with sf_* fields from latest import

        Returns:
            (ReviewStatus.BANK_CHANGED, notes, True) if changed, else None
        """
        changes = []

        # Compare sf_* fields
        if bank_row.sf_date != import_data.get("sf_date"):
            changes.append("date")
        if float(bank_row.sf_amount or 0) != float(import_data.get("sf_amount", 0) or 0):
            changes.append(f"amount ({bank_row.sf_amount} != {import_data.get('sf_amount')})")
        if (bank_row.sf_payee or "") != (import_data.get("sf_payee") or ""):
            changes.append(f"payee ({bank_row.sf_payee} != {import_data.get('sf_payee')})")
        if (bank_row.sf_memo or "") != (import_data.get("sf_memo") or ""):
            changes.append(f"memo ({bank_row.sf_memo} != {import_data.get('sf_memo')})")

        if changes:
            notes = f"Bank data changed: {', '.join(changes)}"
            return ReviewStatus.BANK_CHANGED, notes, True

        return None

    def _check_missing_category(
        self, group: TransactionGroup
    ) -> Optional[tuple[ReviewStatus, str, bool]]:
        """Check if transaction is missing category or has invalid category.

        Args:
            group: TransactionGroup to check

        Returns:
            (ReviewStatus.MISSING_CATEGORY, notes, True) if missing, else None
        """
        # For splits, check all split rows
        if group.has_splits:
            for split in group.split_rows:
                if not split.category:
                    return (ReviewStatus.MISSING_CATEGORY, "Split row missing category", True)
                if not self._is_valid_category(split.category):
                    return (
                        ReviewStatus.MISSING_CATEGORY,
                        f"Invalid category: {split.category}",
                        True,
                    )
        else:
            # Check BANK row category
            if group.bank_row:
                if not group.bank_row.category:
                    return (ReviewStatus.MISSING_CATEGORY, "Transaction missing category", True)
                if group.bank_row.category == "Expenses:Uncategorized":
                    return (ReviewStatus.MISSING_CATEGORY, "Category is Uncategorized", True)
                if not self._is_valid_category(group.bank_row.category):
                    return (
                        ReviewStatus.MISSING_CATEGORY,
                        f"Invalid category: {group.bank_row.category}",
                        True,
                    )

        return None

    def _review_manual_group(
        self, group: TransactionGroup
    ) -> tuple[ReviewStatus, Optional[str], bool]:
        """Review a MANUAL transaction group.

        Args:
            group: TransactionGroup with manual rows

        Returns:
            Tuple of (review_status, review_notes, needs_attention)
        """
        # Manual transactions don't have splits in v1, just validate fields
        for manual in group.manual_rows:
            if not manual.category:
                return (ReviewStatus.MISSING_CATEGORY, "Manual transaction missing category", True)
            if not self._is_valid_category(manual.category):
                return (ReviewStatus.MISSING_CATEGORY, f"Invalid category: {manual.category}", True)

        return ReviewStatus.OK, None, False

    def _is_valid_category(self, category: str) -> bool:
        """Check if category is in valid categories list.

        Args:
            category: Category string

        Returns:
            True if valid
        """
        return category in self.valid_categories


def group_transactions_by_key(transactions: list[Transaction]) -> dict[str, TransactionGroup]:
    """Group transactions by txn_key.

    Args:
        transactions: List of Transaction objects

    Returns:
        Dict mapping txn_key to TransactionGroup
    """
    groups: dict[str, TransactionGroup] = {}

    for txn in transactions:
        if txn.txn_key not in groups:
            groups[txn.txn_key] = TransactionGroup(txn_key=txn.txn_key)

        group = groups[txn.txn_key]

        if txn.row_role == RowRole.BANK:
            group.bank_row = txn
        elif txn.row_role == RowRole.SPLIT:
            group.split_rows.append(txn)
        elif txn.row_role == RowRole.MANUAL:
            group.manual_rows.append(txn)

    return groups
