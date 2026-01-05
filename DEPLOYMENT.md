# G-Ledger Production Deployment Guide

This guide covers building and deploying G-Ledger for production use on your server.

## Quick Start

```bash
# Build and install for production
make install-prod

# Verify installation
gledger --help
```

## Deployment Options

### Option 1: Install Globally (Recommended for Single User)

```bash
# Install to system Python or active virtual environment
make install-prod

# The gledger command is now available globally
gledger --version
```

### Option 2: Install in Virtual Environment (Recommended for Server)

```bash
# Create dedicated virtual environment
python3 -m venv /opt/gledger-venv

# Activate it
source /opt/gledger-venv/bin/activate

# Install G-Ledger
make install-prod

# The gledger command is available when venv is activated
gledger --version
```

### Option 3: System-Wide Installation (Requires sudo)

```bash
# Install for all users
sudo pip install .

# Or build wheel first
make build
sudo pip install dist/*.whl
```

## Production Configuration

G-Ledger uses a smart configuration path hierarchy that automatically finds your config file.

### Configuration Path Hierarchy

G-Ledger searches for configuration in this order:

1. **Explicit `--config` path** (if provided)
2. **`GLEDGER_CONFIG` environment variable**
3. **`~/.config/gledger/config.yaml`** (XDG standard location, recommended)
4. **`./config.yaml`** (current directory fallback)

### 1. Set Up Configuration Directory (Recommended)

```bash
# Create config directory
mkdir -p ~/.config/gledger

# Copy example config
cp config.production.example.yaml ~/.config/gledger/config.yaml

# Copy service account key
cp service-account-key.json ~/.config/gledger/

# Edit config with your values
nano ~/.config/gledger/config.yaml
```

Edit `~/.config/gledger/config.yaml`:

```yaml
sheet_id: "your-sheet-id-here"
service_account_key_path: "service-account-key.json"  # Relative to config file
simplefin_token: "your-simplefin-token"
window_days: 30
log_level: "INFO"
```

**Important Notes**:
- **Relative paths** in the config file are resolved relative to the config file's directory
  - With config at `~/.config/gledger/config.yaml`
  - `service_account_key_path: "service-account-key.json"` resolves to `~/.config/gledger/service-account-key.json`
  - You can also use absolute paths: `~/path/to/key.json` or `/absolute/path/to/key.json`
- `snapshot_dir` defaults to `~/gledger-snapshots` if not specified

### 2. Set Up Snapshots Directory

```bash
# Create snapshots directory (default location)
mkdir -p ~/gledger-snapshots

# Initialize git repo
cd ~/gledger-snapshots
git init
git config user.name "G-Ledger Sync"
git config user.email "sync@gledger.local"
```

### 3. Test Configuration

```bash
# Test without specifying config path (uses automatic discovery)
gledger --help

# Verify it finds your config
gledger list-snapshots
```

## Automated Sync with Cron

### Daily Sync at 6 AM

```bash
# Edit crontab
crontab -e

# Add this line (config auto-discovered from ~/.config/gledger/):
0 6 * * * /opt/gledger-venv/bin/gledger sync >> /var/log/gledger/sync.log 2>&1

# Or with explicit config path:
0 6 * * * /opt/gledger-venv/bin/gledger --config ~/.config/gledger/config.yaml sync >> /var/log/gledger/sync.log 2>&1

# Or using environment variable:
0 6 * * * GLEDGER_CONFIG=~/.config/gledger/config.yaml /opt/gledger-venv/bin/gledger sync >> /var/log/gledger/sync.log 2>&1
```

### Using systemd Timer (Alternative to Cron)

Create `/etc/systemd/system/gledger-sync.service`:

```ini
[Unit]
Description=G-Ledger Transaction Sync
After=network.target

[Service]
Type=oneshot
User=youruser
ExecStart=/opt/gledger-venv/bin/gledger sync
StandardOutput=append:/var/log/gledger/sync.log
StandardError=append:/var/log/gledger/sync.log

# Optional: Set environment variables
# Environment="GLEDGER_CONFIG=/home/youruser/.config/gledger/config.yaml"
```

Create `/etc/systemd/system/gledger-sync.timer`:

```ini
[Unit]
Description=G-Ledger Daily Sync Timer
Requires=gledger-sync.service

[Timer]
OnCalendar=daily
OnCalendar=06:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable gledger-sync.timer
sudo systemctl start gledger-sync.timer

# Check status
sudo systemctl status gledger-sync.timer
```

## Log Management

### Create Log Directory

```bash
# Create log directory
sudo mkdir -p /var/log/gledger
sudo chown $USER:$USER /var/log/gledger
```

### Log Rotation

Create `/etc/logrotate.d/gledger`:

```
/var/log/gledger/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0644 youruser youruser
}
```

## Upgrading

### Upgrade to New Version

```bash
# Pull latest code
cd /home/ncbrown/workspace/g-ledger
git pull

# Rebuild and reinstall
make install-prod

# Verify new version
gledger --version
```

### Rollback

```bash
# Uninstall current version
make uninstall

# Install specific version
pip install dist/gledger-0.1.0-py3-none-any.whl
```

## Environment Variables

G-Ledger supports environment variables for all configuration values. Environment variables override config file values.

### Configuration Path Variable

```bash
# Point to custom config location
export GLEDGER_CONFIG=~/.config/gledger/config.yaml
```

### Configuration Value Overrides

```bash
# Override specific config values
export GLEDGER_SHEET_ID="your-sheet-id"
export GLEDGER_SERVICE_ACCOUNT_KEY="/path/to/key.json"
export GLEDGER_SIMPLEFIN_TOKEN="your-token"
export GLEDGER_SNAPSHOT_DIR="/path/to/snapshots"
export GLEDGER_LOG_LEVEL="DEBUG"
```

### Making Variables Persistent

**User-level** (add to `~/.bashrc` or `~/.profile`):

```bash
echo 'export GLEDGER_CONFIG=~/.config/gledger/config.yaml' >> ~/.bashrc
source ~/.bashrc
```

**System-level** (add to `/etc/environment`):

```bash
# Requires sudo
sudo nano /etc/environment
# Add: GLEDGER_CONFIG=/home/youruser/.config/gledger/config.yaml
```

**systemd service** (in service file):

```ini
[Service]
Environment="GLEDGER_CONFIG=/home/youruser/.config/gledger/config.yaml"
Environment="GLEDGER_LOG_LEVEL=INFO"
```

## Important Limitations

### SimpleFIN Transaction History Lookback

**⚠️ Critical Information**:

SimpleFIN's transaction history lookback is **limited by financial institutions**:

- **Typical maximum**: 90 days of transaction history
- **Common variations**: Some institutions only provide 30-60 days
- **Institution-dependent**: Varies by bank and their data provider (MX)
- **No control**: SimpleFIN and G-Ledger cannot extend this limit

**Implications**:
- If you connect accounts after 90 days of activity, you'll miss older transactions
- Historical data beyond the lookback window must be manually imported
- **Recommendation**: Connect and sync accounts within 90 days of starting

**For Historical Data**:
1. Use manual transactions to add older data
2. Import from bank statement CSVs (requires custom script)
3. Start fresh and only track going forward

**Testing Lookback Period**:
```bash
# Test with progressively larger windows
gledger sync --days 30 --dry-run
gledger sync --days 60 --dry-run
gledger sync --days 90 --dry-run
```

If transaction counts stop increasing after a certain window, you've hit your institution's limit.

## Health Checks

### Basic Health Check Script

Create `~/bin/gledger-health-check.sh`:

```bash
#!/bin/bash

# Check if gledger is installed
if ! command -v gledger &> /dev/null; then
    echo "ERROR: gledger not found"
    exit 1
fi

# Check config file exists
if [ ! -f ~/.config/gledger/config.yaml ]; then
    echo "ERROR: config file not found"
    exit 1
fi

# Test dry-run sync
if gledger --config ~/.config/gledger/config.yaml sync --dry-run &> /dev/null; then
    echo "OK: gledger is healthy"
    exit 0
else
    echo "ERROR: gledger sync test failed"
    exit 1
fi
```

### Monitor with systemd

Create `/etc/systemd/system/gledger-health-check.service`:

```ini
[Unit]
Description=G-Ledger Health Check

[Service]
Type=oneshot
User=youruser
ExecStart=/home/youruser/bin/gledger-health-check.sh
```

Create `/etc/systemd/system/gledger-health-check.timer`:

```ini
[Unit]
Description=G-Ledger Health Check Timer

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
```

## Security Best Practices

1. **Protect credentials**:
   ```bash
   chmod 600 ~/.config/gledger/config.yaml
   chmod 600 ~/.config/gledger/service-account-key.json
   ```

2. **Use dedicated service account**: Don't run as root

3. **Restrict sheet permissions**: Give service account only necessary permissions

4. **Enable audit logging**: Monitor sheet access in Google Cloud Console

5. **Backup snapshots**: Regularly backup the snapshots directory
   ```bash
   # Add to cron
   0 0 * * 0 tar czf ~/backups/gledger-snapshots-$(date +%Y%m%d).tar.gz ~/gledger-snapshots
   ```

## Troubleshooting

### Command not found after installation

```bash
# Check if installed
pip list | grep gledger

# If installed but not found, check PATH
which gledger

# May need to add pip's bin directory to PATH
export PATH="$HOME/.local/bin:$PATH"
```

### Permission errors

```bash
# Ensure correct ownership
chown -R $USER:$USER ~/.config/gledger
chown -R $USER:$USER ~/gledger-snapshots
```

### Service account authentication fails

```bash
# Test service account directly
python3 -c "
from google.oauth2 import service_account
creds = service_account.Credentials.from_service_account_file(
    '~/.config/gledger/service-account-key.json'
)
print('Service account loaded successfully')
"
```

## Monitoring and Alerts

### Email Notifications on Failure

Add to cron with mail support:

```bash
MAILTO=youremail@example.com
0 6 * * * /opt/gledger-venv/bin/gledger sync || echo "G-Ledger sync failed at $(date)"
```

### Slack Webhook Integration

Create `~/bin/gledger-sync-with-notify.sh`:

```bash
#!/bin/bash

SLACK_WEBHOOK="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

if gledger sync; then
    curl -X POST -H 'Content-type: application/json' \
        --data '{"text":"✅ G-Ledger sync completed successfully"}' \
        $SLACK_WEBHOOK
else
    curl -X POST -H 'Content-type: application/json' \
        --data '{"text":"❌ G-Ledger sync failed"}' \
        $SLACK_WEBHOOK
    exit 1
fi
```

## Performance Tuning

### Large Transaction Volumes

For accounts with 10k+ transactions:

1. Increase sync window conservatively:
   ```bash
   gledger sync --days 90  # Instead of default 30
   ```

2. Run sync more frequently to reduce batch size

3. Consider archiving old reconciled transactions

## Uninstalling

```bash
# Remove package
make uninstall

# Remove configuration
rm -rf ~/.config/gledger

# Remove snapshots (if desired)
rm -rf ~/gledger-snapshots

# Remove logs
sudo rm -rf /var/log/gledger
```
