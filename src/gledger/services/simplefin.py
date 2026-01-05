"""SimpleFIN API client for fetching bank transactions."""

from datetime import date, datetime, timedelta
from typing import Any, Optional
import requests
from requests.auth import HTTPBasicAuth

from ..utils.logging import get_logger

logger = get_logger(__name__)


class SimpleFINClient:
    """Client for SimpleFIN Bridge API.

    SimpleFIN provides read-only access to bank transactions via a secure token.
    API documentation: https://beta-bridge.simplefin.org/info/api
    """

    def __init__(self, token: str, base_url: str = "https://bridge.simplefin.org/simplefin"):
        """Initialize SimpleFIN client.

        Args:
            token: SimpleFIN access token (setup token or claim URL)
            base_url: SimpleFIN API base URL
        """
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.session = requests.Session()

        # Parse token for authentication
        # SimpleFIN tokens are in format: https://username:password@bridge.simplefin.org/simplefin
        # Or just the credentials part: username:password
        if "://" in token:
            # Extract credentials from URL
            parts = token.split("://")
            if len(parts) > 1:
                creds_and_host = parts[1]
                if "@" in creds_and_host:
                    creds = creds_and_host.split("@")[0]
                    username, password = creds.split(":", 1)
                    self.auth = HTTPBasicAuth(username, password)
                else:
                    raise ValueError("Invalid SimpleFIN token format")
            else:
                raise ValueError("Invalid SimpleFIN token format")
        elif ":" in token:
            # Direct credentials
            username, password = token.split(":", 1)
            self.auth = HTTPBasicAuth(username, password)
        else:
            raise ValueError("Invalid SimpleFIN token format")

        logger.info("Initialized SimpleFIN client")

    def get_accounts(self, balances_only: bool = False) -> list[dict[str, Any]]:
        """Fetch all accounts from SimpleFIN.

        Args:
            balances_only: If True, fetch only balances without transaction data

        Returns:
            List of account dictionaries with structure:
            {
                'id': str,
                'name': str,
                'org': {'name': str},
                'currency': str,
                'balance': float,
                'available-balance': float,
                ...
            }

        Raises:
            requests.HTTPError: If API request fails
        """
        url = f"{self.base_url}/accounts"
        params = {}

        # If balances_only, don't include transaction data
        if balances_only:
            params["balances-only"] = "1"

        try:
            response = self.session.get(url, auth=self.auth, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            accounts = data.get("accounts", [])
            logger.info(f"Fetched {len(accounts)} accounts from SimpleFIN")
            return accounts

        except requests.HTTPError as e:
            logger.error(f"SimpleFIN API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Error fetching SimpleFIN accounts: {e}")
            raise

    def get_transactions(
        self,
        account_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        posted_only: bool = True,
    ) -> list[dict[str, Any]]:
        """Fetch transactions for an account.

        Args:
            account_id: SimpleFIN account ID
            start_date: Start date (inclusive). If None, uses 30 days ago.
            end_date: End date (exclusive). If None, uses today + 1 day.
            posted_only: If True, exclude pending transactions

        Returns:
            List of transaction dictionaries with structure:
            {
                'id': str,
                'posted': int (Unix timestamp),
                'amount': int (cents),
                'description': str,
                'memo': str,
                'pending': bool,
                ...
            }

        Raises:
            requests.HTTPError: If API request fails
        """
        url = f"{self.base_url}/accounts"

        # Set date defaults
        if end_date is None:
            end_date = date.today() + timedelta(days=1)  # API end_date is exclusive
        if start_date is None:
            start_date = end_date - timedelta(days=31)  # Go back 31 days from end

        # Build query parameters
        params = {
            "start-date": int(datetime.combine(start_date, datetime.min.time()).timestamp()),
            "end-date": int(datetime.combine(end_date, datetime.min.time()).timestamp()),
            "account": account_id,
        }

        # Include pending transactions if requested
        if not posted_only:
            params["pending"] = "1"

        try:
            response = self.session.get(url, auth=self.auth, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            # Find the account
            accounts = data.get("accounts", [])
            target_account = None
            for account in accounts:
                if account.get("id") == account_id:
                    target_account = account
                    break

            if not target_account:
                logger.warning(f"Account {account_id} not found in SimpleFIN response")
                return []

            # Extract transactions (already filtered by API)
            transactions = target_account.get("transactions", [])

            logger.info(
                f"Fetched {len(transactions)} transactions for account {account_id} "
                f"({start_date} to {end_date})"
            )
            return transactions

        except requests.HTTPError as e:
            logger.error(f"SimpleFIN API error for account {account_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error fetching transactions for account {account_id}: {e}")
            raise

    def get_all_transactions(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        posted_only: bool = True,
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch transactions for all accounts.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (exclusive)
            posted_only: If True, exclude pending transactions

        Returns:
            Dict mapping account_id to list of transactions

        Raises:
            requests.HTTPError: If API request fails
        """
        # Set date defaults
        if end_date is None:
            end_date = date.today() + timedelta(days=1)  # API end_date is exclusive
        if start_date is None:
            start_date = end_date - timedelta(days=31)  # Go back 31 days from end

        # Build query parameters
        params = {
            "start-date": int(datetime.combine(start_date, datetime.min.time()).timestamp()),
            "end-date": int(datetime.combine(end_date, datetime.min.time()).timestamp()),
        }

        # Include pending transactions if requested
        if not posted_only:
            params["pending"] = "1"

        try:
            url = f"{self.base_url}/accounts"
            response = self.session.get(url, auth=self.auth, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            accounts = data.get("accounts", [])
            result = {}

            for account in accounts:
                account_id = account.get("id")
                if not account_id:
                    continue

                # Transactions are already filtered by API
                transactions = account.get("transactions", [])
                result[account_id] = transactions

            total_txns = sum(len(txns) for txns in result.values())
            logger.info(
                f"Fetched {total_txns} transactions across {len(result)} accounts "
                f"({start_date} to {end_date})"
            )
            return result

        except requests.HTTPError as e:
            logger.error(f"SimpleFIN API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Error fetching all transactions: {e}")
            raise

    def _is_pending(self, txn: dict[str, Any]) -> bool:
        """Check if a transaction is pending.

        Args:
            txn: Transaction dictionary

        Returns:
            True if transaction is pending
        """
        # SimpleFIN marks pending transactions with 'pending': true
        # or transacted timestamp without posted timestamp
        if txn.get("pending"):
            return True

        # If transacted but not posted, it's pending
        if txn.get("transacted") and not txn.get("posted"):
            return True

        return False

    def normalize_transaction(self, txn: dict[str, Any], account_id: str) -> dict[str, Any]:
        """Normalize SimpleFIN transaction to our internal format.

        Args:
            txn: SimpleFIN transaction dict
            account_id: Account ID this transaction belongs to

        Returns:
            Normalized transaction dict with keys:
            - sf_txn_id
            - sf_account_id
            - sf_date
            - sf_amount (Decimal, signed)
            - sf_payee
            - sf_memo
        """

        # Convert posted timestamp to date
        posted_ts = txn.get("posted", 0)
        posted_date = datetime.fromtimestamp(posted_ts).date() if posted_ts else date.today()

        # Get the amount in dollars
        amount = txn.get("amount", 0)

        # Extract description and memo
        description = txn.get("description", "")
        memo = txn.get("memo", "")

        return {
            "sf_txn_id": str(txn.get("id", "")),
            "sf_account_id": account_id,
            "sf_date": posted_date,
            "sf_amount": amount,
            "sf_payee": description,
            "sf_memo": memo,
        }
