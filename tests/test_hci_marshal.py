"""Verify the HCI recv loop marshals adverts onto the event-loop thread."""

import asyncio
import logging
import socket
import threading

from helpers import ad_name, build_ext_adv_report

from scan_backends import HciCodedScanBackend


class FakeSock:
    """Yields canned packets, then raises socket.timeout so the loop polls _stop."""

    def __init__(self, packets):
        self._packets = list(packets)

    def settimeout(self, _t):
        pass

    def recv(self, _n):
        if self._packets:
            return self._packets.pop(0)
        raise socket.timeout()

    def close(self):
        pass


def test_advert_dispatched_on_loop_thread():
    loop = asyncio.new_event_loop()
    loop_thread_ident = {}
    received = []
    done = threading.Event()

    def on_advert(msg):
        # Records the thread the callback ran on.
        received.append((threading.get_ident(), msg))
        done.set()

    # Run the event loop in its own thread.
    def run_loop():
        loop_thread_ident["id"] = threading.get_ident()
        loop.run_forever()

    t = threading.Thread(target=run_loop)
    t.start()
    # Wait until the loop thread id is recorded.
    while "id" not in loop_thread_ident:
        pass

    backend = HciCodedScanBackend({}, on_advert, logging.getLogger("test"), loop=loop)
    pkt = build_ext_adv_report("AA:BB:CC:DD:EE:FF", -55, ad_name("molleau_469430"))
    backend._sock = FakeSock([pkt])

    recv_thread = threading.Thread(target=backend._recv_loop, name="recv")
    recv_thread.start()

    assert done.wait(timeout=5), "advert was never dispatched"
    backend._stop.set()
    recv_thread.join(timeout=3)

    loop.call_soon_threadsafe(loop.stop)
    t.join(timeout=3)
    loop.close()

    assert len(received) == 1
    cb_thread_ident, msg = received[0]
    # The callback must have executed on the event-loop thread, NOT the recv thread.
    assert cb_thread_ident == loop_thread_ident["id"]
    assert cb_thread_ident != recv_thread.ident
    assert msg.device_name == "molleau_469430"
