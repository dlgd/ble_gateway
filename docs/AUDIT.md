# Code Audit — ble_gateway

**Date:** 2026-07-02
**Scope:** `ble_gateway.py`, `ble_message.py`, `scan_backends.py`, `tools/rssi_range_test.py`, `tools/hci_live_test.py`, packaging files.
**Method:** manual review of all source, cross-checked against the *installed* dependencies in `venv` (bleak 3.0.2, paho-mqtt 2.1.0) and against the Bluetooth Core Spec HCI packet layouts. The existing test suite (37 tests) passes and none of the findings below are covered by it.

Severity: how bad the consequence is when the bug fires.
Confidence: how sure I am the behavior is actually wrong (not intentional).
Fix complexity / regression risk: effort to fix correctly / chance the fix breaks something else.

## Summary

| # | Finding | Location | Severity | Confidence | Fix complexity | Regression risk |
|---|---------|----------|----------|------------|----------------|-----------------|
| 1 | `bluetooth_adapter` silently ignored by BlueZ backend | `scan_backends.py:391-414` | **High** | **High** (verified against installed bleak) | Trivial | Low |
| 2 | Shutdown flush publishes a different message format (`to_json` vs GPRP) | `ble_gateway.py:818-825` | **High** | High | Trivial | Low |
| 3 | Service data reconstructed with wrong AD type / UUID width in GPRP payload | `ble_message.py:79-88` | Medium | High (wrong per spec), Medium (that it matters downstream) | Low-Medium | Medium |
| 4 | Hardware service-UUID filter breaks whitelist OR semantics | `scan_backends.py:399-421` + `ble_gateway.py:208-255` | Medium | Medium | Low | Low-Medium |
| 5 | paho-mqtt v1 fallback is dead code (`AttributeError` not caught) + v1-incompatible `on_disconnect` signature | `ble_gateway.py:361-400` | Medium | High | Low | Low |
| 6 | Whitelist entries not normalized (UUID case, MAC format) | `ble_gateway.py:577-585`, `229-252` | Medium | High | Low | Low |
| 7 | `auto` backend falls back to `hci_coded` on *any* BlueZ error | `scan_backends.py:133-140, 707-710` | Low-Medium | Medium | Low | Medium |
| 8 | Races between recv thread and `stop()` / recovery in `HciCodedScanBackend` | `scan_backends.py:621-698` | Low | High | Low | Low |
| 9 | New `hci_coded.phy` key not validated in `load_config` | `ble_gateway.py:889-944` (vs `scan_backends.py:459-465`) | Low | High | Trivial | Low |
| 10 | `random_address` config validation only hex-checks the first octet | `ble_gateway.py:911-930` | Low | High | Trivial | Low |
| 11 | Publish stats misleading (queued counted as published; queued-on-outage counted as errors) | `ble_gateway.py:444-469, 729-741` | Low | High | Low | Low |
| 12 | CONNACK error table uses MQTT v3 codes under the VERSION2 callback API | `ble_gateway.py:341-359` | Low | Medium | Trivial | Low |
| 13 | `rssi_range_test` capture window overshoots; rate divided by nominal duration | `tools/rssi_range_test.py:114-126, 156` | Low | High | Trivial | Low |
| 14 | `--analyze` crashes on groups whose `rate_hz` cells are all empty (migrated CSVs) | `tools/rssi_range_test.py:257-277` | Low | Medium | Trivial | Low |
| 15 | `requirements.txt` and `pyproject.toml` pin different dependency ranges | `requirements.txt`, `pyproject.toml` | Low | High | Trivial | Low |

---

## 1. `bluetooth_adapter` is silently ignored by the BlueZ backend

- **Severity:** High &nbsp;|&nbsp; **Confidence it's a bug:** High (verified against installed bleak 3.0.2) &nbsp;|&nbsp; **Fix complexity:** Trivial &nbsp;|&nbsp; **Regression risk:** Low

**Problem.** `BlueZScanBackend.start()` puts the configured adapter *inside* the BlueZ-specific args when `bleak.args.bluez` is importable:

```python
if bluez_available:
    bluez_args["adapter"] = adapter          # scan_backends.py:395
...
scanner_kwargs["bluez"] = BlueZScannerArgs(**bluez_args)
```

In bleak, `BlueZScannerArgs` is a `TypedDict` containing only `filters` and `or_patterns`; the adapter is a **top-level** `BleakScanner(..., adapter=...)` kwarg (bleak's BlueZ scanner reads it via `kwargs.get("adapter", ...)`). Because a `TypedDict` is a plain dict at runtime, the bogus `adapter` key raises no error — bleak's scanner just never sees it.

**Bad behavior.** On any multi-adapter host (the shipped `config.json` sets `"bluetooth_adapter": "hci1"`), the `bluez` and `auto` backends scan the *default* adapter (hci0) instead of the configured one, with a log line falsely claiming `Using Bluetooth adapter: hci1`. In `auto` mode this can also defeat the probe/fallback logic: hci0 may deliver adverts, so the gateway never falls back to `hci_coded` on the intended dongle. Note the `hci_coded` backend is unaffected (it uses `resolve_dev_id`), which is why the current production config masks this.

**Fix.** Always pass the adapter as a top-level scanner kwarg and never into `BlueZScannerArgs`:

```python
if adapter:
    scanner_kwargs["adapter"] = adapter
```

Drop the `bluez_available` branch for the adapter (keep it only for `filters`). Add a unit test that constructs the backend with a fake `BleakScanner` and asserts `adapter` arrives as a top-level kwarg.

## 2. Shutdown flush publishes the wrong message format

- **Severity:** High &nbsp;|&nbsp; **Confidence:** High &nbsp;|&nbsp; **Fix complexity:** Trivial &nbsp;|&nbsp; **Regression risk:** Low

**Problem.** The normal publish path wraps every advert in the GPRP CSV-in-JSON envelope (`to_gprp_format`, `ble_gateway.py:718`). The shutdown path in `run()`'s `finally` block publishes raw `to_json()` instead:

```python
json_payload = ble_message.to_json()     # ble_gateway.py:822
self.publisher.publish(json_payload)
```

**Bad behavior.** Whatever was buffered at shutdown (up to `max_buffer_size` messages — with the shipped 2 s interval there is almost always something in the buffer) is published in a completely different schema: a flat JSON object with hex fields instead of `{"data": ["$GPRP,..."], "mqtt_topic": ...}`. A cloud consumer parsing GPRP will reject or misprocess these; per-shutdown data is effectively lost, intermittently and only at restarts, which makes it hard to notice. Also note that at this point the topic is the same, so the malformed records land in the production pipeline.

**Fix.** Reuse the normal path: call `to_gprp_format(gateway_mac=self.gateway_mac, topic=self.topic)` in the shutdown flush (or better, factor the publish loop out of `_flush_buffer` and call it with `force=True`).

## 3. Service data reconstructed with wrong AD type / UUID width

- **Severity:** Medium &nbsp;|&nbsp; **Confidence:** High that the bytes violate the BLE spec; Medium that a downstream decoder consumes service data &nbsp;|&nbsp; **Fix complexity:** Low-Medium &nbsp;|&nbsp; **Regression risk:** Medium (changes published bytes; a downstream consumer may have adapted to the current encoding)

**Problem.** `BLEMessage._reconstruct_advertising_data()` emits every `service_data` entry as AD type `0x16` (Service Data — **16-bit** UUID) but writes the full UUID key as bytes (`ble_message.py:79-88`). Both backends produce service-data keys as *128-bit* UUID strings (bleak canonicalizes; `parse_ad_structures` uses `_format_uuid_short`/`_format_uuid128`), so the emitted structure is `len | 0x16 | <16 UUID bytes LE> | data`. A spec-compliant parser of type 0x16 reads only 2 UUID bytes and treats the remaining 14 UUID bytes as payload. Relatedly, all service UUIDs from the UUID-list fields are re-emitted as 128-bit "incomplete" lists (type 0x06) even when the original advert used 16/32-bit lists — semantically equivalent but not byte-faithful.

**Bad behavior.** Any consumer of the GPRP `advertising_hex` that decodes service data gets a garbage UUID (`0xfb34` — a fragment of the Bluetooth Base UUID) and a payload prefixed with 14 junk bytes. If the V3 decryption path only needs local name + manufacturer data (as the comments suggest), this is currently dormant — but it corrupts the record for any other analytics.

**Fix.** When reconstructing service data, detect Base-UUID form (`0000xxxx-0000-1000-8000-00805f9b34fb`): emit `0x16` with the 2-byte UUID (or `0x20` with 4 bytes for 32-bit values); otherwise emit type `0x21` (128-bit service data) with the 16-byte UUID. Mirror the same logic for the UUID list (types 0x03/0x05/0x06-0x07). Coordinate with the cloud consumer before changing published bytes.

## 4. Hardware service-UUID filter breaks the whitelist OR semantics

- **Severity:** Medium &nbsp;|&nbsp; **Confidence:** Medium (HW filtering is documented as intentional; the interaction with other whitelists looks unintended) &nbsp;|&nbsp; **Fix complexity:** Low &nbsp;|&nbsp; **Regression risk:** Low-Medium

**Problem.** `PayloadFilter.should_accept` accepts a device if it matches **any** configured whitelist (MAC *or* name *or* manufacturer ID *or* service UUID). But `BlueZScanBackend.start()` also pushes `service_uuid_whitelist` down to BlueZ as a hardware discovery filter (`scan_backends.py:400-407`), which drops every advert not containing one of those UUIDs *before* the software filter runs.

**Bad behavior.** With both `service_uuid_whitelist` and e.g. `mac_whitelist` configured, a device that matches the MAC whitelist but doesn't advertise a whitelisted service UUID is silently never seen on the `bluez`/`auto` backends — while the `hci_coded` backend (no HW filter) *does* deliver it. Same config, different results per backend, and the OR contract in `PayloadFilter`'s docstring is violated.

**Fix.** Only pass `service_uuids` to `BleakScanner` when the service-UUID whitelist is the *only* whitelist configured; otherwise scan unfiltered and rely on `PayloadFilter`. Log which mode is in effect.

## 5. paho-mqtt v1 compatibility fallback can never work

- **Severity:** Medium (only when paho 1.x is installed — which `requirements.txt` permits) &nbsp;|&nbsp; **Confidence:** High &nbsp;|&nbsp; **Fix complexity:** Low &nbsp;|&nbsp; **Regression risk:** Low

**Problem.** Two independent defects in the "older paho" path:

1. `ble_gateway.py:392-400` — on paho 1.x, `mqtt.CallbackAPIVersion` raises **`AttributeError`** (the attribute doesn't exist), but the fallback only catches **`TypeError`**. The exception escapes to the broad handler in `connect()`, which returns `False`.
2. `_on_disconnect(self, client, userdata, flags, rc, properties=None)` (`ble_gateway.py:361`) — paho v1 invokes `on_disconnect(client, userdata, rc)`, so even if the client were constructed, every disconnect callback would raise `TypeError` inside paho's thread.

**Bad behavior.** With paho-mqtt 1.x (allowed by `requirements.txt`'s `paho-mqtt>=1.6.0`), the gateway always exits at startup with the misleading message `Failed to connect to MQTT broker: module 'paho.mqtt.client' has no attribute 'CallbackAPIVersion'`.

**Fix.** Either (a) commit to paho ≥ 2: change `requirements.txt` to `paho-mqtt>=2.1.0,<3.0` (matching `pyproject.toml`) and delete the fallback and its dead branch; or (b) keep the fallback and catch `(TypeError, AttributeError)` plus provide version-appropriate callback signatures. Option (a) is simpler and is what the project already declares in `pyproject.toml`.

## 6. Whitelist entries are not normalized (UUID case, MAC format)

- **Severity:** Medium (silent filtering of wanted devices) &nbsp;|&nbsp; **Confidence:** High &nbsp;|&nbsp; **Fix complexity:** Low &nbsp;|&nbsp; **Regression risk:** Low

**Problem.**
- Service UUIDs are compared case-sensitively (`ble_gateway.py:249-252`). Both backends emit lowercase canonical UUIDs, so a config entry like `"0000EFF0-EFF0-1212-1515-EEFFD1024132"` never matches. The same unnormalized list is passed to bleak's hardware filter.
- MAC whitelist entries are uppercased but not canonicalized (`ble_gateway.py:578`): an entry without colons (`"AABBCCDDEEFF"`) never matches `msg.device_address` (`AA:BB:CC:DD:EE:FF`).

**Bad behavior.** A user whose whitelist entries differ only in case/format silently receives *no* data from those devices (and since `should_accept` returns `False` when any whitelist is configured, the devices are dropped, not passed through). No warning is emitted.

**Fix.** Normalize at config load: lowercase UUIDs (and optionally expand 4/8-char short forms to Base-UUID form), and canonicalize MACs to colon-separated uppercase. Add validation errors for entries that don't look like UUIDs/MACs at all.

## 7. `auto` backend falls back to raw HCI on *any* BlueZ error

- **Severity:** Low-Medium &nbsp;|&nbsp; **Confidence:** Medium (deliberately broad, but with harmful side effects) &nbsp;|&nbsp; **Fix complexity:** Low &nbsp;|&nbsp; **Regression risk:** Medium (narrowing the markers may miss a real multi-PHY rejection string)

**Problem.** `_MULTIPHY_REJECTION_MARKERS` (`scan_backends.py:133-140`) includes `"org.bluez.error"` and `"not supported"`, which match essentially *every* BlueZ/D-Bus failure — permission denied, adapter missing, discovery already in progress from another app, etc. — not just the multi-PHY rejection the fallback is designed for.

**Bad behavior.** A transient or unrelated BlueZ error (e.g. the gateway user lacking D-Bus permissions) silently switches the gateway to `hci_coded`, which **downs the adapter and takes exclusive HCI_CHANNEL_USER control**, kicking bluetoothd (and any other BLE consumer on the host) off the radio. The real root cause is hidden behind a warning line.

**Fix.** Narrow the marker list to the strings actually observed for the multi-PHY rejection (keep `"not supported"`/`"inprogress"` if those are the observed ones, drop the catch-all `"org.bluez.error"`), and log the full original exception at WARNING before falling back so the root cause stays visible.

## 8. Thread-lifecycle races in `HciCodedScanBackend`

- **Severity:** Low (shutdown-time noise; rare edge cases) &nbsp;|&nbsp; **Confidence:** High that the races exist; Low that they bite often &nbsp;|&nbsp; **Fix complexity:** Low &nbsp;|&nbsp; **Regression risk:** Low

**Problem.**
- `stop()` → `_shutdown_socket()` (executor thread) sets `self._sock = None` while `_recv_loop` (recv thread) may be about to call `self._sock.recv(1024)` (`scan_backends.py:625`). `AttributeError` on `None` is not caught (only `socket.timeout`/`OSError` are), so the recv thread dies with an unhandled-exception traceback.
- `stop()` joins the recv thread with a 3 s timeout (`scan_backends.py:694`), but if the thread is inside `_open_and_configure()` recovery it can block ~10 s (bind retries + five 2 s command timeouts). The leaked daemon thread can then re-bind the user channel *after* `stop()` has re-powered the adapter, leaving the adapter in the wrong state.

**Bad behavior.** Traceback spam on shutdown; in the recovery-during-shutdown window, the adapter can be left down / detached from bluetoothd even though `power_on_at_shutdown=True`.

**Fix.** In `_recv_loop`, copy the socket to a local (`sock = self._sock`) and skip/exit if `None`; catch `AttributeError` alongside `OSError`. In `_reopen_with_backoff`/`_open_and_configure`, check `self._stop.is_set()` between retries and before installing a new socket; after a successful reopen, if `_stop` is set, immediately close and power the adapter back on.

## 9. New `hci_coded.phy` key is not validated by `load_config`

- **Severity:** Low &nbsp;|&nbsp; **Confidence:** High &nbsp;|&nbsp; **Fix complexity:** Trivial &nbsp;|&nbsp; **Regression risk:** Low

**Problem.** The (uncommitted) PHY-selection feature validates `phy` only in the `HciCodedScanBackend` constructor (`scan_backends.py:459-465`), while every other `hci_coded.*` key is validated up front in `load_config` (`ble_gateway.py:889-944`).

**Bad behavior.** A typo like `"phy": "2m"` passes config validation, the gateway starts, connects to MQTT, and only then dies in the scanning loop with a generic "Error in scanning loop" — instead of a clear config error at startup like its sibling keys. (In `rssi_range_test.py` the constructor check is fine because the tool sets the value itself.)

**Fix.** Add to `load_config`: `if "phy" in hci and str(hci["phy"]).lower() not in ("1m", "coded"): raise ValueError(...)`, mirroring the existing style, plus a test alongside `test_load_config_rejects_bad_scan_type`.

## 10. `random_address` validation only hex-checks the first octet

- **Severity:** Low &nbsp;|&nbsp; **Confidence:** High &nbsp;|&nbsp; **Fix complexity:** Trivial &nbsp;|&nbsp; **Regression risk:** Low

**Problem.** `load_config` (`ble_gateway.py:911-930`) checks each colon group is 2 chars and parses only `parts[0]` as hex. `"C0:ZZ:11:22:33:44"` passes validation, then `bytes.fromhex` blows up later in `_random_addr_le()` (`scan_backends.py:504`) during scan startup.

**Bad behavior.** Same failure mode as #9: a config error surfaces as a runtime scanning-loop error after MQTT connect instead of a clear message at load time.

**Fix.** Validate all six octets: `int(p, 16) for p in parts` inside the existing `try`, keeping the static-random top-bits check on the first octet.

## 11. Publish statistics are misleading

- **Severity:** Low (observability only — no data loss) &nbsp;|&nbsp; **Confidence:** High &nbsp;|&nbsp; **Fix complexity:** Low &nbsp;|&nbsp; **Regression risk:** Low

**Problem.** `MQTTPublisher.publish` (`ble_gateway.py:444-469`) treats paho's synchronous return code as delivery status. With QoS 1: (a) `MQTT_ERR_SUCCESS` only means *queued*, yet it increments `messages_published`; (b) while disconnected, paho still queues the message for redelivery on reconnect but returns `MQTT_ERR_NO_CONN`, so the gateway increments `publish_errors` and logs a failure for a message that will actually be delivered.

**Bad behavior.** During a broker outage the logs/final stats claim publish errors (suggesting data loss) while messages are in fact delivered after reconnect; conversely `messages_published` overcounts if the process dies before the queue drains.

**Fix.** Count confirmed deliveries in `_on_publish` (mid-based), and treat `MQTT_ERR_NO_CONN` as "queued while offline" (separate counter + warning) rather than an error. Optionally set `client.max_queued_messages_set()` to bound the offline queue on the 1 GB Pi.

## 12. CONNACK error table wrong for the VERSION2 callback API

- **Severity:** Low (wrong log message only) &nbsp;|&nbsp; **Confidence:** Medium &nbsp;|&nbsp; **Fix complexity:** Trivial &nbsp;|&nbsp; **Regression risk:** Low

**Problem.** `_on_connect` (`ble_gateway.py:341-359`) maps failure codes 1–5 (MQTT v3 CONNACK codes), but under `CallbackAPIVersion.VERSION2` paho delivers a `ReasonCode` with MQTT5-style values (e.g. 135 = Not authorized, 134 = Bad user name or password) even for v3.1.1 brokers.

**Bad behavior.** Real failures (bad credentials, not authorized — the common AWS IoT policy mistakes) log as `Unknown error code: Not authorized` instead of the intended friendly message. Diagnosis, not function, is affected.

**Fix.** Log `str(rc)` directly — paho's `ReasonCode.__str__` already produces a human-readable name — and drop the hand-rolled table (or key it by the ReasonCode names).

## 13. `rssi_range_test` capture window overshoots and skews `rate_hz`

- **Severity:** Low (measurement bias in a tool built to compare measurements) &nbsp;|&nbsp; **Confidence:** High &nbsp;|&nbsp; **Fix complexity:** Trivial &nbsp;|&nbsp; **Regression risk:** Low

**Problem.** `capture()` sleeps in 2 s slices and exits the loop only after `time.monotonic() < end` fails (`tools/rssi_range_test.py:118-122`), so the actual capture window is `secs` + up to 2 s (plus backend stop latency), while `summarize()` divides the count by the nominal `args.secs` (line 156).

**Bad behavior.** `rate_hz` (documented as "the single best field metric" for A/B mounting comparisons) is inflated by a variable ~0–2 %, adding noise exactly where the tool is comparing small differences; `pdr` can exceed its cap-source similarly.

**Fix.** Record `start = time.monotonic()` before `backend.start()` returns adverts and compute `elapsed` when the loop exits; divide by `elapsed` (and use it for `expected` in the PDR calculation). Sleeping `min(2.0, end - now)` also tightens the window.

## 14. `--analyze` crashes on groups with no `rate_hz` values

- **Severity:** Low &nbsp;|&nbsp; **Confidence:** Medium (requires a migrated/hand-edited CSV) &nbsp;|&nbsp; **Fix complexity:** Trivial &nbsp;|&nbsp; **Regression risk:** Low

**Problem.** `append_csv` deliberately migrates older CSVs by back-filling missing columns with `""` (`tools/rssi_range_test.py:194-208`). In `analyze()`, `agg()` returns `None` when every value in a group is empty, and the table print does `f"{rate:>9.2f}"` / `f"{rssi:>7.0f}"` unconditionally (line 275-277).

**Bad behavior.** `TypeError: unsupported format string passed to NoneType` — the whole analyze run dies because one legacy group lacks a metric the migration itself created as empty.

**Fix.** Format via a helper that renders `None` as `"-"` (the code already does this for `pdr` on the same line).

## 15. `requirements.txt` and `pyproject.toml` disagree on dependency ranges

- **Severity:** Low (but it is what arms finding #5) &nbsp;|&nbsp; **Confidence:** High &nbsp;|&nbsp; **Fix complexity:** Trivial &nbsp;|&nbsp; **Regression risk:** Low

**Problem.** `requirements.txt` says `bleak>=1.1.1`, `paho-mqtt>=1.6.0`; `pyproject.toml` says `bleak>=0.20.0`, `paho-mqtt>=2.1.0,<3.0`. Also `requires-python = ">=3.7"` is untrue: the code uses `X | Y` union syntax nowhere, but bleak ≥ 1.x itself requires ≥ 3.9, and the repo is developed/tested on 3.13/3.14.

**Bad behavior.** Depending on the install path, a user can get paho 1.6 (gateway won't start — see #5) or a bleak far older than anything this code was written against.

**Fix.** Make both files declare the same ranges (recommend `bleak>=1.1.1`, `paho-mqtt>=2.1.0,<3.0`), raise `requires-python` to what CI actually tests, and prune the 3.7/3.8 classifiers.

---

## Non-findings worth recording

Things checked and found **correct**, to save the next auditor time:

- `parse_ext_adv_report` field offsets match the Core Spec LE Extended Advertising Report layout (RSSI at report offset 13, Data_Length at 23).
- `HCIDEVUP`/`HCIDEVDOWN` ioctl values (0x400448C9/CA) are correct `_IOW('H', 201/202, int)` encodings.
- The HCI command packet framing, Command Complete/Status opcode matching, and the extended-scan parameter block (single PHY triplet matching the single `Scanning_PHYs` bit) are correct.
- bleak converts plain-Python filter values (e.g. `DuplicateData: bool`) to D-Bus `Variant`s itself — passing a bool is fine.
- The default static random address `DE:DE:DE:DE:DE:C0` has the required top-two bits set (0xDE & 0xC0 == 0xC0).
- `certificates/` and `config.json` are gitignored and not committed, despite living in the working tree.
- `signal.signal`-based shutdown works with `asyncio.run` here (handler runs on the main thread; the 0.1–1 s loop tick observes `running=False`).
