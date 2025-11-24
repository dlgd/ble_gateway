# Feature Implementation

This document describes the gateway features as specified in commercial BLE gateways like the iGS03M.

## Request Interval

**Feature**: Assign the request interval to upload data to MQTT broker.

**Implementation**:
- Configuration parameter: `publish_interval_sec`
- When set to **0**: Data is sent immediately without buffering
- When set to **> 0**: Data is buffered and sent when:
  - The buffer is full (`max_buffer_size`), OR
  - The time interval is reached

**Benefits**:
- Reduces MQTT broker connections and bandwidth
- Aggregates multiple advertisements into single publish operations
- Configurable trade-off between latency and efficiency

**Code Location**: `ble_gateway.py:61-136` (MessageBuffer class)

**Example Configuration**:
```json
{
  "publish_interval_sec": 10.0,
  "max_buffer_size": 100
}
```

## Throttle Control

**Feature**: Keep only the last record for each BLE device (TAG/Beacon ID) within the given interval.

**Implementation**:
- Configuration parameter: `throttle_control` (boolean)
- When **enabled (true)**:
  - Buffer maintains a dictionary keyed by device address
  - Each new advertisement from a device **replaces** the previous one
  - Only the most recent advertisement per device is sent
- When **disabled (false)**:
  - Buffer maintains a list of all advertisements
  - All advertisements are sent (no deduplication)

**Benefits**:
- Further reduces upload connections and bandwidth
- Ensures you always have the latest state for each device
- Prevents duplicate/outdated data from being sent

**Code Location**: `ble_gateway.py:84-100` (MessageBuffer.add_message)

**Example Configuration**:
```json
{
  "publish_interval_sec": 10.0,
  "throttle_control": true,
  "max_buffer_size": 50
}
```

**Behavior**:
- With 100 devices advertising every second
- Without throttle: Could buffer 1000 messages in 10 seconds
- With throttle: Buffers only 100 messages (last one per device)

## Payload Whitelist

**Feature**: Filter which BLE devices are processed based on whitelists.

**Implementation**:
- Four whitelist types available:
  1. `mac_whitelist`: Filter by MAC address
  2. `name_whitelist`: Filter by advertised device name
  3. `manufacturer_id_whitelist`: Filter by manufacturer ID
  4. `service_uuid_whitelist`: Filter by advertised service UUID

**Logic**: Device is accepted if it matches **ANY** of the configured whitelists.

**Code Location**: `ble_gateway.py:139-180` (PayloadFilter class)

**Example**:
```json
{
  "mac_whitelist": ["AA:BB:CC:DD:EE:FF"],
  "manufacturer_id_whitelist": [76, 89],
  "service_uuid_whitelist": ["0000180f-0000-1000-8000-00805f9b34fb"]
}
```

## Timestamp in Milliseconds

**Feature**: Append a timestamp in milliseconds to each message.

**Implementation**:
- Every BLE message includes `timestamp_ms` field
- Unix timestamp in milliseconds precision
- Generated when advertisement is received

**Code Location**: `ble_gateway.py:277` (timestamp_ms field)

**Output Example**:
```json
{
  "timestamp_ms": 1699564823456,
  "device_address": "AA:BB:CC:DD:EE:FF",
  "rssi": -65
}
```

## JSON Message Format

**Feature**: Structured JSON string output with all BLE advertisement data.

**Implementation**:
- Messages formatted as JSON strings
- Binary data (manufacturer_data, service_data) hex-encoded
- Compact format (no whitespace)

**Code Location**: `ble_gateway.py:48-58` (BLEMessage.to_json)

**Full Message Example**:
```json
{
  "timestamp_ms": 1699564823456,
  "device_address": "AA:BB:CC:DD:EE:FF",
  "device_name": "SensorBeacon",
  "rssi": -65,
  "manufacturer_data": {
    "76": "4c000215fda50693a4e24fb1afcfc6eb07647825ec760001000101c5"
  },
  "service_data": {
    "0000180f-0000-1000-8000-00805f9b34fb": "64"
  },
  "service_uuids": [
    "0000180f-0000-1000-8000-00805f9b34fb"
  ],
  "tx_power": -10
}
```

## Operating Mode Comparison

| Feature | iGS03M | This Gateway | Implementation |
|---------|--------|--------------|----------------|
| Request Interval | ✓ | ✓ | `publish_interval_sec` parameter |
| Throttle Control | ✓ | ✓ | `throttle_control` parameter |
| Payload Whitelist | ✓ | ✓ | Multiple whitelist types |
| Timestamp (ms) | ✓ | ✓ | `timestamp_ms` field |
| JSON Format | ✓ | ✓ | Compact JSON strings |
| Buffer Size Control | ✓ | ✓ | `max_buffer_size` parameter |
| MQTT Protocol | HTTP | MQTT | Any MQTT Broker |
| Passive Scanning | ✓ | ✓ | Low power BLE scanning |
| Daemon Mode | ✓ | ✓ | systemd service |

## Configuration Examples

### 1. Immediate Mode (Like iGS03M with interval=0)
```json
{
  "publish_interval_sec": 0.0,
  "throttle_control": false
}
```
**Behavior**: Send every BLE advertisement immediately

### 2. Buffered with Throttle (Like iGS03M default)
```json
{
  "publish_interval_sec": 10.0,
  "throttle_control": true,
  "max_buffer_size": 100
}
```
**Behavior**: Keep last record per device, send every 10s or when 100 unique devices seen

### 3. High Efficiency Mode
```json
{
  "publish_interval_sec": 60.0,
  "throttle_control": true,
  "max_buffer_size": 50
}
```
**Behavior**: Minimize MQTT connections, send once per minute

### 4. All Records Mode
```json
{
  "publish_interval_sec": 30.0,
  "throttle_control": false,
  "max_buffer_size": 500
}
```
**Behavior**: Keep all advertisements, useful for analytics

## Command Line Overrides

All features can be overridden via command line:

```bash
# Immediate mode
python ble_gateway.py -c config.json --request-interval 0

# Disable throttle
python ble_gateway.py -c config.json --no-throttle

# Adjust buffer size
python ble_gateway.py -c config.json --buffer-size 200

# Combine options
python ble_gateway.py -c config.json --request-interval 30 --buffer-size 50 -v
```

## Performance Impact

| Configuration | CPU Usage | MQTT Messages/min | Bandwidth |
|---------------|-----------|-------------------|-----------|
| Immediate + No Throttle | Medium | High (100+) | High |
| Immediate + Throttle | Low-Medium | Medium (50+) | Medium |
| Buffered (30s) + No Throttle | Low | 2 | High |
| Buffered (30s) + Throttle | Very Low | 2 | Low |

**Recommendation for Raspberry Pi**:
- `publish_interval_sec`: 10-30 seconds
- `throttle_control`: true
- `max_buffer_size`: 50-100

This provides the best balance of:
- Low CPU usage (< 5%)
- Minimal broker load and bandwidth
- Reasonable latency (< 30s)
- Efficient network usage
