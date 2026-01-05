"""Bootstrap Google Sheet with proper schema, protections, and validations."""

from ..models.category import Category
from ..models.enums import AccountType, RowRole, ReviewStatus
from ..services.sheets import SheetsClient
from ..repositories.sheet_repo import SheetRepository
from ..utils.logging import get_logger

logger = get_logger(__name__)


class SheetBootstrap:
    """Handles initialization of Google Sheet structure.

    Creates tabs, headers, protections, and validations.
    """

    def __init__(self, sheets_client: SheetsClient):
        """Initialize bootstrap.

        Args:
            sheets_client: Initialized SheetsClient
        """
        self.sheets = sheets_client
        self.repo = SheetRepository(sheets_client)

    def bootstrap(self, force: bool = False):
        """Initialize all sheet structure.

        Args:
            force: If True, recreate protections/validations even if they exist

        Raises:
            ValueError: If sheet structure is invalid
        """
        logger.info("Starting sheet bootstrap...")

        # Create or verify tabs (Categories MUST be created first since Transactions references it)
        self._ensure_categories_tab()
        self._seed_categories_if_empty()  # Seed before Transactions tab needs it
        self._ensure_accounts_tab()
        self._ensure_transactions_tab()
        self._ensure_balance_history_tab()
        self._ensure_audit_log_tab()

        logger.info("Sheet bootstrap completed successfully")

    def _ensure_accounts_tab(self):
        """Create or verify Accounts tab."""
        tab_name = self.repo.ACCOUNTS_TAB
        sheet_id = self.sheets.get_sheet_id_by_name(tab_name)

        if sheet_id is None:
            logger.info(f"Creating {tab_name} tab...")
            sheet_id = self.sheets.create_sheet(tab_name)
            self._setup_accounts_structure(sheet_id)
        else:
            logger.info(f"{tab_name} tab exists, verifying structure...")
            self._verify_headers(tab_name, self.repo.ACCOUNT_COLUMNS)
            # Re-apply protections and validations (idempotent)
            self._setup_accounts_structure(sheet_id)

    def _setup_accounts_structure(self, sheet_id: int):
        """Set up Accounts tab structure."""
        # Write headers if empty (now 19 columns A-S)
        values = self.sheets.read_range(f"{self.repo.ACCOUNTS_TAB}!A1:S1")
        if not values or not values[0]:
            self.sheets.write_range(f"{self.repo.ACCOUNTS_TAB}!A1:S1", [self.repo.ACCOUNT_COLUMNS])

        # Freeze header row
        self.sheets.freeze_rows(sheet_id, num_rows=1)

        # Protect sf_account_id column (column A, rows 2+)
        self.sheets.create_protected_range(
            sheet_id=sheet_id,
            start_row=1,  # Skip header
            end_row=None,  # Unbounded
            start_col=0,  # Column A
            end_col=1,  # Column A (end_col is exclusive)
            description="Protected: sf_account_id (server-managed)",
        )

        # Protect SimpleFIN metadata columns (D-E: institution, sf_org_name)
        self.sheets.create_protected_range(
            sheet_id=sheet_id,
            start_row=1,
            end_row=None,
            start_col=3,  # Column D
            end_col=5,  # Column E (end_col is exclusive)
            description="Protected: SimpleFIN metadata (server-managed)",
        )

        # Protect balance columns (J-M: balance, available_balance, balance_date, last_synced_at)
        self.sheets.create_protected_range(
            sheet_id=sheet_id,
            start_row=1,
            end_row=None,
            start_col=9,  # Column J
            end_col=13,  # Column M (end_col is exclusive)
            description="Protected: Balance data (server-managed)",
        )

        # Protect computed reconciliation columns (R-T: expected_balance, balance_discrepancy, reconciliation_status_text)
        self.sheets.create_protected_range(
            sheet_id=sheet_id,
            start_row=1,
            end_row=None,
            start_col=17,  # Column R
            end_col=20,  # Column T (end_col is exclusive)
            description="Protected: Reconciliation computed fields (server-managed)",
        )

        # Data validations
        # enabled (column B): checkbox
        self.sheets.create_checkbox_validation(
            sheet_id=sheet_id, start_row=1, end_row=None, start_col=1, end_col=2
        )

        # ignored (column C): checkbox
        self.sheets.create_checkbox_validation(
            sheet_id=sheet_id, start_row=1, end_row=None, start_col=2, end_col=3
        )

        # account_type (column G): dropdown
        account_types = [t.value for t in AccountType]
        self.sheets.create_data_validation(
            sheet_id=sheet_id,
            start_row=1,
            end_row=None,
            start_col=6,
            end_col=7,
            values=account_types,
            strict=True,
        )

        # Apply currency formatting to balance columns
        self._apply_currency_formatting_accounts(sheet_id)

        # Apply visual themes
        self._apply_alternating_rows(sheet_id, num_columns=19)
        self._apply_protected_column_colors_accounts(sheet_id)

        # Apply reconciliation attention highlighting
        self._apply_reconciliation_highlight_accounts(sheet_id)

        logger.info(f"Accounts tab structure configured (sheet_id={sheet_id})")

    def _apply_currency_formatting_accounts(self, sheet_id: int):
        """Apply currency formatting to balance columns in Accounts.

        Args:
            sheet_id: Accounts sheet ID
        """
        requests = []

        # Format balance column (J, index 9)
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,  # Skip header
                        "startColumnIndex": 9,
                        "endColumnIndex": 10,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "numberFormat": {"type": "CURRENCY", "pattern": "$#,##0.00"}
                        }
                    },
                    "fields": "userEnteredFormat.numberFormat",
                }
            }
        )

        # Format available_balance column (K, index 10)
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "startColumnIndex": 10,
                        "endColumnIndex": 11,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "numberFormat": {"type": "CURRENCY", "pattern": "$#,##0.00"}
                        }
                    },
                    "fields": "userEnteredFormat.numberFormat",
                }
            }
        )

        # Format starting_balance column (N, index 13)
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "startColumnIndex": 13,
                        "endColumnIndex": 14,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "numberFormat": {"type": "CURRENCY", "pattern": "$#,##0.00"}
                        }
                    },
                    "fields": "userEnteredFormat.numberFormat",
                }
            }
        )

        # Format expected_balance column (P, index 15)
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "startColumnIndex": 15,
                        "endColumnIndex": 16,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "numberFormat": {"type": "CURRENCY", "pattern": "$#,##0.00"}
                        }
                    },
                    "fields": "userEnteredFormat.numberFormat",
                }
            }
        )

        # Format balance_discrepancy column (Q, index 16)
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "startColumnIndex": 16,
                        "endColumnIndex": 17,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "numberFormat": {"type": "CURRENCY", "pattern": "$#,##0.00"}
                        }
                    },
                    "fields": "userEnteredFormat.numberFormat",
                }
            }
        )

        self.sheets.batch_update(requests)
        logger.debug("Applied currency formatting to Accounts balance columns")

    def _ensure_transactions_tab(self):
        """Create or verify Transactions tab."""
        tab_name = self.repo.TRANSACTIONS_TAB
        sheet_id = self.sheets.get_sheet_id_by_name(tab_name)

        if sheet_id is None:
            logger.info(f"Creating {tab_name} tab...")
            sheet_id = self.sheets.create_sheet(tab_name)
            self._setup_transactions_structure(sheet_id)
        else:
            logger.info(f"{tab_name} tab exists, verifying structure...")
            self._verify_headers(tab_name, self.repo.TRANSACTION_COLUMNS)
            # Re-apply protections and validations
            self._setup_transactions_structure(sheet_id)

    def _setup_transactions_structure(self, sheet_id: int):
        """Set up Transactions tab structure."""
        # Write headers if empty (now 22 columns A-V)
        values = self.sheets.read_range(f"{self.repo.TRANSACTIONS_TAB}!A1:V1")
        if not values or not values[0]:
            self.sheets.write_range(
                f"{self.repo.TRANSACTIONS_TAB}!A1:V1", [self.repo.TRANSACTION_COLUMNS]
            )

        # Freeze header row
        self.sheets.freeze_rows(sheet_id, num_rows=1)

        # Add formula for accounting_month column (column B, derived from date in column A)
        self._apply_accounting_month_formula(sheet_id)

        # Protected ranges (Tier 1: truly server-managed, never user-editable)

        # Tier 1 Protection: accounting_month (column B, index 1) - formula-derived
        self.sheets.create_protected_range(
            sheet_id=sheet_id,
            start_row=1,
            end_row=None,
            start_col=1,
            end_col=2,
            description="Protected: Accounting month (formula-derived)",
        )

        # Tier 1 Protection: review fields (columns J-L, indices 9-11)
        # Includes: review_status, review_notes, needs_attention
        self.sheets.create_protected_range(
            sheet_id=sheet_id,
            start_row=1,
            end_row=None,
            start_col=9,
            end_col=12,
            description="Protected: Review fields (server-computed)",
        )

        # Tier 1 Protection: SimpleFIN snapshot fields (columns Q-V, indices 16-21)
        # Includes: sf_date, sf_amount, sf_payee, sf_memo, sf_imported_at, sf_last_seen_at
        self.sheets.create_protected_range(
            sheet_id=sheet_id,
            start_row=1,
            end_row=None,
            start_col=16,
            end_col=22,
            description="Protected: SimpleFIN snapshot (server-only)",
        )

        # Tier 2 (Reference columns - unprotected but styled):
        # - account_name, account_type (H-I, indices 7-8): copy for splits
        # - row_role (M, index 12): set to SPLIT/MANUAL
        # - txn_key (N, index 13): copy from BANK or generate MANUAL:guid
        # - sf_account_id (O, index 14): copy for splits
        # - sf_txn_id (P, index 15): leave empty for splits/manual
        # These are NOT protected to allow users to populate them for splits/manual entries

        # Data validations
        # row_role (column M, index 12): dropdown (unprotected for user-created splits/manual)
        row_roles = [r.value for r in RowRole]
        self.sheets.create_data_validation(
            sheet_id=sheet_id,
            start_row=1,
            end_row=None,
            start_col=12,
            end_col=13,
            values=row_roles,
            strict=True,
        )

        # review_status (column J, index 9): dropdown
        review_statuses = [s.value for s in ReviewStatus]
        self.sheets.create_data_validation(
            sheet_id=sheet_id,
            start_row=1,
            end_row=None,
            start_col=9,
            end_col=10,
            values=review_statuses,
            strict=True,
        )

        # needs_attention (column L, index 11): checkbox
        self.sheets.create_checkbox_validation(
            sheet_id=sheet_id, start_row=1, end_row=None, start_col=11, end_col=12
        )

        # category (column E, index 4): dropdown from Categories tab
        self._create_category_dropdown_validation(sheet_id)

        # Apply filter view with default sort (reverse by date)
        self._create_transactions_filter(sheet_id)

        # Apply currency formatting to amount columns
        self._apply_currency_formatting_transactions(sheet_id)

        # Apply date formatting to date column
        self._apply_date_formatting_transactions(sheet_id)

        # Apply visual themes
        self._apply_alternating_rows(sheet_id, num_columns=22)
        self._apply_protected_column_colors_transactions(sheet_id)
        self._apply_attention_highlight_transactions(sheet_id)

        logger.info(f"Transactions tab structure configured (sheet_id={sheet_id})")

    def _create_category_dropdown_validation(self, sheet_id: int):
        """Create category dropdown validation that references Categories tab.

        Args:
            sheet_id: Transactions sheet ID
        """
        # Use strict=True to validate against Categories tab
        grid_range = {
            "sheetId": sheet_id,
            "startRowIndex": 1,  # Skip header
            "startColumnIndex": 5,  # Column F (category)
            "endColumnIndex": 6,
        }

        request = {
            "setDataValidation": {
                "range": grid_range,
                "rule": {
                    "condition": {
                        "type": "ONE_OF_RANGE",
                        "values": [
                            {"userEnteredValue": f"={self.repo.CATEGORIES_TAB}!$A$2:$A$1000"}
                        ],
                    },
                    "strict": True,  # User chose strict validation
                    "showCustomUi": True,
                },
            }
        }
        self.sheets.batch_update([request])
        logger.debug("Added category dropdown validation to Transactions")

    def _create_transactions_filter(self, sheet_id: int):
        """Create filter view with default sort on Transactions tab.

        Args:
            sheet_id: Transactions sheet ID
        """
        # Create basic filter on all data (row 1 = header, rest = data)
        # Sort by date column (A) in descending order (newest first)
        request = {
            "setBasicFilter": {
                "filter": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,  # Include header
                        "startColumnIndex": 0,
                        "endColumnIndex": 22,  # All 22 columns (A-V)
                    },
                    "sortSpecs": [
                        {
                            "dimensionIndex": 0,  # Column A (date)
                            "sortOrder": "DESCENDING",  # Newest first
                        }
                    ],
                }
            }
        }
        self.sheets.batch_update([request])
        logger.debug("Added filter view to Transactions with date sort")

    def _apply_currency_formatting_transactions(self, sheet_id: int):
        """Apply currency formatting to amount columns in Transactions.

        Args:
            sheet_id: Transactions sheet ID
        """
        requests = []

        # Format amount column (C, index 2)
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,  # Skip header
                        "startColumnIndex": 2,
                        "endColumnIndex": 3,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "numberFormat": {"type": "CURRENCY", "pattern": "$#,##0.00"}
                        }
                    },
                    "fields": "userEnteredFormat.numberFormat",
                }
            }
        )

        # Format sf_amount column (R, index 17)
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "startColumnIndex": 17,
                        "endColumnIndex": 18,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "numberFormat": {"type": "CURRENCY", "pattern": "$#,##0.00"}
                        }
                    },
                    "fields": "userEnteredFormat.numberFormat",
                }
            }
        )

        self.sheets.batch_update(requests)
        logger.debug("Applied currency formatting to Transactions amount columns")

    def _apply_date_formatting_transactions(self, sheet_id: int):
        """Apply date formatting to date column in Transactions.

        Args:
            sheet_id: Transactions sheet ID
        """
        request = {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,  # Skip header
                    "startColumnIndex": 0,
                    "endColumnIndex": 1,
                },
                "cell": {
                    "userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}}
                },
                "fields": "userEnteredFormat.numberFormat",
            }
        }
        self.sheets.batch_update([request])
        logger.debug("Applied date formatting to Transactions date column")

    def _apply_accounting_month_formula(self, sheet_id: int):
        """Apply ARRAYFORMULA to accounting_month column (column B) in Transactions.

        The formula derives the accounting month from the date in column A.
        Uses ARRAYFORMULA so it automatically applies to all rows including new ones.

        Args:
            sheet_id: Transactions sheet ID
        """
        # Use ARRAYFORMULA to automatically apply to all rows including new ones
        # Formula in B2: =ARRAYFORMULA(IF(ROW(A:A)=1, "", IF(A:A="", "", TEXT(A:A, "yyyy-MM"))))
        # This:
        # - Skips the header row (ROW()=1)
        # - Returns empty string if date is empty
        # - Otherwise formats date as yyyy-MM
        # - Automatically applies to all rows including future ones

        # First, clear any existing formulas in column B (except header)
        clear_request = {
            "updateCells": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,
                    "startColumnIndex": 1,
                    "endColumnIndex": 2,
                },
                "fields": "userEnteredValue",
            }
        }

        # Apply the ARRAYFORMULA to cell B2
        formula_request = {
            "updateCells": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,  # Row 2 (0-indexed)
                    "endRowIndex": 2,  # Just cell B2
                    "startColumnIndex": 1,
                    "endColumnIndex": 2,
                },
                "rows": [
                    {
                        "values": [
                            {
                                "userEnteredValue": {
                                    "formulaValue": '=ARRAYFORMULA(IF(ROW(A2:A)=1, "", IF(A2:A="", "", TEXT(A2:A, "yyyy-MM"))))'
                                }
                            }
                        ]
                    }
                ],
                "fields": "userEnteredValue",
            }
        }

        self.sheets.batch_update([clear_request, formula_request])
        logger.debug("Applied ARRAYFORMULA to Transactions column B for accounting_month")

    def _ensure_balance_history_tab(self):
        """Create or verify Balance History tab."""
        tab_name = self.repo.BALANCE_HISTORY_TAB
        sheet_id = self.sheets.get_sheet_id_by_name(tab_name)

        if sheet_id is None:
            logger.info(f"Creating {tab_name} tab...")
            sheet_id = self.sheets.create_sheet(tab_name)
            self._setup_balance_history_structure(sheet_id)
        else:
            logger.info(f"{tab_name} tab exists, verifying structure...")
            self._verify_headers(tab_name, self.repo.BALANCE_HISTORY_COLUMNS)
            # Re-apply protections and formatting (idempotent)
            self._setup_balance_history_structure(sheet_id)

    def _setup_balance_history_structure(self, sheet_id: int):
        """Set up Balance History tab structure."""
        # Write headers if empty (10 columns A-J)
        values = self.sheets.read_range(f"{self.repo.BALANCE_HISTORY_TAB}!A1:J1")
        if not values or not values[0]:
            self.sheets.write_range(
                f"{self.repo.BALANCE_HISTORY_TAB}!A1:J1", [self.repo.BALANCE_HISTORY_COLUMNS]
            )

        # Freeze header row
        self.sheets.freeze_rows(sheet_id, num_rows=1)

        # Add filter with default sort by recorded_at (newest first)
        self._apply_balance_history_filter_with_sort(sheet_id)

        # Protect all columns except notes (server-managed data)
        # Columns A-I (indices 0-8): sf_account_id through is_starting_balance
        self.sheets.create_protected_range(
            sheet_id=sheet_id,
            start_row=1,
            end_row=None,
            start_col=0,  # Column A
            end_col=9,  # Through column I (end_col is exclusive)
            description="Protected: Balance history data (server-managed)",
        )

        # Apply currency formatting to balance columns
        self._apply_currency_formatting_balance_history(sheet_id)

        # Apply visual themes
        self._apply_alternating_rows(sheet_id, num_columns=10)
        self._apply_protected_column_colors_balance_history(sheet_id)

        logger.info(f"Balance History tab structure configured (sheet_id={sheet_id})")

    def _apply_currency_formatting_balance_history(self, sheet_id: int):
        """Apply currency formatting to balance columns in Balance History.

        Args:
            sheet_id: Balance History sheet ID
        """
        requests = []

        # Format balance column (E, index 4)
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,  # Skip header
                        "startColumnIndex": 4,
                        "endColumnIndex": 5,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "numberFormat": {"type": "CURRENCY", "pattern": "$#,##0.00"}
                        }
                    },
                    "fields": "userEnteredFormat.numberFormat",
                }
            }
        )

        # Format available_balance column (F, index 5)
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "startColumnIndex": 5,
                        "endColumnIndex": 6,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "numberFormat": {"type": "CURRENCY", "pattern": "$#,##0.00"}
                        }
                    },
                    "fields": "userEnteredFormat.numberFormat",
                }
            }
        )

        self.sheets.batch_update(requests)
        logger.debug("Applied currency formatting to Balance History balance columns")

    def _apply_balance_history_filter_with_sort(self, sheet_id: int):
        """Apply filter with default sort by recorded_at (newest first) to Balance History tab.

        Args:
            sheet_id: Balance History sheet ID
        """
        # Create basic filter on all data with sort by recorded_at (column G, index 6)
        request = {
            "setBasicFilter": {
                "filter": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,  # Include header
                        "startColumnIndex": 0,
                        "endColumnIndex": 10,  # All 10 columns (A-J)
                    },
                    "sortSpecs": [
                        {
                            "dimensionIndex": 6,  # Column G (recorded_at)
                            "sortOrder": "DESCENDING",  # Newest first
                        }
                    ],
                }
            }
        }
        self.sheets.batch_update([request])
        logger.debug(f"Applied filter with recorded_at sort to Balance History sheet {sheet_id}")

    def _apply_protected_column_colors_balance_history(self, sheet_id: int):
        """Apply darker gray background to protected columns in Balance History tab.

        Args:
            sheet_id: Balance History sheet ID
        """
        requests = []

        # Protected columns A-I (indices 0-8): all except notes
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,  # Skip header
                        "startColumnIndex": 0,
                        "endColumnIndex": 9,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {"red": 0.85, "green": 0.85, "blue": 0.85}
                        }
                    },
                    "fields": "userEnteredFormat.backgroundColor",
                }
            }
        )

        self.sheets.batch_update(requests)
        logger.debug(f"Applied protected column colors to Balance History sheet {sheet_id}")

    def _apply_auto_filter(self, sheet_id: int, num_columns: int):
        """Apply auto-filter to sheet for sorting and filtering.

        Args:
            sheet_id: Sheet ID
            num_columns: Number of columns to include in filter range
        """
        request = {
            "setBasicFilter": {
                "filter": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,  # Include header row
                        "startColumnIndex": 0,
                        "endColumnIndex": num_columns,
                        # endRowIndex omitted to include all rows
                    }
                }
            }
        }

        self.sheets.batch_update([request])
        logger.debug(f"Applied auto-filter to sheet {sheet_id} (columns 0-{num_columns})")

    def _ensure_audit_log_tab(self):
        """Create or verify Audit Log tab."""
        tab_name = self.repo.AUDIT_LOG_TAB
        sheet_id = self.sheets.get_sheet_id_by_name(tab_name)

        if sheet_id is None:
            logger.info(f"Creating {tab_name} tab...")
            sheet_id = self.sheets.create_sheet(tab_name)
            self._setup_audit_log_structure(sheet_id)
        else:
            logger.info(f"{tab_name} tab exists, verifying structure...")
            self._verify_headers(tab_name, self.repo.AUDIT_LOG_COLUMNS)
            # Re-apply protections and formatting (idempotent)
            self._setup_audit_log_structure(sheet_id)

    def _setup_audit_log_structure(self, sheet_id: int):
        """Set up Audit Log tab structure."""
        # Write headers if empty (12 columns A-L)
        values = self.sheets.read_range(f"{self.repo.AUDIT_LOG_TAB}!A1:L1")
        if not values or not values[0]:
            self.sheets.write_range(
                f"{self.repo.AUDIT_LOG_TAB}!A1:L1", [self.repo.AUDIT_LOG_COLUMNS]
            )

        # Freeze header row
        self.sheets.freeze_rows(sheet_id, num_rows=1)

        # Add auto-filter to entire range for sorting and filtering
        self._apply_auto_filter(sheet_id, num_columns=12)

        # Protect all columns (server-managed audit log)
        self.sheets.create_protected_range(
            sheet_id=sheet_id,
            start_row=1,
            end_row=None,
            start_col=0,  # Column A
            end_col=12,  # Through column L (end_col is exclusive)
            description="Protected: Audit log data (server-managed)",
        )

        # Apply visual themes
        self._apply_alternating_rows(sheet_id, num_columns=12)
        self._apply_protected_column_colors_audit_log(sheet_id)

        logger.info(f"Audit Log tab structure configured (sheet_id={sheet_id})")

    def _apply_protected_column_colors_audit_log(self, sheet_id: int):
        """Apply darker gray background to protected columns in Audit Log tab.

        Args:
            sheet_id: Audit Log sheet ID
        """
        requests = []

        # All columns protected (A-L, indices 0-11)
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,  # Skip header
                        "startColumnIndex": 0,
                        "endColumnIndex": 12,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {"red": 0.85, "green": 0.85, "blue": 0.85}
                        }
                    },
                    "fields": "userEnteredFormat.backgroundColor",
                }
            }
        )

        self.sheets.batch_update(requests)
        logger.debug(f"Applied protected column colors to Audit Log sheet {sheet_id}")

    def _ensure_categories_tab(self):
        """Create or verify Categories tab."""
        tab_name = self.repo.CATEGORIES_TAB
        sheet_id = self.sheets.get_sheet_id_by_name(tab_name)

        if sheet_id is None:
            logger.info(f"Creating {tab_name} tab...")
            sheet_id = self.sheets.create_sheet(tab_name)
            self._setup_categories_structure(sheet_id)
        else:
            logger.info(f"{tab_name} tab exists, verifying structure...")
            self._verify_headers(tab_name, self.repo.CATEGORY_COLUMNS)
            self._setup_categories_structure(sheet_id)

    def _setup_categories_structure(self, sheet_id: int):
        """Set up Categories tab structure."""
        # Write headers if empty
        values = self.sheets.read_range(f"{self.repo.CATEGORIES_TAB}!A1:C1")
        if not values or not values[0]:
            self.sheets.write_range(
                f"{self.repo.CATEGORIES_TAB}!A1:C1", [self.repo.CATEGORY_COLUMNS]
            )

        # Freeze header row
        self.sheets.freeze_rows(sheet_id, num_rows=1)

        # active (column B): checkbox
        self.sheets.create_checkbox_validation(
            sheet_id=sheet_id, start_row=1, end_row=None, start_col=1, end_col=2
        )

        # Apply visual themes
        self._apply_alternating_rows(sheet_id, num_columns=3)

        logger.info(f"Categories tab structure configured (sheet_id={sheet_id})")

    def _seed_categories_if_empty(self):
        """Seed default categories if Categories tab is empty."""
        existing = self.repo.read_categories(active_only=False)
        if existing:
            logger.info(f"Categories tab already has {len(existing)} categories, skipping seed")
            return

        logger.info("Seeding default categories...")
        default_categories = self._get_default_categories()
        self.repo.write_categories(default_categories)
        logger.info(f"Seeded {len(default_categories)} default categories")

    def _get_default_categories(self) -> list[Category]:
        """Get default category list.

        Returns:
            List of default Category objects
        """
        categories = [
            # Expenses
            "Expenses:Uncategorized",
            "Expenses:Groceries",
            "Expenses:Dining",
            "Expenses:Gifts",
            "Expenses:Transport",
            "Expenses:Utilities",
            "Expenses:Rent",
            "Expenses:Subscriptions",
            "Expenses:Medical",
            "Expenses:Travel",
            "Expenses:Entertainment",
            "Expenses:Clothing",
            "Expenses:Home",
            "Expenses:Insurance",
            "Expenses:Taxes",
            # Income
            "Income:Salary",
            "Income:Investment",
            "Income:Other",
            # Assets
            "Assets:Cash",
            "Assets:Bank:Checking",
            "Assets:Bank:Savings",
            # Liabilities
            "Liabilities:CreditCard",
            "Liabilities:Loan",
        ]

        return [Category(category=cat, active=True) for cat in categories]

    def _verify_headers(self, tab_name: str, expected_headers: list[str]):
        """Verify that tab headers match expected schema.

        Args:
            tab_name: Name of the tab
            expected_headers: List of expected column headers

        Raises:
            ValueError: If headers don't match
        """
        range_name = f"{tab_name}!A1:ZZ1"
        values = self.sheets.read_range(range_name)

        if not values:
            # Empty sheet, will be initialized
            return

        actual_headers = values[0] if values else []

        # Check that expected headers are present (in order)
        for i, expected in enumerate(expected_headers):
            if i >= len(actual_headers) or actual_headers[i] != expected:
                error_msg = (
                    f"Header mismatch in {tab_name} tab at column {i}.\n"
                    f"Expected: {expected}\n"
                    f"Actual: {actual_headers[i] if i < len(actual_headers) else '(missing)'}\n"
                    f"Full expected: {expected_headers}\n"
                    f"Full actual: {actual_headers}"
                )
                raise ValueError(error_msg)

        logger.debug(f"{tab_name} headers verified OK")

    def _apply_alternating_rows(self, sheet_id: int, num_columns: int):
        """Apply alternating row colors (banding) to a sheet.

        Args:
            sheet_id: Sheet ID (gid)
            num_columns: Number of columns to apply banding to
        """
        # First, remove any existing banding on this sheet
        metadata = self.sheets.get_sheet_metadata()
        requests = []

        # Find and delete existing banded ranges for this sheet
        for sheet in metadata.get("sheets", []):
            if sheet["properties"]["sheetId"] == sheet_id:
                for banded_range in sheet.get("bandedRanges", []):
                    requests.append(
                        {"deleteBanding": {"bandedRangeId": banded_range["bandedRangeId"]}}
                    )

        # Delete existing banding if any
        if requests:
            self.sheets.batch_update(requests)
            logger.debug(f"Removed {len(requests)} existing banded ranges from sheet {sheet_id}")

        # Now add the new banding
        request = {
            "addBanding": {
                "bandedRange": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,  # Include header
                        "startColumnIndex": 0,
                        "endColumnIndex": num_columns,
                    },
                    "rowProperties": {
                        "headerColor": {"red": 0.8, "green": 0.8, "blue": 0.8},
                        "firstBandColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                        "secondBandColor": {"red": 0.95, "green": 0.95, "blue": 0.95},
                    },
                }
            }
        }
        self.sheets.batch_update([request])
        logger.debug(f"Applied alternating row colors to sheet {sheet_id}")

    def _apply_protected_column_colors_accounts(self, sheet_id: int):
        """Apply darker gray background to protected columns in Accounts tab.

        Args:
            sheet_id: Accounts sheet ID
        """
        requests = []

        # Protected columns in Accounts:
        # - Column A (index 0): sf_account_id
        # - Columns D-E (indices 3-4): institution, sf_org_name
        # - Columns I-L (indices 8-11): balance, available_balance, balance_date, last_synced_at
        # - Columns N-R (indices 13-17): starting_balance, starting_balance_date, expected_balance, balance_discrepancy, reconciliation_status_text

        protected_ranges = [
            (0, 1),  # Column A
            (3, 5),  # Columns D-E
            (8, 12),  # Columns I-L
            (13, 18),  # Columns N-R (reconciliation fields - all server-managed)
        ]

        for start_col, end_col in protected_ranges:
            requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,  # Skip header
                            "startColumnIndex": start_col,
                            "endColumnIndex": end_col,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {"red": 0.85, "green": 0.85, "blue": 0.85}
                            }
                        },
                        "fields": "userEnteredFormat.backgroundColor",
                    }
                }
            )

        self.sheets.batch_update(requests)
        logger.debug(f"Applied protected column colors to Accounts sheet {sheet_id}")

    def _apply_reconciliation_highlight_accounts(self, sheet_id: int):
        """Apply conditional formatting to highlight reconciliation columns when status needs attention.

        Highlights columns P-R (expected_balance, balance_discrepancy, reconciliation_status_text)
        in light red when reconciliation_status_text is not OK/IGNORED and not empty.

        Args:
            sheet_id: Accounts sheet ID
        """
        request = {
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [
                        {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,  # Skip header
                            "startColumnIndex": 15,  # Column P (expected_balance)
                            "endColumnIndex": 18,  # Through column R (reconciliation_status_text)
                        }
                    ],
                    "booleanRule": {
                        "condition": {
                            "type": "CUSTOM_FORMULA",
                            "values": [
                                {"userEnteredValue": '=AND($R2<>"", $R2<>"OK", $R2<>"IGNORED")'}
                            ],
                        },
                        "format": {"backgroundColor": {"red": 1.0, "green": 0.85, "blue": 0.85}},
                    },
                },
                "index": 0,  # Add at beginning so it takes precedence over alternating rows
            }
        }

        self.sheets.batch_update([request])
        logger.debug(f"Applied reconciliation attention highlighting to Accounts sheet {sheet_id}")

    def _apply_protected_column_colors_transactions(self, sheet_id: int):
        """Apply two-tier background colors to columns in Transactions tab.

        Tier 1 (truly protected - dark gray): Never user-editable
        Tier 2 (reference - light blue-gray): User may edit for splits/manual entries

        Args:
            sheet_id: Transactions sheet ID
        """
        requests = []

        # Tier 1: Truly protected columns (dark gray: 0.85, 0.85, 0.85)
        # - Column B (index 1): accounting_month (formula-derived)
        # - Columns J-L (indices 9-11): review_status, review_notes, needs_attention
        # - Columns Q-V (indices 16-21): sf_date, sf_amount, sf_payee, sf_memo, sf_imported_at, sf_last_seen_at

        tier1_ranges = [
            (1, 2),  # Column B (accounting_month)
            (9, 12),  # Columns J-L (review fields)
            (16, 22),  # Columns Q-V (sf_* snapshot fields)
        ]

        for start_col, end_col in tier1_ranges:
            requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,  # Skip header
                            "startColumnIndex": start_col,
                            "endColumnIndex": end_col,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {"red": 0.85, "green": 0.85, "blue": 0.85}
                            }
                        },
                        "fields": "userEnteredFormat.backgroundColor",
                    }
                }
            )

        # Tier 2: Reference columns (light blue-gray: 0.90, 0.92, 0.95)
        # Unprotected but styled to indicate "usually server-managed, copy for splits/manual"
        # - Columns H-I (indices 7-8): account_name, account_type
        # - Columns M-P (indices 12-15): row_role, txn_key, sf_account_id, sf_txn_id

        tier2_ranges = [
            (7, 9),  # Columns H-I (account display)
            (12, 16),  # Columns M-P (identity fields)
        ]

        for start_col, end_col in tier2_ranges:
            requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,  # Skip header
                            "startColumnIndex": start_col,
                            "endColumnIndex": end_col,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {"red": 0.90, "green": 0.92, "blue": 0.95}
                            }
                        },
                        "fields": "userEnteredFormat.backgroundColor",
                    }
                }
            )

        self.sheets.batch_update(requests)
        logger.debug(f"Applied two-tier column colors to Transactions sheet {sheet_id}")

    def _apply_attention_highlight_transactions(self, sheet_id: int):
        """Apply conditional formatting to highlight review columns when needs_attention=TRUE.

        Applies light red background to review columns (J-L) for rows requiring attention.

        Args:
            sheet_id: Transactions sheet ID
        """
        # First, remove any existing conditional format rules for this sheet
        metadata = self.sheets.get_sheet_metadata()
        requests = []

        # Find and delete existing conditional format rules for this sheet
        for sheet in metadata.get("sheets", []):
            if sheet["properties"]["sheetId"] == sheet_id:
                # Add delete requests for each existing rule (will delete from index 0 repeatedly)
                num_rules = len(sheet.get("conditionalFormats", []))
                for _ in range(num_rules):
                    requests.append(
                        {
                            "deleteConditionalFormatRule": {
                                "sheetId": sheet_id,
                                "index": 0,  # Always delete the first rule until none remain
                            }
                        }
                    )

        # Delete existing rules if any
        if requests:
            # Delete one at a time since indices shift
            for request in requests:
                try:
                    self.sheets.batch_update([request])
                except Exception as e:
                    logger.debug(f"Skipping conditional format rule deletion: {e}")

        # Add new conditional formatting rule
        # Highlight review columns (J-L, indices 9-11) in light red when needs_attention (column L) is TRUE
        request = {
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [
                        {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,  # Skip header
                            "startColumnIndex": 9,  # Column J
                            "endColumnIndex": 12,  # Through column L
                        }
                    ],
                    "booleanRule": {
                        "condition": {
                            "type": "CUSTOM_FORMULA",
                            "values": [{"userEnteredValue": "=$L2=TRUE"}],
                        },
                        "format": {"backgroundColor": {"red": 1.0, "green": 0.85, "blue": 0.85}},
                    },
                },
                "index": 0,
            }
        }

        self.sheets.batch_update([request])
        logger.debug(
            f"Applied attention highlight conditional formatting to Transactions sheet {sheet_id}"
        )
