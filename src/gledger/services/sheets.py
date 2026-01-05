"""Google Sheets API client wrapper."""

import time
import random
from pathlib import Path
from typing import Any, Optional
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ..utils.logging import get_logger

logger = get_logger(__name__)


def retry_with_backoff(max_retries: int = 5, base_delay: float = 1.0):
    """Decorator to retry API calls with exponential backoff and jitter.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds (will be multiplied exponentially)
    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            retries = 0
            while retries <= max_retries:
                try:
                    return func(*args, **kwargs)
                except HttpError as e:
                    # Only retry on rate limit errors (429)
                    if e.resp.status == 429 and retries < max_retries:
                        # Calculate delay with exponential backoff and jitter
                        delay = base_delay * (2**retries)
                        jitter = random.uniform(0, delay * 0.1)  # 10% jitter
                        total_delay = delay + jitter

                        logger.warning(
                            f"Rate limit hit, retrying in {total_delay:.2f}s "
                            f"(attempt {retries + 1}/{max_retries})"
                        )
                        time.sleep(total_delay)
                        retries += 1
                    else:
                        raise

        return wrapper

    return decorator


class SheetsClient:
    """Low-level Google Sheets API wrapper.

    Handles authentication, reading/writing ranges, batch operations,
    and sheet metadata operations like creating protections and validations.
    """

    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

    def __init__(self, credentials_path: Path, sheet_id: str):
        """Initialize Sheets client.

        Args:
            credentials_path: Path to service account JSON key file
            sheet_id: Google Sheet ID
        """
        self.sheet_id = sheet_id
        self.credentials = service_account.Credentials.from_service_account_file(
            str(credentials_path), scopes=self.SCOPES
        )
        self.service = build("sheets", "v4", credentials=self.credentials)
        self.sheets = self.service.spreadsheets()
        logger.info(f"Initialized Sheets client for sheet {sheet_id}")

    def read_range(self, range_name: str) -> list[list[str]]:
        """Read values from a range.

        Args:
            range_name: A1 notation range (e.g., "Sheet1!A1:Z100")

        Returns:
            List of rows, each row is a list of cell values

        Raises:
            HttpError: If API request fails
        """
        try:
            result = (
                self.sheets.values()
                .get(
                    spreadsheetId=self.sheet_id,
                    range=range_name,
                    valueRenderOption="UNFORMATTED_VALUE",
                    dateTimeRenderOption="SERIAL_NUMBER",
                )
                .execute()
            )
            values = result.get("values", [])
            logger.debug(f"Read {len(values)} rows from {range_name}")
            return values
        except HttpError as e:
            logger.error(f"Error reading range {range_name}: {e}")
            raise

    @retry_with_backoff(max_retries=5, base_delay=2.0)
    def write_range(self, range_name: str, values: list[list[Any]]):
        """Write values to a range.

        Args:
            range_name: A1 notation range
            values: List of rows to write

        Raises:
            HttpError: If API request fails
        """
        try:
            body = {"values": values}
            self.sheets.values().update(
                spreadsheetId=self.sheet_id,
                range=range_name,
                valueInputOption="USER_ENTERED",
                body=body,
            ).execute()
            logger.debug(f"Wrote {len(values)} rows to {range_name}")
        except HttpError as e:
            logger.error(f"Error writing range {range_name}: {e}")
            raise

    @retry_with_backoff(max_retries=5, base_delay=2.0)
    def append_rows(self, range_name: str, values: list[list[Any]]):
        """Append rows to the end of a range.

        Args:
            range_name: A1 notation range (e.g., "Transactions!A:A")
            values: List of rows to append

        Raises:
            HttpError: If API request fails
        """
        try:
            body = {"values": values}
            self.sheets.values().append(
                spreadsheetId=self.sheet_id,
                range=range_name,
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body=body,
            ).execute()
            logger.debug(f"Appended {len(values)} rows to {range_name}")
        except HttpError as e:
            logger.error(f"Error appending to {range_name}: {e}")
            raise

    @retry_with_backoff(max_retries=5, base_delay=2.0)
    def batch_update_values(self, data: list[dict[str, Any]]):
        """Batch update multiple ranges in a single API call.

        Args:
            data: List of update dicts, each with 'range' and 'values' keys
                  Example: [
                      {'range': 'Sheet1!A1', 'values': [['value']]},
                      {'range': 'Sheet1!B2', 'values': [['value2']]}
                  ]

        Raises:
            HttpError: If API request fails
        """
        if not data:
            return

        try:
            body = {"valueInputOption": "USER_ENTERED", "data": data}
            result = (
                self.sheets.values().batchUpdate(spreadsheetId=self.sheet_id, body=body).execute()
            )
            logger.debug(f"Batch updated {len(data)} ranges")
            return result
        except HttpError as e:
            logger.error(f"Error in batch values update: {e}")
            raise

    def batch_update(self, requests: list[dict]) -> dict:
        """Execute batch update requests.

        Args:
            requests: List of update request objects

        Returns:
            Response dict from batch update

        Raises:
            HttpError: If API request fails
        """
        try:
            body = {"requests": requests}
            response = self.sheets.batchUpdate(spreadsheetId=self.sheet_id, body=body).execute()
            logger.debug(f"Executed {len(requests)} batch requests")
            return response
        except HttpError as e:
            logger.error(f"Error in batch update: {e}")
            raise

    def get_sheet_metadata(self) -> dict:
        """Get spreadsheet metadata including sheet IDs.

        Returns:
            Spreadsheet metadata

        Raises:
            HttpError: If API request fails
        """
        try:
            return self.sheets.get(spreadsheetId=self.sheet_id).execute()
        except HttpError as e:
            logger.error(f"Error getting sheet metadata: {e}")
            raise

    def get_sheet_id_by_name(self, sheet_name: str) -> Optional[int]:
        """Get sheet ID (gid) by sheet name.

        Args:
            sheet_name: Name of the sheet tab

        Returns:
            Sheet ID (integer) or None if not found
        """
        metadata = self.get_sheet_metadata()
        for sheet in metadata.get("sheets", []):
            if sheet["properties"]["title"] == sheet_name:
                return sheet["properties"]["sheetId"]
        return None

    def create_sheet(self, sheet_name: str) -> int:
        """Create a new sheet tab.

        Args:
            sheet_name: Name for the new sheet

        Returns:
            Sheet ID of the created sheet

        Raises:
            HttpError: If API request fails
        """
        try:
            request = {"addSheet": {"properties": {"title": sheet_name}}}
            response = self.batch_update([request])
            sheet_id = response["replies"][0]["addSheet"]["properties"]["sheetId"]
            logger.info(f"Created sheet '{sheet_name}' with ID {sheet_id}")
            return sheet_id
        except HttpError as e:
            logger.error(f"Error creating sheet {sheet_name}: {e}")
            raise

    def freeze_rows(self, sheet_id: int, num_rows: int = 1):
        """Freeze top rows of a sheet.

        Args:
            sheet_id: Sheet ID (gid)
            num_rows: Number of rows to freeze

        Raises:
            HttpError: If API request fails
        """
        request = {
            "updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": num_rows}},
                "fields": "gridProperties.frozenRowCount",
            }
        }
        self.batch_update([request])
        logger.debug(f"Froze {num_rows} rows in sheet {sheet_id}")

    def create_protected_range(
        self,
        sheet_id: int,
        start_row: int,
        end_row: Optional[int],
        start_col: int,
        end_col: int,
        description: str = "Protected by G-Ledger",
    ):
        """Create a protected range.

        The service account email is automatically granted edit access,
        while regular users are restricted.

        Args:
            sheet_id: Sheet ID (gid)
            start_row: Start row (0-indexed)
            end_row: End row (0-indexed, None for unbounded)
            start_col: Start column (0-indexed)
            end_col: End column (0-indexed)
            description: Protection description

        Raises:
            HttpError: If API request fails
        """
        grid_range = {
            "sheetId": sheet_id,
            "startRowIndex": start_row,
            "startColumnIndex": start_col,
            "endColumnIndex": end_col,
        }
        if end_row is not None:
            grid_range["endRowIndex"] = end_row

        request = {
            "addProtectedRange": {
                "protectedRange": {
                    "range": grid_range,
                    "description": description,
                    "warningOnly": False,
                    "editors": {"users": [self.credentials.service_account_email]},
                }
            }
        }
        self.batch_update([request])
        logger.debug(f"Protected range in sheet {sheet_id}: cols {start_col}-{end_col}")

    def create_data_validation(
        self,
        sheet_id: int,
        start_row: int,
        end_row: Optional[int],
        start_col: int,
        end_col: int,
        values: Optional[list[str]] = None,
        validation_type: str = "ONE_OF_LIST",
        strict: bool = True,
    ):
        """Create data validation rule.

        Args:
            sheet_id: Sheet ID (gid)
            start_row: Start row (0-indexed)
            end_row: End row (0-indexed, None for unbounded)
            start_col: Start column (0-indexed)
            end_col: End column (0-indexed)
            values: List of valid values (for dropdown)
            validation_type: Type of validation (ONE_OF_LIST, etc.)
            strict: Whether to reject invalid input

        Raises:
            HttpError: If API request fails
        """
        grid_range = {
            "sheetId": sheet_id,
            "startRowIndex": start_row,
            "startColumnIndex": start_col,
            "endColumnIndex": end_col,
        }
        if end_row is not None:
            grid_range["endRowIndex"] = end_row

        condition = {"type": validation_type}
        if values:
            condition["values"] = [{"userEnteredValue": v} for v in values]

        request = {
            "setDataValidation": {
                "range": grid_range,
                "rule": {"condition": condition, "strict": strict, "showCustomUi": True},
            }
        }
        self.batch_update([request])
        logger.debug(f"Added validation to sheet {sheet_id}: cols {start_col}-{end_col}")

    def create_checkbox_validation(
        self, sheet_id: int, start_row: int, end_row: Optional[int], start_col: int, end_col: int
    ):
        """Create checkbox validation (boolean).

        Args:
            sheet_id: Sheet ID (gid)
            start_row: Start row (0-indexed)
            end_row: End row (0-indexed, None for unbounded)
            start_col: Start column (0-indexed)
            end_col: End column (0-indexed)

        Raises:
            HttpError: If API request fails
        """
        grid_range = {
            "sheetId": sheet_id,
            "startRowIndex": start_row,
            "startColumnIndex": start_col,
            "endColumnIndex": end_col,
        }
        if end_row is not None:
            grid_range["endRowIndex"] = end_row

        request = {
            "setDataValidation": {
                "range": grid_range,
                "rule": {"condition": {"type": "BOOLEAN"}, "strict": True, "showCustomUi": True},
            }
        }
        self.batch_update([request])
        logger.debug(f"Added checkbox validation to sheet {sheet_id}: cols {start_col}-{end_col}")

    def update_basic_filter_range(self, sheet_id: int, end_row: int, num_columns: int):
        """Update the basic filter range to include new rows.

        Args:
            sheet_id: Sheet ID (gid)
            end_row: Last row with data (1-based)
            num_columns: Number of columns to include in filter

        Raises:
            HttpError: If API request fails
        """
        # Clear existing filter first, then recreate with new range
        # We need to clear because setBasicFilter replaces the entire filter
        request = {
            "setBasicFilter": {
                "filter": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,  # Include header
                        "endRowIndex": end_row,  # 0-based exclusive, so end_row is correct
                        "startColumnIndex": 0,
                        "endColumnIndex": num_columns,
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
        self.batch_update([request])
        logger.debug(f"Updated filter range for sheet {sheet_id} to row {end_row}")
