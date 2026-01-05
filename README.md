# G-Ledger

Transaction sync system that syncs SimpleFIN bank transactions into a Google Sheet (Source of Truth), computes review status, supports transaction splits and manual entries, and enables continuous reconciliation of actual vs expected balances.

## Why This Project?

After years of using YNAB (You Need A Budget), I developed solid financial habits and forward-based budgeting skills. But over time, my needs evolved—I no longer needed the elaborate planning and budgeting features. What I really wanted was simple: **categorize transactions and understand spending trends over time**.

That should be easy with spreadsheets, right? Except for one critical challenge: **getting the transaction data in there automatically**.

### The Problem with Existing Solutions

- **YNAB/Mint/etc.**: Great tools, but I'm paying for budgeting features I don't use anymore. Plus, Mint's shutdown reminded me that relying on third-party services means your data can disappear.
- **Plain Spreadsheets**: Full control and simplicity, but manually copying transactions from multiple banks is tedious and error-prone.
- **Self-hosted Solutions**: Many exist, but they're often heavyweight, require complex setup, or lack automatic transaction importing.

### What I Wanted

1. **Own my data** - No vendor lock-in, no service shutdowns
2. **Automatic transaction imports** - Minimal manual overhead
3. **Spreadsheet simplicity** - Easy to view, filter, and analyze on any device (mobile-friendly!)
4. **Lightweight** - Just sync transactions and categorize them, nothing more
5. **Version control** - Track changes over time with git

### The Solution: G-Ledger

G-Ledger bridges the gap: it's a **lightweight CLI tool** that automatically syncs bank transactions (via SimpleFIN) into a Google Sheet where you can categorize and review them. The sheet is your source of truth, accessible anywhere. Transaction data is versioned with git snapshots, and you can export to hledger for deeper analysis when needed.

It's the simplicity of spreadsheets with the power of automated imports, designed for people who've outgrown budgeting software but still want to track their spending without manual data entry.

## Features

- **SimpleFIN Integration**: Automatically fetch posted transactions from enabled bank accounts
  - ⚠️ Note: SimpleFIN typically provides 90 days of history (varies by institution: 30-90 days)
- **Google Sheets as SOT**: Google Sheet is the canonical source of truth for all transaction data
- **Transaction Splits**: Split a single bank transaction across multiple expense categories
- **Manual Transactions**: Add manual transactions that aren't from SimpleFIN
- **Review Status System**: Automatic flagging of new, changed, or problematic transactions
- **Per-Account Reconciliation**: Track reconciliation status per account with cutoff dates
- **Git Snapshots**: Automatic versioning with git commits before/after each sync
- **Idempotent Sync**: Running sync multiple times produces no duplicates
- **Batched Sync**: Large date ranges (>60 days) automatically batched to reduce memory pressure

## Architecture

```
SimpleFIN API → Sync Engine → Google Sheets (SOT)
                     ↓
                Git Snapshots
```

### Sheet Structure

**Accounts Tab**: Define your bank accounts
- `sf_account_id`: SimpleFIN account ID (protected)
- `enabled`: Whether to sync this account
- `ignored`: If true, balance shown as $0.00 (hide from reports)
- `institution`, `display_name`: Display info
- `account_type`: checking, savings, credit, investment, loan
- `currency`: Currency code (default USD)
- `balance`, `available_balance`, `balance_date`: Current balance info (synced from SimpleFIN)
- `reconcile_date`: Date through which user has confirmed accuracy
- `starting_balance`, `starting_balance_date`: Computed from Balance History (server-managed)
- `expected_balance`, `balance_discrepancy`, `reconciliation_status_text`: Reconciliation status (server-managed)

**Transactions Tab**: All transactions (bank-imported and manual)
- User-editable: `date`, `amount`, `payee`, `memo`, `category`, `tags`
- Display (reference): `account_name`, `account_type`
- Identity (reference): `row_role`, `txn_key`, `sf_account_id`, `sf_txn_id`
- Review (protected): `review_status`, `review_notes`, `needs_attention`
- Bank snapshot (protected): `sf_date`, `sf_amount`, `sf_payee`, `sf_memo`, `sf_imported_at`, `sf_last_seen_at`

**Column Protection Tiers**:
- **Tier 1 (Dark gray, protected)**: Never editable - formula-derived or server-computed
- **Tier 2 (Light blue-gray, unprotected)**: Reference fields - server-managed for BANK rows, but user must populate for SPLIT/MANUAL rows

**Categories Tab**: Transaction categories for dropdown validation
- `category`: Full hierarchical ledger-style path
- `active`: Show in dropdown?
- `notes`: Optional description

**Balance History Tab**: Historical account balance snapshots for reconciliation
- `sf_account_id`: Account identifier
- `account_name`, `account_type`: Display info (reference)
- `balance_date`: Date of balance snapshot
- `balance`, `available_balance`: Balance amounts
- `recorded_at`: Timestamp when snapshot was captured
- `source`: Where balance came from (simplefin, user_suggested, manual)
- `is_starting_balance`: TRUE if designated as starting balance for reconciliation
- `notes`: Optional notes

### Transaction Types

1. **BANK rows**: Imported from SimpleFIN, one per transaction
2. **SPLIT rows**: User-added rows to split a BANK transaction across categories
3. **MANUAL rows**: User-added transactions not from SimpleFIN

### Splits

To split a transaction:
1. Keep the original BANK row (set its `amount` to 0)
2. Add one or more SPLIT rows with the same `txn_key`
3. For each SPLIT row:
   - **Copy from BANK row**: `date`, `payee`, `txn_key`, `sf_account_id`, `account_name`, `account_type`
   - **Set independently**: `row_role` (SPLIT), `category`, `amount` (your split amount)
   - **Leave empty**: `sf_txn_id` and all `sf_*` snapshot fields
4. Sum of SPLIT `amount` values must equal the BANK `sf_amount` (±$0.01)

**Note**: The light blue-gray columns indicate fields you should copy from the BANK row when creating splits.

### Review Status

The system automatically computes `review_status` for each transaction:
- **NEW**: Just imported, needs categorization
- **SPLIT_MISMATCH**: Split amounts don't sum to bank amount
- **BANK_CHANGED**: Bank snapshot data changed since last sync
- **MISSING_CATEGORY**: Transaction missing category or using "Uncategorized"
- **UNMATCHABLE**: Transaction not found in SimpleFIN import window
- **INVALID**: Missing required fields
- **OK**: All checks passed

Transactions with `needs_attention=TRUE` require user review.

## Installation

### Prerequisites

- Python 3.10 or higher
- Google Cloud Platform account
- SimpleFIN account and access token
- Git (for snapshots)

### 1. Set Up Google Cloud Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use existing)
3. Enable Google Sheets API:
   - Navigate to "APIs & Services" > "Library"
   - Search for "Google Sheets API"
   - Click "Enable"
4. Create a service account:
   - Navigate to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "Service Account"
   - Give it a name (e.g., "gledger-sync")
   - Grant role: "Editor" (or just Sheets access)
   - Click "Done"
5. Create and download key:
   - Click on the created service account
   - Go to "Keys" tab
   - Click "Add Key" > "Create new key"
   - Choose "JSON" format
   - Save as `service-account-key.json` in your project directory

### 2. Create Google Sheet

1. Create a new Google Sheet
2. Note the Sheet ID from the URL:
   ```
   https://docs.google.com/spreadsheets/d/SHEET_ID_HERE/edit
   ```
3. Share the sheet with your service account email:
   - Click "Share" button
   - Add the service account email (e.g., `gledger-sync@project-id.iam.gserviceaccount.com`)
   - Give it "Editor" access

### 3. Get SimpleFIN Access Token

1. Sign up for SimpleFIN: https://beta-bridge.simplefin.org/
2. Connect your bank accounts
3. Generate an access token (claim URL)
4. Note the token format: `https://username:password@bridge.simplefin.org/simplefin`

### 4. Install G-Ledger

**Development Installation** (editable mode):
```bash
# Clone or download this repository
cd g-ledger

# Install in development mode (creates .venv automatically)
make dev-install

# Or manually with pip
pip install -e ".[dev]"
```

**Note**: The Makefile automatically creates and uses a `.venv` virtual environment. You don't need to create or activate it manually. To use your own Python environment instead, run: `SKIP_VENV=1 make dev-install`

**Production Installation** (system-wide):
```bash
# Quick install using deploy script
./deploy.sh install

# Or using Make
make install-prod

# Or manual install
pip install .
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed production deployment, cron setup, systemd configuration, and more.

### 5. Configure

```bash
# Copy example config
cp config.example.yaml config.yaml

# Edit config.yaml and fill in:
# - sheet_id (from Google Sheet URL)
# - service_account_key_path (path to JSON key file)
# - simplefin_token (your SimpleFIN access token)
```

### 6. Bootstrap Sheet

```bash
# Initialize sheet structure (tabs, headers, protections, validations)
gledger bootstrap-sheet
```

This creates the four tabs (Accounts, Transactions, Categories, Balance History) with proper schema, protections, and seeds default categories.

### 7. Sync Accounts

Automatically fetch and sync your SimpleFIN accounts:

```bash
# Preview accounts first
gledger sync-accounts --list-only

# Sync them to your sheet
gledger sync-accounts
```

This creates rows in the **Accounts** tab for each SimpleFIN account (disabled by default). Then:

1. Open your Google Sheet
2. Go to the **Accounts** tab
3. For each account:
   - Set `enabled` to TRUE to start syncing transactions
   - Optionally customize `display_name` and other fields

**Note**: The `accounts-sync` command preserves your manual edits to `enabled`, `display_name`, and reconciliation settings. It only updates metadata like institution, currency, and balance information.

## Usage

### Sync Accounts

```bash
# List SimpleFIN accounts
gledger accounts-sync --list-only

# Sync accounts to sheet
gledger accounts-sync
```

Features:
- Fetches all connected accounts from SimpleFIN
- Adds new accounts as disabled (you must enable them)
- Updates balance information and metadata (institution, currency) for existing accounts
- Creates balance snapshots in Balance History tab (when balances change)
- Computes reconciliation status for enabled accounts
- Preserves your manual edits (enabled, display_name, reconcile_date, notes)
- Allows manual accounts to coexist

### Sync Transactions

```bash
# Sync last 30 days (default)
gledger sync

# Sync custom window
gledger sync --days 60

# Dry run (preview changes)
gledger sync --dry-run
```

**⚠️ SimpleFIN Lookback Limitations**:
- SimpleFIN typically provides **90 days** of transaction history
- Some institutions only provide **30-60 days**
- Lookback period varies by financial institution and their data provider (MX)
- For historical data beyond this window, you'll need to manually import or reconcile from statements
- Recommended: Run initial sync within 90 days of connecting accounts

The sync command:
1. Creates a pre-sync snapshot
2. Fetches transactions from SimpleFIN for enabled accounts
3. Matches with existing sheet data (by `txn_key`)
4. Appends new transactions as BANK rows
5. Updates existing transactions (if unreconciled and changed)
6. Computes review status for all transactions
7. Creates a post-sync snapshot (if changes occurred)

**Idempotency**: Running sync multiple times is safe and produces no duplicates.

**Large Sync Windows**: For windows >60 days, G-Ledger automatically batches requests into 30-day chunks to reduce memory pressure.

### Reconcile Accounts

```bash
# Suggest starting balances for accounts without balance history
gledger reconcile --suggest-starting-balance

# Check reconciliation status for all enabled accounts
gledger reconcile

# Check specific account
gledger reconcile --account <sf_account_id>
```

The `--suggest-starting-balance` command:
1. Analyzes accounts that don't have user-designated starting balances
2. For accounts with transactions: calculates starting balance by working backwards from current balance
3. For accounts without transactions: suggests current balance as starting balance
4. Writes approved suggestions to Balance History tab with `is_starting_balance=TRUE`
5. Works independently of SimpleFIN snapshots - only checks for user-designated starting balances

**Workflow:**
1. Run `accounts-sync` to get current balances
2. Run `reconcile --suggest-starting-balance` to suggest starting balances
3. Review and approve suggestions - they'll be written to Balance History
4. Run `accounts-sync` again to compute reconciliation status
5. Set `reconcile_date` in Accounts tab to mark transactions as reconciled

### Manage Snapshots

```bash
# List recent snapshots
gledger list-snapshots

# List more snapshots
gledger list-snapshots --limit 20

# Restore from snapshot (DANGEROUS!)
gledger restore <commit_hash>
```

Snapshots are git commits in `./snapshots/` directory. Each snapshot includes:
- `accounts.csv`: All accounts
- `transactions.csv`: All transactions
- `metadata.json`: Counts and sync result

### Running on Cron

For automatic daily sync:

```bash
# Edit crontab
crontab -e

# Add line (runs daily at 6 AM):
0 6 * * * cd /path/to/g-ledger && /path/to/venv/bin/gledger sync >> /var/log/gledger.log 2>&1
```

## Workflow

### Typical User Workflow

1. **Initial Setup** (once):
   ```bash
   gledger bootstrap-sheet           # Create sheet structure
   gledger accounts-sync             # Sync accounts from SimpleFIN
   # Open Google Sheet and enable accounts
   gledger reconcile --suggest-starting-balance  # Set starting balances
   gledger accounts-sync             # Compute reconciliation status
   ```

2. **Daily Sync** (automated or manual):
   ```bash
   gledger sync                      # Sync transactions
   gledger accounts-sync             # Update balances and reconciliation
   ```

3. **Review Transactions** (mobile-friendly):
   - Open Google Sheet on phone/computer
   - Filter Transactions tab by `needs_attention = TRUE`
   - For each flagged transaction:
     - **NEW**: Set `category` (dropdown from Categories tab)
     - **MISSING_CATEGORY**: Set `category`
     - **SPLIT_MISMATCH**: Add/fix SPLIT rows with same `txn_key`, ensure amounts sum correctly
     - **BANK_CHANGED**: Review changes, update canonical fields if needed

4. **Monthly Reconciliation**:
   - Run `accounts-sync` to get current balances and reconciliation status
   - Review `balance_discrepancy` in Accounts tab
   - Investigate any discrepancies by checking transactions
   - When satisfied transactions are correct up to a date, update `reconcile_date` in Accounts tab
   - Run `accounts-sync` again to recompute with new reconcile_date

### Splitting a Transaction

Example: Grocery store transaction for $150 includes both food and household items.

1. Find the BANK row in Transactions tab (e.g., txn_key = "ACC123:TXN789")
2. Note the `sf_amount` (e.g., -150.00)
3. Set BANK row `amount` to 0
4. Add two SPLIT rows by copying the light blue-gray fields from the BANK row:
   ```
   Row 1 (SPLIT):
   - date: [copy from BANK]
   - payee: [copy from BANK]
   - category: Expenses:Groceries
   - amount: -100.00
   - account_name: [copy from BANK]
   - account_type: [copy from BANK]
   - row_role: SPLIT
   - txn_key: ACC123:TXN789 [copy from BANK]
   - sf_account_id: [copy from BANK]

   Row 2 (SPLIT):
   - date: [copy from BANK]
   - payee: [copy from BANK]
   - category: Expenses:Home
   - amount: -50.00
   - account_name: [copy from BANK]
   - account_type: [copy from BANK]
   - row_role: SPLIT
   - txn_key: ACC123:TXN789 [copy from BANK]
   - sf_account_id: [copy from BANK]
   ```
5. Next sync will validate that split sum (-150) equals `sf_amount` (-150)

### Adding a Manual Transaction

Example: Cash purchase not tracked by bank.

1. Go to Transactions tab
2. Add a MANUAL row:
   ```
   - date: 2024-01-15
   - amount: -25.00
   - payee: Corner Deli
   - category: Expenses:Dining
   - account_name: Manual Entry
   - account_type: (optional)
   - row_role: MANUAL
   - txn_key: MANUAL:2024-01-15-cash-lunch (generate unique ID)
   - sf_account_id: (leave empty)
   - sf_txn_id: (leave empty)
   ```

## Data Protection

### Two-Tier Column Protection

G-Ledger uses a two-tier protection system to balance data integrity with split/manual transaction flexibility:

**Tier 1 (Dark gray, protected)**: Never editable by users
- **Accounts**: `sf_account_id`, `institution`, `sf_org_name`, `balance`, `available_balance`, `balance_date`, `last_synced_at`
- **Transactions**:
  - `accounting_month` (formula-derived from date)
  - `review_status`, `review_notes`, `needs_attention` (server-computed)
  - `sf_date`, `sf_amount`, `sf_payee`, `sf_memo`, `sf_imported_at`, `sf_last_seen_at` (SimpleFIN snapshot)

**Tier 2 (Light blue-gray, unprotected)**: Reference fields
- Server-managed for BANK rows, but users must populate for SPLIT/MANUAL rows
- **Transactions**: `account_name`, `account_type`, `row_role`, `txn_key`, `sf_account_id`, `sf_txn_id`
- **Visual cue**: Light blue-gray background indicates "copy from BANK row when creating splits"

**User-Editable (White, unprotected)**: Full editing freedom
- **Accounts**: `enabled`, `ignored`, `display_name`, `account_type`, `currency`, `reconcile_date`, `notes`
- **Transactions**: `date`, `amount`, `payee`, `memo`, `category`, `tags`

## Reconciliation

G-Ledger provides automatic reconciliation by comparing expected vs. actual account balances:

### How It Works

1. **Balance History**: The Balance History tab tracks account balances over time from SimpleFIN syncs and user-suggested starting balances

2. **Starting Balance**: Each account's reconciliation uses a starting balance from Balance History:
   - If `reconcile_date` is set: uses most recent balance where `balance_date < reconcile_date`
   - If `reconcile_date` is empty: uses oldest entry marked with `is_starting_balance=TRUE`
   - Prefers user-designated starting balances over SimpleFIN snapshots

3. **Expected Balance Calculation**:
   - Expected balance = starting_balance + Σ(transactions since starting_balance_date)
   - Compares expected vs. actual balance
   - Shows discrepancy if they don't match (within ±$0.01 tolerance)

4. **Reconciliation Status**: For each account, displays:
   - `starting_balance`, `starting_balance_date`: From Balance History
   - `expected_balance`: Calculated from transactions
   - `balance_discrepancy`: Actual - expected
   - `reconciliation_status_text`: OK, DISCREPANCY, NO_BALANCE_HISTORY, etc.

### Workflow

1. **Initial Setup**:
   ```bash
   gledger accounts-sync                      # Get current balances
   gledger reconcile --suggest-starting-balance  # Suggest starting balances
   # Review and approve suggestions
   gledger accounts-sync                      # Compute reconciliation status
   ```

2. **Ongoing Reconciliation**:
   - Review transactions in Google Sheet
   - Verify account balances match bank statements
   - Update `reconcile_date` in Accounts tab when verified
   - Run `accounts-sync` to recompute reconciliation with new cutoff

3. **Protected Transactions**: Transactions with `date <= reconcile_date` are protected from bank snapshot updates during sync

## Troubleshooting

### "Account not found" errors

- Ensure account is added to Accounts tab with correct `sf_account_id`
- Set `enabled = TRUE`
- Check that SimpleFIN token is valid and account is connected

### "Sheet headers don't match" error

- Don't manually edit header rows
- If headers are corrupted, delete the tab and run `bootstrap-sheet` again
- Or manually fix headers to match expected schema (see code)

### Splits not balancing

- Check that sum of SPLIT row `amount` values equals BANK `sf_amount` exactly (±$0.01)
- Review `review_status = SPLIT_MISMATCH` transactions
- Common issue: forgetting to negate amounts correctly

### Protected column errors

- Service account must have Editor access to the sheet
- Bootstrap should set protections automatically
- If still issues, check Google Sheets permissions

### SimpleFIN token issues

- Token format: `https://username:password@bridge.simplefin.org/simplefin`
- Or just `username:password`
- Check that token hasn't expired
- Regenerate from SimpleFIN dashboard if needed

## Development

### Project Structure

```
g-ledger/
├── src/gledger/
│   ├── models/          # Pydantic data models
│   ├── services/        # Business logic (sync, export, SimpleFIN, sheets)
│   ├── repositories/    # Data access (sheet_repo, snapshot_repo)
│   ├── bootstrap/       # Sheet initialization
│   ├── utils/           # Utilities (logging, validation)
│   ├── config.py        # Configuration management
│   └── cli.py           # CLI commands
├── tests/               # Test suite
├── snapshots/           # Git snapshots (created at runtime)
├── config.yaml          # Your configuration (not in git)
├── pyproject.toml       # Project metadata and dependencies
└── README.md            # This file
```

### Running Tests

```bash
# Install with dev dependencies (auto-creates .venv)
make dev-install

# Run tests (uses .venv automatically)
make test

# Run with coverage
make test-coverage

# Or use pytest directly if you prefer
pytest
```

### Code Quality

```bash
# Format code
make format

# Check formatting (no changes)
make format-check

# Lint code (with auto-fix)
make lint

# Check linting (no fixes)
make lint-check

# Run all pre-commit checks
make check
```

**Note**: All `make` commands automatically use the `.venv` virtual environment if it exists. The venv is created automatically on first use. To bypass and use your own environment, set `SKIP_VENV=1`.

## Assumptions and Design Decisions

### v1 Constraints

- **Posted transactions only**: Ignores pending transactions to avoid pending→posted replacement complexity
- **No automatic reconciliation by date**: User must manually mark transactions as reconciled
- **Single-threaded sync**: No concurrent sheet access during sync
- **CSV snapshots**: Simple versioning with git, not a database
- **Strict category validation**: Categories must be in Categories tab (user preference)
- **BANK row amount = 0 for splits**: When splits exist, BANK row amount is 0 (user preference)

### Future Enhancements (v2+)

- Support pending transactions with state machine
- Automatic reconciliation by account reconcile_date
- Web UI for review workflow
- Enhanced reporting (balance assertions, category summaries)
- Support multiple currencies with exchange rates
- Import from other sources (CSV, OFX)
- Automated category suggestions (ML-based)

## License

MIT License (or specify your license)

## Contributing

Contributions welcome! Please open issues for bugs or feature requests.

## Support

For questions or issues:
- Open a GitHub issue
- Check SimpleFIN documentation: https://beta-bridge.simplefin.org/
