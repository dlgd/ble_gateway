#!/usr/bin/env python3
"""BLE range / signal-quality measurement tool.

Drives the *same* scan backend the gateway uses (``create_scan_backend`` from
``scan_backends.py``), records every received advert's RSSI for a fixed window,
and reports the metrics that actually determine usable range:

* ``rate_hz``     — adverts received per second. The single best field metric:
                    needs no baseline and is directly comparable between two
                    mountings at the same spot. A cable that delivers a higher
                    rate is recovering adverts the direct-plug dongle lost.
* ``median_rssi`` — signal strength, robust to the multipath swings that make
                    any single sample meaningless.
* ``iqr_rssi``    — spread of RSSI (link stability).
* ``pdr``         — packet delivery ratio, if you pass the sensor's advertising
                    interval via ``--interval`` (received / expected).

Two modes:

  Capture one (location x mounting) cell and append a CSV row. Both labels are
  free text: --mounting names the cable under test, --distance names the spot
  (a room name, or a distance like '10m'):
      sudo venv/bin/python tools/rssi_range_test.py \
          --mounting cable-3m --distance kitchen --secs 120 --interval 1.2 \
          --out range_data.csv

  Compare LE Coded PHY vs 1M PHY at one spot (two back-to-back windows). The
  molleau advertises both, but its 1M set uses a rotating RPA, so filter by
  --name (stable across PHYs), NOT the Coded --target MAC:
      sudo venv/bin/python tools/rssi_range_test.py \
          --mounting cable --distance kitchen --phy both --name Molleau \
          --secs 120 --interval 0.2 --config range_test_coded.config.json \
          --out phy_data.csv

  Aggregate a CSV across repeats and compare each mounting to a baseline:
      venv/bin/python tools/rssi_range_test.py --analyze range_data.csv \
          --baseline direct

Notes
-----
* The ``hci_coded`` backend takes exclusive control of the adapter, so capture
  needs CAP_NET_RAW + CAP_NET_ADMIN — run it with ``sudo``.
* This controller can't scan 1M and Coded at once, so ``--phy both`` runs them
  sequentially (Coded then 1M) and writes one CSV row per PHY. In --analyze,
  when >1 PHY is present, each mounting×PHY becomes its own comparison series
  (e.g. 'cable/coded' vs 'cable/1m').
* Capture forces ``duplicate_filtering=False`` so *every* advert is counted
  (otherwise the controller collapses repeats and rate/PDR are meaningless).
  Override with ``--keep-config-dedup`` if you really want config behaviour.
* Config (backend, adapter, service-UUID whitelist) is loaded from
  ``config.json`` so you measure the exact link the gateway uses. The whitelist
  keeps you from counting your neighbour's beacons.
"""

import argparse
import asyncio
import csv
import json
import logging
import os
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scan_backends import create_scan_backend  # noqa: E402

CSV_FIELDS = [
    "timestamp_iso",
    "mounting",
    "location",
    "phy",
    "secs",
    "target",
    "count",
    "rate_hz",
    "median_rssi",
    "iqr_rssi",
    "min_rssi",
    "max_rssi",
    "est_interval_s",
    "pdr",
    "note",
]


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------
async def capture(args, config, logger):
    """Scan for ``args.secs`` and return per-advert records keyed by address."""
    records = defaultdict(list)  # address -> [(monotonic_ts, rssi), ...]

    def on_advert(msg):
        # Filter by name when given (works across PHYs — the 1M set advertises
        # from a rotating RPA, so its MAC differs from the Coded identity MAC),
        # else by MAC, else accept all.
        if args.name:
            if args.name.lower() not in (msg.device_name or "").lower():
                return
        elif args.target and msg.device_address.upper() != args.target.upper():
            return
        records[msg.device_address.upper()].append((time.monotonic(), msg.rssi))

    phy = (config.get("hci_coded") or {}).get("phy", "?")
    backend = create_scan_backend(config, on_advert, logger, loop=asyncio.get_event_loop())
    logger.info(
        f"Scanning {args.secs}s  (mounting={args.mounting}, "
        f"location={args.distance}, phy={phy})"
    )
    await backend.start()
    start = time.monotonic()
    try:
        # Sleep in small slices so a Ctrl-C is responsive and we can show a
        # live heartbeat of the running count. Cap the final slice at the
        # remaining time so the window doesn't overshoot args.secs by up to 2s
        # (which would inflate rate_hz — the metric this tool exists to compare).
        end = start + args.secs
        while True:
            now = time.monotonic()
            if now >= end:
                break
            await asyncio.sleep(min(2.0, end - now))
            seen = sum(len(v) for v in records.values())
            print(f"  ... {seen} adverts", end="\r", flush=True)
    finally:
        elapsed = time.monotonic() - start
        await backend.stop()
        print()
    return records, elapsed


def summarize(records, args, phy, elapsed):
    """Pick the target device and compute its stats."""
    if not records:
        return None, "no adverts received"

    # Show everything we saw so the operator can confirm the right device.
    ranked = sorted(records.items(), key=lambda kv: len(kv[1]), reverse=True)
    print("Devices seen this run:")
    for addr, samples in ranked:
        rssis = [r for _, r in samples]
        print(
            f"  {addr}  count={len(samples):5d}  "
            f"median_rssi={int(statistics.median(rssis))} dBm"
        )

    # With --name we already filtered to the device, so the busiest address is
    # it (for 1M that's the current RPA). With --target, pin to that MAC.
    addr, samples = ranked[0]
    if args.target and not args.name:
        addr = args.target.upper()
        samples = records.get(addr, [])
        if not samples:
            return None, f"target {addr} never seen"

    rssis = [r for _, r in samples]
    times = sorted(t for t, _ in samples)
    count = len(samples)
    # Divide by the measured window, not the nominal args.secs, so backend
    # start/stop latency and slice granularity don't skew the comparison.
    rate_hz = count / elapsed if elapsed > 0 else 0.0

    # Estimate the advertising interval from median inter-arrival (informational
    # — and a sanity check against the --interval you passed).
    deltas = [b - a for a, b in zip(times, times[1:])]
    est_interval = statistics.median(deltas) if deltas else None

    if len(rssis) >= 4:
        q = statistics.quantiles(rssis, n=4)
        iqr = q[2] - q[0]
    else:
        iqr = 0.0

    pdr = None
    if args.interval:
        expected = elapsed / args.interval
        pdr = min(1.0, count / expected) if expected else None

    row = {
        "timestamp_iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mounting": args.mounting,
        "location": args.distance,
        "phy": phy,
        "secs": args.secs,
        "target": addr,
        "count": count,
        "rate_hz": round(rate_hz, 3),
        "median_rssi": int(statistics.median(rssis)),
        "iqr_rssi": round(iqr, 1),
        "min_rssi": min(rssis),
        "max_rssi": max(rssis),
        "est_interval_s": round(est_interval, 3) if est_interval else "",
        "pdr": round(pdr, 3) if pdr is not None else "",
        "note": args.note or "",
    }
    return row, None


def append_csv(path, row):
    # Seamlessly migrate an older CSV (e.g. one without the 'phy' column):
    # rewrite it with the current header, back-filling missing cells, so the
    # file stays consistent when new columns are added.
    if os.path.exists(path):
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            old_fields = reader.fieldnames or []
            old_rows = list(reader)
        if old_fields != CSV_FIELDS:
            with open(path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
                w.writeheader()
                for r in old_rows:
                    w.writerow({k: r.get(k, "") for k in CSV_FIELDS})
    exists = os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not exists:
            w.writeheader()
        w.writerow(row)


def print_row(row):
    print("\n=== Result ===")
    print(f"  mounting     : {row['mounting']}")
    print(f"  location     : {row['location']}")
    print(f"  phy          : {row['phy']}")
    print(f"  target       : {row['target']}")
    print(f"  adverts       : {row['count']}  over {row['secs']}s")
    print(f"  rate         : {row['rate_hz']} adv/s   <- compare this A/B")
    print(f"  median RSSI  : {row['median_rssi']} dBm  (IQR {row['iqr_rssi']}, "
          f"min {row['min_rssi']}, max {row['max_rssi']})")
    if row["est_interval_s"]:
        print(f"  est. interval: {row['est_interval_s']} s (sensor advertising period)")
    if row["pdr"] != "":
        print(f"  PDR          : {row['pdr']}  (received / expected)")


# ---------------------------------------------------------------------------
# Analyze
# ---------------------------------------------------------------------------
def analyze(path, baseline=None, plot_path=None):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("No data.")
        return

    # location / mounting / phy are free-text labels. When more than one PHY is
    # present, fold it into the series label (e.g. 'cable/coded' vs 'cable/1m')
    # so the comparison and plot treat each mounting×PHY as its own series.
    phys_present = {r.get("phy", "") for r in rows if r.get("phy", "")}
    multi_phy = len(phys_present) > 1

    def series_of(r):
        m, p = r["mounting"], r.get("phy", "")
        return f"{m}/{p}" if (multi_phy and p) else m

    groups = defaultdict(list)
    for r in rows:
        groups[(r["location"], series_of(r))].append(r)

    def agg(rs, field):
        vals = [float(r[field]) for r in rs if r.get(field) not in ("", None)]
        return statistics.mean(vals) if vals else None

    locations = _sorted_unique(loc for loc, _ in groups)
    mountings = _sorted_unique(m for _, m in groups)
    colname = "mtg/phy" if multi_phy else "mounting"
    lw = max(8, *(len(l) for l in locations))   # column width for labels
    mw = max(8, len(colname), *(len(m) for m in mountings))

    print(f"\n{'location':>{lw}} {colname:>{mw}} {'runs':>5} "
          f"{'rate_hz':>9} {'rssi':>7} {'pdr':>6}")
    print("-" * (lw + mw + 32))
    summary = {}
    for (loc, mounting), rs in sorted(groups.items(),
                                      key=lambda kv: (_loc_key(kv[0][0]), kv[0][1])):
        rate, rssi, pdr = agg(rs, "rate_hz"), agg(rs, "median_rssi"), agg(rs, "pdr")
        summary[(loc, mounting)] = (rate, rssi, pdr)
        print(f"{loc:>{lw}} {mounting:>{mw}} {len(rs):>5} "
              f"{rate:>9.2f} {rssi:>7.0f} "
              f"{(f'{pdr:.2f}' if pdr is not None else '-'):>6}")

    # Per-location comparison against a baseline series.
    base = baseline or ("direct" if "direct" in mountings else mountings[0])
    if base not in mountings:
        print(f"\nBaseline '{base}' not in data; skipping comparison.")
    elif len(mountings) > 1:
        others = [m for m in mountings if m != base]
        print(f"\nΔ vs baseline '{base}'  (positive = better than baseline)")
        head = f"{'location':>{lw}}"
        for m in others:
            head += f" | {m+' Δrate':>{mw+9}} {'Δrssi':>7}"
        print(head)
        print("-" * len(head))
        for loc in locations:
            b = summary.get((loc, base))
            line = f"{loc:>{lw}}"
            for m in others:
                o = summary.get((loc, m))
                if b and o and b[0] is not None and o[0] is not None:
                    drate = o[0] - b[0]
                    drssi = ((o[1] - b[1])
                             if (o[1] is not None and b[1] is not None) else None)
                    line += (f" | {drate:>+{mw+9}.2f} "
                             f"{(f'{drssi:+.1f}' if drssi is not None else '-'):>7}")
                else:
                    line += f" | {'-':>{mw+9}} {'-':>7}"
            print(line)

    if plot_path is not False:
        _plot(summary, locations, mountings,
              plot_path or (os.path.splitext(path)[0] + ".png"))


def _loc_key(loc):
    """Sort key: numeric if the location parses as a number, else the string."""
    try:
        return (0, float(loc))
    except (ValueError, TypeError):
        return (1, str(loc))


def _sorted_unique(values):
    return sorted(set(values), key=_loc_key)


def _plot(summary, locations, mountings, out_png):
    """Save rate and RSSI vs location for every mounting.

    If all locations are numeric (e.g. distances in metres) the x-axis is a
    sorted line chart; otherwise (room names) it's a categorical grouped bar
    chart so unordered labels read cleanly.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")  # headless: no display on the Pi
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n(matplotlib not installed — skipping plot. Install with: "
              "venv/bin/pip install matplotlib)")
        return

    numeric = all(_loc_key(l)[0] == 0 for l in locations)
    x = list(range(len(locations)))
    fig, (ax_rate, ax_rssi) = plt.subplots(1, 2, figsize=(11, 4.5))
    n = len(mountings)
    width = 0.8 / max(1, n)

    for i, mounting in enumerate(mountings):
        rates = [summary.get((l, mounting), (None,))[0] for l in locations]
        rssis = [summary.get((l, mounting), (None, None))[1] for l in locations]
        if numeric:
            xs = [float(l) for l in locations]
            ax_rate.plot(xs, rates, marker="o", label=mounting)
            ax_rssi.plot(xs, rssis, marker="o", label=mounting)
        else:
            offs = [xi + (i - (n - 1) / 2) * width for xi in x]
            ax_rate.bar(offs, [r or 0 for r in rates], width, label=mounting)
            ax_rssi.bar(offs, [r or 0 for r in rssis], width, label=mounting)

    xlabel = "distance" if numeric else "location"
    ax_rate.set(xlabel=xlabel, ylabel="rate (adv/s)",
                title="Advert rate vs " + xlabel)
    ax_rssi.set(xlabel=xlabel, ylabel="median RSSI (dBm)",
                title="Signal strength vs " + xlabel)
    for ax in (ax_rate, ax_rssi):
        if not numeric:
            ax.set_xticks(x)
            ax.set_xticklabels(locations, rotation=30, ha="right")
        ax.grid(True, axis="y", alpha=0.3)
        ax.legend()
    fig.tight_layout()
    fig.savefig(out_png, dpi=120)
    plt.close(fig)
    print(f"\nPlot saved to {out_png}")


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--analyze", metavar="CSV",
                    help="aggregate a results CSV and print comparison, then exit")
    ap.add_argument("--plot", metavar="PNG",
                    help="path for the analyze plot (default: CSV name with .png)")
    ap.add_argument("--no-plot", action="store_true",
                    help="skip plotting in --analyze mode")
    ap.add_argument("--mounting",
                    help="free-text label for the dongle mounting under test "
                         "(e.g. 'direct', 'cable-3m', 'cable-usb2-5m')")
    ap.add_argument("--distance",
                    help="free-text location label (e.g. a room name, or a "
                         "distance like '10m')")
    ap.add_argument("--baseline",
                    help="mounting to compare others against in --analyze "
                         "(default: 'direct' if present, else the first one)")
    ap.add_argument("--secs", type=int, default=120, help="scan window (default 120)")
    ap.add_argument("--interval", type=float,
                    help="sensor advertising interval in seconds (enables PDR)")
    ap.add_argument("--phy", choices=["coded", "1m", "both"], default="coded",
                    help="primary PHY to scan. 'both' runs two back-to-back "
                         "windows (Coded then 1M) and logs a row for each")
    ap.add_argument("--target", help="only count this device MAC. NOTE: the "
                    "molleau's 1M set uses a rotating RPA, so its MAC differs "
                    "from the Coded identity MAC — prefer --name for --phy both")
    ap.add_argument("--name", help="only count devices whose name contains this "
                    "string (e.g. 'Molleau'); works across both PHYs")
    ap.add_argument("--config", default="config.json", help="gateway config file")
    ap.add_argument("--out", default="range_data.csv", help="CSV to append to")
    ap.add_argument("--note", help="free-text note stored with the row")
    ap.add_argument("--keep-config-dedup", action="store_true",
                    help="do NOT force duplicate_filtering off")
    args = ap.parse_args()

    if args.analyze:
        analyze(args.analyze, baseline=args.baseline,
                plot_path=False if args.no_plot else args.plot)
        return

    if not args.mounting or not args.distance:
        ap.error("--mounting and --distance are required for capture")

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("rssi_range_test")

    with open(args.config) as f:
        config = json.load(f)
    if not args.keep_config_dedup:
        # Count every advert, not just payload-distinct ones.
        config["duplicate_filtering"] = False

    phys = ["coded", "1m"] if args.phy == "both" else [args.phy]
    if args.phy == "both" and not args.name:
        logger.warning("--phy both without --name: the 1M set uses a rotating "
                       "RPA, so --target won't match it. Use --name (e.g. "
                       "--name Molleau) for a fair cross-PHY comparison.")
    failures = 0
    for phy in phys:
        # Point the hci_coded backend at this PHY for the run.
        hc = dict(config.get("hci_coded") or {})
        hc["phy"] = phy
        config["hci_coded"] = hc

        records, elapsed = asyncio.run(capture(args, config, logger))
        row, err = summarize(records, args, phy, elapsed)
        if err:
            logger.error(f"[phy={phy}] {err}")
            failures += 1
            continue
        print_row(row)
        append_csv(args.out, row)
        print(f"\nAppended to {args.out}")

    if failures == len(phys):
        sys.exit(1)


if __name__ == "__main__":
    main()
