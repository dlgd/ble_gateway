#!/usr/bin/env python3
"""Live hardware test for the hci_coded scan backend.

Drives the real HciCodedScanBackend (the same code the gateway uses) against the
dongle and prints what it receives on LE Coded PHY. Needs CAP_NET_RAW +
CAP_NET_ADMIN, so run it with sudo:

    sudo venv/bin/python tools/hci_live_test.py --dev-id 1 --secs 40

It brings the adapter down (HCIDEVDOWN ioctl) and takes exclusive control while
running, then brings it back up at exit.
"""

import argparse
import asyncio
import logging
import sys
import time
from collections import Counter

sys.path.insert(0, ".")

from scan_backends import HciCodedScanBackend  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev-id", type=int, default=1, help="HCI index (hci1 -> 1)")
    ap.add_argument("--secs", type=int, default=40, help="scan duration")
    ap.add_argument(
        "--scan-type", choices=["passive", "active"], default="passive"
    )
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    log = logging.getLogger("hci_live_test")

    stats = Counter()
    names = Counter()
    last = {"t": time.time()}

    def on_advert(msg):
        stats["total"] += 1
        if msg.device_name:
            names[msg.device_name] += 1
            if "molleau" in msg.device_name.lower():
                stats["molleau"] += 1
        now = time.time()
        if now - last["t"] >= 5:
            last["t"] = now
            top = ", ".join(f"{n}({c})" for n, c in names.most_common(6))
            log.info(
                f"... reports={stats['total']} molleau={stats['molleau']} | {top}"
            )

    cfg = {
        "bluetooth_adapter": f"hci{args.dev_id}",
        "hci_coded": {"scan_type": args.scan_type, "power_on_at_shutdown": True},
    }

    async def run():
        backend = HciCodedScanBackend(cfg, on_advert, log)
        log.info(
            f"Starting hci_coded backend on hci{args.dev_id} "
            f"({args.scan_type}, Coded PHY only) for {args.secs}s ..."
        )
        await backend.start()
        try:
            await asyncio.sleep(args.secs)
        finally:
            log.info("Stopping backend ...")
            await backend.stop()

    asyncio.run(run())

    print("\n===== RESULT =====")
    print(f"total ext-adv reports : {stats['total']}")
    print(f"MOLLEAU reports       : {stats['molleau']}")
    if names:
        print("named devices seen    :")
        for n, c in names.most_common(15):
            print(f"   {c:5d}  {n}")
    if stats["molleau"] > 0:
        print("\nOK: meter received on Coded PHY via the new backend.")
    else:
        print("\nNo molleau adverts seen — check the meter is advertising on Coded.")


if __name__ == "__main__":
    main()
