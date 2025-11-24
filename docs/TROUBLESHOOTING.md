# Troubleshooting Guide

## Common Errors and Solutions

### Error: "bleak library not installed"

**Problem**: Virtual environment is not activated or dependencies not installed.

**Solution**:
```bash
# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the gateway
python ble_gateway.py -c config.json -v
```

---

### Error: MQTT Connection Issues (TLS/Certificate errors)

**Problem**: Certificate files are missing, empty, or invalid (when using TLS).

**What this means**: The MQTT client cannot read your certificate files or connect to the broker. This happens when:
- Certificate file paths in `config.json` are incorrect
- Certificate files don't exist at the specified paths
- Certificate files exist but are empty (0 bytes)
- Broker address or port is incorrect
- Network connectivity issues

**Solution for Certificate-based Authentication (TLS)**:

**Step 1**: Check if your certificates exist and are valid:
```bash
# Navigate to your certificate directory
cd /path/to/your/certs

# List files and check sizes (all should be > 0 bytes)
ls -lh

# Verify certificate content (should show "BEGIN CERTIFICATE")
head -2 certificate.pem.crt
head -2 private.pem.key
head -2 root_ca.pem
```

**Step 2**: Update your `config.json` with the correct paths:
```json
{
  "mqtt": {
    "broker": "your-broker-hostname.example.com",
    "port": 8883,
    "cert_path": "/absolute/path/to/certificate.pem.crt",
    "key_path": "/absolute/path/to/private.pem.key",
    "root_ca_path": "/absolute/path/to/root_ca.pem",
    "client_id": "bluetooth-gateway-001",
    "topic": "ble/gateway/data"
  }
}
```

**Step 3**: Set proper permissions:
```bash
chmod 644 certificate.pem.crt
chmod 600 private.pem.key
chmod 644 root_ca.pem
```

**Step 4**: Test broker connectivity:
```bash
# Test network connection
ping your-broker-hostname.example.com

# Test MQTT connection (if mosquitto-clients installed)
mosquitto_pub -h your-broker-hostname.example.com -p 8883 -t test -m "hello" \
  --cafile root_ca.pem --cert certificate.pem.crt --key private.pem.key
```

**Important**: Use absolute paths in your config.json (e.g., `/home/pi/certs/cert.pem`) not relative paths.

---

### Error: "Certificate file not found" or "Private key file not found"

**Problem**: The paths in your `config.json` are incorrect or the files don't exist.

**Solution**:
```bash
# Check where your certificates actually are
find ~ -name "*.pem.crt" -o -name "*.pem.key"

# Update config.json with the correct absolute paths
# Example:
{
  "mqtt": {
    "cert_path": "/home/daniel/certs/certificate.pem.crt",
    "key_path": "/home/daniel/certs/private.pem.key",
    "root_ca_path": "/home/daniel/certs/root_ca.pem"
  }
}
```

---

### Error: "Certificate file is empty" or "Private key file is empty"

**Problem**: Certificate files exist but contain no data (0 bytes).

**Solution**: You need to obtain valid certificates from your MQTT broker provider. Empty files won't work.

```bash
# Check file sizes
ls -lh /path/to/certs/

# If files are 0 bytes, delete them and get real certificates from your provider
rm certificate.pem.crt private.pem.key

# For local Mosquitto without TLS, update config.json to not use certificates:
{
  "mqtt": {
    "broker": "localhost",
    "port": 1883
  }
}
```

---

### Bluetooth Adapter Issues

**Error**: "No Bluetooth adapter found" or scanning doesn't work

**Solution**:
```bash
# Check if Bluetooth is enabled
hciconfig

# Enable Bluetooth
sudo systemctl start bluetooth
sudo systemctl enable bluetooth

# Reset adapter
sudo hciconfig hci0 down
sudo hciconfig hci0 up

# Test scanning manually
sudo hcitool lescan
```

---

### Permission Errors

**Error**: "Permission denied" when accessing Bluetooth

**Solution**:
```bash
# Add user to bluetooth group
sudo usermod -a -G bluetooth $USER

# Log out and back in for changes to take effect

# OR grant capabilities to Python binary
sudo setcap cap_net_raw,cap_net_admin+eip venv/bin/python3
```

---

## Need More Help?

1. **Enable debug mode** to see detailed logs:
   ```bash
   python ble_gateway.py -c config.json -d
   ```

2. **Check the full README** for complete setup instructions

3. **Verify your setup**:
   - Python 3.7+ installed: `python3 --version`
   - Virtual environment activated: `which python` should show venv path
   - Dependencies installed: `pip list | grep -E "(bleak|paho-mqtt)"`
   - Bluetooth working: `hciconfig`
   - Certificates valid (if using TLS): `ls -lh /path/to/certs/`

---

### Hardware-Level Filtering (Optional Performance Optimization)

**Info**: The gateway supports hardware-level manufacturer ID filtering using BlueZ `or_patterns`. This is more efficient than application-level filtering but requires BlueZ experimental features.

**Current Behavior**:
- The gateway automatically attempts hardware-level filtering when manufacturer ID filters are configured
- If not available, it falls back to application-level filtering (which still works fine)

**To Enable Hardware-Level Filtering** (optional):

1. **Check BlueZ version** (requires >= 5.56):
   ```bash
   bluetoothctl --version
   ```

2. **Enable BlueZ experimental features**:

   Edit the Bluetooth service configuration:
   ```bash
   sudo nano /etc/systemd/system/bluetooth.target.wants/bluetooth.service
   ```

   Find the line starting with `ExecStart=` and add `--experimental` flag:
   ```
   ExecStart=/usr/lib/bluetooth/bluetoothd --experimental
   ```

3. **Restart Bluetooth service**:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart bluetooth
   ```

4. **Verify** - Run the gateway and look for this log message:
   ```
   Hardware-level manufacturer filtering enabled (requires BlueZ experimental mode)
   ```

   Without the warning about "Falling back to active scanning"

**Benefits**:
- Lower CPU usage (filtering done by Bluetooth hardware/driver)
- More efficient battery usage on battery-powered devices
- Reduced number of wakeups from Bluetooth controller

**Note**: Application-level filtering works well for most use cases. Hardware-level filtering is only beneficial when scanning in high-traffic BLE environments.
