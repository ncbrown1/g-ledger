"""Repository for reading/writing sheet data with domain models."""

from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Any, Optional
from dateutil import parser as date_parser

from ..models.account import Account
from ..models.transaction import Transaction
from ..models.category import Category
from ..models.balance_history import BalanceSnapshot
from ..models.audit_log import AuditLogEntry
from ..models.enums import AccountType, RowRole, ReviewStatus
from ..services.sheets import SheetsClient
from ..utils.logging import get_logger
from ..utils.validation import parse_amount

logger = get_logger(__name__)


class SheetRepository:
    """High-level repository for accessing sheet data.

    Handles parsing sheet rows into Pydantic models and serializing
    models back to sheet rows.
    """

    # Sheet tab names
    ACCOUNTS_TAB = "Accounts"
    TRANSACTIONS_TAB = "Transactions"
    CATEGORIES_TAB = "Categories"
    BALANCE_HISTORY_TAB = "Balance History"
    AUDIT_LOG_TAB = "Audit Log"

    # Column definitions
    ACCOUNT_COLUMNS = [
        "sf_account_id",
        "enabled",
        "ignored",
        "institution",
        "sf_org_name",
        "display_name",
        "account_type",
        "currency",
        "balance",
        "available_balance",
        "balance_date",
        "last_synced_at",
        "reconcile_date",
        "starting_balance",
        "starting_balance_date",
        "expected_balance",
        "balance_discrepancy",
        "reconciliation_status_text",
        "notes",
    ]

    TRANSACTION_COLUMNS = [
        # User-editable canonical fields (displayed first for mobile)
        "date",
        "accounting_month",
        "amount",
        "payee",
        "memo",
        "category",
        "tags",
        # Server-managed display
        "account_name",
        "account_type",
        # Server-managed review (before technical fields for visibility)
        "review_status",
        "review_notes",
        "needs_attention",
        # Server-managed identity/bank fields (hidden on right)
        "row_role",
        "txn_key",
        "sf_account_id",
        "sf_txn_id",
        "sf_date",
        "sf_amount",
        "sf_payee",
        "sf_memo",
        "sf_imported_at",
        "sf_last_seen_at",
    ]

    CATEGORY_COLUMNS = ["category", "active", "notes"]

    BALANCE_HISTORY_COLUMNS = [
        "sf_account_id",
        "account_name",
        "account_type",
        "balance_date",
        "balance",
        "available_balance",
        "recorded_at",
        "source",
        "is_starting_balance",
        "notes",
    ]

    AUDIT_LOG_COLUMNS = [
        "timestamp",
        "command",
        "hostname",
        "status",
        "new_count",
        "updated_count",
        "unchanged_count",
        "needs_attention_count",
        "duration_seconds",
        "error_type",
        "error_message",
        "notes",
    ]

    def __init__(self, sheets_client: SheetsClient):
        """Initialize repository.

        Args:
            sheets_client: Initialized SheetsClient
        """
        self.sheets = sheets_client

    # ========== Accounts ==========

    def read_accounts(self, enabled_only: bool = True) -> list[Account]:
        """Read accounts from sheet.

        Args:
            enabled_only: Only return enabled accounts

        Returns:
            List of Account objects
        """
        range_name = f"{self.ACCOUNTS_TAB}!A:S"
        values = self.sheets.read_range(range_name)

        if not values or len(values) < 2:
            logger.warning("No accounts found in sheet")
            return []

        # Skip header row
        accounts = []
        skipped_empty = 0
        for i, row in enumerate(values[1:], start=2):
            try:
                # Skip rows without sf_account_id (empty/incomplete rows)
                # sf_account_id is in column A (index 0)
                if len(row) < 1 or not row[0]:
                    skipped_empty += 1
                    continue

                account = self._parse_account_row(row, sheet_row_index=i)
                if not enabled_only or account.enabled:
                    accounts.append(account)
            except Exception as e:
                logger.error(f"Error parsing account row {i}: {e}")
                continue

        if skipped_empty > 0:
            logger.debug(f"Skipped {skipped_empty} empty account rows without sf_account_id")

        logger.info(f"Read {len(accounts)} accounts from sheet")
        return accounts

    def write_accounts(self, accounts: list[Account]):
        """Write accounts to sheet (overwrites data rows).

        Args:
            accounts: List of accounts to write
        """
        # Write header + data rows
        values = [self.ACCOUNT_COLUMNS]
        values.extend([self._serialize_account(a) for a in accounts])

        # 19 columns (A-S)
        range_name = f"{self.ACCOUNTS_TAB}!A1:S{len(values)}"
        self.sheets.write_range(range_name, values)
        logger.info(f"Wrote {len(accounts)} accounts to sheet")

    def _parse_account_row(self, row: list[Any], sheet_row_index: int) -> Account:
        """Parse a row into an Account object."""
        # Pad row to expected length
        while len(row) < len(self.ACCOUNT_COLUMNS):
            row.append("")

        return Account(
            sf_account_id=str(row[0]) if row[0] else "",
            enabled=self._parse_bool(row[1], default=True),
            ignored=self._parse_bool(row[2], default=False),
            institution=str(row[3]) if row[3] else None,
            sf_org_name=str(row[4]) if row[4] else None,
            display_name=str(row[5]) if row[5] else "",
            account_type=AccountType(row[6]) if row[6] else AccountType.CHECKING,
            currency=str(row[7]) if row[7] else "USD",
            balance=parse_amount(row[8]) if row[8] != "" else None,
            available_balance=parse_amount(row[9]) if row[9] != "" else None,
            balance_date=self._parse_datetime(row[10]),
            last_synced_at=self._parse_datetime(row[11]),
            reconcile_date=self._parse_date(row[12]),
            starting_balance=parse_amount(row[13]) if row[13] != "" else None,
            starting_balance_date=self._parse_date(row[14]),
            expected_balance=parse_amount(row[15]) if row[15] != "" else None,
            balance_discrepancy=parse_amount(row[16]) if row[16] != "" else None,
            reconciliation_status_text=str(row[17]) if row[17] else None,
            notes=str(row[18]) if row[18] else None,
            sheet_row_index=sheet_row_index,
        )

    def _serialize_account(self, account: Account) -> list[Any]:
        """Serialize an Account to a row."""
        # If ignored, show balance as 0.00
        balance = (
            Decimal("0")
            if account.ignored
            else (account.balance if account.balance is not None else None)
        )
        available_balance = (
            Decimal("0")
            if account.ignored
            else (account.available_balance if account.available_balance is not None else None)
        )

        return [
            account.sf_account_id,
            account.enabled,
            account.ignored,
            account.institution or "",
            account.sf_org_name or "",
            account.display_name,
            account.account_type.value,
            account.currency,
            float(balance) if balance is not None else "",
            float(available_balance) if available_balance is not None else "",
            account.balance_date.isoformat() if account.balance_date else "",
            account.last_synced_at.isoformat() if account.last_synced_at else "",
            account.reconcile_date.isoformat() if account.reconcile_date else "",
            float(account.starting_balance) if account.starting_balance is not None else "",
            account.starting_balance_date.isoformat() if account.starting_balance_date else "",
            float(account.expected_balance) if account.expected_balance is not None else "",
            float(account.balance_discrepancy) if account.balance_discrepancy is not None else "",
            account.reconciliation_status_text or "",
            account.notes or "",
        ]

    # ========== Transactions ==========

    def read_transactions(self) -> list[Transaction]:
        """Read all transactions from sheet.

        Returns:
            List of Transaction objects
        """
        range_name = f"{self.TRANSACTIONS_TAB}!A:V"  # 22 columns (A-V)
        values = self.sheets.read_range(range_name)

        if not values or len(values) < 2:
            logger.warning("No transactions found in sheet")
            return []

        # Skip header row
        transactions = []
        skipped_empty = 0
        for i, row in enumerate(values[1:], start=2):
            try:
                # Skip rows without txn_key (empty/incomplete rows)
                # txn_key is now in column N (index 13)
                if len(row) < 14 or not row[13]:
                    skipped_empty += 1
                    continue

                txn = self._parse_transaction_row(row, sheet_row_index=i)
                transactions.append(txn)
            except Exception as e:
                logger.error(f"Error parsing transaction row {i}: {e}")
                continue

        if skipped_empty > 0:
            logger.debug(f"Skipped {skipped_empty} empty rows without txn_key")

        logger.info(f"Read {len(transactions)} transactions from sheet")
        return transactions

    def append_transactions(self, transactions: list[Transaction]):
        """Append new transactions to sheet.

        Args:
            transactions: List of transactions to append
        """
        if not transactions:
            return

        # Clear trailing empty rows to prevent appending after them
        self._clear_trailing_empty_rows(self.TRANSACTIONS_TAB)

        values = [self._serialize_transaction(t) for t in transactions]
        range_name = f"{self.TRANSACTIONS_TAB}!A:V"
        self.sheets.append_rows(range_name, values)
        logger.info(f"Appended {len(transactions)} transactions to sheet")

        # Update filter range to include new rows
        self._update_transactions_filter()

    def _update_transactions_filter(self):
        """Update the filter range on Transactions tab to include all rows."""
        # Read current data to determine row count
        range_name = f"{self.TRANSACTIONS_TAB}!A:V"
        values = self.sheets.read_range(range_name)

        if values and len(values) > 1:
            # Update filter to include all rows
            sheet_id = self.sheets.get_sheet_id_by_name(self.TRANSACTIONS_TAB)
            if sheet_id is not None:
                total_rows = len(values)
                self.sheets.update_basic_filter_range(
                    sheet_id=sheet_id,
                    end_row=total_rows,  # 0-based exclusive, so this includes all rows
                    num_columns=22,  # A-V
                )
                logger.debug(f"Updated Transactions filter to include {total_rows} rows")

    def _clear_trailing_empty_rows(self, tab_name: str):
        """Clear trailing empty rows from a tab.

        This prevents Google Sheets append from placing data after empty rows.

        Args:
            tab_name: Name of the tab to clean
        """
        # Read all data to find the last non-empty row
        range_name = f"{tab_name}!A:V"
        values = self.sheets.read_range(range_name)

        if not values or len(values) <= 1:
            return  # Only header or empty

        # Find last row with any data (check for txn_key in column N)
        last_data_row = 1  # Start at 1 (header is row 1)
        for i in range(len(values) - 1, 0, -1):  # Scan backwards from end
            row = values[i]
            # Check if row has txn_key (column N, index 13)
            if len(row) > 13 and row[13]:
                last_data_row = i + 1  # Convert to 1-based
                break

        # If there are empty rows after last_data_row, clear them
        total_rows = len(values)
        if total_rows > last_data_row + 1:
            empty_row_count = total_rows - last_data_row - 1
            logger.debug(f"Clearing {empty_row_count} trailing empty rows from {tab_name}")
            # Clear by deleting the dimension (rows)
            sheet_id = self.sheets.get_sheet_id_by_name(tab_name)
            if sheet_id is not None:
                delete_request = {
                    "deleteDimension": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "ROWS",
                            "startIndex": last_data_row + 1,  # 0-based, after last data row
                            "endIndex": total_rows,  # 0-based, exclusive
                        }
                    }
                }
                self.sheets.batch_update([delete_request])

    def update_transaction_cells(self, updates: dict[int, dict[str, Any]]):
        """Update specific cells in transaction rows.

        Args:
            updates: Dict mapping sheet_row_index to dict of {column_name: value}
        """
        if not updates:
            return

        # Build batch data for all cell updates
        batch_data = []
        for row_idx, column_updates in updates.items():
            for col_name, value in column_updates.items():
                if col_name not in self.TRANSACTION_COLUMNS:
                    logger.warning(f"Unknown column: {col_name}")
                    continue

                col_idx = self.TRANSACTION_COLUMNS.index(col_name)
                col_letter = self._col_index_to_letter(col_idx)
                range_name = f"{self.TRANSACTIONS_TAB}!{col_letter}{row_idx}"

                # Serialize value
                serialized = self._serialize_cell_value(value)
                batch_data.append({"range": range_name, "values": [[serialized]]})

        # Execute all updates in a single batch API call
        if batch_data:
            logger.info(
                f"Batch updating {len(batch_data)} cells in {len(updates)} transaction rows"
            )
            self.sheets.batch_update_values(batch_data)

    def _parse_transaction_row(self, row: list[Any], sheet_row_index: int) -> Transaction:
        """Parse a row into a Transaction object."""
        # Pad row to expected length
        while len(row) < len(self.TRANSACTION_COLUMNS):
            row.append("")

        return Transaction(
            # User-editable canonical (columns 0-6)
            date=self._parse_date(row[0]) or date.today(),
            accounting_month=str(row[1]) if row[1] else None,  # Derived from date
            amount=parse_amount(row[2]) if row[2] else Decimal("0"),
            payee=str(row[3]) if row[3] else "",
            memo=str(row[4]) if row[4] else None,
            category=str(row[5]) if row[5] else None,
            tags=str(row[6]) if row[6] else None,
            # Server-managed display (columns 7-8)
            account_name=str(row[7]) if row[7] else None,
            account_type=str(row[8]) if row[8] else None,
            # Server-managed review (columns 9-11)
            review_status=ReviewStatus(row[9]) if row[9] else ReviewStatus.NEW,
            review_notes=str(row[10]) if row[10] else None,
            needs_attention=self._parse_bool(row[11], default=False),
            # Server-managed identity (columns 12-15)
            row_role=RowRole(row[12]) if row[12] else RowRole.BANK,
            txn_key=str(row[13]) if row[13] else "",
            sf_account_id=str(row[14]) if row[14] else "",
            sf_txn_id=str(row[15]) if row[15] else None,
            # Server-managed bank snapshot (columns 16-21)
            sf_date=self._parse_date(row[16]),
            sf_amount=parse_amount(row[17]) if row[17] else None,
            sf_payee=str(row[18]) if row[18] else None,
            sf_memo=str(row[19]) if row[19] else None,
            sf_imported_at=self._parse_datetime(row[20]),
            sf_last_seen_at=self._parse_datetime(row[21]),
            sheet_row_index=sheet_row_index,
        )

    def _serialize_transaction(self, txn: Transaction) -> list[Any]:
        """Serialize a Transaction to a row."""
        return [
            # User-editable canonical (columns 0-6)
            txn.date.isoformat() if txn.date else "",
            "",  # accounting_month (derived via formula, left empty)
            float(txn.amount),
            txn.payee,
            txn.memo or "",
            txn.category or "",
            txn.tags or "",
            # Server-managed display (columns 7-8)
            txn.account_name or "",
            txn.account_type or "",
            # Server-managed review (columns 9-11)
            txn.review_status.value,
            txn.review_notes or "",
            txn.needs_attention,
            # Server-managed identity (columns 12-15)
            txn.row_role.value,
            txn.txn_key,
            txn.sf_account_id,
            txn.sf_txn_id or "",
            # Server-managed bank snapshot (columns 16-21)
            txn.sf_date.isoformat() if txn.sf_date else "",
            float(txn.sf_amount) if txn.sf_amount is not None else "",
            txn.sf_payee or "",
            txn.sf_memo or "",
            txn.sf_imported_at.isoformat() if txn.sf_imported_at else "",
            txn.sf_last_seen_at.isoformat() if txn.sf_last_seen_at else "",
        ]

    # ========== Categories ==========

    def read_categories(self, active_only: bool = True) -> list[Category]:
        """Read categories from sheet.

        Args:
            active_only: Only return active categories

        Returns:
            List of Category objects
        """
        range_name = f"{self.CATEGORIES_TAB}!A:C"
        values = self.sheets.read_range(range_name)

        if not values or len(values) < 2:
            logger.warning("No categories found in sheet")
            return []

        # Skip header row
        categories = []
        skipped_empty = 0
        for i, row in enumerate(values[1:], start=2):
            try:
                # Skip rows without category name (empty/incomplete rows)
                # category is in column A (index 0)
                if len(row) < 1 or not row[0]:
                    skipped_empty += 1
                    continue

                category = self._parse_category_row(row, sheet_row_index=i)
                if not active_only or category.active:
                    categories.append(category)
            except Exception as e:
                logger.error(f"Error parsing category row {i}: {e}")
                continue

        if skipped_empty > 0:
            logger.debug(f"Skipped {skipped_empty} empty category rows")

        logger.info(f"Read {len(categories)} categories from sheet")
        return categories

    def write_categories(self, categories: list[Category]):
        """Write categories to sheet.

        Args:
            categories: List of categories to write
        """
        # Clear any trailing empty rows first
        self._clear_trailing_empty_rows_categories()

        # Write header + data rows
        values = [self.CATEGORY_COLUMNS]
        values.extend([self._serialize_category(c) for c in categories])

        range_name = f"{self.CATEGORIES_TAB}!A1:C{len(values)}"
        self.sheets.write_range(range_name, values)
        logger.info(f"Wrote {len(categories)} categories to sheet")

    def _clear_trailing_empty_rows_categories(self):
        """Clear trailing empty rows from Categories tab."""
        range_name = f"{self.CATEGORIES_TAB}!A:C"
        values = self.sheets.read_range(range_name)

        if not values or len(values) <= 1:
            return  # Only header or empty

        # Find last row with category data (column A)
        last_data_row = 1  # Start at 1 (header is row 1)
        for i in range(len(values) - 1, 0, -1):  # Scan backwards
            row = values[i]
            if len(row) > 0 and row[0]:  # Check if category name exists
                last_data_row = i + 1  # Convert to 1-based
                break

        # Clear empty rows if they exist
        total_rows = len(values)
        if total_rows > last_data_row + 1:
            empty_row_count = total_rows - last_data_row - 1
            logger.debug(f"Clearing {empty_row_count} trailing empty rows from Categories")
            sheet_id = self.sheets.get_sheet_id_by_name(self.CATEGORIES_TAB)
            if sheet_id is not None:
                delete_request = {
                    "deleteDimension": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "ROWS",
                            "startIndex": last_data_row + 1,
                            "endIndex": total_rows,
                        }
                    }
                }
                self.sheets.batch_update([delete_request])

    def _parse_category_row(self, row: list[Any], sheet_row_index: int) -> Category:
        """Parse a row into a Category object."""
        while len(row) < len(self.CATEGORY_COLUMNS):
            row.append("")

        return Category(
            category=str(row[0]) if row[0] else "",
            active=self._parse_bool(row[1], default=True),
            notes=str(row[2]) if row[2] else None,
            sheet_row_index=sheet_row_index,
        )

    def _serialize_category(self, category: Category) -> list[Any]:
        """Serialize a Category to a row."""
        return [category.category, category.active, category.notes or ""]

    # ========== Utilities ==========

    def _parse_bool(self, value: Any, default: bool = False) -> bool:
        """Parse a boolean value."""
        if value is None or value == "":
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "yes", "1")
        return bool(value)

    def _parse_date(self, value: Any) -> Optional[date]:
        """Parse a date value."""
        if not value or value == "":
            return None
        if isinstance(value, date):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, (int, float)):
            # Excel serial number (days since 1899-12-30)
            return datetime(1899, 12, 30) + timedelta(days=value)
        if isinstance(value, str):
            try:
                return date_parser.parse(value).date()
            except Exception:
                return None
        return None

    def _parse_datetime(self, value: Any) -> Optional[datetime]:
        """Parse a datetime value."""
        if not value or value == "":
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, (int, float)):
            # Excel serial number (days since 1899-12-30)
            return datetime(1899, 12, 30) + timedelta(days=value)
        if isinstance(value, str):
            try:
                return date_parser.parse(value)
            except Exception:
                return None
        return None

    def _serialize_cell_value(self, value: Any) -> Any:
        """Serialize a single cell value."""
        if value is None:
            return ""
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, bool):
            return value
        return str(value)

    def _col_index_to_letter(self, col_idx: int) -> str:
        """Convert 0-based column index to letter (A, B, ..., Z, AA, ...).

        Args:
            col_idx: 0-based column index

        Returns:
            Column letter(s)
        """
        result = ""
        while col_idx >= 0:
            result = chr(col_idx % 26 + ord("A")) + result
            col_idx = col_idx // 26 - 1
        return result

    # Balance History methods

    def read_balance_history(
        self,
        sf_account_id: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[BalanceSnapshot]:
        """Read balance history from sheet.

        Args:
            sf_account_id: Optional filter by account ID
            start_date: Optional filter by balance_date >= start_date
            end_date: Optional filter by balance_date <= end_date

        Returns:
            List of BalanceSnapshot objects
        """
        range_name = f"{self.BALANCE_HISTORY_TAB}!A:J"
        values = self.sheets.read_range(range_name)

        if not values or len(values) <= 1:
            logger.debug("No balance history found")
            return []

        snapshots = []
        skipped_empty = 0

        # Skip header row
        for row_idx, row in enumerate(values[1:], start=2):
            # Skip empty rows
            if not row or len(row) == 0 or not row[0]:
                skipped_empty += 1
                continue

            try:
                snapshot = self._parse_balance_snapshot_row(row, row_idx)

                # Apply filters
                if sf_account_id and snapshot.sf_account_id != sf_account_id:
                    continue
                if start_date and snapshot.balance_date < start_date:
                    continue
                if end_date and snapshot.balance_date > end_date:
                    continue

                snapshots.append(snapshot)
            except Exception as e:
                logger.warning(f"Error parsing balance history row {row_idx}: {e}")
                continue

        logger.debug(
            f"Read {len(snapshots)} balance snapshots " f"(skipped {skipped_empty} empty rows)"
        )
        return snapshots

    def append_balance_snapshots(self, snapshots: list[BalanceSnapshot]):
        """Append balance snapshots to Balance History sheet.

        Args:
            snapshots: List of BalanceSnapshot objects to append
        """
        if not snapshots:
            logger.debug("No balance snapshots to append")
            return

        range_name = f"{self.BALANCE_HISTORY_TAB}!A:J"
        rows = [self._serialize_balance_snapshot(s) for s in snapshots]
        self.sheets.append_rows(range_name, rows)
        logger.info(f"Appended {len(snapshots)} balance snapshots")

    def _parse_balance_snapshot_row(self, row: list[Any], sheet_row_index: int) -> BalanceSnapshot:
        """Parse a balance history row into BalanceSnapshot.

        Args:
            row: Raw row data from sheet
            sheet_row_index: Row number in sheet (1-indexed)

        Returns:
            BalanceSnapshot object
        """
        return BalanceSnapshot(
            sf_account_id=str(row[0]) if row[0] else "",
            account_name=str(row[1]) if len(row) > 1 and row[1] else "",
            account_type=str(row[2]) if len(row) > 2 and row[2] else None,
            balance_date=(self._parse_date(row[3]) if len(row) > 3 else None) or date.today(),
            balance=parse_amount(row[4]) if len(row) > 4 and row[4] else Decimal("0"),
            available_balance=parse_amount(row[5]) if len(row) > 5 and row[5] else None,
            recorded_at=(self._parse_datetime(row[6]) if len(row) > 6 else None) or datetime.now(),
            source=str(row[7]) if len(row) > 7 and row[7] else "simplefin",
            is_starting_balance=self._parse_bool(row[8], default=False) if len(row) > 8 else False,
            notes=str(row[9]) if len(row) > 9 and row[9] else None,
            sheet_row_index=sheet_row_index,
        )

    def _serialize_balance_snapshot(self, snapshot: BalanceSnapshot) -> list[Any]:
        """Serialize BalanceSnapshot to sheet row.

        Args:
            snapshot: BalanceSnapshot object

        Returns:
            List of values for sheet row
        """
        return [
            snapshot.sf_account_id,
            snapshot.account_name,
            snapshot.account_type or "",
            snapshot.balance_date.isoformat(),
            float(snapshot.balance),
            float(snapshot.available_balance) if snapshot.available_balance is not None else "",
            snapshot.recorded_at.isoformat(),
            snapshot.source,
            snapshot.is_starting_balance,
            snapshot.notes or "",
        ]

    # ========== Audit Log ==========

    def append_audit_log_entry(self, entry: AuditLogEntry):
        """Append audit log entry to Audit Log sheet.

        Args:
            entry: AuditLogEntry object to append
        """
        range_name = f"{self.AUDIT_LOG_TAB}!A:L"
        row = self._serialize_audit_log_entry(entry)
        self.sheets.append_rows(range_name, [row])
        logger.debug(f"Appended audit log entry: {entry.command} - {entry.status}")

    def _serialize_audit_log_entry(self, entry: AuditLogEntry) -> list[Any]:
        """Serialize AuditLogEntry to sheet row.

        Args:
            entry: AuditLogEntry object

        Returns:
            List of values for sheet row
        """
        return [
            entry.timestamp.isoformat(),
            entry.command,
            entry.hostname,
            entry.status,
            entry.new_count,
            entry.updated_count,
            entry.unchanged_count,
            entry.needs_attention_count,
            float(entry.duration_seconds) if entry.duration_seconds is not None else "",
            entry.error_type or "",
            entry.error_message or "",
            entry.notes or "",
        ]
