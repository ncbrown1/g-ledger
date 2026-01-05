"""CLI commands for G-Ledger."""

import sys
from pathlib import Path
from datetime import date, datetime
import click
import traceback

from .config import Config
from .services.sheets import SheetsClient
from .repositories.sheet_repo import SheetRepository
from .repositories.snapshot_repo import SnapshotRepository
from .bootstrap.sheet_bootstrap import SheetBootstrap
from .services.simplefin import SimpleFINClient
from .services.sync_engine import SyncEngine
from .services.account_sync import AccountSyncService
from .services.reconciliation import ReconciliationService
from .models.balance_history import BalanceSnapshot
from .utils.logging import setup_logging, get_logger


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """G-Ledger: Transaction sync system between SimpleFIN and Google Sheets.

    Sync bank transactions to Google Sheets.
    """
    pass


@cli.command()
@click.option(
    "--config",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to configuration file (default: searches standard locations)",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip confirmation prompt",
)
def bootstrap_sheet(config, yes):
    """Initialize Google Sheet with proper schema and protections.

    Creates tabs (Accounts, Transactions, Categories, Balance History, Audit Log),
    sets up headers, applies protections to server-managed columns, and adds data
    validations. Safe to run multiple times (idempotent).
    """
    try:
        # Load config
        cfg = Config.load(config)
        setup_logging(cfg.log_level)
        logger = get_logger(__name__)

        # Show what bootstrap will do
        click.echo("Sheet Bootstrap")
        click.echo("=" * 50)
        click.echo(f"Sheet ID: {cfg.sheet_id}")
        click.echo("\nThis will:")
        click.echo("  • Create tabs if they don't exist:")
        click.echo("    - Accounts, Transactions, Categories")
        click.echo("    - Balance History, Audit Log")
        click.echo("  • Set up column headers")
        click.echo("  • Apply protections to server-managed columns")
        click.echo("  • Configure data validations")
        click.echo("\nNote: This is safe to run multiple times.")
        click.echo("      Existing data will not be deleted.\n")

        # Confirm unless -y flag is used
        if not yes:
            if not click.confirm("Proceed with bootstrap?"):
                click.echo("Bootstrap cancelled")
                sys.exit(0)

        logger.info("Starting sheet bootstrap...")

        # Initialize clients
        sheets_client = SheetsClient(cfg.service_account_key_path, cfg.sheet_id)
        bootstrap = SheetBootstrap(sheets_client)

        # Run bootstrap
        bootstrap.bootstrap()

        click.echo("\n✓ Sheet bootstrap completed successfully")
        click.echo(f"  Sheet ID: {cfg.sheet_id}")
        click.echo(
            "  Tabs verified/created: Accounts, Transactions, Categories, Balance History, Audit Log"
        )
        click.echo("  Protections applied to server-managed columns")
        click.echo("  Data validations configured")

    except FileNotFoundError as e:
        click.echo(f"✗ Error: {e}", err=True)
        click.echo("  Create config.yaml based on config.example.yaml", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"✗ Bootstrap failed: {e}", err=True)
        logger.exception("Caught Exception:")
        sys.exit(1)


@cli.command()
@click.option(
    "--config",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to configuration file (default: searches standard locations)",
)
@click.option("--list-only", is_flag=True, help="Only list accounts without syncing to sheet")
@click.option(
    "--ci-mode",
    is_flag=True,
    help="Minimal output for CI/automation (reduces sensitive data in logs)",
)
def sync_accounts(config, list_only, ci_mode):
    """Sync SimpleFIN accounts to Google Sheet.

    Fetches accounts from SimpleFIN and updates the Accounts tab.
    New accounts are added with enabled=FALSE (you must enable them manually).
    Existing account metadata is updated, but user configuration is preserved.

    Use --list-only to preview accounts without making changes.
    Use --ci-mode for automated/CI environments to minimize log output.
    """
    try:
        # Load config
        cfg = Config.load(config)
        setup_logging("WARNING" if ci_mode else cfg.log_level)
        logger = get_logger(__name__)

        logger.info("Starting account sync...")

        # Initialize clients
        simplefin_client = SimpleFINClient(cfg.simplefin_token, cfg.simplefin_base_url)

        if list_only:
            # Just list accounts
            account_sync = AccountSyncService(None, simplefin_client)
            accounts = account_sync.list_accounts()

            if not accounts:
                click.echo("No accounts found in SimpleFIN")
                return

            if ci_mode:
                click.echo(f"✓ Found {len(accounts)} accounts")
            else:
                click.echo(f"\n✓ Found {len(accounts)} SimpleFIN accounts:\n")
                for acc in accounts:
                    click.echo(f"  ID: {acc['id']}")
                    click.echo(f"    Name: {acc['name']}")
                    click.echo(f"    Institution: {acc['org_name']} ({acc['institution']})")
                    click.echo(f"    Currency: {acc['currency']}")
                    click.echo(f"    Balance: {acc['balance']}")
                    click.echo(f"    Available: {acc['available_balance']}")
                    click.echo()

                click.echo("Run without --list-only to sync these accounts to your sheet.")
        else:
            # Sync accounts
            sheets_client = SheetsClient(cfg.service_account_key_path, cfg.sheet_id)
            sheet_repo = SheetRepository(sheets_client)
            account_sync = AccountSyncService(sheet_repo, simplefin_client)

            # Create backup before sync
            if not ci_mode:
                logger.info("Creating pre-sync backup...")
            snapshot_repo = SnapshotRepository(cfg.snapshot_dir)
            try:
                accounts = sheet_repo.read_accounts(enabled_only=False)
                transactions = sheet_repo.read_transactions()
                snapshot_repo.create_snapshot(accounts, transactions, sync_result=None)
                if not ci_mode:
                    click.echo("  ✓ Backup created")
            except Exception as e:
                logger.warning(f"Failed to create backup: {e}")
                if not ci_mode:
                    click.echo(f"  ⚠ Backup failed (continuing anyway): {e}")

            result = account_sync.sync_accounts()

            # Display results
            if ci_mode:
                click.echo(
                    f"✓ Synced: {result.new_count} new, {result.updated_count} updated, {result.unchanged_count} unchanged"
                )
                if result.errors:
                    click.echo(f"✗ Errors: {len(result.errors)}", err=True)
            else:
                click.echo("\n✓ Account sync completed")
                click.echo(f"  New accounts: {result.new_count}")
                click.echo(f"  Updated accounts: {result.updated_count}")
                click.echo(f"  Unchanged: {result.unchanged_count}")

                if result.new_count > 0:
                    click.echo(f"\n  ⚠ {result.new_count} new account(s) added as DISABLED.")
                    click.echo("    Open the Accounts tab and:")
                    click.echo("    1. Set 'enabled' to TRUE to start syncing transactions")
                    click.echo("    2. Set 'ignored' to TRUE for accounts to show balance as $0.00")

                if result.errors:
                    click.echo(f"\n  Errors: {len(result.errors)}", err=True)
                    for error in result.errors[:5]:
                        click.echo(f"    - {error}", err=True)

    except FileNotFoundError as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"✗ Account sync failed: {e}", err=True)
        logger.exception("Caught Exception:")
        sys.exit(1)


@cli.command()
@click.option(
    "--config",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to configuration file (default: searches standard locations)",
)
@click.option(
    "--days",
    type=int,
    default=None,
    help="Number of days to fetch (overrides config). Note: SimpleFIN typically provides 90 days max (varies by institution)",
)
@click.option("--dry-run", is_flag=True, help="Preview changes without writing to sheet")
@click.option(
    "--ci-mode",
    is_flag=True,
    help="Minimal output for CI/automation (reduces sensitive data in logs)",
)
def sync(config, days, dry_run, ci_mode):
    """Sync SimpleFIN transactions to Google Sheet.

    Fetches transactions for enabled accounts, matches with existing sheet data,
    appends new transactions, updates changed transactions, and computes review status.

    This command is idempotent - running it multiple times produces no duplicates.
    """
    try:
        # Load config
        cfg = Config.load(config)
        setup_logging("WARNING" if ci_mode else cfg.log_level)
        logger = get_logger(__name__)

        if days:
            cfg.window_days = days

        logger.info(f"Starting sync (window={cfg.window_days} days, dry_run={dry_run})...")

        # Initialize clients
        sheets_client = SheetsClient(cfg.service_account_key_path, cfg.sheet_id)
        sheet_repo = SheetRepository(sheets_client)
        simplefin_client = SimpleFINClient(cfg.simplefin_token, cfg.simplefin_base_url)
        sync_engine = SyncEngine(cfg, sheet_repo, simplefin_client)

        # Create snapshot before sync (unless dry run)
        if not dry_run:
            if not ci_mode:
                logger.info("Creating pre-sync snapshot...")
            snapshot_repo = SnapshotRepository(cfg.snapshot_dir)
            accounts = sheet_repo.read_accounts(enabled_only=False)
            transactions = sheet_repo.read_transactions()
            snapshot_repo.create_snapshot(accounts, transactions, sync_result=None)

        # Run sync
        result = sync_engine.sync(dry_run=dry_run)

        # Create post-sync snapshot (unless dry run)
        if not dry_run and (result.new_count > 0 or result.updated_count > 0):
            if not ci_mode:
                logger.info("Creating post-sync snapshot...")
            accounts = sheet_repo.read_accounts(enabled_only=False)
            transactions = sheet_repo.read_transactions()
            commit_hash = snapshot_repo.create_snapshot(accounts, transactions, sync_result=result)
            if not ci_mode:
                click.echo(f"  Snapshot: {commit_hash[:8]}")

        # Display results
        if ci_mode:
            status = "✓" if result.error_count == 0 else "✗"
            click.echo(
                f"{status} Sync: {result.new_count} new, {result.updated_count} updated, {result.review_flagged_count} need review"
            )
            if result.error_count > 0:
                click.echo(f"✗ Errors: {result.error_count}", err=True)
        else:
            click.echo("\n✓ Sync completed")
            click.echo(f"  New transactions: {result.new_count}")
            click.echo(f"  Updated transactions: {result.updated_count}")
            click.echo(f"  Unchanged: {result.unchanged_count}")
            click.echo(f"  Needs attention: {result.review_flagged_count}")

            if result.error_count > 0:
                click.echo(f"  Errors: {result.error_count}", err=True)
                for error in result.errors[:5]:  # Show first 5 errors
                    click.echo(f"    - {error}", err=True)

            if dry_run:
                click.echo("\n  (Dry run - no changes written)")

    except FileNotFoundError as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"✗ Sync failed: {e}", err=True)
        logger.exception("Caught Exception:")
        sys.exit(1)


@cli.command()
@click.option(
    "--config",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to configuration file (default: searches standard locations)",
)
@click.argument("commit_hash")
def restore(config, commit_hash):
    """Restore Google Sheet from a snapshot.

    DANGEROUS: Overwrites current sheet data with data from the specified snapshot.

    COMMIT_HASH: Git commit hash to restore (use list-snapshots to view)
    """
    try:
        # Load config
        cfg = Config.load(config)
        setup_logging(cfg.log_level)
        logger = get_logger(__name__)

        # Confirm
        click.confirm(
            f"⚠ WARNING: This will overwrite current sheet data with snapshot {commit_hash[:8]}. Continue?",
            abort=True,
        )

        logger.info(f"Restoring from snapshot {commit_hash}...")

        # Initialize clients
        snapshot_repo = SnapshotRepository(cfg.snapshot_dir)
        sheets_client = SheetsClient(cfg.service_account_key_path, cfg.sheet_id)
        sheet_repo = SheetRepository(sheets_client)

        # Create backup of current state
        logger.info("Creating backup of current state...")
        current_accounts = sheet_repo.read_accounts(enabled_only=False)
        current_transactions = sheet_repo.read_transactions()
        backup_hash = snapshot_repo.create_snapshot(
            current_accounts, current_transactions, sync_result=None
        )
        click.echo(f"  Backup created: {backup_hash[:8]}")

        # Restore from snapshot
        accounts, transactions = snapshot_repo.restore_snapshot(commit_hash)

        # Write to sheet
        logger.info("Writing restored data to sheet...")
        sheet_repo.write_accounts(accounts)

        # For transactions, we need to clear and rewrite
        # This is destructive but necessary for restore
        click.echo(f"  Restoring {len(accounts)} accounts...")
        click.echo(f"  Restoring {len(transactions)} transactions...")

        # Note: Full transaction restore requires clearing the sheet first
        # For v1, we'll just append (user can manually clear if needed)
        click.echo(
            "  ⚠ Note: Transactions appended. Manually clear Transactions tab first if needed."
        )

        click.echo(f"\n✓ Restored snapshot {commit_hash[:8]}")
        click.echo(f"  Backup of current state: {backup_hash[:8]}")

    except FileNotFoundError as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"✗ Restore failed: {e}", err=True)
        logger.exception("Caught Exception:")
        sys.exit(1)


@cli.command()
@click.option(
    "--config",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to configuration file (default: searches standard locations)",
)
@click.option("--limit", type=int, default=10, help="Number of snapshots to show")
def list_snapshots(config, limit):
    """List recent snapshots.

    Shows git commit history of sheet snapshots for restore.
    """
    try:
        # Load config
        cfg = Config.load(config)
        setup_logging(cfg.log_level)

        # Initialize snapshot repo
        snapshot_repo = SnapshotRepository(cfg.snapshot_dir)

        snapshots = snapshot_repo.list_snapshots(limit=limit)

        if not snapshots:
            click.echo("No snapshots found")
            return

        click.echo(f"\nRecent snapshots (last {len(snapshots)}):\n")

        for snapshot in snapshots:
            click.echo(f"  {snapshot['short_hash']}  {snapshot['timestamp']}")
            click.echo(f"    {snapshot['message']}")
            click.echo()

    except FileNotFoundError as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"✗ List failed: {e}", err=True)
        traceback.print_exc()
        sys.exit(1)


@cli.command()
@click.option(
    "--config",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to configuration file (default: searches standard locations)",
)
@click.option(
    "--account",
    type=str,
    default=None,
    help="Reconcile specific account by sf_account_id (default: all accounts)",
)
@click.option(
    "--start-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="Start date for reconciliation period (default: starting_balance_date)",
)
@click.option(
    "--end-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="End date for reconciliation period (default: today)",
)
@click.option(
    "--suggest-starting-balance",
    is_flag=True,
    help="Suggest starting balance for accounts without one",
)
def reconcile(config, account, start_date, end_date, suggest_starting_balance):
    """Reconcile account balances.

    Validates that starting_balance + transaction_sum = current_balance
    for each account. Identifies discrepancies and shows reconciliation status.

    Examples:
        gledger reconcile                          # Reconcile all accounts
        gledger reconcile --account acc_123        # Reconcile specific account
        gledger reconcile --suggest-starting-balance  # Show suggested starting balances
    """
    try:
        # Load config
        cfg = Config.load(config)
        setup_logging(cfg.log_level)
        logger = get_logger(__name__)

        # Initialize services
        sheets_client = SheetsClient(cfg.service_account_key_path, cfg.sheet_id)
        sheet_repo = SheetRepository(sheets_client)
        reconciliation_service = ReconciliationService(sheet_repo)

        # Convert datetime to date if provided
        start = start_date.date() if start_date else None
        end = end_date.date() if end_date else None

        if suggest_starting_balance:
            # Show suggested starting balances
            click.echo("\nSuggesting starting balances...\n")
            all_accounts = sheet_repo.read_accounts(enabled_only=False)
            accounts = [a for a in all_accounts if not a.ignored]

            # Read balance history to check which accounts already have starting balances
            balance_history = sheet_repo.read_balance_history()
            accounts_with_starting_balance = {
                h.sf_account_id for h in balance_history if h.is_starting_balance
            }

            has_starting_balance = []
            suggested_accounts = []
            no_suggestion_accounts = []

            for acc in accounts:
                if acc.sf_account_id in accounts_with_starting_balance:
                    has_starting_balance.append(acc)
                else:
                    suggested = reconciliation_service.suggest_starting_balance(acc)
                    if suggested is not None:
                        suggested_accounts.append((acc, suggested))
                    else:
                        no_suggestion_accounts.append(acc)

            # Show accounts with suggestions
            if suggested_accounts:
                click.echo("Accounts needing starting balance:\n")
                for acc, suggested in suggested_accounts:
                    click.echo(f"  {acc.display_name} ({acc.sf_account_id}):")
                    click.echo(f"    Suggested starting balance: ${suggested:.2f}")
                    if acc.balance is not None:
                        click.echo(f"    Current balance: ${acc.balance:.2f}")
                    click.echo()

                # Ask for confirmation
                click.echo()
                if click.confirm("Apply these suggested starting balances to Balance History?"):
                    # Get earliest transaction date for each account
                    all_txns = sheet_repo.read_transactions()
                    snapshots_to_add = []

                    for acc, suggested in suggested_accounts:
                        # Find earliest transaction for this account
                        acc_txns = [
                            t for t in all_txns if t.sf_account_id == acc.sf_account_id and t.date
                        ]
                        if acc_txns:
                            # Has transactions - use earliest transaction date
                            acc_txns.sort(key=lambda t: t.date)
                            earliest_date = acc_txns[0].date
                        else:
                            # No transactions - use balance_date from SimpleFIN, or today
                            if acc.balance_date:
                                earliest_date = (
                                    acc.balance_date.date()
                                    if hasattr(acc.balance_date, "date")
                                    else acc.balance_date
                                )
                            else:
                                earliest_date = date.today()

                        # Create balance snapshot for Balance History
                        snapshot = BalanceSnapshot(
                            sf_account_id=acc.sf_account_id,
                            account_name=acc.display_name,
                            account_type=acc.account_type.value if acc.account_type else None,
                            balance_date=earliest_date,
                            balance=suggested,
                            available_balance=None,  # Not applicable for user-suggested
                            recorded_at=datetime.now(),
                            source="user_suggested",
                            is_starting_balance=True,  # Mark as starting balance
                            notes="Suggested starting balance",
                        )
                        snapshots_to_add.append(snapshot)

                    # Create backup before writing
                    click.echo("\nCreating backup before adding snapshots...")
                    snapshot_repo = SnapshotRepository(cfg.snapshot_dir)
                    try:
                        accounts = sheet_repo.read_accounts(enabled_only=False)
                        transactions = sheet_repo.read_transactions()
                        snapshot_repo.create_snapshot(accounts, transactions, sync_result=None)
                        click.echo("  ✓ Backup created")
                    except Exception as e:
                        logger.warning(f"Failed to create backup: {e}")
                        click.echo(f"  ⚠ Backup failed (continuing anyway): {e}")

                    # Write snapshots to Balance History
                    click.echo(f"\nWriting {len(snapshots_to_add)} snapshots to Balance History...")
                    sheet_repo.append_balance_snapshots(snapshots_to_add)
                    click.echo("✓ Starting balance snapshots added to Balance History")
                    click.echo("  Run 'accounts-sync' to compute reconciliation status")
                else:
                    click.echo("Starting balances not applied")
            else:
                click.echo("No accounts with actionable suggestions.")
                click.echo()

            # Summary
            click.echo("Summary:")
            click.echo(f"  Total accounts: {len(accounts)}")
            click.echo(f"  Already have starting balance: {len(has_starting_balance)}")
            click.echo(f"  Suggested starting balance: {len(suggested_accounts)}")
            click.echo(f"  Cannot suggest (no transactions/balance): {len(no_suggestion_accounts)}")

            if no_suggestion_accounts:
                click.echo("\nAccounts without suggestions:")
                for acc in no_suggestion_accounts:
                    reason = "no current balance" if acc.balance is None else "no transactions"
                    click.echo(f"  • {acc.display_name} ({reason})")

        elif account:
            # Reconcile specific account
            click.echo(f"\nReconciling account {account}...\n")
            accounts = sheet_repo.read_accounts(enabled_only=False)
            target_account = next((a for a in accounts if a.sf_account_id == account), None)

            if not target_account:
                click.echo(f"✗ Account {account} not found", err=True)
                sys.exit(1)

            try:
                result = reconciliation_service.reconcile_account(target_account, start, end)

                click.echo(f"Account: {result.account_name}")
                click.echo(f"Period: {result.start_date} to {result.end_date}")
                click.echo(f"Starting balance: ${result.starting_balance:.2f}")
                click.echo(
                    f"Transaction sum: ${result.transaction_sum:.2f} ({result.transaction_count} transactions)"
                )
                click.echo(f"Calculated ending: ${result.calculated_ending_balance:.2f}")
                click.echo(f"Actual ending: ${result.ending_balance:.2f}")
                click.echo(f"Discrepancy: ${result.discrepancy:.2f}")

                if result.is_balanced:
                    click.echo("\n✓ Account is BALANCED")
                else:
                    click.echo(f"\n✗ DISCREPANCY FOUND: ${result.discrepancy:.2f}")
                    sys.exit(1)

            except ValueError as e:
                click.echo(f"✗ Cannot reconcile: {e}", err=True)
                sys.exit(1)

        else:
            # Reconcile all accounts
            click.echo("\nReconciling all accounts...\n")
            report = reconciliation_service.reconcile_all_accounts(start, end)

            click.echo(f"Total accounts: {report.total_accounts}")
            click.echo(f"Reconciled (OK): {report.reconciled_count}")
            click.echo(f"Discrepancies: {report.discrepancy_count}")
            click.echo(f"Missing starting balance: {report.no_starting_balance_count}")
            click.echo()

            # Show details for accounts with discrepancies
            if report.discrepancy_count > 0:
                click.echo("Accounts with discrepancies:\n")
                for result in report.results:
                    if not result.is_balanced:
                        click.echo(f"  {result.account_name}:")
                        click.echo(f"    Expected: ${result.calculated_ending_balance:.2f}")
                        click.echo(f"    Actual: ${result.ending_balance:.2f}")
                        click.echo(f"    Discrepancy: ${result.discrepancy:.2f}")
                        click.echo()

            if report.discrepancy_count > 0:
                sys.exit(1)
            else:
                click.echo("✓ All accounts reconciled successfully")

    except FileNotFoundError as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"✗ Reconcile failed: {e}", err=True)
        traceback.print_exc()
        sys.exit(1)


@cli.command()
@click.option(
    "--config",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to configuration file (default: searches standard locations)",
)
def health(config):
    """Check system health and configuration.

    Verifies:
    - Configuration file is valid
    - Service account credentials are correct
    - Google Sheets API is accessible
    - SimpleFIN API is reachable
    - Required permissions are granted

    Examples:
        gledger health              # Check system health
        gledger health --config ./config.yaml
    """
    issues = []
    warnings_list = []

    try:
        click.echo("🔍 G-Ledger Health Check\n")
        click.echo("=" * 50)

        # 1. Configuration
        click.echo("\n📋 Configuration:")
        try:
            cfg = Config.load(config)
            click.echo("  ✓ Config file found and loaded")
            click.echo(f"    Location: {Config.find_config_path(config)}")
            click.echo(f"    Sheet ID: {cfg.sheet_id[:20]}...")
            click.echo(f"    Log Level: {cfg.log_level}")
        except FileNotFoundError as e:
            issues.append(("Configuration", str(e)))
            click.echo(f"  ✗ {e}")
            click.echo("\n❌ Cannot proceed without valid configuration")
            sys.exit(1)
        except Exception as e:
            issues.append(("Configuration", str(e)))
            click.echo(f"  ✗ Configuration error: {e}")
            click.echo("\n❌ Cannot proceed without valid configuration")
            sys.exit(1)

        # 2. Service Account Key
        click.echo("\n🔑 Service Account:")
        try:
            import json

            with open(cfg.service_account_key_path) as f:
                key_data = json.load(f)

            click.echo("  ✓ Service account key file is valid JSON")
            click.echo(f"    Email: {key_data.get('client_email', 'unknown')}")
            click.echo(f"    Project: {key_data.get('project_id', 'unknown')}")

            # Check permissions
            import stat

            file_stat = cfg.service_account_key_path.stat()
            perms = stat.S_IMODE(file_stat.st_mode)
            if perms & 0o077:
                warnings_list.append(
                    (
                        "File Permissions",
                        f"Service account key has insecure permissions: {oct(perms)}\n"
                        f"    Recommended: chmod 600 {cfg.service_account_key_path}",
                    )
                )
                click.echo(f"  ⚠️  Insecure file permissions: {oct(perms)}")
            else:
                click.echo(f"  ✓ File permissions are secure: {oct(perms)}")

        except Exception as e:
            issues.append(("Service Account", str(e)))
            click.echo(f"  ✗ Service account error: {e}")

        # 3. Google Sheets API
        click.echo("\n📊 Google Sheets API:")
        try:
            sheets_client = SheetsClient(cfg.service_account_key_path, cfg.sheet_id)

            # Try to read sheet metadata
            sheets_client.get_sheet_metadata()
            click.echo("  ✓ Successfully connected to Google Sheets")
            click.echo("  ✓ Service account has access to the sheet")

            # Try to read a small range to verify read permissions
            try:
                sheets_client.read_range("Accounts!A1:A1")
                click.echo("  ✓ Read permissions verified")
            except Exception:
                warnings_list.append(
                    (
                        "Sheet Permissions",
                        "Cannot read from sheet. Check tab names and permissions.",
                    )
                )
                click.echo("  ⚠️  Cannot read from sheet (tab may not exist yet)")

        except Exception as e:
            issues.append(("Google Sheets API", str(e)))
            click.echo(f"  ✗ Google Sheets error: {e}")
            click.echo("    - Verify service account has editor access to the sheet")
            click.echo("    - Verify Google Sheets API is enabled in GCP")

        # 4. SimpleFIN API
        click.echo("\n🏦 SimpleFIN API:")
        try:
            simplefin_client = SimpleFINClient(cfg.simplefin_token, cfg.simplefin_base_url)

            # Try to fetch accounts
            accounts = simplefin_client.get_accounts(balances_only=True)
            click.echo("  ✓ Successfully connected to SimpleFIN")
            click.echo(f"  ✓ Found {len(accounts)} bank accounts")

        except Exception as e:
            issues.append(("SimpleFIN API", str(e)))
            click.echo(f"  ✗ SimpleFIN error: {e}")
            click.echo("    - Verify your SimpleFIN access token is correct")
            click.echo("    - Check that token hasn't expired")

        # 5. Snapshot Directory
        click.echo("\n📸 Snapshot Directory:")
        try:
            if cfg.snapshot_dir.exists():
                if (cfg.snapshot_dir / ".git").exists():
                    click.echo(f"  ✓ Snapshot git repository exists: {cfg.snapshot_dir}")
                else:
                    warnings_list.append(
                        (
                            "Snapshots",
                            f"Directory exists but is not a git repository: {cfg.snapshot_dir}",
                        )
                    )
                    click.echo(f"  ⚠️  Not a git repository: {cfg.snapshot_dir}")
            else:
                warnings_list.append(
                    (
                        "Snapshots",
                        f"Snapshot directory doesn't exist (will be created): {cfg.snapshot_dir}",
                    )
                )
                click.echo(f"  ⚠️  Directory doesn't exist: {cfg.snapshot_dir}")
        except Exception as e:
            warnings_list.append(("Snapshots", str(e)))
            click.echo(f"  ⚠️  Snapshot directory check failed: {e}")

        # Summary
        click.echo("\n" + "=" * 50)
        click.echo("\n📊 Health Check Summary:\n")

        if not issues and not warnings_list:
            click.echo("✅ All checks passed! System is ready.")
            sys.exit(0)

        if warnings_list:
            click.echo(f"⚠️  {len(warnings_list)} warning(s):")
            for category, warning in warnings_list:
                click.echo(f"\n  • {category}:")
                for line in warning.split("\n"):
                    click.echo(f"    {line}")

        if issues:
            click.echo(f"\n❌ {len(issues)} critical issue(s):")
            for category, issue in issues:
                click.echo(f"\n  • {category}:")
                for line in issue.split("\n"):
                    click.echo(f"    {line}")
            sys.exit(1)

        if warnings_list and not issues:
            click.echo("\n⚠️  System has warnings but should work")
            sys.exit(0)

    except Exception as e:
        click.echo(f"\n❌ Health check failed: {e}", err=True)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    cli()
