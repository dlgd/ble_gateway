# Gateway MAC Address Configuration

## Overview

The `gateway_mac` field in the configuration identifies the gateway device in GPRP-formatted messages sent to AWS IoT Core. This is included in every message to distinguish which gateway collected the BLE data.

## Auto-Detection (Recommended)

**If you omit the `gateway_mac` field**, the gateway will automatically use the MAC address of the network interface on the device running the script.

### Example Configuration (Auto-Detect)
```json
{
  "aws_iot": {
    "endpoint": "your-endpoint.iot.region.amazonaws.com",
    ...
  },
  "publish_interval_sec": 2.0,
  ...
}
```

### What Happens
```
2025-11-20 23:05:31 - BLEGateway - INFO - Using device MAC address as gateway MAC: BC091BCC991C
```

The gateway automatically detects its MAC address: `BC:09:1B:CC:99:1C` and formats it as `BC091BCC991C` for GPRP messages.

### Example GPRP Message (Auto-Detected)
```json
{
  "data": [
    "$GPRP,BC091BCC991C,FA27FADA172D,-40,1106324102D1FFEE...,1763676354.015"
  ],
  "mqtt_topic": "molleaumetre/event"
}
```

Where:
- `BC091BCC991C` = Gateway MAC (auto-detected from device)
- `FA27FADA172D` = BLE device MAC address
- `-40` = RSSI
- `1106...` = BLE advertising data (hex)
- `1763676354.015` = Timestamp

## Manual Configuration

You can **optionally** specify a custom gateway MAC address:

### Example Configuration (Manual)
```json
{
  "gateway_mac": "AA:BB:CC:DD:EE:FF",
  "aws_iot": {
    ...
  }
}
```

### Supported Formats

All these formats work:

```json
"gateway_mac": "AA:BB:CC:DD:EE:FF"  // With colons
"gateway_mac": "AABBCCDDEEFF"       // Without colons
"gateway_mac": "aa:bb:cc:dd:ee:ff"  // Lowercase (converted to uppercase)
```

### What Happens
```
2025-11-20 23:06:27 - BLEGateway - DEBUG - Using configured gateway MAC: AABBCCDDEEFF
```

### Example GPRP Message (Manual)
```json
{
  "data": [
    "$GPRP,AABBCCDDEEFF,FA27FADA172D,-40,1106324102D1FFEE...,1763676389.428"
  ],
  "mqtt_topic": "molleaumetre/event"
}
```

## When to Use Manual Configuration

Use manual configuration when:

1. **Multiple gateways share the same device** - If you're running multiple gateway instances on the same machine, give each a unique identifier
2. **Virtual machines/containers** - VMs may have randomized or duplicate MAC addresses
3. **Testing** - Using a known test MAC makes it easier to filter test data
4. **Custom identification** - You want to use a specific identifier that doesn't match the hardware MAC

## When to Use Auto-Detection

Use auto-detection when:

1. **Single gateway per device** - Each gateway runs on its own hardware
2. **Raspberry Pi/dedicated hardware** - Physical devices with stable MAC addresses
3. **Simplicity** - You want zero configuration for gateway identification
4. **Production deployments** - Let the gateway identify itself automatically

## Troubleshooting

### How to find your device's MAC address

**On Linux/Raspberry Pi:**
```bash
ip link show
# Or
ifconfig
```

Look for your primary network interface (usually `eth0` or `wlan0`).

**In the gateway logs:**
```bash
./ble_gateway.py -c config.json --log-level INFO
```

Look for:
```
Using device MAC address as gateway MAC: BC091BCC991C
```

### Fallback Behavior

If the gateway cannot detect a MAC address (rare), it will fall back to `000000000000` and log a warning.

## Best Practices

1. **Use auto-detection for simple setups** - Let the gateway handle it
2. **Document custom MACs** - If you configure manually, document which MAC belongs to which gateway
3. **Use consistent format** - Stick to either colons or no colons across your fleet
4. **Include location in naming** - Consider using the location as part of client_id instead of overriding MAC

## Example: Multiple Gateways in Same Location

Instead of different MAC addresses, consider using descriptive client IDs:

```json
// Gateway 1 - Warehouse North
{
  "mqtt": {
    "client_id": "warehouse-north-gateway"
  }
  // gateway_mac auto-detected: AA11BB22CC33
}

// Gateway 2 - Warehouse South
{
  "mqtt": {
    "client_id": "warehouse-south-gateway"
  }
  // gateway_mac auto-detected: DD44EE55FF66
}
```

Both gateways will have unique MAC addresses automatically, and their client IDs make them easy to identify in AWS IoT Core.
