"""Snapshot repository for git-based versioning of sheet data."""

import csv
import json
from pathlib import Path
from typing import Optional
from datetime import datetime
import git

from ..models.account import Account
from ..models.transaction import Transaction
from ..services.sync_engine import SyncResult
from ..utils.logging import get_logger

logger = get_logger(__name__)


class SnapshotRepository:
    """Handles snapshots of sheet data with git versioning.

    Exports sheet data to CSV files and commits to a local git repository.
    Provides restore functionality to rollback to previous snapshots.
    """

    def __init__(self, snapshot_dir: Path):
        """Initialize snapshot repository.

        Args:
            snapshot_dir: Directory for snapshots (will contain git repo)
        """
        self.snapshot_dir = snapshot_dir
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.repo: Optional[git.Repo] = None
        logger.info(f"Initialized SnapshotRepository at {snapshot_dir}")

    def initialize_repo(self):
        """Initialize git repository in snapshot directory."""
        git_dir = self.snapshot_dir / ".git"

        if git_dir.exists():
            try:
                self.repo = git.Repo(self.snapshot_dir)
                logger.debug("Loaded existing git repo")
            except git.InvalidGitRepositoryError:
                logger.warning("Invalid git repo, reinitializing...")
                self.repo = git.Repo.init(self.snapshot_dir)
        else:
            logger.info("Initializing new git repo...")
            self.repo = git.Repo.init(self.snapshot_dir)

            # Create .gitignore
            gitignore_path = self.snapshot_dir / ".gitignore"
            if not gitignore_path.exists():
                gitignore_path.write_text("*.pyc\n__pycache__/\n.DS_Store\n")
                self.repo.index.add([".gitignore"])
                self.repo.index.commit("Initial commit")

    def create_snapshot(
        self,
        accounts: list[Account],
        transactions: list[Transaction],
        sync_result: Optional[SyncResult] = None,
    ) -> str:
        """Create a snapshot of sheet data.

        Args:
            accounts: List of accounts
            transactions: List of transactions
            sync_result: Optional sync result for commit message

        Returns:
            Commit hash

        Raises:
            Exception: If snapshot creation fails
        """
        if not self.repo:
            self.initialize_repo()

        try:
            # Export to CSV
            accounts_path = self.snapshot_dir / "accounts.csv"
            transactions_path = self.snapshot_dir / "transactions.csv"

            self._export_accounts_csv(accounts, accounts_path)
            self._export_transactions_csv(transactions, transactions_path)

            # Also export metadata
            metadata = {
                "timestamp": datetime.now().isoformat(),
                "account_count": len(accounts),
                "transaction_count": len(transactions),
            }
            if sync_result:
                metadata["sync_result"] = {
                    "new": sync_result.new_count,
                    "updated": sync_result.updated_count,
                    "unchanged": sync_result.unchanged_count,
                    "flagged": sync_result.review_flagged_count,
                    "errors": sync_result.error_count,
                }

            metadata_path = self.snapshot_dir / "metadata.json"
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)

            # Git add and commit
            self.repo.index.add(["accounts.csv", "transactions.csv", "metadata.json"])
            commit_msg = self._generate_commit_message(sync_result)
            commit = self.repo.index.commit(commit_msg)

            logger.info(f"Created snapshot: {commit.hexsha[:8]}")
            return commit.hexsha

        except Exception as e:
            logger.error(f"Error creating snapshot: {e}", exc_info=True)
            raise

    def restore_snapshot(self, commit_hash: str) -> tuple[list[Account], list[Transaction]]:
        """Restore snapshot from git commit.

        Args:
            commit_hash: Commit hash to restore

        Returns:
            Tuple of (accounts, transactions)

        Raises:
            Exception: If restore fails
        """
        if not self.repo:
            self.initialize_repo()

        try:
            # Checkout the commit
            self.repo.git.checkout(commit_hash)

            # Read CSVs
            accounts_path = self.snapshot_dir / "accounts.csv"
            transactions_path = self.snapshot_dir / "transactions.csv"

            accounts = self._import_accounts_csv(accounts_path)
            transactions = self._import_transactions_csv(transactions_path)

            # Return to HEAD
            self.repo.git.checkout("HEAD")

            logger.info(
                f"Restored snapshot {commit_hash[:8]}: "
                f"{len(accounts)} accounts, {len(transactions)} transactions"
            )
            return accounts, transactions

        except Exception as e:
            logger.error(f"Error restoring snapshot {commit_hash}: {e}", exc_info=True)
            # Try to return to HEAD
            try:
                self.repo.git.checkout("HEAD")
            except Exception:
                pass
            raise

    def list_snapshots(self, limit: int = 10) -> list[dict]:
        """List recent snapshots.

        Args:
            limit: Maximum number of snapshots to return

        Returns:
            List of snapshot metadata dicts
        """
        if not self.repo:
            self.initialize_repo()

        snapshots = []
        for commit in list(self.repo.iter_commits())[:limit]:
            snapshots.append(
                {
                    "hash": commit.hexsha,
                    "short_hash": commit.hexsha[:8],
                    "message": commit.message.strip(),
                    "author": str(commit.author),
                    "timestamp": datetime.fromtimestamp(commit.committed_date).isoformat(),
                }
            )

        return snapshots

    def _export_accounts_csv(self, accounts: list[Account], path: Path):
        """Export accounts to CSV.

        Args:
            accounts: List of accounts
            path: Output CSV path
        """
        fieldnames = [
            "sf_account_id",
            "enabled",
            "institution",
            "display_name",
            "account_type",
            "currency",
            "reconcile_date",
            "notes",
        ]

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for account in accounts:
                row = {
                    "sf_account_id": account.sf_account_id,
                    "enabled": account.enabled,
                    "institution": account.institution or "",
                    "display_name": account.display_name,
                    "account_type": account.account_type.value,
                    "currency": account.currency,
                    "reconcile_date": (
                        account.reconcile_date.isoformat() if account.reconcile_date else ""
                    ),
                    "notes": account.notes or "",
                }
                writer.writerow(row)

        logger.debug(f"Exported {len(accounts)} accounts to {path}")

    def _export_transactions_csv(self, transactions: list[Transaction], path: Path):
        """Export transactions to CSV.

        Args:
            transactions: List of transactions
            path: Output CSV path
        """
        fieldnames = [
            "sf_account_id",
            "sf_txn_id",
            "txn_key",
            "row_role",
            "sf_date",
            "sf_amount",
            "sf_payee",
            "sf_memo",
            "sf_imported_at",
            "sf_last_seen_at",
            "date",
            "accounting_month",
            "amount",
            "payee",
            "memo",
            "category",
            "tags",
            "account_name",
            "account_type",
            "review_status",
            "review_notes",
            "needs_attention",
        ]

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for txn in transactions:
                row = {
                    "sf_account_id": txn.sf_account_id,
                    "sf_txn_id": txn.sf_txn_id or "",
                    "txn_key": txn.txn_key,
                    "row_role": txn.row_role.value,
                    "sf_date": txn.sf_date.isoformat() if txn.sf_date else "",
                    "sf_amount": str(txn.sf_amount) if txn.sf_amount else "",
                    "sf_payee": txn.sf_payee or "",
                    "sf_memo": txn.sf_memo or "",
                    "sf_imported_at": txn.sf_imported_at.isoformat() if txn.sf_imported_at else "",
                    "sf_last_seen_at": (
                        txn.sf_last_seen_at.isoformat() if txn.sf_last_seen_at else ""
                    ),
                    "date": txn.date.isoformat() if txn.date else "",
                    "accounting_month": txn.accounting_month or "",
                    "amount": str(txn.amount),
                    "payee": txn.payee,
                    "memo": txn.memo or "",
                    "category": txn.category or "",
                    "tags": txn.tags or "",
                    "account_name": txn.account_name or "",
                    "account_type": txn.account_type or "",
                    "review_status": txn.review_status.value,
                    "review_notes": txn.review_notes or "",
                    "needs_attention": txn.needs_attention,
                }
                writer.writerow(row)

        logger.debug(f"Exported {len(transactions)} transactions to {path}")

    def _import_accounts_csv(self, path: Path) -> list[Account]:
        """Import accounts from CSV.

        Args:
            path: CSV file path

        Returns:
            List of Account objects
        """
        from ..models.enums import AccountType
        from dateutil import parser as date_parser

        accounts = []
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                account = Account(
                    sf_account_id=row["sf_account_id"],
                    enabled=row["enabled"].lower() in ("true", "yes", "1"),
                    institution=row["institution"] or None,
                    display_name=row["display_name"],
                    account_type=AccountType(row["account_type"]),
                    currency=row["currency"] or "USD",
                    reconcile_date=(
                        date_parser.parse(row["reconcile_date"]).date()
                        if row["reconcile_date"]
                        else None
                    ),
                    notes=row["notes"] or None,
                )
                accounts.append(account)

        return accounts

    def _import_transactions_csv(self, path: Path) -> list[Transaction]:
        """Import transactions from CSV.

        Args:
            path: CSV file path

        Returns:
            List of Transaction objects
        """
        from decimal import Decimal
        from ..models.enums import RowRole, ReviewStatus
        from dateutil import parser as date_parser

        transactions = []
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                txn = Transaction(
                    sf_account_id=row["sf_account_id"],
                    sf_txn_id=row["sf_txn_id"] or None,
                    txn_key=row["txn_key"],
                    row_role=RowRole(row["row_role"]),
                    sf_date=date_parser.parse(row["sf_date"]).date() if row["sf_date"] else None,
                    sf_amount=Decimal(row["sf_amount"]) if row["sf_amount"] else None,
                    sf_payee=row["sf_payee"] or None,
                    sf_memo=row["sf_memo"] or None,
                    sf_imported_at=(
                        date_parser.parse(row["sf_imported_at"]) if row["sf_imported_at"] else None
                    ),
                    sf_last_seen_at=(
                        date_parser.parse(row["sf_last_seen_at"])
                        if row["sf_last_seen_at"]
                        else None
                    ),
                    date=date_parser.parse(row["date"]).date() if row["date"] else None,
                    accounting_month=row.get("accounting_month") or None,
                    amount=Decimal(row["amount"]) if row["amount"] else Decimal("0"),
                    payee=row["payee"],
                    memo=row["memo"] or None,
                    category=row["category"] or None,
                    tags=row["tags"] or None,
                    account_name=row.get("account_name") or None,
                    account_type=row.get("account_type") or None,
                    review_status=(
                        ReviewStatus(row["review_status"])
                        if row["review_status"]
                        else ReviewStatus.NEW
                    ),
                    review_notes=row["review_notes"] or None,
                    needs_attention=row["needs_attention"].lower() in ("true", "yes", "1"),
                )
                transactions.append(txn)

        return transactions

    def _generate_commit_message(self, sync_result: Optional[SyncResult]) -> str:
        """Generate git commit message from sync result.

        Args:
            sync_result: Sync result

        Returns:
            Commit message string
        """
        if not sync_result:
            return f"Snapshot created at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        parts = []
        if sync_result.new_count:
            parts.append(f"{sync_result.new_count} new")
        if sync_result.updated_count:
            parts.append(f"{sync_result.updated_count} updated")
        if sync_result.review_flagged_count:
            parts.append(f"{sync_result.review_flagged_count} flagged")
        if sync_result.error_count:
            parts.append(f"{sync_result.error_count} errors")

        summary = ", ".join(parts) if parts else "no changes"
        return f"Sync: {summary}"
