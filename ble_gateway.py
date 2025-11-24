#!/usr/bin/env python3
"""
Cloud-Agnostic Bluetooth Gateway
Captures Bluetooth Low Energy (BLE) advertisement packets and publishes them via MQTT.
Supports AWS IoT Core, Azure IoT Hub, HiveMQ, Mosquitto, and any MQTT broker.
"""

__version__ = "2.0.0"

import argparse
import asyncio
import json
import logging
import os
import platform
import signal
import ssl
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Union

try:
    from bleak import BleakScanner
    from bleak.backends.device import BLEDevice
    from bleak.backends.scanner import AdvertisementData
except ImportError:
    print("Error: bleak library not installed. Run: pip install bleak")
    sys.exit(1)

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("Error: paho-mqtt library not installed. Run: pip install paho-mqtt")
    sys.exit(1)


# ANSI color codes for cross-platform colored output
class Colors:
    """ANSI color codes for terminal output."""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


# Icons with colors for different log levels
ICON_SUCCESS = f"{Colors.GREEN}✓{Colors.RESET}"
ICON_ERROR = f"{Colors.RED}✗{Colors.RESET}"
ICON_WARNING = f"{Colors.YELLOW}⚠{Colors.RESET}"
ICON_INFO = f"{Colors.BLUE}ℹ{Colors.RESET}"
ICON_PUBLISH = f"{Colors.CYAN}{Colors.BOLD}⬆{Colors.RESET}"  # Larger upward arrow for publish
ICON_RECEIVE = f"{Colors.CYAN}⬇{Colors.RESET}"  # Downward arrow for receive


# Constants for configuration defaults
DEFAULT_PUBLISH_INTERVAL = 0.0
DEFAULT_MAX_BUFFER_SIZE = 100
DEFAULT_THROTTLE_CONTROL = True
DEFAULT_QOS = 1
DEFAULT_KEEPALIVE = 1200  # MQTT keepalive: 1200 seconds (20 minutes)
DEFAULT_PORT = 8883
DEFAULT_TOPIC = 'ble/gateway/data'
DEFAULT_CLIENT_ID = 'ble-gateway-001'
DEFAULT_LOG_LEVEL = 'WARNING'

# Connection timeouts
CONNECTION_TIMEOUT_SEC = 10
DISCONNECT_TIMEOUT_SEC = 5
STATS_LOG_INTERVAL_SEC = 10.0
FLUSH_CHECK_INTERVAL_IMMEDIATE = 0.1
FLUSH_CHECK_INTERVAL_BUFFERED = 1.0

# BLE packet structure constants
BLE_UUID_TYPE_INCOMPLETE_128 = 0x06
BLE_TYPE_MANUFACTURER_DATA = 0xFF
BLE_TYPE_SERVICE_DATA_16BIT = 0x16

# Validation limits
MAX_CLIENT_ID_LENGTH = 128
MAX_HOSTNAME_LENGTH = 20


@dataclass
class BLEMessage:
    """Structured BLE advertisement message."""
    timestamp_ms: int
    device_address: str
    device_name: Optional[str]
    rssi: int
    manufacturer_data: Dict[int, bytes]
    service_data: Dict[str, bytes]
    service_uuids: List[str]
    tx_power: Optional[int]

    def _reconstruct_advertising_data(self) -> bytes:
        """Reconstruct BLE advertising data from parsed components.

        Returns raw BLE advertising packet as bytes.
        """
        packet = bytearray()

        # Add service UUIDs (incomplete list of 128-bit UUIDs)
        if self.service_uuids:
            for uuid_str in self.service_uuids:
                # Remove hyphens and convert to bytes (little-endian for BLE)
                uuid_hex = uuid_str.replace('-', '')
                uuid_bytes = bytes.fromhex(uuid_hex)
                # Reverse for little-endian
                uuid_bytes_le = uuid_bytes[::-1]

                # Length = 1 (type) + 16 (UUID bytes)
                packet.append(17)
                packet.append(BLE_UUID_TYPE_INCOMPLETE_128)
                packet.extend(uuid_bytes_le)

        # Add manufacturer specific data
        for company_id, data in self.manufacturer_data.items():
            # Length = 1 (type) + 2 (company ID) + data length
            length = 1 + 2 + len(data)
            packet.append(length)
            packet.append(BLE_TYPE_MANUFACTURER_DATA)
            # Company ID in little-endian
            packet.append(company_id & 0xFF)
            packet.append((company_id >> 8) & 0xFF)
            packet.extend(data)

        # Add service data (16-bit UUID service data)
        for uuid_str, data in self.service_data.items():
            uuid_hex = uuid_str.replace('-', '')
            uuid_bytes = bytes.fromhex(uuid_hex)

            # Length = 1 (type) + UUID bytes + data length
            length = 1 + len(uuid_bytes) + len(data)
            packet.append(length)
            packet.append(BLE_TYPE_SERVICE_DATA_16BIT)
            packet.extend(uuid_bytes[::-1])  # Little-endian
            packet.extend(data)

        return bytes(packet)

    def to_gprp_format(self, gateway_mac: str, topic: str) -> str:
        """Convert to GPRP CSV format wrapped in JSON.

        Format: $GPRP,<gateway_mac>,<device_mac>,<rssi>,<ble_advertising_hex>,<timestamp>

        Args:
            gateway_mac: Gateway MAC address (12 hex chars, no separators)
            topic: MQTT topic name

        Returns:
            JSON string with data array and mqtt_topic
        """
        # Reconstruct raw advertising data
        advertising_hex = self._reconstruct_advertising_data().hex().upper()

        # Convert timestamp from ms to seconds with decimal
        timestamp_sec = self.timestamp_ms / 1000.0

        # Remove colons from device MAC address
        device_mac = self.device_address.replace(':', '').upper()

        # Build GPRP CSV line
        gprp_line = f"$GPRP,{gateway_mac},{device_mac},{self.rssi},{advertising_hex},{timestamp_sec:.3f}"

        # Wrap in JSON structure
        return json.dumps({
            "data": [gprp_line],
            "mqtt_topic": topic
        }, separators=(',', ':'))

    def to_json(self) -> str:
        """Convert to JSON string with hex-encoded bytes."""
        data = asdict(self)
        # Convert bytes to hex strings
        data['manufacturer_data'] = {
            str(k): v.hex() for k, v in self.manufacturer_data.items()
        }
        data['service_data'] = {
            k: v.hex() for k, v in self.service_data.items()
        }
        return json.dumps(data, separators=(',', ':'))


class MessageBuffer:
    """
    Buffers BLE messages and flushes based on publish interval or buffer size.

    When publish_interval_sec is 0, messages are sent immediately.
    When non-zero, messages are buffered and sent when:
    - The buffer is full (max_buffer_size), OR
    - The time interval is reached

    With throttle_control enabled, only the last record per device is kept.

    Uses __slots__ for memory efficiency on Raspberry Pi.
    """
    __slots__ = ('publish_interval_sec', 'max_buffer_size', 'throttle_control',
                 'buffer', 'last_flush_time')

    def __init__(
        self,
        publish_interval_sec: float = DEFAULT_PUBLISH_INTERVAL,
        max_buffer_size: int = DEFAULT_MAX_BUFFER_SIZE,
        throttle_control: bool = DEFAULT_THROTTLE_CONTROL
    ):
        self.publish_interval_sec = publish_interval_sec
        self.max_buffer_size = max_buffer_size
        self.throttle_control = throttle_control

        # Buffer stores messages by device address if throttle enabled, else list
        self.buffer: Union[Dict[str, BLEMessage], List[BLEMessage]]
        if throttle_control and publish_interval_sec > 0:
            # Keep last record per device (dict keyed by device address)
            self.buffer = {}
        else:
            # Keep all messages (list)
            self.buffer = []

        self.last_flush_time = time.time()

    def add_message(self, message: BLEMessage) -> None:
        """Add a message to the buffer."""
        if self.throttle_control and self.publish_interval_sec > 0:
            # Throttle mode: keep only last record per device
            self.buffer[message.device_address] = message
        else:
            # Non-throttle mode: keep all messages
            self.buffer.append(message)

    def should_flush(self) -> bool:
        """Check if buffer should be flushed."""
        # Immediate mode (interval = 0): always flush
        if self.publish_interval_sec == 0:
            return len(self.buffer) > 0

        # Check if buffer is full
        buffer_size = len(self.buffer)
        if buffer_size >= self.max_buffer_size:
            return True

        # Check if time interval reached
        current_time = time.time()
        if current_time - self.last_flush_time >= self.publish_interval_sec:
            return buffer_size > 0

        return False

    def get_messages(self) -> List[BLEMessage]:
        """Get all buffered messages and clear the buffer."""
        if self.throttle_control and self.publish_interval_sec > 0:
            # Return dict values as list
            messages = list(self.buffer.values())
            self.buffer = {}
        else:
            # Return list
            messages = self.buffer.copy()
            self.buffer = []

        self.last_flush_time = time.time()
        return messages

    def size(self) -> int:
        """Get current buffer size."""
        return len(self.buffer)


class PayloadFilter:
    """Filters BLE devices based on whitelist criteria.

    Uses __slots__ for memory efficiency on Raspberry Pi.
    """
    __slots__ = ('mac_whitelist', 'name_whitelist', 'manufacturer_id_whitelist',
                 'service_uuid_whitelist')

    def __init__(
        self,
        mac_whitelist: Optional[Set[str]] = None,
        name_whitelist: Optional[Set[str]] = None,
        manufacturer_id_whitelist: Optional[Set[int]] = None,
        service_uuid_whitelist: Optional[Set[str]] = None
    ):
        self.mac_whitelist = mac_whitelist
        self.name_whitelist = name_whitelist
        self.manufacturer_id_whitelist = manufacturer_id_whitelist
        self.service_uuid_whitelist = service_uuid_whitelist

    def should_accept(
        self,
        device: BLEDevice,
        advertisement: AdvertisementData
    ) -> bool:
        """Check if device matches any whitelist criteria."""
        # If no whitelists configured, accept all
        if not any([
            self.mac_whitelist,
            self.name_whitelist,
            self.manufacturer_id_whitelist,
            self.service_uuid_whitelist
        ]):
            return True

        # Check MAC address
        if self.mac_whitelist and device.address.upper() in self.mac_whitelist:
            return True

        # Check device name
        if self.name_whitelist and device.name and device.name in self.name_whitelist:
            return True

        # Check manufacturer IDs
        if self.manufacturer_id_whitelist and advertisement.manufacturer_data:
            if any(mid in self.manufacturer_id_whitelist
                   for mid in advertisement.manufacturer_data.keys()):
                return True

        # Check service UUIDs
        if self.service_uuid_whitelist and advertisement.service_uuids:
            if any(uuid in self.service_uuid_whitelist
                   for uuid in advertisement.service_uuids):
                return True

        return False


class MQTTPublisher:
    """Handles MQTT connection and publishing using paho-mqtt (cloud-agnostic)."""

    @staticmethod
    def _validate_cert_file(file_path: str, file_type: str) -> None:
        """Validate that a certificate file exists and is not empty."""
        # Support environment variable expansion
        expanded_path = os.path.expandvars(file_path)
        cert_file = Path(expanded_path)
        if not cert_file.exists():
            raise FileNotFoundError(f"{file_type} file not found: {expanded_path}")
        if cert_file.stat().st_size == 0:
            raise ValueError(f"{file_type} file is empty: {expanded_path}")

    def __init__(
        self,
        broker: str,
        port: int,
        client_id: str,
        topic: str,
        logger: logging.Logger,
        auth_type: str = "mtls",
        tls_config: Optional[Dict] = None,
        credentials: Optional[Dict] = None,
        qos: int = DEFAULT_QOS,
        keepalive: int = DEFAULT_KEEPALIVE
    ):
        self.broker = broker
        self.port = port
        self.client_id = client_id
        self.topic = topic
        self.logger = logger
        self.qos = qos
        self.keepalive = keepalive
        self.auth_type = auth_type

        self.connected = False
        self.client = None
        self.connection_event = asyncio.Event()

        # Configure authentication
        if auth_type == "mtls":
            self._configure_mtls(tls_config or {})
        elif auth_type == "userpass":
            self._configure_userpass(credentials or {})
        elif auth_type == "none":
            self.logger.info("No authentication configured (insecure)")
        else:
            raise ValueError(f"Unsupported auth_type: {auth_type}")

    def _configure_mtls(self, tls_config: Dict) -> None:
        """Configure mutual TLS authentication."""
        ca_certs = tls_config.get('ca_certs')
        certfile = tls_config.get('certfile')
        keyfile = tls_config.get('keyfile')

        if not all([ca_certs, certfile, keyfile]):
            raise ValueError("mtls auth requires ca_certs, certfile, and keyfile")

        # Validate certificate files
        self._validate_cert_file(ca_certs, "CA certificate")
        self._validate_cert_file(certfile, "Client certificate")
        self._validate_cert_file(keyfile, "Private key")

        # Expand environment variables and store paths
        self.ca_filepath = os.path.expandvars(ca_certs)
        self.cert_filepath = os.path.expandvars(certfile)
        self.key_filepath = os.path.expandvars(keyfile)

        self.logger.info("Configured mTLS authentication")

    def _configure_userpass(self, credentials: Dict) -> None:
        """Configure username/password authentication."""
        self.username = credentials.get('username')
        self.password = credentials.get('password')

        if not self.username:
            raise ValueError("userpass auth requires username")

        self.logger.info(f"Configured username/password authentication for user: {self.username}")

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        """Callback when connection is established."""
        if rc == 0:
            self.connected = True
            self.connection_event.set()
            self.logger.info(f"{ICON_SUCCESS} Successfully connected to MQTT broker: {self.broker}:{self.port}")
        else:
            self.connected = False
            error_messages = {
                1: "Connection refused - incorrect protocol version",
                2: "Connection refused - invalid client identifier",
                3: "Connection refused - server unavailable",
                4: "Connection refused - bad username or password",
                5: "Connection refused - not authorized"
            }
            error_msg = error_messages.get(rc, f"Unknown error code: {rc}")
            self.logger.error(f"{ICON_ERROR} Connection failed: {error_msg}")

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        """Callback when connection is lost."""
        self.connected = False
        self.connection_event.clear()

        # In paho-mqtt v2.0+, rc is a ReasonCode object; in v1.x it's an int
        # Convert to int for comparison
        try:
            rc_value = int(rc) if hasattr(rc, '__int__') else rc
        except (ValueError, TypeError):
            rc_value = -1

        if rc_value != 0:
            # Get human-readable error message
            rc_str = str(rc) if hasattr(rc, '__str__') else f"code {rc_value}"
            self.logger.warning(f"{ICON_WARNING} Unexpected disconnection (rc={rc_str}), will auto-reconnect")
        else:
            self.logger.info("Disconnected from MQTT broker")

    def _on_publish(self, client, userdata, mid, rc=None, properties=None):
        """Callback when message is published."""
        self.logger.debug(f"Message published successfully (mid={mid})")

    async def connect(self) -> bool:
        """Establish connection to MQTT broker."""
        try:
            self.logger.info(f"Connecting to MQTT broker: {self.broker}:{self.port}")

            # Create MQTT client (paho-mqtt v2.0+ uses CallbackAPIVersion)
            try:
                self.client = mqtt.Client(
                    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                    client_id=self.client_id,
                    clean_session=True
                )
            except TypeError:
                # Fallback for older paho-mqtt versions
                self.client = mqtt.Client(
                    client_id=self.client_id,
                    clean_session=True
                )

            # Set callbacks
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_publish = self._on_publish

            # Configure authentication
            if self.auth_type == "mtls":
                self.client.tls_set(
                    ca_certs=self.ca_filepath,
                    certfile=self.cert_filepath,
                    keyfile=self.key_filepath,
                    tls_version=ssl.PROTOCOL_TLSv1_2
                )
            elif self.auth_type == "userpass":
                self.client.username_pw_set(self.username, self.password)
                if self.port == 8883:
                    # Use TLS for secure connection
                    self.client.tls_set(tls_version=ssl.PROTOCOL_TLSv1_2)

            # Set keep-alive
            self.client._keepalive = self.keepalive

            # Connect (non-blocking)
            self.client.connect_async(self.broker, self.port, keepalive=self.keepalive)
            self.client.loop_start()

            # Wait for connection with timeout
            try:
                await asyncio.wait_for(
                    self.connection_event.wait(),
                    timeout=CONNECTION_TIMEOUT_SEC
                )
                return True
            except asyncio.TimeoutError:
                self.logger.error(f"{ICON_ERROR} Connection timeout after {CONNECTION_TIMEOUT_SEC}s")
                return False

        except Exception as e:
            self.logger.error(f"{ICON_ERROR} Failed to connect to MQTT broker: {e}")
            return False

    def publish(self, message: str) -> bool:
        """Publish message to MQTT topic."""
        try:
            if not self.client:
                self.logger.warning(f"{ICON_WARNING} No MQTT client, cannot publish")
                return False

            # Publish message (will queue if disconnected)
            result = self.client.publish(
                topic=self.topic,
                payload=message,
                qos=self.qos,
                retain=False
            )

            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                self.logger.debug(
                    f"MQTT publish queued - Topic: {self.topic}, "
                    f"QoS: {self.qos}, "
                    f"Payload length: {len(message)} bytes"
                )
                return True
            else:
                self.logger.error(f"{ICON_ERROR} Failed to publish: {result.rc}")
                return False

        except Exception as e:
            self.logger.error(f"{ICON_ERROR} Failed to publish message: {e}")
            return False

    def disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        if self.client:
            try:
                self.logger.info("Disconnecting from MQTT broker")
                self.client.disconnect()
                self.client.loop_stop()
                self.connected = False
            except Exception as e:
                self.logger.error(f"{ICON_ERROR} Error during disconnect: {e}")


def get_gateway_mac_address() -> str:
    """Get the MAC address of the gateway device.

    Returns:
        MAC address as uppercase hex string without separators (12 characters)
    """
    try:
        # Get MAC address from the node's UUID
        mac = uuid.getnode()
        # Convert to hex string with leading zeros (48 bits = 12 hex chars)
        mac_hex = f'{mac:012x}'.upper()
        return mac_hex
    except Exception:
        # Fallback to all zeros if unable to get MAC
        return '000000000000'


class BluetoothGateway:
    """Main Bluetooth Gateway application."""

    @staticmethod
    def _parse_manufacturer_ids(manufacturer_ids: list) -> Optional[Set[int]]:
        """
        Parse manufacturer IDs from config, supporting both decimal and hexadecimal formats.

        Args:
            manufacturer_ids: List of manufacturer IDs (can be int or hex string like "0x004C")

        Returns:
            Set of integer manufacturer IDs, or None if empty
        """
        if not manufacturer_ids:
            return None

        parsed_ids = set()
        for mid in manufacturer_ids:
            if isinstance(mid, str):
                # Parse hex string (e.g., "0x004C" or "004C")
                try:
                    parsed_ids.add(int(mid, 16))
                except ValueError:
                    raise ValueError(f"Invalid manufacturer ID format: {mid}. Use decimal (76) or hex ('0x004C')")
            elif isinstance(mid, int):
                # Already an integer
                parsed_ids.add(mid)
            else:
                raise ValueError(f"Invalid manufacturer ID type: {type(mid)}. Expected int or hex string")

        return parsed_ids

    def __init__(
        self,
        config: dict,
        logger: logging.Logger
    ):
        self.config = config
        self.logger = logger

        # Gateway MAC address for GPRP format
        # If not configured, use the actual MAC address of this device
        configured_mac = config.get('gateway_mac')
        if configured_mac:
            self.gateway_mac = configured_mac.replace(':', '').upper()
            self.logger.debug(f"Using configured gateway MAC: {self.gateway_mac}")
        else:
            self.gateway_mac = get_gateway_mac_address()
            self.logger.info(f"{ICON_INFO} Using device MAC address as gateway MAC: {self.gateway_mac}")

        # Initialize message buffer with publish interval and throttle control
        self.message_buffer = MessageBuffer(
            publish_interval_sec=config.get('publish_interval_sec', DEFAULT_PUBLISH_INTERVAL),
            max_buffer_size=config.get('max_buffer_size', DEFAULT_MAX_BUFFER_SIZE),
            throttle_control=config.get('throttle_control', DEFAULT_THROTTLE_CONTROL)
        )

        # Build payload filter
        self.payload_filter = PayloadFilter(
            mac_whitelist=set(map(str.upper, config.get('mac_whitelist', []))) or None,
            name_whitelist=set(config.get('name_whitelist', [])) or None,
            manufacturer_id_whitelist=self._parse_manufacturer_ids(config.get('manufacturer_id_whitelist', [])),
            service_uuid_whitelist=set(config.get('service_uuid_whitelist', [])) or None
        )

        # Initialize MQTT publisher
        mqtt_config = config.get('mqtt', {})

        # Extract MQTT settings
        broker = mqtt_config.get('broker')
        port = mqtt_config.get('port', DEFAULT_PORT)

        # Client ID: Read directly from config
        client_id = mqtt_config.get('client_id', DEFAULT_CLIENT_ID)
        logger.info(f"Using client_id: {client_id}")

        self.topic = mqtt_config.get('topic', DEFAULT_TOPIC)
        auth_type = mqtt_config.get('auth_type', 'mtls')
        qos = mqtt_config.get('qos', DEFAULT_QOS)
        keepalive = mqtt_config.get('keepalive', DEFAULT_KEEPALIVE)
        
        # Build TLS config for mTLS
        tls_config = None
        if auth_type == 'mtls':
            tls_config = {
                'ca_certs': mqtt_config.get('root_ca_path'),
                'certfile': mqtt_config.get('cert_path'),
                'keyfile': mqtt_config.get('key_path')
            }
        
        # Build credentials for userpass/token
        credentials = mqtt_config.get('credentials')
        
        self.publisher = MQTTPublisher(
            broker=broker,
            port=port,
            client_id=client_id,
            topic=self.topic,
            logger=logger,
            auth_type=auth_type,
            tls_config=tls_config,
            credentials=credentials,
            qos=qos,
            keepalive=keepalive
        )

        self.running = False
        self.stats = {
            'devices_seen': 0,
            'messages_filtered': 0,
            'messages_buffered': 0,
            'messages_published': 0,
            'publish_errors': 0,
            'buffer_flushes': 0
        }

        # Signal handlers for graceful shutdown
        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            self.logger.info(f"Received signal {signum}, shutting down gracefully...")
            self.running = False

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    def _create_ble_message(
        self,
        device: BLEDevice,
        advertisement: AdvertisementData
    ) -> BLEMessage:
        """Create BLEMessage from device and advertisement data.

        Uses UTC timestamp to ensure consistency across time zones.
        """
        # Get current UTC time in milliseconds
        utc_timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        return BLEMessage(
            timestamp_ms=utc_timestamp_ms,
            device_address=device.address,
            device_name=device.name,
            rssi=advertisement.rssi,
            manufacturer_data=dict(advertisement.manufacturer_data),
            service_data=dict(advertisement.service_data),
            service_uuids=list(advertisement.service_uuids),
            tx_power=advertisement.tx_power
        )

    def _detection_callback(
        self,
        device: BLEDevice,
        advertisement: AdvertisementData
    ):
        """
        Handle BLE device detection.

        Note: If service_uuids filter is configured in scanner, this callback
        only receives advertisements matching those UUIDs (hardware-level filtering).
        Additional filtering is applied here for MAC, name, and manufacturer ID.
        """
        # Apply payload filter first
        if not self.payload_filter.should_accept(device, advertisement):
            self.stats['messages_filtered'] += 1
            self.logger.debug(
                f"Filtered device: {device.address} ({device.name}) - "
                f"not in whitelist"
            )
            return

        self.stats['devices_seen'] += 1

        # Create BLE message and add to buffer
        try:
            ble_message = self._create_ble_message(device, advertisement)
            self.message_buffer.add_message(ble_message)
            self.stats['messages_buffered'] += 1

            # Debug log with full message details
            # Format manufacturer data as hex strings for readability
            mfg_data_str = {k: v.hex() for k, v in advertisement.manufacturer_data.items()} if advertisement.manufacturer_data else {}
            svc_data_str = {k: v.hex() for k, v in advertisement.service_data.items()} if advertisement.service_data else {}

            self.logger.debug(
                f"{ICON_RECEIVE} BLE message received - Device: {device.address} ({device.name}), "
                f"RSSI: {advertisement.rssi} dBm, "
                f"Manufacturer Data: {mfg_data_str}, "
                f"Service UUIDs: {advertisement.service_uuids}, "
                f"Service Data: {svc_data_str}, "
                f"TX Power: {advertisement.tx_power}, "
                f"Buffer size: {self.message_buffer.size()}"
            )

        except Exception as e:
            self.logger.error(f"{ICON_ERROR} Error processing device {device.address}: {e}")

    def _flush_buffer(self) -> None:
        """Flush buffered messages to MQTT broker."""
        if not self.message_buffer.should_flush():
            return

        messages = self.message_buffer.get_messages()
        if not messages:
            return

        self.stats['buffer_flushes'] += 1

        # Log flush event
        self.logger.info(
            f"{ICON_INFO} Flushing buffer: {len(messages)} message(s) "
            f"[Publish interval: {self.message_buffer.publish_interval_sec}s, "
            f"Throttle: {self.message_buffer.throttle_control}]"
        )

        # Publish each message in GPRP format
        for ble_message in messages:
            try:
                json_payload = ble_message.to_gprp_format(
                    gateway_mac=self.gateway_mac,
                    topic=self.topic
                )

                # Debug log: show message being published
                self.logger.debug(
                    f"{ICON_PUBLISH} Publishing to MQTT - Device: {ble_message.device_address}, "
                    f"Topic: {self.topic}, "
                    f"Payload: {json_payload}"
                )

                if self.publisher.publish(json_payload):
                    self.stats['messages_published'] += 1
                    self.logger.debug(
                        f"{ICON_SUCCESS} Successfully published message for device {ble_message.device_address}"
                    )
                else:
                    self.stats['publish_errors'] += 1
                    self.logger.debug(
                        f"{ICON_ERROR} Failed to publish message for device {ble_message.device_address}"
                    )
            except Exception as e:
                self.logger.error(f"{ICON_ERROR} Error publishing message: {e}")
                self.stats['publish_errors'] += 1

    async def run(self):
        """Run the gateway scanning loop."""
        self.logger.info("Starting Bluetooth Gateway")
        self.logger.info(
            f"Publish interval: {self.message_buffer.publish_interval_sec}s "
            f"(0=immediate, >0=buffered)"
        )
        self.logger.info(f"Throttle control: {self.message_buffer.throttle_control}")
        self.logger.info(f"Max buffer size: {self.message_buffer.max_buffer_size}")

        # Connect to MQTT broker
        if not await self.publisher.connect():
            self.logger.error(f"{ICON_ERROR} Failed to connect to MQTT broker. Exiting.")
            return

        self.running = True
        scanner = None

        try:
            # Build service UUID filter from whitelist (if configured)
            # This provides hardware-level filtering at the Bluetooth controller
            service_uuids = None
            if self.payload_filter.service_uuid_whitelist:
                service_uuids = list(self.payload_filter.service_uuid_whitelist)
                self.logger.info(
                    f"{ICON_INFO} Hardware-level filtering enabled for {len(service_uuids)} service UUID(s): "
                    f"{service_uuids}"
                )

            # Configure BlueZ-specific options (Linux/Raspberry Pi)
            bluez_args = {}
            if self.config.get('bluetooth_adapter'):
                bluez_args['adapter'] = self.config['bluetooth_adapter']
                self.logger.info(f"Using Bluetooth adapter: {self.config['bluetooth_adapter']}")

            # Configure scanner with hardware-level service UUID filtering
            scanner = BleakScanner(
                detection_callback=self._detection_callback,
                service_uuids=service_uuids,  # Hardware-level filtering
                scanning_mode="active",
                bluez=bluez_args if bluez_args else None
            )

            self.logger.info("Starting continuous BLE scanning...")
            self.logger.info("Scanning mode: active")
            await scanner.start()

            # Use a reasonable sleep interval for stats logging
            last_stats_time = time.time()

            # Determine flush check interval
            # If immediate mode (interval=0), check frequently for low latency
            # Otherwise, check every second (reasonable for buffered mode)
            flush_check_interval = (
                FLUSH_CHECK_INTERVAL_IMMEDIATE
                if self.message_buffer.publish_interval_sec == 0
                else FLUSH_CHECK_INTERVAL_BUFFERED
            )

            while self.running:
                # Flush buffer if needed
                self._flush_buffer()

                # Sleep for flush check interval
                await asyncio.sleep(flush_check_interval)

                # Only log stats periodically to reduce overhead
                current_time = time.time()
                if current_time - last_stats_time >= STATS_LOG_INTERVAL_SEC:
                    self.logger.debug(
                        f"Stats - Seen: {self.stats['devices_seen']}, "
                        f"Filtered: {self.stats['messages_filtered']}, "
                        f"Buffered: {self.stats['messages_buffered']}, "
                        f"Published: {self.stats['messages_published']}, "
                        f"Flushes: {self.stats['buffer_flushes']}, "
                        f"Errors: {self.stats['publish_errors']}, "
                        f"Current buffer: {self.message_buffer.size()}"
                    )
                    last_stats_time = current_time

        except KeyboardInterrupt:
            self.logger.info(f"{ICON_INFO} Received shutdown signal")
        except Exception as e:
            self.logger.error(f"{ICON_ERROR} Error in scanning loop: {e}", exc_info=True)
        finally:
            # Flush any remaining messages before shutdown
            self.logger.info("Flushing remaining messages before shutdown...")
            messages = self.message_buffer.get_messages()
            for ble_message in messages:
                try:
                    json_payload = ble_message.to_json()
                    self.publisher.publish(json_payload)
                except Exception as e:
                    self.logger.error(f"{ICON_ERROR} Error flushing message: {e}")

            if scanner:
                await scanner.stop()
            self.publisher.disconnect()
            self.logger.info("Gateway stopped")
            self.logger.info(f"Final stats: {self.stats}")


def load_config(config_path: str) -> dict:
    """Load and validate configuration from JSON file."""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except FileNotFoundError as e:
        raise FileNotFoundError(f"Configuration file not found: {config_path}") from e
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in configuration file: {e}") from e

    # Validate configuration values
    if 'publish_interval_sec' in config:
        interval = config['publish_interval_sec']
        if not isinstance(interval, (int, float)) or interval < 0:
            raise ValueError(
                f"publish_interval_sec must be a non-negative number, got: {interval}"
            )

    if 'max_buffer_size' in config:
        size = config['max_buffer_size']
        if not isinstance(size, int) or size < 1:
            raise ValueError(
                f"max_buffer_size must be a positive integer, got: {size}"
            )

    if 'throttle_control' in config:
        if not isinstance(config['throttle_control'], bool):
            raise ValueError(
                f"throttle_control must be a boolean, got: {config['throttle_control']}"
            )

    # Validate MQTT configuration
    mqtt_config = config.get('mqtt')
    if not mqtt_config:
        raise ValueError("Configuration must include 'mqtt' section")

    # Validate required MQTT fields
    if 'broker' not in mqtt_config:
        raise ValueError("MQTT configuration must include 'broker'")

    # Validate topic format
    topic = mqtt_config.get('topic', DEFAULT_TOPIC)
    if not topic or not isinstance(topic, str):
        raise ValueError(f"MQTT topic must be a non-empty string, got: {topic}")

    # Validate client_id format
    client_id = mqtt_config.get('client_id', DEFAULT_CLIENT_ID)
    if not client_id or not isinstance(client_id, str):
        raise ValueError(f"MQTT client_id must be a non-empty string, got: {client_id}")
    if len(client_id) > MAX_CLIENT_ID_LENGTH:
        raise ValueError(
            f"MQTT client_id too long (max {MAX_CLIENT_ID_LENGTH} chars): {len(client_id)} chars"
        )

    return config


def setup_logging(log_level: str = 'WARNING') -> logging.Logger:
    """Configure logging with appropriate level.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger('BLEGateway')

    # Convert string to logging level
    numeric_level = getattr(logging, log_level.upper(), logging.WARNING)
    logger.setLevel(numeric_level)

    # Console handler with formatting
    handler = logging.StreamHandler()
    handler.setLevel(numeric_level)

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)

    logger.addHandler(handler)

    return logger


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Bluetooth Gateway for MQTT',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with default config file (WARNING level)
  %(prog)s -c config.json

  # Run with INFO level logging
  %(prog)s -c config.json --log-level INFO

  # Run with DEBUG level logging
  %(prog)s -c config.json --log-level DEBUG

Configuration file format: See config.example.json
        """
    )

    parser.add_argument(
        '-c', '--config',
        required=True,
        help='Path to configuration JSON file'
    )

    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        default=DEFAULT_LOG_LEVEL,
        help=f'Set logging level (default: {DEFAULT_LOG_LEVEL})'
    )

    parser.add_argument(
        '--publish-interval',
        type=float,
        help='Override publish interval in seconds (0=immediate, >0=buffered)'
    )

    parser.add_argument(
        '--no-throttle',
        action='store_true',
        help='Disable throttle control (keep all records instead of last per device)'
    )

    parser.add_argument(
        '--buffer-size',
        type=int,
        help='Override maximum buffer size'
    )

    args = parser.parse_args()

    # Setup logging
    logger = setup_logging(log_level=args.log_level)

    try:
        # Load configuration
        logger.info(f"Loading configuration from: {args.config}")
        config = load_config(args.config)

        # Apply command-line overrides
        if args.publish_interval is not None:
            config['publish_interval_sec'] = args.publish_interval
        if args.no_throttle:
            config['throttle_control'] = False
        if args.buffer_size:
            config['max_buffer_size'] = args.buffer_size

        # Create and run gateway
        gateway = BluetoothGateway(config, logger)

        # Run async event loop
        import asyncio
        asyncio.run(gateway.run())

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=(args.log_level == 'DEBUG'))
        sys.exit(1)


if __name__ == '__main__':
    main()
