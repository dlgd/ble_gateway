# Cloud-Agnostic Bluetooth Gateway

A professional-grade Bluetooth Low Energy (BLE) gateway application that captures BLE advertisement packets from nearby devices and publishes them to any MQTT broker. Supports AWS IoT Core, Azure IoT Hub, HiveMQ, Mosquitto, and any standard MQTT broker. Designed for Raspberry Pi and other Linux systems.

## Quick Start

**BEFORE running the gateway, you must:**

1. **Install dependencies**: Follow the [Installation](#installation) section
2. **Set up MQTT broker**: Configure your MQTT broker and obtain any required certificates
3. **Configure the gateway**: Copy `config.example.json` to `config.json` and fill in your MQTT broker details
4. **Run**: `source venv/bin/activate && python ble_gateway.py -c config.json -v`

For cloud MQTT brokers requiring TLS/certificates (AWS IoT Core, Azure IoT Hub, etc.), ensure you have valid certificates configured. See the [Configuration](#configuration) section for details.

## Features

Implements all features from commercial BLE gateways like the [iGS03M](https://fcc.report/FCC-ID/2AH2IIGS03W/4974289.pdf):

- **Request Interval**: Configure upload interval (0=immediate, >0=buffered)
  - Data sent immediately when interval=0
  - Data buffered and sent when interval reached OR buffer full
- **Throttle Control**: Keep only LAST record per device in buffer
  - Reduces connections and bandwidth usage
  - Ensures latest state for each device
- **Message Buffering**: Intelligent buffering with configurable size limits
  - Buffer flushes on time interval or size threshold
  - All buffered messages sent before shutdown
- **Payload Whitelist**: Filter by MAC, name, manufacturer ID, or service UUID
- **Timestamp Appending**: Millisecond-precision timestamps on all messages
- **JSON Message Format**: Structured JSON with hex-encoded binary data
- **BLE Scanning**: Continuous passive scanning for low power consumption
- **Universal MQTT Integration**: Works with any MQTT broker (AWS IoT, Azure, HiveMQ, Mosquitto, etc.)
- **Daemon Mode**: Run as systemd service with auto-start on boot
- **Verbose/Debug Modes**: Comprehensive logging for troubleshooting
- **CPU Optimized**: Typically 2-5% CPU usage on Raspberry Pi 4

See [FEATURES.md](docs/FEATURES.md) for detailed feature documentation.

## Requirements

### Hardware
- Raspberry Pi (3, 4, or 5) with built-in Bluetooth or USB Bluetooth adapter
- Any Linux system with Bluetooth Low Energy support

### Software
- Python 3.7 or higher
- Bluetooth adapter with BLE support
- MQTT broker (cloud-based or local)

## Installation

### 1. System Dependencies

On Raspberry Pi/Debian/Ubuntu:
```bash
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv bluetooth bluez libbluetooth-dev
```

### 2. Python Environment Setup

```bash
# Navigate to the project directory
cd ble_gateway

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Install dependencies from requirements file
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Bluetooth Permissions

Add your user to the bluetooth group:
```bash
sudo usermod -a -G bluetooth $USER
```

For running without sudo, grant capabilities:
```bash
sudo setcap cap_net_raw,cap_net_admin+eip $(eval readlink -f $(which python3))
```

Or for the venv Python:
```bash
sudo setcap cap_net_raw,cap_net_admin+eip venv/bin/python3
```

Log out and log back in for group changes to take effect.

## MQTT Broker Setup

The gateway supports any MQTT broker. Choose the option that best fits your needs:

### Option 1: Local Mosquitto Broker (Simplest)

```bash
# Install Mosquitto
sudo apt-get install mosquitto mosquitto-clients

# Start Mosquitto
sudo systemctl start mosquitto
sudo systemctl enable mosquitto

# Test connection
mosquitto_pub -h localhost -t test -m "hello"
```

### Option 2: AWS IoT Core (Cloud)

1. Create a Thing in AWS IoT Core:
```bash
aws iot create-thing --thing-name bluetooth-gateway-001
```

2. Create and download certificates:
```bash
aws iot create-keys-and-certificate \
  --set-as-active \
  --certificate-pem-outfile certificate.pem.crt \
  --public-key-outfile public.pem.key \
  --private-key-outfile private.pem.key

wget https://www.amazontrust.com/repository/AmazonRootCA1.pem
```

3. Create and attach policy (see AWS IoT documentation)

4. Get your endpoint:
```bash
aws iot describe-endpoint --endpoint-type iot:Data-ATS
```

### Option 3: Azure IoT Hub (Cloud)

Follow Azure IoT Hub documentation to create an IoT Hub and obtain connection strings and certificates.

### Option 4: HiveMQ Cloud or Other MQTT Brokers

Follow your provider's documentation to obtain connection details and any required certificates.

## Configuration

### Basic Configuration

**Step 1**: Copy the example configuration:
```bash
cp config.example.json config.json
```

**Step 2**: Edit `config.json` with your MQTT broker details:

#### Local Mosquitto (No TLS):
```json
{
  "mqtt": {
    "broker": "localhost",
    "port": 1883,
    "client_id": "bluetooth-gateway-001",
    "topic": "ble/gateway/data"
  },
  "publish_interval_sec": 0.0,
  "throttle_control": true,
  "max_buffer_size": 100,
  "mac_whitelist": [],
  "name_whitelist": [],
  "manufacturer_id_whitelist": [],
  "service_uuid_whitelist": []
}
```

#### AWS IoT Core (TLS with certificates):
```json
{
  "mqtt": {
    "broker": "your-endpoint.iot.us-east-1.amazonaws.com",
    "port": 8883,
    "cert_path": "certs/certificate.pem.crt",
    "key_path": "certs/private.pem.key",
    "root_ca_path": "certs/AmazonRootCA1.pem",
    "client_id": "bluetooth-gateway-001",
    "topic": "ble/gateway/data"
  },
  "publish_interval_sec": 0.0,
  "throttle_control": true,
  "max_buffer_size": 100
}
```

#### Other Cloud Brokers (TLS with username/password):
```json
{
  "mqtt": {
    "broker": "your-broker.hivemq.cloud",
    "port": 8883,
    "username": "your-username",
    "password": "your-password",
    "client_id": "bluetooth-gateway-001",
    "topic": "ble/gateway/data"
  }
}
```

**IMPORTANT**: For brokers requiring TLS/certificates, ensure certificate files:
- Exist at the specified paths
- Are not empty
- Have proper permissions (cert: 644, key: 600)

### Configuration Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `mqtt.broker` | string | MQTT broker hostname or IP (required) |
| `mqtt.port` | integer | MQTT broker port (default: 1883 for plain, 8883 for TLS) |
| `mqtt.client_id` | string | MQTT client ID (default: "bluetooth-gateway") |
| `mqtt.topic` | string | MQTT topic to publish to (default: "ble/gateway/data") |
| `mqtt.username` | string | MQTT username (optional, for brokers requiring authentication) |
| `mqtt.password` | string | MQTT password (optional, for brokers requiring authentication) |
| `mqtt.cert_path` | string | Path to device certificate (optional, for TLS) |
| `mqtt.key_path` | string | Path to private key (optional, for TLS) |
| `mqtt.root_ca_path` | string | Path to root CA certificate (optional, for TLS) |
| **`publish_interval_sec`** | **float** | **Publish interval for uploading data (default: 0.0)**<br>• **0** = Send immediately (no buffering)<br>• **> 0** = Buffer messages and send when interval reached OR buffer is full |
| **`throttle_control`** | **boolean** | **Enable throttle control (default: true)**<br>• **true** = Keep only LAST record per device in buffer<br>• **false** = Keep ALL records in buffer |
| `max_buffer_size` | integer | Maximum buffer size before forced flush (default: 100) |
| `bluetooth_adapter` | string | Bluetooth adapter to use (default: "hci0") - Linux/Raspberry Pi only |
| `mac_whitelist` | array | List of MAC addresses to allow (empty = allow all) |
| `name_whitelist` | array | List of device names to allow (empty = allow all) |
| `manufacturer_id_whitelist` | array | List of manufacturer IDs to allow in hex format like `"0x004C"` for Apple (also accepts decimal). Empty = allow all |
| `service_uuid_whitelist` | array | **List of service UUIDs to allow (empty = allow all)**<br>⚡ **Hardware-accelerated filtering** when used - more efficient than software filtering |

### Publish Interval & Throttle Control

The gateway implements buffering and throttle control similar to commercial BLE gateways:

**Publish Interval (`publish_interval_sec`):**
- When set to **0**, data is sent immediately without buffering
- When set to a **non-zero value** (in seconds), data is buffered and sent when:
  - The time interval is reached, OR
  - The buffer is full (`max_buffer_size`)

**Throttle Control (`throttle_control`):**
- When **enabled (true)**, the gateway keeps only the **last record for each device** within the request interval
- This reduces upload connections and bandwidth usage
- When **disabled (false)**, all advertisements are kept and sent

**Operating Modes:**

| Mode | publish_interval_sec | throttle_control | Behavior |
|------|---------------------|------------------|----------|
| **Immediate** | 0.0 | false | Send every advertisement immediately |
| **Immediate + Throttle** | 0.0 | true | Send only latest per device immediately |
| **Buffered** | 10.0 | false | Send all advertisements every 10s or when buffer full |
| **Buffered + Throttle** | 10.0 | true | Send last record per device every 10s |

**Examples:**

```json
{
  "_comment": "Immediate mode - lowest latency",
  "publish_interval_sec": 0.0,
  "throttle_control": false
}
```

```json
{
  "_comment": "Efficient mode - reduce bandwidth and broker load",
  "publish_interval_sec": 30.0,
  "throttle_control": true,
  "max_buffer_size": 50
}
```

See `config.modes.example.json` for more configuration examples.

### Advanced Filtering Example

```json
{
  "mac_whitelist": ["AA:BB:CC:DD:EE:FF"],
  "name_whitelist": ["SensorBeacon", "TempHumidity"],
  "manufacturer_id_whitelist": ["0x004C", "0x0059"],
  "service_uuid_whitelist": [
    "0000180f-0000-1000-8000-00805f9b34fb"
  ]
}
```

**Common Manufacturer IDs** (hex format recommended):
- `"0x004C"` - Apple Inc.
- `"0x0059"` - Nordic Semiconductor
- `"0x0006"` - Microsoft
- `"0x00E0"` - Google
- `"0x004B"` - Qualcomm

Whitelist logic: A device is accepted if it matches ANY of the configured whitelists.

## Usage

### Basic Usage

**IMPORTANT**: Always activate the virtual environment before running the script:

```bash
# Activate virtual environment
source venv/bin/activate

# Run with default settings
python ble_gateway.py -c config.json

# Or use the shebang (only if venv is activated)
./ble_gateway.py -c config.json
```

### Verbose Mode

```bash
# Show informational messages
python ble_gateway.py -c config.json -v
```

### Debug Mode

```bash
# Show detailed debug information
python ble_gateway.py -c config.json -d
```

### Override Configuration

```bash
# Override publish interval (immediate mode)
python ble_gateway.py -c config.json --publish-interval 0

# Override publish interval (buffered mode)
python ble_gateway.py -c config.json --publish-interval 10

# Disable throttle control
python ble_gateway.py -c config.json --no-throttle

# Override buffer size
python ble_gateway.py -c config.json --buffer-size 50

# Combine options
python ble_gateway.py -c config.json -v --publish-interval 5 --buffer-size 50
```

### Command-Line Options

```
usage: ble_gateway.py [-h] -c CONFIG [-v] [-d]
                      [--publish-interval PUBLISH_INTERVAL]
                      [--no-throttle] [--buffer-size BUFFER_SIZE]

Bluetooth Gateway for MQTT Brokers

options:
  -h, --help            show this help message and exit
  -c, --config CONFIG   Path to configuration JSON file
  -v, --verbose         Enable verbose output (INFO level)
  -d, --debug           Enable debug output (DEBUG level)
  --publish-interval PUBLISH_INTERVAL
                        Override publish interval in seconds (0=immediate,
                        >0=buffered)
  --no-throttle         Disable throttle control (keep all records instead of
                        last per device)
  --buffer-size BUFFER_SIZE
                        Override maximum buffer size
```

## Message Format

The gateway publishes JSON messages with the following structure:

```json
{
  "timestamp_ms": 1699564823456,
  "device_address": "AA:BB:CC:DD:EE:FF",
  "device_name": "SensorBeacon",
  "rssi": -65,
  "manufacturer_data": {
    "76": "4c000215..."
  },
  "service_data": {
    "0000180f-0000-1000-8000-00805f9b34fb": "64"
  },
  "service_uuids": [
    "0000180f-0000-1000-8000-00805f9b34fb",
    "0000181a-0000-1000-8000-00805f9b34fb"
  ],
  "tx_power": -10
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `timestamp_ms` | integer | Unix timestamp in milliseconds |
| `device_address` | string | BLE MAC address |
| `device_name` | string/null | Advertised device name (if available) |
| `rssi` | integer | Received Signal Strength Indicator in dBm |
| `manufacturer_data` | object | Manufacturer-specific data (hex-encoded) |
| `service_data` | object | Service-specific data (hex-encoded) |
| `service_uuids` | array | List of advertised service UUIDs |
| `tx_power` | integer/null | Transmit power level in dBm (if available) |

## Running as a System Service (Daemon Mode)

The gateway is designed to run as a background service (daemon) that starts automatically when your Raspberry Pi boots.

**Quick Reference**: See [DAEMON_SETUP.md](docs/DAEMON_SETUP.md) for a condensed setup guide.

### Automatic Installation (Recommended)

Use the provided installation script:

```bash
# Navigate to project directory
cd ble_gateway

# Ensure config.json is configured with your MQTT broker settings
cp config.example.json config.json
nano config.json  # Edit with your MQTT broker details

# Run the installation script
sudo ./install-service.sh
```

The script will:
- Create and configure the systemd service file
- Grant necessary Bluetooth capabilities to Python
- Set up proper permissions and security settings
- Apply CPU and memory limits for efficiency

After installation:

```bash
# Enable service to start on boot
sudo systemctl enable ble-gateway

# Start the service
sudo systemctl start ble-gateway

# Check status
sudo systemctl status ble-gateway

# View live logs
sudo journalctl -u ble-gateway -f
```

### Manual Installation

If you prefer manual setup, create `/etc/systemd/system/ble-gateway.service`:

```ini
[Unit]
Description=Bluetooth Gateway for MQTT
Documentation=https://github.com/dlgd/ble_gateway
After=network-online.target bluetooth.target
Wants=network-online.target

[Service]
Type=simple
User=YOUR_USER
Group=YOUR_USER
WorkingDirectory=/path/to/ble_gateway

# Use the virtual environment Python
ExecStart=/path/to/ble_gateway/venv/bin/python3 /path/to/ble_gateway/ble_gateway.py -c /path/to/ble_gateway/config.json -v

# Restart policy
Restart=always
RestartSec=10

# Resource limits to prevent excessive CPU usage
CPUQuota=50%
MemoryMax=512M

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/path/to/ble_gateway

# Grant Bluetooth capabilities
AmbientCapabilities=CAP_NET_RAW CAP_NET_ADMIN

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=ble-gateway

# Graceful shutdown
TimeoutStopSec=30
KillMode=mixed
KillSignal=SIGTERM

[Install]
WantedBy=multi-user.target
```

Replace `YOUR_USER` and `/path/to/ble_gateway` with your actual values. Then:

```bash
# Grant Bluetooth capabilities
sudo setcap cap_net_raw,cap_net_admin+eip /path/to/ble_gateway/venv/bin/python3

# Reload systemd and enable service
sudo systemctl daemon-reload
sudo systemctl enable ble-gateway
sudo systemctl start ble-gateway
```

### Service Management Commands

```bash
# Start the service
sudo systemctl start ble-gateway

# Stop the service
sudo systemctl stop ble-gateway

# Restart the service
sudo systemctl restart ble-gateway

# Check service status
sudo systemctl status ble-gateway

# Enable auto-start on boot
sudo systemctl enable ble-gateway

# Disable auto-start on boot
sudo systemctl disable ble-gateway

# View logs (live)
sudo journalctl -u ble-gateway -f

# View logs (last 100 lines)
sudo journalctl -u ble-gateway -n 100

# View logs since last boot
sudo journalctl -u ble-gateway -b
```

### Auto-Start on Raspberry Pi Boot

Once enabled, the service will:
1. **Start automatically** when the Raspberry Pi boots
2. **Wait for network** to be available before starting
3. **Wait for Bluetooth** to be initialized
4. **Restart automatically** if it crashes (after 10 second delay)
5. **Shutdown gracefully** when system stops

### Performance Optimizations

The systemd service includes several optimizations for CPU efficiency:

1. **CPU Quota**: Limited to 50% of one CPU core (adjust in service file)
2. **Memory Limit**: Maximum 512MB RAM usage
3. **Passive Scanning**: BLE scanning uses passive mode for lower power consumption
4. **Throttle Control**: Prevents excessive message processing
5. **Stats Logging**: Reduced frequency to minimize overhead

### Monitoring Resource Usage

Check CPU and memory usage:

```bash
# View service resource usage
systemctl status ble-gateway

# Detailed resource statistics
systemd-cgtop

# Check CPU usage with top
top -p $(pgrep -f ble_gateway.py)

# Monitor resource usage over time
journalctl -u ble-gateway -f | grep -E "(CPU|Memory|Stats)"
```

### Adjusting Resource Limits

Edit `/etc/systemd/system/ble-gateway.service` and modify:

```ini
# Increase CPU limit to 75% of one core
CPUQuota=75%

# Increase memory limit to 1GB
MemoryMax=1G
```

Then reload:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ble-gateway
```

## Troubleshooting

### "Error: bleak library not installed"

This means the virtual environment is not activated or dependencies weren't installed:

```bash
# Make sure virtual environment is activated
source venv/bin/activate

# Verify you see (venv) in your prompt
# Install/reinstall dependencies
pip install -r requirements.txt

# Run with venv Python explicitly
python ble_gateway.py -c config.json -v
```

### Bluetooth Adapter Not Found

```bash
# Check if Bluetooth adapter is available
hciconfig

# Enable Bluetooth
sudo systemctl start bluetooth
sudo systemctl enable bluetooth

# Reset adapter
sudo hciconfig hci0 down
sudo hciconfig hci0 up
```

### Permission Denied Errors

```bash
# Grant Bluetooth capabilities
sudo setcap cap_net_raw,cap_net_admin+eip venv/bin/python3

# Or run with sudo (not recommended)
sudo venv/bin/python3 ble_gateway.py -c config.json
```

### MQTT Connection Issues

**Certificate or TLS errors (for cloud brokers):**

Check your certificate files if using TLS:

```bash
# 1. Verify certificate files exist and are not empty
ls -lh /path/to/certs/
# All files should have size > 0

# 2. Check if certificates are readable
cat certificate.pem.crt | head -2
# Should show: -----BEGIN CERTIFICATE-----

cat private.pem.key | head -2
# Should show: -----BEGIN RSA PRIVATE KEY----- or -----BEGIN PRIVATE KEY-----

# 3. Verify certificate with OpenSSL
openssl x509 -in certificate.pem.crt -text -noout

# 4. Set proper permissions
chmod 644 certificate.pem.crt
chmod 600 private.pem.key
chmod 644 root_ca.pem

# 5. Test connectivity to broker
ping your-broker-hostname
```

**Connection refused errors:**
- Verify broker hostname and port are correct
- Check firewall rules allow outbound connections
- Ensure broker is running and accessible
- For local Mosquitto: `sudo systemctl status mosquitto`

### No BLE Devices Detected

```bash
# Scan manually to verify devices are nearby
sudo hcitool lescan

# Check Bluetooth service
sudo systemctl status bluetooth

# Enable verbose mode to see scan activity
./ble_gateway.py -c config.json -d
```

### Import Errors

```bash
# Ensure virtual environment is activated
source venv/bin/activate

# Reinstall dependencies
pip install --force-reinstall bleak awsiotsdk
```

## Performance Optimization

### CPU Efficiency

The gateway is optimized for low CPU usage on Raspberry Pi. Typical CPU usage: **2-5%** on Raspberry Pi 4.

**Built-in optimizations:**
1. **Passive BLE scanning** - Lower power consumption than active scanning
2. **Hardware-level filtering** - Service UUID filtering handled by Bluetooth chip (when configured)
3. **Fast-path filtering** - Software filtering only for non-hardware-filterable criteria
4. **Reduced logging** - Stats logged every 10+ seconds instead of every scan
5. **Async I/O** - Non-blocking event loop for efficient operation
6. **Signal handlers** - Graceful shutdown on SIGTERM/SIGINT

### Hardware-Accelerated Filtering

When `service_uuid_whitelist` is configured, the gateway uses **Bleak's hardware-level filtering**:

```json
{
  "service_uuid_whitelist": [
    "0000180f-0000-1000-8000-00805f9b34fb"
  ]
}
```

**Benefits:**
- ⚡ Filtering happens at the **Bluetooth chip level** (not in software)
- 🔋 Significantly reduces CPU usage and power consumption
- 📡 Only matching advertisements reach the detection callback
- 💾 Less memory usage from filtered-out devices

**Performance comparison:**
- Without UUID filter: Process every BLE advertisement in software
- With UUID filter: Bluetooth chip only reports matching advertisements

**Recommended**: Always use `service_uuid_whitelist` when you know the service UUIDs of your target devices.

**Configuration tips to reduce CPU usage:**

```json
{
  "publish_interval_sec": 5.0,
  "throttle_control": true,
  "mac_whitelist": ["AA:BB:CC:DD:EE:FF"]
}
```

**Recommended settings for different scenarios:**

| Scenario | publish_interval_sec | max_buffer_size | Expected CPU |
|----------|----------------------|-----------------|--------------|
| Low traffic (< 10 devices) | 5.0 | 20 | 2-3% |
| Medium traffic (10-50 devices) | 10.0 | 50 | 3-5% |
| High traffic (50+ devices) | 15.0 | 100 | 5-8% |
| Battery powered | 30.0 | 20 | < 2% |

**Monitor CPU usage:**

```bash
# Real-time CPU monitoring
top -p $(pgrep -f ble_gateway.py)

# Check systemd resource limits
systemctl status ble-gateway

# View detailed cgroup stats
systemd-cgtop
```

### Reduce Bandwidth and Broker Load

- Increase `publish_interval_sec` to minimize messages (e.g., 10-30 seconds)
- Enable `throttle_control` to send only latest record per device
- Use MAC or manufacturer ID whitelists to only track specific devices
- Use MQTT QoS 0 instead of QoS 1 if you can tolerate message loss
- For cloud brokers, consider batch publishing to reduce connection overhead

### Handle High Device Density

```json
{
  "publish_interval_sec": 10.0,
  "throttle_control": true,
  "max_buffer_size": 100,
  "manufacturer_id_whitelist": ["0x004C"]
}
```

## Security Best Practices

1. **Certificate Storage**: Store certificates with restrictive permissions
   ```bash
   chmod 600 private.pem.key
   chmod 644 certificate.pem.crt
   ```

2. **Access Control**: Configure appropriate broker access policies and permissions

3. **Network**: Run on isolated network or VLAN when possible

4. **Updates**: Keep dependencies updated
   ```bash
   pip install --upgrade -r requirements.txt
   ```

## Documentation

Additional documentation is available in the [`docs/`](docs/) directory:

- **[FEATURES.md](docs/FEATURES.md)** - Detailed feature documentation and comparison with commercial gateways
- **[DAEMON_SETUP.md](docs/DAEMON_SETUP.md)** - Quick reference guide for setting up as a systemd service
- **[TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)** - Comprehensive troubleshooting guide

## Installation as Python Package

You can install the gateway as a Python package:

```bash
# Install in development mode (editable)
pip install -e .

# Or install normally
pip install .

# After installation, you can run it directly
ble-gateway -c config.json -v
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

For issues and questions:
- Check the [troubleshooting guide](docs/TROUBLESHOOTING.md)
- Review your MQTT broker documentation
- Verify Bluetooth adapter compatibility
- Check the [CHANGELOG](CHANGELOG.md) for recent changes

## Example Use Cases

- **Asset Tracking**: Track BLE beacons in warehouses
- **Environmental Monitoring**: Collect data from BLE temperature/humidity sensors
- **Proximity Detection**: Detect when devices enter/leave areas
- **Inventory Management**: Monitor BLE-tagged products
- **Healthcare**: Track medical equipment with BLE tags

## Version History

- **1.0.0** - Initial release
  - BLE scanning and AWS IoT Core publishing
  - Throttle control and payload filtering
  - Configurable intervals and whitelists
  - Verbose and debug modes
