#!/bin/bash
#
# Installation script for BLE Gateway systemd service
# Run as: sudo ./install-service.sh
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: This script must be run as root (use sudo)${NC}"
    exit 1
fi

# Get the actual user (not root when using sudo)
ACTUAL_USER="${SUDO_USER:-$USER}"
ACTUAL_HOME=$(eval echo ~$ACTUAL_USER)

echo -e "${GREEN}BLE Gateway Service Installation${NC}"
echo "================================"
echo ""

# Detect current directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
echo "Installation directory: $SCRIPT_DIR"
echo "User: $ACTUAL_USER"
echo ""

# Check if config.json exists
if [ ! -f "$SCRIPT_DIR/config.json" ]; then
    echo -e "${YELLOW}Warning: config.json not found!${NC}"
    echo "Please create config.json before starting the service."
    echo "Copy config.example.json and edit with your AWS IoT settings:"
    echo "  cp config.example.json config.json"
    echo ""
fi

# Check if venv exists
if [ ! -d "$SCRIPT_DIR/venv" ]; then
    echo -e "${RED}Error: Virtual environment not found!${NC}"
    echo "Please create the virtual environment first:"
    echo "  python3 -m venv venv"
    echo "  source venv/bin/activate"
    echo "  pip install -r requirements.txt"
    exit 1
fi

# Create service file from template
SERVICE_FILE="/etc/systemd/system/ble-gateway.service"
TEMP_SERVICE="/tmp/ble-gateway.service.tmp"

echo "Creating systemd service file..."

# Replace placeholders in service file
sed "s|/home/pi|$ACTUAL_HOME|g" "$SCRIPT_DIR/ble-gateway.service" | \
sed "s|User=pi|User=$ACTUAL_USER|g" | \
sed "s|Group=pi|Group=$ACTUAL_USER|g" > "$TEMP_SERVICE"

# Copy to systemd directory
cp "$TEMP_SERVICE" "$SERVICE_FILE"
rm "$TEMP_SERVICE"

echo -e "${GREEN}✓${NC} Service file created: $SERVICE_FILE"

# Grant Bluetooth capabilities to Python binary
PYTHON_BIN="$SCRIPT_DIR/venv/bin/python3"
if [ -f "$PYTHON_BIN" ]; then
    echo "Granting Bluetooth capabilities to Python binary..."
    setcap cap_net_raw,cap_net_admin+eip "$PYTHON_BIN"
    echo -e "${GREEN}✓${NC} Capabilities granted to $PYTHON_BIN"
else
    echo -e "${RED}Error: Python binary not found at $PYTHON_BIN${NC}"
    exit 1
fi

# Reload systemd
echo "Reloading systemd daemon..."
systemctl daemon-reload
echo -e "${GREEN}✓${NC} Systemd reloaded"

echo ""
echo -e "${GREEN}Installation complete!${NC}"
echo ""
echo "Next steps:"
echo "  1. Ensure config.json is properly configured with AWS IoT settings"
echo "  2. Enable service to start on boot: sudo systemctl enable ble-gateway"
echo "  3. Start the service: sudo systemctl start ble-gateway"
echo "  4. Check status: sudo systemctl status ble-gateway"
echo "  5. View logs: sudo journalctl -u ble-gateway -f"
echo ""
echo "Service management commands:"
echo "  Start:   sudo systemctl start ble-gateway"
echo "  Stop:    sudo systemctl stop ble-gateway"
echo "  Restart: sudo systemctl restart ble-gateway"
echo "  Status:  sudo systemctl status ble-gateway"
echo "  Logs:    sudo journalctl -u ble-gateway -f"
echo "  Disable: sudo systemctl disable ble-gateway"
echo ""
