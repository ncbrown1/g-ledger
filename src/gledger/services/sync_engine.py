"""Sync engine for orchestrating SimpleFIN to Google Sheets sync."""

import socket
import time
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Any, Optional
from pydantic import BaseModel

from ..config import Config
from ..models.account import Account
from ..models.transaction import Transaction
from ..models.category import Category
from ..models.audit_log import AuditLogEntry
from ..models.enums import RowRole, ReviewStatus
from ..repositories.sheet_repo import SheetRepository
from ..services.simplefin import SimpleFINClient
from ..services.review_engine import ReviewEngine, group_transactions_by_key
from ..utils.logging import get_logger

logger = get_logger(__name__)


class SyncResult(BaseModel):
    """Result of a sync operation."""

    new_count: int = 0
    updated_count: int = 0
    unchanged_count: int = 0
    error_count: int = 0
    errors: list[str] = []
    review_flagged_count: int = 0


class SyncEngine:
    """Orchestrates sync workflow between SimpleFIN and Google Sheets.

    Responsibilities:
    - Fetch transactions from SimpleFIN for enabled accounts
    - Match with existing sheet transactions
    - Append new transactions
    - Update existing transactions (bank snapshot fields)
    - Compute review status
    - Ensure idempotency
    """

    def __init__(
        self, config: Config, sheet_repo: SheetRepository, simplefin_client: SimpleFINClient
    ):
        """Initialize sync engine.

        Args:
            config: Application configuration
            sheet_repo: Sheet repository
            simplefin_client: SimpleFIN client
        """
        self.config = config
        self.sheet_repo = sheet_repo
        self.simplefin = simplefin_client
        logger.info("Initialized SyncEngine")

    def sync(self, dry_run: bool = False) -> SyncResult:
        """Execute full sync workflow.

        For large date ranges (>60 days), automatically batches into 30-day windows
        to reduce memory pressure.

        Args:
            dry_run: If True, don't write to sheet (preview only)

        Returns:
            SyncResult with counts and errors
        """
        logger.info(f"Starting sync (dry_run={dry_run})...")
        result = SyncResult()
        now = datetime.now()
        start_time = time.time()
        hostname = socket.gethostname()
        audit_entry = None

        try:
            # 1. Load sheet data
            logger.info("Loading sheet data...")
            accounts = self.sheet_repo.read_accounts(enabled_only=True)
            transactions = self.sheet_repo.read_transactions()
            categories = self.sheet_repo.read_categories(active_only=True)

            logger.info(
                f"Loaded {len(accounts)} enabled accounts, "
                f"{len(transactions)} transactions, "
                f"{len(categories)} categories"
            )

            if not accounts:
                logger.warning("No enabled accounts found")
                return result

            # 2. Fetch SimpleFIN data (batched for large windows)
            end_date = date.today()
            start_date = end_date - timedelta(days=self.config.window_days)

            # WARNING: SimpleFIN typically provides 90 days of transaction history max.
            # This varies by institution - some only provide 30-60 days.
            # The lookback period depends on the bank and their data provider (MX).
            # Users cannot fetch data beyond what the institution provides.

            # Use batching if window is large (>60 days)
            BATCH_SIZE_DAYS = 30
            BATCH_THRESHOLD_DAYS = 60

            if self.config.window_days > BATCH_THRESHOLD_DAYS:
                logger.info(
                    f"Large sync window ({self.config.window_days} days) detected. "
                    f"Batching into {BATCH_SIZE_DAYS}-day windows to reduce memory pressure..."
                )
                import_data = self._fetch_simplefin_data_batched(
                    accounts, start_date, end_date, BATCH_SIZE_DAYS
                )
            else:
                logger.info(
                    f"Fetching transactions from SimpleFIN (last {self.config.window_days} days)..."
                )
                import_data = self._fetch_simplefin_data(accounts, start_date, end_date)

            total_imported = sum(len(txns) for txns in import_data.values())
            logger.info(f"Fetched {total_imported} transactions from SimpleFIN")

            # 3. Group existing transactions by txn_key
            existing_by_key = self._index_transactions_by_key(transactions)
            logger.info(f"Indexed {len(existing_by_key)} existing transaction keys")

            # 4. Compute new and updated transactions
            new_transactions = []
            updated_cells = {}  # row_idx -> {col_name: value}
            accounts_by_id = {a.sf_account_id: a for a in accounts}

            for account_id, sf_txns in import_data.items():
                account = accounts_by_id.get(account_id)
                if not account:
                    continue

                for sf_txn in sf_txns:
                    txn_key = self._compute_txn_key(account_id, sf_txn["sf_txn_id"])

                    if txn_key not in existing_by_key:
                        # New transaction - use learned defaults from previous edits
                        new_txn = self._create_new_bank_row(account, sf_txn, now, transactions)
                        new_transactions.append(new_txn)
                        result.new_count += 1
                    else:
                        # Existing transaction - check for changes
                        bank_row = existing_by_key[txn_key]
                        if bank_row.row_role != RowRole.BANK:
                            logger.warning(f"Existing key {txn_key} is not a BANK row, skipping")
                            continue

                        # Update sf_last_seen_at and account_name
                        if bank_row.sheet_row_index:
                            if bank_row.sheet_row_index not in updated_cells:
                                updated_cells[bank_row.sheet_row_index] = {}
                            updated_cells[bank_row.sheet_row_index]["sf_last_seen_at"] = now

                            # Update account_name if missing or changed
                            if bank_row.account_name != account.display_name:
                                updated_cells[bank_row.sheet_row_index][
                                    "account_name"
                                ] = account.display_name

                            # Update account_type if missing or changed
                            account_type_value = (
                                account.account_type.value if account.account_type else None
                            )
                            if bank_row.account_type != account_type_value:
                                updated_cells[bank_row.sheet_row_index][
                                    "account_type"
                                ] = account_type_value

                        # Check if transaction is reconciled by comparing date with account's reconcile_date
                        is_reconciled = self._is_transaction_reconciled(bank_row, account)

                        # If unreconciled, check for changes and update sf_* fields
                        if not is_reconciled:
                            changes = self._detect_changes(bank_row, sf_txn)
                            if changes:
                                if bank_row.sheet_row_index:
                                    if bank_row.sheet_row_index not in updated_cells:
                                        updated_cells[bank_row.sheet_row_index] = {}
                                    updated_cells[bank_row.sheet_row_index].update(changes)
                                result.updated_count += 1
                            else:
                                result.unchanged_count += 1
                        else:
                            # Reconciled - don't update sf_* fields
                            result.unchanged_count += 1

            # 5. Compute review status for all transaction groups
            # Re-read transactions (including new ones we'll append)
            all_transactions = transactions + new_transactions
            review_updates = self._compute_review_status(
                all_transactions, categories, import_data, accounts_by_id
            )

            # Merge review updates into updated_cells
            for row_idx, review_fields in review_updates.items():
                if row_idx not in updated_cells:
                    updated_cells[row_idx] = {}
                updated_cells[row_idx].update(review_fields)
                if review_fields.get("needs_attention"):
                    result.review_flagged_count += 1

            # 6. Write to sheet
            if not dry_run:
                if new_transactions:
                    logger.info(f"Appending {len(new_transactions)} new transactions...")
                    self.sheet_repo.append_transactions(new_transactions)

                if updated_cells:
                    logger.info(f"Updating {len(updated_cells)} transaction rows...")
                    self.sheet_repo.update_transaction_cells(updated_cells)

                logger.info("Sheet updated successfully")
            else:
                logger.info(f"DRY RUN: Would append {len(new_transactions)} transactions")
                logger.info(f"DRY RUN: Would update {len(updated_cells)} rows")

        except Exception as e:
            logger.error(f"Sync error: {e}", exc_info=True)
            result.errors.append(str(e))
            result.error_count += 1

            # Create audit log entry for failure
            if not dry_run:
                duration = time.time() - start_time
                audit_entry = AuditLogEntry(
                    timestamp=datetime.now(),
                    command="sync",
                    hostname=hostname,
                    status="FAILED",
                    new_count=result.new_count,
                    updated_count=result.updated_count,
                    unchanged_count=result.unchanged_count,
                    needs_attention_count=result.review_flagged_count,
                    duration_seconds=duration,
                    error_type=type(e).__name__,
                    error_message=str(e)[:200],  # Truncate to 200 chars
                )

        else:
            # Create audit log entry for success
            if not dry_run:
                duration = time.time() - start_time
                audit_entry = AuditLogEntry(
                    timestamp=datetime.now(),
                    command="sync",
                    hostname=hostname,
                    status="SUCCESS",
                    new_count=result.new_count,
                    updated_count=result.updated_count,
                    unchanged_count=result.unchanged_count,
                    needs_attention_count=result.review_flagged_count,
                    duration_seconds=duration,
                )

        finally:
            # Always write audit log entry (even on failure, but skip for dry runs)
            if audit_entry and not dry_run:
                try:
                    self.sheet_repo.append_audit_log_entry(audit_entry)
                except Exception as log_error:
                    logger.error(f"Failed to write audit log: {log_error}")

        logger.info(
            f"Sync complete: {result.new_count} new, {result.updated_count} updated, "
            f"{result.unchanged_count} unchanged, {result.review_flagged_count} flagged, "
            f"{result.error_count} errors"
        )
        return result

    def _fetch_simplefin_data(
        self, accounts: list[Account], start_date: date, end_date: date
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch transactions from SimpleFIN for enabled accounts.

        Args:
            accounts: List of enabled accounts
            start_date: Start date for transaction window
            end_date: End date for transaction window

        Returns:
            Dict mapping account_id to list of normalized transaction dicts
        """
        result = {}

        for account in accounts:
            try:
                sf_txns = self.simplefin.get_transactions(
                    account_id=account.sf_account_id,
                    start_date=start_date,
                    end_date=end_date,
                    posted_only=True,
                )

                # Normalize transactions
                normalized = [
                    self.simplefin.normalize_transaction(txn, account.sf_account_id)
                    for txn in sf_txns
                ]
                result[account.sf_account_id] = normalized

            except Exception as e:
                logger.error(
                    f"Error fetching transactions for account {account.sf_account_id}: {e}"
                )
                continue

        return result

    def _fetch_simplefin_data_batched(
        self, accounts: list[Account], start_date: date, end_date: date, batch_size_days: int = 30
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch transactions from SimpleFIN in batches to reduce memory pressure.

        Breaks large date ranges into smaller batches and processes sequentially.

        Args:
            accounts: List of enabled accounts
            start_date: Start date for transaction window
            end_date: End date for transaction window
            batch_size_days: Size of each batch in days (default 30)

        Returns:
            Dict mapping account_id to list of normalized transaction dicts
        """
        # Calculate batches (oldest to newest)
        batches = []
        current_start = start_date
        while current_start < end_date:
            current_end = min(current_start + timedelta(days=batch_size_days), end_date)
            batches.append((current_start, current_end))
            current_start = current_end

        logger.info(f"Processing {len(batches)} batches of {batch_size_days} days each")

        # Accumulate results across all batches
        accumulated_results = {}

        # Process each batch
        for batch_num, (batch_start, batch_end) in enumerate(batches, 1):
            logger.info(
                f"Fetching batch {batch_num}/{len(batches)}: "
                f"{batch_start.isoformat()} to {batch_end.isoformat()}"
            )

            batch_data = self._fetch_simplefin_data(accounts, batch_start, batch_end)

            # Merge batch results into accumulated results
            for account_id, txns in batch_data.items():
                if account_id not in accumulated_results:
                    accumulated_results[account_id] = []
                accumulated_results[account_id].extend(txns)

            # Log batch progress
            batch_txn_count = sum(len(txns) for txns in batch_data.values())
            total_so_far = sum(len(txns) for txns in accumulated_results.values())
            logger.info(
                f"Batch {batch_num} complete: {batch_txn_count} transactions "
                f"({total_so_far} total so far)"
            )

        logger.info(
            f"All batches complete: {sum(len(txns) for txns in accumulated_results.values())} "
            f"total transactions fetched"
        )

        return accumulated_results

    def _index_transactions_by_key(self, transactions: list[Transaction]) -> dict[str, Transaction]:
        """Index BANK transactions by txn_key.

        Args:
            transactions: List of all transactions

        Returns:
            Dict mapping txn_key to BANK row Transaction
        """
        result = {}
        for txn in transactions:
            if txn.row_role == RowRole.BANK:
                result[txn.txn_key] = txn
        return result

    def _compute_txn_key(self, account_id: str, txn_id: str) -> str:
        """Compute transaction key.

        Args:
            account_id: SimpleFIN account ID
            txn_id: SimpleFIN transaction ID

        Returns:
            Transaction key (account_id:txn_id)
        """
        return f"{account_id}:{txn_id}"

    def _create_new_bank_row(
        self,
        account: Account,
        sf_txn: dict[str, Any],
        now: datetime,
        existing_transactions: list[Transaction],
    ) -> Transaction:
        """Create a new BANK row from SimpleFIN data.

        Learns from previous user edits: if the user has edited the payee/category
        for transactions with the same sf_payee, use those edits as defaults.

        Args:
            account: Account object
            sf_txn: Normalized SimpleFIN transaction dict
            now: Current timestamp
            existing_transactions: List of existing transactions to learn from

        Returns:
            New Transaction object
        """
        txn_key = self._compute_txn_key(sf_txn["sf_account_id"], sf_txn["sf_txn_id"])

        # Learn from previous edits for this sf_payee
        learned_payee, learned_category = self._learn_from_previous_edits(
            sf_txn["sf_payee"], existing_transactions
        )

        return Transaction(
            # Canonical (defaults from SimpleFIN or learned from previous edits)
            date=sf_txn["sf_date"],
            amount=sf_txn["sf_amount"],  # Default to SimpleFIN amount
            payee=learned_payee or sf_txn["sf_payee"],
            memo=(sf_txn["sf_memo"] if sf_txn["sf_memo"] != sf_txn["sf_payee"] else None),
            category=learned_category or "Expenses:Uncategorized",
            tags=None,
            # Display
            account_name=account.display_name,
            account_type=account.account_type.value if account.account_type else None,
            # Identity
            sf_account_id=sf_txn["sf_account_id"],
            sf_txn_id=sf_txn["sf_txn_id"],
            txn_key=txn_key,
            row_role=RowRole.BANK,
            # Bank snapshot
            sf_date=sf_txn["sf_date"],
            sf_amount=sf_txn["sf_amount"],
            sf_payee=sf_txn["sf_payee"],
            sf_memo=sf_txn["sf_memo"],
            sf_imported_at=now,
            sf_last_seen_at=now,
            # Review
            review_status=ReviewStatus.NEW,
            review_notes="New transaction from SimpleFIN",
            needs_attention=True,
        )

    def _learn_from_previous_edits(
        self, sf_payee: str, existing_transactions: list[Transaction]
    ) -> tuple[Optional[str], Optional[str]]:
        """Learn payee and category from previous user edits.

        Finds the most recent transaction where:
        - sf_payee matches the given value
        - payee has been edited (payee != sf_payee)

        Returns the edited payee and category from that transaction.

        Args:
            sf_payee: The SimpleFIN payee value to match
            existing_transactions: List of existing transactions

        Returns:
            Tuple of (learned_payee, learned_category) or (None, None) if no match
        """
        if not sf_payee:
            return None, None

        # Find all BANK transactions with matching sf_payee where user edited the payee
        matching_txns = []
        for txn in existing_transactions:
            if (
                txn.row_role == RowRole.BANK and txn.sf_payee == sf_payee and txn.payee != sf_payee
            ):  # User has edited it
                matching_txns.append(txn)

        if not matching_txns:
            return None, None

        # Sort by date descending (most recent first)
        matching_txns.sort(key=lambda t: t.date, reverse=True)

        # Use the most recent edit
        most_recent = matching_txns[0]
        logger.debug(
            f"Learned from previous edit: sf_payee='{sf_payee}' -> "
            f"payee='{most_recent.payee}', category='{most_recent.category}'"
        )

        return most_recent.payee, most_recent.category

    def _detect_changes(self, bank_row: Transaction, sf_txn: dict[str, Any]) -> dict[str, Any]:
        """Detect changes between existing BANK row and SimpleFIN data.

        Normalizes values before comparison to avoid false positives from
        type differences or transformations.

        Args:
            bank_row: Existing BANK row
            sf_txn: Normalized SimpleFIN transaction dict

        Returns:
            Dict of {column_name: new_value} for changed fields, or empty dict
        """
        changes = {}

        # Compare sf_date
        if bank_row.sf_date != sf_txn["sf_date"]:
            changes["sf_date"] = sf_txn["sf_date"]

        # Compare sf_amount (normalize to Decimal for comparison)
        existing_amount = Decimal(str(bank_row.sf_amount)) if bank_row.sf_amount else Decimal("0")
        new_amount = Decimal(str(sf_txn["sf_amount"])) if sf_txn["sf_amount"] else Decimal("0")
        if existing_amount != new_amount:
            changes["sf_amount"] = sf_txn["sf_amount"]

        # Compare sf_payee (normalize to strings, strip whitespace)
        existing_payee = (bank_row.sf_payee or "").strip()
        new_payee = (sf_txn["sf_payee"] or "").strip()
        if existing_payee != new_payee:
            changes["sf_payee"] = sf_txn["sf_payee"]

        # Compare sf_memo (normalize to strings, strip whitespace, treat None and empty as same)
        existing_memo = (bank_row.sf_memo or "").strip()
        new_memo = (sf_txn["sf_memo"] or "").strip()
        if existing_memo != new_memo:
            changes["sf_memo"] = sf_txn["sf_memo"]

        return changes

    def _is_transaction_reconciled(self, transaction: Transaction, account: Account) -> bool:
        """Check if transaction is reconciled based on account's reconcile_date.

        A transaction is considered reconciled if the account's reconcile_date
        is non-empty and on or after the transaction's posted date.

        Args:
            transaction: Transaction to check
            account: Account the transaction belongs to

        Returns:
            True if reconciled, False otherwise
        """
        if not account.reconcile_date:
            # No reconcile date set - transaction is unreconciled
            return False

        # Use sf_date (posted date) for comparison, fall back to date if not available
        txn_date = transaction.sf_date or transaction.date

        # Transaction is reconciled if account's reconcile_date is on or after the transaction date
        return account.reconcile_date >= txn_date

    def _compute_review_status(
        self,
        transactions: list[Transaction],
        categories: list[Category],
        import_data: dict[str, list[dict[str, Any]]],
        accounts_by_id: dict[str, Account],
    ) -> dict[int, dict[str, Any]]:
        """Compute review status for all transaction groups.

        Args:
            transactions: All transactions (including new)
            categories: List of categories
            import_data: Import data from SimpleFIN
            accounts_by_id: Dict of accounts by ID

        Returns:
            Dict mapping sheet_row_index to {review_status, review_notes, needs_attention}
        """
        # Group transactions
        groups = group_transactions_by_key(transactions)

        # Create review engine
        review_engine = ReviewEngine(categories)

        # Build import lookup for bank change detection
        import_lookup = {}
        for account_id, sf_txns in import_data.items():
            for sf_txn in sf_txns:
                txn_key = self._compute_txn_key(account_id, sf_txn["sf_txn_id"])
                import_lookup[txn_key] = sf_txn

        # Compute review for each group
        updates = {}
        for txn_key, group in groups.items():
            import_data_for_key = import_lookup.get(txn_key)
            review_status, review_notes, needs_attention = review_engine.compute_review_for_group(
                group, import_data_for_key
            )

            # Update all rows in group
            for row in group.all_rows:
                if row.sheet_row_index:
                    updates[row.sheet_row_index] = {
                        "review_status": review_status.value,
                        "review_notes": review_notes or "",
                        "needs_attention": needs_attention,
                    }

        return updates
