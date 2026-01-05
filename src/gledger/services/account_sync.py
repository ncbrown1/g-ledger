"""Account sync service for syncing SimpleFIN accounts to sheet."""

import socket
import time
from typing import Any
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel

from ..models.account import Account
from ..models.balance_history import BalanceSnapshot
from ..models.audit_log import AuditLogEntry
from ..models.enums import AccountType
from ..repositories.sheet_repo import SheetRepository
from ..services.simplefin import SimpleFINClient
from ..utils.logging import get_logger

logger = get_logger(__name__)


class AccountSyncResult(BaseModel):
    """Result of account sync operation."""

    new_count: int = 0
    updated_count: int = 0
    unchanged_count: int = 0
    balance_snapshots_count: int = 0
    needs_attention_count: int = 0  # Accounts failing reconciliation check
    errors: list[str] = []


class AccountSyncService:
    """Syncs SimpleFIN accounts to Google Sheet Accounts tab.

    Fetches accounts from SimpleFIN and updates the Accounts tab,
    preserving user edits to configuration fields.
    """

    def __init__(self, sheet_repo: SheetRepository, simplefin_client: SimpleFINClient):
        """Initialize account sync service.

        Args:
            sheet_repo: Sheet repository
            simplefin_client: SimpleFIN client
        """
        self.sheet_repo = sheet_repo
        self.simplefin = simplefin_client
        logger.info("Initialized AccountSyncService")

    def sync_accounts(self) -> AccountSyncResult:
        """Sync SimpleFIN accounts to sheet.

        Fetches accounts from SimpleFIN and updates/adds them to the Accounts tab.
        Preserves user-editable fields (enabled, reconcile settings).

        Returns:
            AccountSyncResult with counts
        """
        result = AccountSyncResult()
        start_time = time.time()
        hostname = socket.gethostname()
        audit_entry = None

        try:
            # Fetch SimpleFIN accounts (balances only, no transactions)
            logger.info("Fetching accounts from SimpleFIN...")
            sf_accounts = self.simplefin.get_accounts(balances_only=True)
            logger.info(f"Found {len(sf_accounts)} accounts in SimpleFIN")

            # Read existing accounts from sheet
            existing_accounts = self.sheet_repo.read_accounts(enabled_only=False)
            accounts_by_id = {a.sf_account_id: a for a in existing_accounts}
            logger.info(f"Found {len(existing_accounts)} existing accounts in sheet")

            # Process each SimpleFIN account
            accounts_to_write = []
            for sf_account in sf_accounts:
                sf_account_id = sf_account.get("id", "")
                if not sf_account_id:
                    logger.warning("SimpleFIN account missing 'id', skipping")
                    continue

                if sf_account_id in accounts_by_id:
                    # Update existing account (limited fields only)
                    account = accounts_by_id[sf_account_id]
                    updated = self._update_account_metadata(account, sf_account)
                    accounts_to_write.append(account)

                    if updated:
                        result.updated_count += 1
                        logger.info(f"Updated metadata for account {sf_account_id}")
                    else:
                        result.unchanged_count += 1
                else:
                    # New account - add with defaults
                    account = self._create_account_from_simplefin(sf_account)
                    accounts_to_write.append(account)
                    result.new_count += 1
                    logger.info(f"Added new account {sf_account_id}: {account.display_name}")

            # Add any manual accounts that aren't from SimpleFIN
            for existing_account in existing_accounts:
                if (
                    existing_account.sf_account_id not in {a.get("id") for a in sf_accounts}
                    and existing_account.sf_account_id
                ):
                    # Keep manual/disconnected accounts
                    accounts_to_write.append(existing_account)
                    logger.debug(f"Preserving manual account: {existing_account.sf_account_id}")

            # Capture balance snapshots for changed balances
            # Check if this is first run (empty Balance History sheet)
            existing_history = self.sheet_repo.read_balance_history()
            is_first_run = len(existing_history) == 0

            if is_first_run:
                logger.info(
                    "Balance History is empty - creating initial snapshots for all accounts"
                )

            balance_snapshots = self._capture_balance_snapshots(
                accounts_to_write, accounts_by_id, force_initial=is_first_run
            )
            if balance_snapshots:
                snapshot_type = "initial snapshots" if is_first_run else "balance snapshots"
                logger.info(f"Appending {len(balance_snapshots)} {snapshot_type}...")
                self.sheet_repo.append_balance_snapshots(balance_snapshots)
                result.balance_snapshots_count = len(balance_snapshots)

            # Compute reconciliation status for all accounts
            needs_attention = self._compute_reconciliation_status(accounts_to_write)
            result.needs_attention_count = needs_attention

            # Write all accounts back to sheet
            if accounts_to_write:
                logger.info(f"Writing {len(accounts_to_write)} accounts to sheet...")
                self.sheet_repo.write_accounts(accounts_to_write)
                logger.info("Accounts synced successfully")

        except Exception as e:
            logger.error(f"Error syncing accounts: {e}", exc_info=True)
            result.errors.append(str(e))

            # Create audit log entry for failure
            duration = time.time() - start_time
            audit_entry = AuditLogEntry(
                timestamp=datetime.now(),
                command="accounts-sync",
                hostname=hostname,
                status="FAILED",
                new_count=result.new_count,
                updated_count=result.updated_count,
                unchanged_count=result.unchanged_count,
                needs_attention_count=result.needs_attention_count,
                duration_seconds=duration,
                error_type=type(e).__name__,
                error_message=str(e)[:200],  # Truncate to 200 chars
            )

        else:
            # Create audit log entry for success
            duration = time.time() - start_time
            audit_entry = AuditLogEntry(
                timestamp=datetime.now(),
                command="accounts-sync",
                hostname=hostname,
                status="SUCCESS",
                new_count=result.new_count,
                updated_count=result.updated_count,
                unchanged_count=result.unchanged_count,
                needs_attention_count=result.needs_attention_count,
                duration_seconds=duration,
            )

        finally:
            # Always write audit log entry (even on failure)
            if audit_entry:
                try:
                    self.sheet_repo.append_audit_log_entry(audit_entry)
                except Exception as log_error:
                    logger.error(f"Failed to write audit log: {log_error}")

        logger.info(
            f"Account sync complete: {result.new_count} new, {result.updated_count} updated, "
            f"{result.unchanged_count} unchanged, {result.balance_snapshots_count} balance snapshots, "
            f"{result.needs_attention_count} need attention"
        )
        return result

    def _create_account_from_simplefin(self, sf_account: dict[str, Any]) -> Account:
        """Create new Account from SimpleFIN data.

        Args:
            sf_account: SimpleFIN account dict

        Returns:
            Account with defaults
        """
        from decimal import Decimal
        from datetime import datetime

        # Extract basic info
        sf_account_id = sf_account.get("id", "")
        name = sf_account.get("name", "Unknown Account")
        org = sf_account.get("org", {})
        institution = org.get("domain", "")
        org_name = org.get("name", "")
        currency = sf_account.get("currency", "USD")

        # Parse balance data
        balance = Decimal(str(sf_account.get("balance", "0")))
        available_balance = Decimal(str(sf_account.get("available-balance", "0")))
        balance_date_ts = sf_account.get("balance-date", 0)
        balance_date = datetime.fromtimestamp(balance_date_ts) if balance_date_ts else None

        # Try to guess account type from name
        account_type = self._guess_account_type(name)

        return Account(
            sf_account_id=sf_account_id,
            enabled=False,  # User must explicitly enable
            ignored=False,
            institution=institution,
            sf_org_name=org_name,
            display_name=name,
            account_type=account_type,
            currency=currency,
            balance=balance,
            available_balance=available_balance,
            balance_date=balance_date,
            last_synced_at=datetime.now(),
            reconcile_date=None,
            notes="Auto-synced from SimpleFIN",
        )

    def _update_account_metadata(self, account: Account, sf_account: dict[str, Any]) -> bool:
        """Update account metadata from SimpleFIN (non-user fields only).

        Only updates fields that are pure metadata from SimpleFIN,
        not user configuration fields like enabled, account_type.

        Args:
            account: Existing Account object
            sf_account: SimpleFIN account dict

        Returns:
            True if any field was updated
        """
        from decimal import Decimal
        from datetime import datetime

        updated = False

        # Update institution if changed
        org = sf_account.get("org", {})
        new_institution = org.get("domain", "")
        if new_institution and account.institution != new_institution:
            account.institution = new_institution
            updated = True

        # Update sf_org_name if changed
        new_org_name = org.get("name", "")
        if new_org_name and account.sf_org_name != new_org_name:
            account.sf_org_name = new_org_name
            updated = True

        # Update currency if changed
        new_currency = sf_account.get("currency", "USD")
        if account.currency != new_currency:
            account.currency = new_currency
            updated = True

        # Always update balance data
        new_balance = Decimal(str(sf_account.get("balance", "0")))
        new_available_balance = Decimal(str(sf_account.get("available-balance", "0")))
        balance_date_ts = sf_account.get("balance-date", 0)
        new_balance_date = datetime.fromtimestamp(balance_date_ts) if balance_date_ts else None

        if account.balance != new_balance:
            account.balance = new_balance
            updated = True

        if account.available_balance != new_available_balance:
            account.available_balance = new_available_balance
            updated = True

        if account.balance_date != new_balance_date:
            account.balance_date = new_balance_date
            updated = True

        # Always update last_synced_at
        account.last_synced_at = datetime.now()
        updated = True

        # Update display_name ONLY if it's still the default (user hasn't customized)
        # We check if it matches the current SimpleFIN name or is empty
        new_name = sf_account.get("name", "")
        if new_name and not account.display_name:
            account.display_name = new_name
            updated = True

        # DO NOT update account_type - this is user-controlled

        return updated

    def _guess_account_type(self, account_name: str) -> AccountType:
        """Guess account type from account name.

        Args:
            account_name: Account name from SimpleFIN

        Returns:
            Guessed AccountType
        """
        name_lower = account_name.lower()

        if "checking" in name_lower or "chk" in name_lower:
            return AccountType.CHECKING
        elif "savings" in name_lower or "sav" in name_lower:
            return AccountType.SAVINGS
        elif "credit" in name_lower or "card" in name_lower or "cc" in name_lower:
            return AccountType.CC
        elif "investment" in name_lower or "brokerage" in name_lower or "ira" in name_lower:
            return AccountType.INVESTMENT
        elif "loan" in name_lower or "mortgage" in name_lower:
            return AccountType.LOAN
        else:
            return AccountType.CHECKING  # Default

    def list_accounts(self) -> list[dict[str, Any]]:
        """List accounts from SimpleFIN with details.

        Returns:
            List of account dicts with formatted info
        """
        try:
            sf_accounts = self.simplefin.get_accounts(balances_only=True)
            accounts = []

            for sf_account in sf_accounts:
                org = sf_account.get("org", {})
                accounts.append(
                    {
                        "id": sf_account.get("id", ""),
                        "name": sf_account.get("name", ""),
                        "institution": org.get("domain", ""),
                        "org_name": org.get("name", ""),
                        "currency": sf_account.get("currency", "USD"),
                        "balance": sf_account.get("balance", "0"),
                        "available_balance": sf_account.get("available-balance", "0"),
                    }
                )

            return accounts

        except Exception as e:
            logger.error(f"Error listing accounts: {e}", exc_info=True)
            return []

    def _capture_balance_snapshots(
        self,
        accounts: list[Account],
        previous_accounts: dict[str, Account],
        force_initial: bool = False,
    ) -> list[BalanceSnapshot]:
        """Capture balance snapshots for accounts where balance has changed.

        Only creates snapshots if:
        1. force_initial=True (first run, create snapshots for all non-ignored accounts), OR
        2. Balance has changed from the most recent value in Balance History sheet

        Args:
            accounts: Current accounts list
            previous_accounts: Dict mapping sf_account_id to previous Account state (unused)
            force_initial: If True, create initial snapshots for all accounts (first run)

        Returns:
            List of BalanceSnapshot objects to append
        """
        snapshots = []
        now = datetime.now()

        # Read existing balance history to get most recent balances
        existing_history = self.sheet_repo.read_balance_history()

        # Build dict of most recent balance per account (by recorded_at)
        most_recent_balances = {}
        for snapshot in existing_history:
            account_id = snapshot.sf_account_id
            if account_id not in most_recent_balances:
                most_recent_balances[account_id] = snapshot
            else:
                # Keep the snapshot with the most recent recorded_at
                if snapshot.recorded_at > most_recent_balances[account_id].recorded_at:
                    most_recent_balances[account_id] = snapshot

        for account in accounts:
            # Skip ignored accounts
            if account.ignored:
                continue

            # Skip if no balance data
            if account.balance is None or account.balance_date is None:
                continue

            # Check if balance changed from most recent snapshot in Balance History
            balance_changed = force_initial  # Always true on first run
            if not force_initial:
                if account.sf_account_id in most_recent_balances:
                    most_recent = most_recent_balances[account.sf_account_id]
                    if most_recent.balance != account.balance:
                        balance_changed = True
                        logger.debug(
                            f"Balance changed for {account.sf_account_id}: "
                            f"{most_recent.balance} → {account.balance}"
                        )
                else:
                    # No history for this account - create initial snapshot
                    balance_changed = True
                    logger.debug(
                        f"No history for {account.sf_account_id}, creating initial snapshot"
                    )

            # Only create snapshot if balance changed or first run
            if balance_changed:
                snapshot = BalanceSnapshot(
                    sf_account_id=account.sf_account_id,
                    account_name=account.display_name,
                    account_type=account.account_type.value if account.account_type else None,
                    balance_date=(
                        account.balance_date.date()
                        if isinstance(account.balance_date, datetime)
                        else account.balance_date
                    ),
                    balance=account.balance,
                    available_balance=account.available_balance,
                    recorded_at=now,
                    source="simplefin",
                    is_starting_balance=False,  # SimpleFIN snapshots are not starting balances
                    notes=None,
                )
                snapshots.append(snapshot)

        return snapshots

    def _compute_reconciliation_status(self, accounts: list[Account]) -> int:
        """Compute reconciliation status for accounts.

        Updates account reconciliation fields:
        - starting_balance: looked up from Balance History based on reconcile_date
        - starting_balance_date: date of the starting balance from Balance History
        - expected_balance: computed from starting_balance + transaction sum
        - balance_discrepancy: actual balance - expected balance
        - reconciliation_status_text: OK, DISCREPANCY, or NO_STARTING_BALANCE

        Logic:
        - Only processes enabled accounts (ignored accounts are skipped)
        - If reconcile_date is empty: uses OLDEST balance from Balance History
        - If reconcile_date is set: uses most recent balance where balance_date < reconcile_date

        Args:
            accounts: List of accounts to update (modified in place)

        Returns:
            Count of accounts that need attention (have discrepancies or errors)
        """
        needs_attention_count = 0

        # Read all balance history upfront (single read for efficiency)
        all_balance_history = self.sheet_repo.read_balance_history()

        for account in accounts:
            # Skip ignored accounts
            if account.ignored:
                account.starting_balance = None
                account.starting_balance_date = None
                account.expected_balance = None
                account.balance_discrepancy = None
                account.reconciliation_status_text = "IGNORED"
                continue

            # Skip disabled accounts (only reconcile enabled accounts)
            if not account.enabled:
                account.starting_balance = None
                account.starting_balance_date = None
                account.expected_balance = None
                account.balance_discrepancy = None
                account.reconciliation_status_text = None
                continue

            # Skip if account has no current balance
            if account.balance is None:
                account.starting_balance = None
                account.starting_balance_date = None
                account.expected_balance = None
                account.balance_discrepancy = None
                account.reconciliation_status_text = "NO_BALANCE"
                continue

            # Find starting balance from Balance History
            account_history = [
                h
                for h in all_balance_history
                if h.sf_account_id == account.sf_account_id and h.balance_date is not None
            ]

            if not account_history:
                # No balance history for this account
                account.starting_balance = None
                account.starting_balance_date = None
                account.expected_balance = None
                account.balance_discrepancy = None
                account.reconciliation_status_text = "NO_BALANCE_HISTORY"
                continue

            # Sort by balance_date
            account_history.sort(key=lambda h: h.balance_date)

            # Determine starting balance based on reconcile_date
            if account.reconcile_date is None:
                # Never reconciled - prefer entries marked as starting_balance
                starting_balance_entries = [h for h in account_history if h.is_starting_balance]
                if starting_balance_entries:
                    # Use OLDEST entry marked as starting balance
                    starting_snapshot = starting_balance_entries[0]
                else:
                    # Fall back to OLDEST balance from history
                    starting_snapshot = account_history[0]
                account.starting_balance = starting_snapshot.balance
                account.starting_balance_date = starting_snapshot.balance_date
            else:
                # Find most recent balance where balance_date < reconcile_date
                eligible_snapshots = [
                    h for h in account_history if h.balance_date < account.reconcile_date
                ]

                if not eligible_snapshots:
                    # No balance history before reconcile_date
                    account.starting_balance = None
                    account.starting_balance_date = None
                    account.expected_balance = None
                    account.balance_discrepancy = None
                    account.reconciliation_status_text = "NO_BALANCE_BEFORE_RECONCILE_DATE"
                    continue

                # Use most recent eligible snapshot
                starting_snapshot = eligible_snapshots[-1]  # Already sorted
                account.starting_balance = starting_snapshot.balance
                account.starting_balance_date = starting_snapshot.balance_date

            # Compute expected balance from transactions
            # For now, we'll just use starting_balance as expected (full computation in reconciliation service)
            # This is a placeholder - the reconciliation service will compute transaction sums
            try:
                # Read transactions for this account (match by sf_account_id)
                all_transactions = self.sheet_repo.read_transactions()
                account_transactions = [
                    t
                    for t in all_transactions
                    if hasattr(t, "sf_account_id") and t.sf_account_id == account.sf_account_id
                ]

                # Filter to transactions after starting_balance_date
                if account.starting_balance_date:
                    relevant_txns = [
                        t
                        for t in account_transactions
                        if t.date and t.date >= account.starting_balance_date
                    ]
                else:
                    relevant_txns = account_transactions

                # Sum transaction amounts
                transaction_sum = sum((t.amount or Decimal("0")) for t in relevant_txns)

                # Expected balance = starting balance + transaction sum
                expected = account.starting_balance + transaction_sum
                account.expected_balance = expected

                # Compute discrepancy
                discrepancy = account.balance - expected
                account.balance_discrepancy = discrepancy

                # Set status text
                tolerance = Decimal("0.01")
                if abs(discrepancy) <= tolerance:
                    account.reconciliation_status_text = "OK"
                else:
                    account.reconciliation_status_text = f"DISCREPANCY: ${discrepancy:.2f}"
                    needs_attention_count += 1

                logger.debug(
                    f"Reconciliation for {account.sf_account_id}: "
                    f"expected={expected}, actual={account.balance}, "
                    f"discrepancy={discrepancy}"
                )

            except Exception as e:
                logger.warning(f"Error computing reconciliation for {account.sf_account_id}: {e}")
                account.expected_balance = None
                account.balance_discrepancy = None
                account.reconciliation_status_text = "ERROR"
                needs_attention_count += 1

        return needs_attention_count
