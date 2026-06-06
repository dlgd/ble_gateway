# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-06-06

Initial public release.

### Added
- BLE advertisement scanning via `bleak`.
- Publishing to any standard MQTT broker via `paho-mqtt` (Mosquitto, HiveMQ,
  Azure IoT Hub, AWS IoT Core, etc.).
- TLS / certificate-based authentication and username/password authentication.
- Configurable upload interval (immediate or buffered) and device whitelists.
- Throttle control and payload filtering.
- Verbose and debug logging modes.
- Auto-generated MQTT client ID derived from hostname and MAC address.
- Systemd service unit (`ble-gateway.service`) and `install-service.sh`
  installation script.
- Example configuration and documentation.

[Unreleased]: https://github.com/dlgd/ble_gateway/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/dlgd/ble_gateway/releases/tag/v1.0.0
