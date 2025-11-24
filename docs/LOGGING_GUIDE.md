# BLE Gateway Logging Guide

## Log Levels

The gateway supports standard Python logging levels:

- **DEBUG**: Detailed information for diagnosing problems
- **INFO**: Confirmation that things are working as expected
- **WARNING**: Indication that something unexpected happened
- **ERROR**: A serious problem that prevented some function from working

## Setting Log Level

Use the `--log-level` command line argument:

```bash
# Show detailed debug information
./ble_gateway.py -c config.json --log-level DEBUG

# Show only informational messages and above (default)
./ble_gateway.py -c config.json --log-level INFO

# Show only warnings and errors
./ble_gateway.py -c config.json --log-level WARNING
```

## What You'll See at Each Level

### DEBUG Level

Shows everything including:

#### BLE Device Detection
```
BLE message received - Device: AA:BB:CC:DD:EE:FF (SensorName), RSSI: -65 dBm,
Manufacturer Data: {76: b'\x02\x15\x01\x02\x03\x04'},
Service UUIDs: ['0000eff0-eff0-1212-1515-eeffd1024132'],
Service Data: {'0000eff0-eff0-1212-1515-eeffd1024132': b'\xaa\xbb\xcc'},
TX Power: -10, Buffer size: 1
```

This shows:
- Device MAC address and name
- Signal strength (RSSI)
- Raw manufacturer data (hex bytes)
- Bluetooth service UUIDs
- Service-specific data
- Transmission power
- Current messages in buffer

#### Publishing to AWS IoT
```
Publishing to AWS IoT - Device: AA:BB:CC:DD:EE:FF,
Topic: molleaumetre/event,
Payload: {"data":["$GPRP,000000000000,AABBCCDDEEFF,-65,1106324102D1FFEE15151212F0EFF0EF000009FF4C000215010203041416324102D1FFEE15151212F0EFF0EF0000AABBCC,1763674855.942"],"mqtt_topic":"molleaumetre/event"}
```

This shows:
- Which device is being published
- MQTT topic name
- **Full GPRP payload** being sent to AWS

#### AWS IoT Queue Status
```
AWS IoT publish queued - Topic: molleaumetre/event,
Packet ID: 1, QoS: AT_LEAST_ONCE,
Payload length: 196 bytes
```

This shows:
- Topic name
- MQTT packet ID (for tracking)
- Quality of Service level
- Message size in bytes

#### Publish Result
```
✓ Successfully published message for device AA:BB:CC:DD:EE:FF
```
or
```
✗ Failed to publish message for device AA:BB:CC:DD:EE:FF
```

Visual confirmation of publish success/failure.

#### Connection Events
```
Connection interrupted (will auto-reconnect): AWS_ERROR_MQTT_UNEXPECTED_HANGUP
```

Shows temporary connection issues (these are normal and auto-recover).

### INFO Level

Shows operational information:

```
Successfully connected to AWS IoT Core: endpoint:8883
Hardware-level filtering enabled for 1 service UUID(s)
Starting continuous BLE scanning...
Flushing buffer: 3 message(s) [Publish interval: 2.0s, Throttle: True]
Connection resumed successfully (rc=0)
```

### WARNING Level

Shows potential issues:

```
Connection interrupted: AWS_ERROR_MQTT_UNEXPECTED_HANGUP
```

### ERROR Level

Shows serious problems:

```
Failed to connect to AWS IoT Core: [error details]
Error publishing message: [error details]
```

## Recommended Usage

### During Development/Debugging
```bash
./ble_gateway.py -c config.json --log-level DEBUG
```

Use DEBUG to see:
- Every BLE advertisement received
- Exact payload being sent to AWS
- Connection status changes
- Message flow through the system

### In Production
```bash
./ble_gateway.py -c config.json --log-level INFO
```

Use INFO to see:
- Connection status
- Buffer flush events
- General operational status

Without excessive detail about every message.

### For Monitoring
```bash
./ble_gateway.py -c config.json --log-level WARNING
```

Use WARNING to only see problems while keeping logs clean.

## Reading GPRP Payloads

The GPRP format in DEBUG logs looks like:
```
$GPRP,GATEWAY_MAC,DEVICE_MAC,RSSI,BLE_ADV_HEX,TIMESTAMP
```

Example:
```
$GPRP,000000000000,AABBCCDDEEFF,-65,1106324102D1FFEE...,1763674855.942
```

- `GATEWAY_MAC`: Your gateway's MAC (from config)
- `DEVICE_MAC`: BLE device MAC address
- `RSSI`: Signal strength in dBm
- `BLE_ADV_HEX`: Raw BLE advertisement data (hex)
- `TIMESTAMP`: Unix timestamp with milliseconds

## Filtering Logs

### Save only BLE detections to a file:
```bash
./ble_gateway.py -c config.json --log-level DEBUG 2>&1 | grep "BLE message received" > ble_devices.log
```

### Watch publishes in real-time:
```bash
./ble_gateway.py -c config.json --log-level DEBUG 2>&1 | grep "Publishing to AWS"
```

### Monitor connection status:
```bash
./ble_gateway.py -c config.json --log-level INFO 2>&1 | grep -E "(connected|Connection)"
```

## Troubleshooting with Logs

### Problem: No BLE devices detected

Look for:
```
Starting continuous BLE scanning...
```

If you see this but no "BLE message received", either:
- No devices are nearby with your configured service UUID
- Bluetooth adapter isn't working
- Service UUID filter is too restrictive

### Problem: Devices detected but not published

Look for:
```
BLE message received - Device: ...   ← Device is detected
Flushing buffer: X message(s)         ← Buffer is being flushed
Not connected, skipping publish       ← Problem: Not connected
```

This means AWS IoT connection isn't stable. Check your certificates and policy.

### Problem: Messages published but not appearing in AWS

Look for:
```
✓ Successfully published message     ← Message sent successfully
```

If you see success but no data in AWS:
- Check your AWS IoT Rule is configured for the topic
- Verify CloudWatch logs in AWS IoT Console
- Check topic name matches your configuration
