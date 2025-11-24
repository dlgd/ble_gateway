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

### Error: "AWS_ERROR_INVALID_ARGUMENT: An invalid argument was passed to a function"

**Problem**: Certificate files are missing, empty, or invalid.

**What this means**: The AWS IoT SDK cannot read your certificate files. This happens when:
- Certificate file paths in `config.json` are incorrect
- Certificate files don't exist at the specified paths
- Certificate files exist but are empty (0 bytes)
- You're using placeholder/test certificates instead of real AWS IoT certificates

**Solution**:

**Step 1**: Check if your certificates exist and are valid:
```bash
# Navigate to your certificate directory
cd /path/to/your/certs

# List files and check sizes (all should be > 0 bytes)
ls -lh

# Verify certificate content (should show "BEGIN CERTIFICATE")
head -2 certificate.pem.crt
head -2 private.pem.key
head -2 AmazonRootCA1.pem
```

**Step 2**: If certificates don't exist or are empty, you need to set up AWS IoT Core:

```bash
# 1. Create an IoT Thing
aws iot create-thing --thing-name bluetooth-gateway-001

# 2. Create certificates
aws iot create-keys-and-certificate \
  --set-as-active \
  --certificate-pem-outfile certificate.pem.crt \
  --public-key-outfile public.pem.key \
  --private-key-outfile private.pem.key

# 3. Download Amazon Root CA
wget https://www.amazontrust.com/repository/AmazonRootCA1.pem

# 4. Get your IoT endpoint
aws iot describe-endpoint --endpoint-type iot:Data-ATS
```

**Step 3**: Update your `config.json` with the correct paths:
```json
{
  "aws_iot": {
    "endpoint": "xxxxx.iot.us-east-1.amazonaws.com",
    "cert_path": "/absolute/path/to/certificate.pem.crt",
    "key_path": "/absolute/path/to/private.pem.key",
    "root_ca_path": "/absolute/path/to/AmazonRootCA1.pem",
    "client_id": "bluetooth-gateway-001",
    "topic": "ble/gateway/data"
  }
}
```

**Step 4**: Set proper permissions:
```bash
chmod 644 certificate.pem.crt
chmod 600 private.pem.key
chmod 644 AmazonRootCA1.pem
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
  "aws_iot": {
    "cert_path": "/home/daniel/aws-certs/certificate.pem.crt",
    "key_path": "/home/daniel/aws-certs/private.pem.key",
    "root_ca_path": "/home/daniel/aws-certs/AmazonRootCA1.pem"
  }
}
```

---

### Error: "Certificate file is empty" or "Private key file is empty"

**Problem**: Certificate files exist but contain no data (0 bytes).

**Solution**: You need to download real certificates from AWS IoT Core. Empty files won't work.

```bash
# Check file sizes
ls -lh /path/to/certs/

# If files are 0 bytes, delete them and get real certificates
rm certificate.pem.crt private.pem.key

# Get certificates from AWS IoT Core (see AWS IoT Core Setup in README)
aws iot create-keys-and-certificate --set-as-active \
  --certificate-pem-outfile certificate.pem.crt \
  --private-key-outfile private.pem.key
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
   - Dependencies installed: `pip list | grep -E "(bleak|awsiotsdk)"`
   - Bluetooth working: `hciconfig`
   - AWS IoT certificates valid and not empty: `ls -lh /path/to/certs/`

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
