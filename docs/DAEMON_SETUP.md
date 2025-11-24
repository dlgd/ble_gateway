# Daemon Setup Quick Reference

This guide shows how to run the Bluetooth Gateway as a background service (daemon) that starts automatically when your Raspberry Pi boots.

## Quick Setup (3 Steps)

### Step 1: Configure the Gateway

```bash
cd /home/daniel/src/ble_gateway

# Copy and edit configuration
cp config.example.json config.json
nano config.json  # Add your AWS IoT Core endpoint and certificate paths
```

### Step 2: Install as Service

```bash
# Run the automated installation script
sudo ./install-service.sh
```

### Step 3: Enable and Start

```bash
# Enable auto-start on boot
sudo systemctl enable ble-gateway

# Start the service now
sudo systemctl start ble-gateway

# Check it's running
sudo systemctl status ble-gateway
```

**Done!** The gateway will now:
- ✓ Start automatically when Raspberry Pi boots
- ✓ Restart automatically if it crashes
- ✓ Run with limited CPU/memory for efficiency
- ✓ Log to system journal

## Common Commands

```bash
# View live logs
sudo journalctl -u ble-gateway -f

# Stop the service
sudo systemctl stop ble-gateway

# Restart the service
sudo systemctl restart ble-gateway

# Disable auto-start
sudo systemctl disable ble-gateway

# Check service status
sudo systemctl status ble-gateway
```

## Monitoring

### Check if Service is Running

```bash
sudo systemctl status ble-gateway
```

Expected output:
```
● ble-gateway.service - Bluetooth Gateway for AWS IoT Core
   Loaded: loaded (/etc/systemd/system/ble-gateway.service; enabled; vendor preset: enabled)
   Active: active (running) since ...
```

### View Logs

```bash
# Live logs (last 50 lines, then follow)
sudo journalctl -u ble-gateway -n 50 -f

# Logs since last boot
sudo journalctl -u ble-gateway -b

# Logs from last hour
sudo journalctl -u ble-gateway --since "1 hour ago"
```

### Check CPU and Memory Usage

```bash
# Quick status
systemctl status ble-gateway

# Detailed resource usage
systemd-cgtop

# Watch CPU in real-time
top -p $(pgrep -f ble_gateway.py)
```

## After Configuration Changes

If you modify `config.json`, restart the service:

```bash
sudo systemctl restart ble-gateway
```

## After Code Updates

If you update the Python script:

```bash
# Restart service to load new code
sudo systemctl restart ble-gateway

# Watch logs for any errors
sudo journalctl -u ble-gateway -f
```

## Troubleshooting

### Service Won't Start

```bash
# Check detailed logs
sudo journalctl -u ble-gateway -n 100

# Common issues:
# 1. config.json not found or invalid
# 2. AWS IoT certificates missing/invalid
# 3. Virtual environment not set up
# 4. Bluetooth adapter not available
```

### Service Starts but Crashes

```bash
# View crash logs
sudo journalctl -u ble-gateway -n 100 --no-pager

# Common causes:
# - Invalid AWS IoT endpoint
# - Network not available
# - Bluetooth permission issues
# - Certificate files corrupted
```

### High CPU Usage

```bash
# Check current CPU usage
top -p $(pgrep -f ble_gateway.py)

# Reduce CPU by editing config.json:
{
  "throttle_interval_sec": 5.0     // Increase from 1.0
}

# Restart after changes
sudo systemctl restart ble-gateway
```

### Manually Test Before Installing Service

```bash
# Test the script manually first
source venv/bin/activate
python ble_gateway.py -c config.json -v

# Once working, install as service
sudo ./install-service.sh
```

## Resource Limits

The service is configured with these limits (in `ble-gateway.service`):

- **CPU**: 50% of one core (can use up to half a CPU)
- **Memory**: 512MB maximum
- **Restart**: Automatic after 10 seconds if crashes

To adjust limits:

```bash
# Edit service file
sudo nano /etc/systemd/system/ble-gateway.service

# Modify these lines:
CPUQuota=75%        # Increase to 75% of one core
MemoryMax=1G        # Increase to 1GB

# Reload and restart
sudo systemctl daemon-reload
sudo systemctl restart ble-gateway
```

## Uninstalling the Service

```bash
# Stop and disable service
sudo systemctl stop ble-gateway
sudo systemctl disable ble-gateway

# Remove service file
sudo rm /etc/systemd/system/ble-gateway.service

# Reload systemd
sudo systemctl daemon-reload
```

## Best Practices

1. **Always test manually first** before installing as service
2. **Monitor logs** after installation to ensure it's working
4. **Use whitelists** to reduce unnecessary processing
5. **Check logs regularly** for any AWS IoT connection issues

## Performance Tips

For lowest CPU usage:

```json
{
  "throttle_interval_sec": 10.0,
  "mac_whitelist": ["AA:BB:CC:DD:EE:FF"]  // Only specific devices
}
```

Expected result: **< 2% CPU usage**

## Getting Help

If issues persist:

1. Check full logs: `sudo journalctl -u ble-gateway --no-pager`
2. Test manually: `python ble_gateway.py -c config.json -d`
3. Check Bluetooth: `hciconfig`
4. Verify AWS IoT certs: `ls -lh /path/to/certs/`
5. Review README.md and TROUBLESHOOTING.md
