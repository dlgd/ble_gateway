# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `duplicate_filtering` config option (default `true`) to suppress duplicate
  advertisement report data at BlueZ, reducing host-ward report volume in active
  scanning.

### Removed
- **Passive scanning mode** (`scanning_mode: "passive"`) and all `or_patterns`
  / `AdvertisementMonitor` handling.

  **Rationale**: The target devices (Molleau water meters) advertise exclusively
  via BLE extended advertising — the payload is in the AUX (secondary) PDU. Passive
  scanning relies on BlueZ's `AdvertisementMonitor` `or_patterns`, which do **not**
  match extended advertisements. Verified on real hardware (BlueZ 5.82, kernel 6.18,
  nRF52840): passive → 0 messages, active → 443. Active mode uses BlueZ
  `SetDiscoveryFilter` on the fully reassembled advertisement and works correctly.

  **Back-compat**: configs that still contain `scanning_mode: "passive"` or an
  `or_patterns` key are not rejected — a warning is logged and the gateway runs
  in active mode.

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
