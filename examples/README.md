# Configuration Examples

This directory contains example configurations for different MQTT brokers and use cases.

## Quick Start

1. Choose a config example based on your MQTT broker
2. Copy it to the project root as `config.json`
3. Edit with your actual credentials/endpoints
4. Run the gateway

```bash
# Example: Using AWS IoT Core
cp examples/configs/config.aws.example.json config.json
nano config.json  # Edit with your values
python ble_gateway.py -c config.json -v
```

## Configuration Files

### Cloud Providers

| File | Provider | Auth Method | Description |
|------|----------|-------------|-------------|
| [`config.aws.example.json`](configs/config.aws.example.json) | AWS IoT Core | mTLS (X.509) | Amazon Web Services IoT Core with certificate authentication |
| [`config.azure.example.json`](configs/config.azure.example.json) | Azure IoT Hub | mTLS (X.509) | Microsoft Azure IoT Hub with X.509 certificate auth |
| [`config.hivemq.example.json`](configs/config.hivemq.example.json) | HiveMQ Cloud | Username/Password | HiveMQ managed MQTT broker |
| [`config.mosquitto.example.json`](configs/config.mosquitto.example.json) | Mosquitto | mTLS or None | Self-hosted Mosquitto MQTT broker |

### Use Cases

| File | Description |
|------|-------------|
| [`config.modes.example.json`](configs/config.modes.example.json) | Different operating modes (immediate, buffered, throttled) |

## Authentication Methods

### mTLS (Mutual TLS) - Most Secure

Used by: AWS IoT Core, Azure IoT Hub (X.509), Mosquitto

```json
{
  "mqtt": {
    "auth_type": "mtls",
    "ca_certs": "certs/ca.pem",
    "certfile": "certs/client-cert.pem",
    "keyfile": "certs/client-key.pem"
  }
}
```

**Setup:**
1. Generate or obtain certificates from your cloud provider
2. Place certificates in a `certs/` directory
3. Update paths in config

### Username/Password - Simple

Used by: HiveMQ Cloud, Mosquitto, most managed MQTT services

```json
{
  "mqtt": {
    "auth_type": "userpass",
    "credentials": {
      "username": "your-username",
      "password": "${MQTT_PASSWORD}"
    }
  }
}
```

**Setup:**
1. Create username/password in your MQTT broker dashboard
2. Store password in environment variable (recommended) or config
3. Always use with TLS (port 8883)

```bash
export MQTT_PASSWORD="your-secret-password"
```

### Token-Based - Cloud Native

Used by: Azure IoT Hub (SAS tokens)

```json
{
  "mqtt": {
    "auth_type": "token",
    "credentials": {
      "username": "myiothub.azure-devices.net/device-id",
      "token": "${AZURE_SAS_TOKEN}"
    }
  }
}
```

## Directory Structure

```
examples/
├── README.md           # This file
└── configs/
    ├── config.aws.example.json         # AWS IoT Core
    ├── config.azure.example.json       # Azure IoT Hub
    ├── config.hivemq.example.json      # HiveMQ Cloud
    ├── config.mosquitto.example.json   # Mosquitto
    └── config.modes.example.json       # Operating modes
```

## Common Configuration Parameters

All configs support these common parameters:

```json
{
  "mqtt": {
    "endpoint": "broker.example.com",
    "port": 8883,
    "client_id": "unique-client-id",
    "topic": "your/mqtt/topic",
    "auth_type": "mtls|userpass|token|none",
    "qos": 0|1|2,
    "keepalive": 60
  },
  
  "publish_interval_sec": 0.0,
  "throttle_control": true,
  "max_buffer_size": 100,
  "bluetooth_adapter": "hci0",
  
  "mac_whitelist": [],
  "name_whitelist": [],
  "manufacturer_id_whitelist": [],
  "service_uuid_whitelist": []
}
```

## Environment Variables

For security, store sensitive values in environment variables:

```bash
# AWS
export AWS_IOT_ENDPOINT="xxx-ats.iot.us-east-1.amazonaws.com"

# Credentials
export MQTT_PASSWORD="your-password"
export AZURE_SAS_TOKEN="SharedAccessSignature sr=..."

# Then reference in config with ${VAR_NAME}
```

## Testing Configs

Test your configuration without running the full gateway:

```bash
# Dry run (validates config and connects)
python ble_gateway.py -c config.json -v --publish-interval 999999
# Stop with Ctrl+C after "Successfully connected"
```

## Need Help?

- 📖 [Main README](../README.md) - Full documentation
- 🔧 [Troubleshooting Guide](../docs/TROUBLESHOOTING.md) - Common issues
- 💬 [GitHub Issues](https://github.com/dlgd/ble_gateway/issues) - Report problems
