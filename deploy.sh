#!/bin/bash
set -e

# G-Ledger Production Deployment Script
# Usage: ./deploy.sh [install|upgrade|uninstall]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[1;33m'
COLOR_RED='\033[0;31m'
COLOR_RESET='\033[0m'

log_info() {
    echo -e "${COLOR_GREEN}[INFO]${COLOR_RESET} $1"
}

log_warn() {
    echo -e "${COLOR_YELLOW}[WARN]${COLOR_RESET} $1"
}

log_error() {
    echo -e "${COLOR_RED}[ERROR]${COLOR_RESET} $1"
}

check_python() {
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is not installed"
        exit 1
    fi

    PYTHON_VERSION=$(python3 --version | awk '{print $2}')
    log_info "Found Python $PYTHON_VERSION"

    # Check if Python >= 3.10
    if ! python3 -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)"; then
        log_error "Python 3.10 or higher is required"
        exit 1
    fi
}

install() {
    log_info "Starting G-Ledger installation..."

    check_python

    # Clean previous builds
    log_info "Cleaning previous builds..."
    make clean 2>/dev/null || true

    # Install build dependencies
    log_info "Installing build dependencies..."
    pip install --upgrade pip build wheel

    # Build package
    log_info "Building package..."
    make build

    # Install package
    log_info "Installing G-Ledger..."
    pip install dist/*.whl --force-reinstall

    # Verify installation
    if command -v gledger &> /dev/null; then
        VERSION=$(gledger --version 2>&1 || echo "unknown")
        log_info "✓ G-Ledger installed successfully: $VERSION"
        log_info "✓ Command available at: $(which gledger)"
    else
        log_error "Installation completed but 'gledger' command not found in PATH"
        log_warn "You may need to add pip's bin directory to your PATH:"
        log_warn "  export PATH=\"\$HOME/.local/bin:\$PATH\""
        exit 1
    fi

    log_info ""
    log_info "Next steps:"
    log_info "  1. Create config: mkdir -p ~/.config/gledger && cp config.yaml ~/.config/gledger/"
    log_info "  2. Set up snapshots: mkdir -p ~/gledger-snapshots && cd ~/gledger-snapshots && git init"
    log_info "  3. Test installation: gledger --help"
    log_info "  4. See DEPLOYMENT.md for production setup (cron, systemd, etc.)"
}

upgrade() {
    log_info "Upgrading G-Ledger..."

    check_python

    # Uninstall old version
    log_info "Removing old version..."
    pip uninstall -y gledger 2>/dev/null || true

    # Install new version
    install
}

uninstall() {
    log_info "Uninstalling G-Ledger..."

    pip uninstall -y gledger

    log_info "✓ G-Ledger uninstalled"
    log_warn "Configuration files in ~/.config/gledger were NOT removed"
    log_warn "Snapshots in ~/gledger-snapshots were NOT removed"
    log_warn "To remove them: rm -rf ~/.config/gledger ~/gledger-snapshots"
}

show_help() {
    echo "G-Ledger Deployment Script"
    echo ""
    echo "Usage: ./deploy.sh [command]"
    echo ""
    echo "Commands:"
    echo "  install     Build and install G-Ledger for production"
    echo "  upgrade     Upgrade to latest version"
    echo "  uninstall   Remove G-Ledger from system"
    echo "  help        Show this help message"
    echo ""
    echo "See DEPLOYMENT.md for detailed production deployment guide"
}

# Main
case "${1:-install}" in
    install)
        install
        ;;
    upgrade)
        upgrade
        ;;
    uninstall)
        uninstall
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        log_error "Unknown command: $1"
        show_help
        exit 1
        ;;
esac
