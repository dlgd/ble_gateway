# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Low-load scanning profile for dense RF environments to improve BLE controller
  stability (e.g. nRF52840 Zephyr `hci_usb` dongles that wedge under an
  advertising-report flood):
  - `scanning_mode` config option (`"active"` | `"passive"`). Passive scanning
    stops the gateway emitting SCAN_REQ packets and pushes filtering to BlueZ.
  - `duplicate_filtering` config option (default `true`) to suppress duplicate
    advertisement report data at BlueZ.
  - Automatic BlueZ `AdvertisementMonitor` `or_patterns`, built from
    `service_uuid_whitelist` / `manufacturer_id_whitelist`, plus an optional
    explicit `or_patterns` config key for advanced use.
  - Example config `examples/configs/config.lowload.example.json` and a
    `low_load_dense_rf_mode` entry in `config.modes.example.json`.
- Backward-compatible: when the new keys are absent the gateway behaves exactly
  as before (active scanning).

### Fixed
- Bluetooth adapter selection is now passed to the BlueZ backend as the
  `adapter` kwarg (it was previously placed inside the unused `bluez` args dict).

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
