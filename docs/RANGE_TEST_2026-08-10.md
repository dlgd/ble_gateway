# BLE Range Test — Dongle & Mounting Comparison

**Date:** 2026-08-10
**Data:** `10082026_data.csv` (15 runs, 120 s each) on `molleau-gateway-athena-001`
**Tool:** `tools/rssi_range_test.py`, `hci_coded` backend, passive scan at 100 % duty cycle
**Sensor:** single Molleaumetre, `D1:11:C2:E2:F5:31`, advertising every ~206 ms
**Locations:** `table` (close, line-of-sight), `wc`, `sdb` (both non-line-of-sight)

## Summary

| # | Finding | Evidence | Confidence |
|---|---------|----------|------------|
| 1 | The April Brother dongle outperforms the Nordic dongle by **+17 dB** | RSSI −55 vs −72 at `table`; PDR 0.645 vs 0.02 at `wc` | **High** — corroborated by PDR, not RSSI alone |
| 2 | The USB extension cable **helps** at range; earlier "cable is bad" result was wrong | 4 of 4 range-limited cells favour the cable, up to 7.5× PDR | **High** — within-dongle A/B, back-to-back |
| 3 | Both effects share one root cause: **antenna environment**, not radio silicon | Identical nRF52840 SoC in both dongles | Medium-High |
| 4 | Coded PHY still wins at the edge, but 1M is now viable mid-range | `sdb`: 0.473 vs 0.182; `wc`: 0.645 vs 0.562 | High |

**Recommended production configuration: April Brother dongle + USB extension cable (elevated, clear of the Pi) + Coded PHY.**

## Reading the numbers: PDR ceilings at 0.90, not 1.00

The four `table` runs land on PDR **0.898 / 0.895 / 0.898 / 0.902** — a ceiling, not a coincidence.
The cause is a units mismatch: the runs passed `--interval 0.2`, but `est_interval_s` shows the
sensor actually advertises every **0.206 s**. PDR is computed as `received / (elapsed / 0.2)`, so a
flawless link scores ≈0.90.

**Every PDR in this document should be read against 0.90 = perfect.** The "% of ceiling" columns
below do that normalisation.

## Hardware under test

| | April Brother nRF52840 Dongle | Nordic nRF52840 Dongle (PCA10059) |
|---|---|---|
| Link | [store.aprbrother.com](https://store.aprbrother.com/product/usb-dongle-nrf52840) | [nordicsemi.com](https://www.nordicsemi.com/Products/Development-hardware/nRF52840-Dongle) |
| SoC | nRF52840 | nRF52840 |
| Max TX power | +8 dBm (SoC spec) | +8 dBm (SoC spec) |
| Antenna | **"Onboard external antenna"** (per vendor page) | Not stated on product page; PCA10059 is a **PCB trace antenna** design |
| Intended role | Deployment / sniffing dongle | Dev-kit companion for nRF Connect for Desktop |
| Label in CSV | `usb2_april_brother_dongle` | `usb2_nrf52840_legacy` |

**The radio silicon is identical.** Same SoC, same nominal TX power, same protocol stack. So the
17 dB gap cannot come from the transceiver — it is antenna design and RF layout. Nordic positions
the PCA10059 as a desktop development companion, not a deployment gateway radio; its compact PCB
trace antenna sits directly at the USB connector, where the host's ground plane and chassis detune
and shadow it. An antenna on a short lead, clear of the host, avoids most of that.

Note that antenna *gain* alone would explain only ~3–5 dB (a PCB trace antenna is roughly −2 to
0 dBi, a small external whip ~+2 dBi). The remaining ~12 dB is best explained by
detuning/shadowing avoidance — which is exactly the same mechanism as Finding 2, and why the two
findings reinforce each other.

## Finding 1 — April Brother dongle: +17 dB over the Nordic dongle

| Location | PHY | Nordic (legacy) | April Brother | Delta |
|---|---|---|---|---|
| table | coded | −72 dBm, PDR 0.852 (95 %) | −55 dBm, PDR 0.898 (100 %) | **+17 dB** |
| table | 1m | −72 dBm, PDR 0.428 (48 %) | −55 dBm, PDR 0.895 (100 %) | **+17 dB, 2.1× PDR** |
| wc | coded | −89 dBm, PDR **0.020** (2 %) | −82 dBm, PDR **0.645** (72 %) | **+7 dB, 32× PDR** |
| wc | 1m | *not tested* | −82 dBm, PDR 0.562 (63 %) | — |
| sdb | coded | *not tested* | −89 dBm, PDR 0.473 (53 %) | — |
| sdb | 1m | *not tested* | −83 dBm, PDR 0.182 (20 %) | — |

17 dB is roughly a **7× increase in free-space range**. The `wc` row shows what that buys at the
edge: the Nordic dongle received **12 adverts in 120 s**, with `est_interval_s` of 6.98 s — about
34 advertising periods between successful receptions, i.e. effectively dead. The April Brother
held a usable 0.645 at the same spot.

**Why this wasn't caught earlier.** At `table` the Nordic dongle's Coded PDR (0.852) still looked
almost fine despite −72 dBm — Coded PHY's ~12 dB processing gain was masking the weak front end.
Add `wc`'s extra path loss and it falls straight off the sensitivity cliff to 0.02. This is the
classic pattern for a link that is sensitivity-limited rather than merely lossy, and it explains
why the legacy dongle passed close-range testing and then failed in real rooms.

**Attribution is clean.** The 17 dB could in principle be a mounting artifact rather than a dongle
difference. It isn't: the cable-vs-no-cable control at `table` (Finding 2) shows **−55 dBm either
way** for the April Brother, so mounting is irrelevant at that location. The 17 dB is the dongle.
Cross-vendor RSSI calibration offsets are a theoretical confound, but the PDR collapse at `wc`
(0.02 vs 0.645) is real packet loss and cannot be a reporting artifact.

## Finding 2 — The USB extension cable helps (earlier conclusion reversed)

Same April Brother dongle, cable vs. direct-plug, back-to-back in one session:

| Location | PHY | With cable | No cable | Delta |
|---|---|---|---|---|
| table | coded | 0.898 (100 %) | 0.898 (100 %) | 0.000 — both at ceiling |
| table | 1m | 0.895 (100 %) | 0.902 (100 %) | −0.007 — both at ceiling |
| **wc** | **coded** | **0.645 (72 %)** | **0.257 (29 %)** | **+0.39 → 2.5×**, +6 dB |
| **wc** | **1m** | **0.562 (63 %)** | **0.075 (8 %)** | **+0.49 → 7.5×**, +4 dB |
| sdb | coded | 0.473 (53 %) | 0.408 (45 %) | +0.07 |
| **sdb** | **1m** | **0.182 (20 %)** | **0.047 (5 %)** | **+0.14 → 3.9×**, +3 dB |

This is the signature of a genuinely beneficial mounting: **neutral at close range**, where both
configurations saturate the 0.90 ceiling and there is no headroom to show a difference, and
**strongly positive wherever the link is budget-limited** — 4 of 4 range-limited cells favour the
cable.

This **reverses the conclusion from the July `phy_data.csv` run**, which appeared to show the cable
hurting (`salle_a_manger` coded: 0.27 with cable vs 0.89 direct). That comparison was confounded —
it compared different mountings without controlling dongle position or orientation, at one run per
cell. The present test is a within-dongle A/B run back-to-back, and is the one to trust.

**The cable is not defective.** The Amazon Basics USB 3.0 A male→female 1 m extension is
appropriate here: the dongle is a USB 2.0 device so no SuperSpeed signalling (and no USB-3
broadband noise) runs through it, 1 m is well within the 5 m USB 2.0 limit, and USB 3.0-rated
cables are typically better shielded than 2.0 ones.

## Finding 3 — Coded PHY still wins at the edge; 1M is now viable mid-range

With the April Brother + cable, 1M PHY is genuinely usable at moderate range for the first time:

| Location | Coded | 1M | Verdict |
|---|---|---|---|
| table | 0.898 (100 %) | 0.895 (100 %) | Identical — both saturated |
| wc | 0.645 (72 %) | 0.562 (63 %) | Coded ahead, but 1M usable |
| sdb | 0.473 (53 %) | 0.182 (20 %) | **Coded decisively ahead** |

**Keep `hci_coded` in production.** It costs nothing and still owns the margin at the edge. The
change is that the link is no longer so fragile that Coded PHY is the only thing holding it
together — the hardware upgrade has absorbed that role.

## Raw data

`--interval 0.2`, `--secs 120`, target `D1:11:C2:E2:F5:31`, all runs 2026-08-10.

| Mounting | Location | PHY | Count | Rate (adv/s) | RSSI | IQR | Min | Max | est_int (s) | PDR | % ceiling |
|---|---|---|---|---|---|---|---|---|---|---|---|
| april_brother (cable) | table | coded | 539 | 4.492 | −55 | 2.0 | −60 | −52 | 0.206 | 0.898 | 100 % |
| april_brother (cable) | table | 1m | 537 | 4.475 | −55 | 2.0 | −60 | −52 | 0.206 | 0.895 | 100 % |
| april_brother (cable) | wc | coded | 387 | 3.225 | −82 | 3.0 | −99 | −80 | 0.207 | 0.645 | 72 % |
| april_brother (cable) | wc | 1m | 337 | 2.808 | −82 | 1.0 | −89 | −81 | 0.208 | 0.562 | 63 % |
| april_brother (cable) | sdb | coded | 284 | 2.367 | −89 | 10.0 | −99 | −81 | 0.403 | 0.473 | 53 % |
| april_brother (cable) | sdb | 1m | 109 | 0.908 | −83 | 1.0 | −89 | −82 | 0.828 | 0.182 | 20 % |
| nrf52840_legacy | table | coded | 511 | 4.258 | −72 | 6.0 | −79 | −64 | 0.206 | 0.852 | 95 % |
| nrf52840_legacy | table | 1m | 257 | 2.142 | −72 | 5.0 | −79 | −65 | 0.409 | 0.428 | 48 % |
| nrf52840_legacy | wc | coded | 12 | 0.100 | −89 | 4.8 | −93 | −84 | 6.981 | 0.020 | 2 % |
| april_brother (no cable) | table | coded | 539 | 4.492 | −55 | 4.0 | −61 | −52 | 0.205 | 0.898 | 100 % |
| april_brother (no cable) | table | 1m | 541 | 4.508 | −56 | 5.0 | −62 | −53 | 0.206 | 0.902 | 100 % |
| april_brother (no cable) | wc | coded | 154 | 1.283 | −88 | 5.0 | −100 | −85 | 0.622 | 0.257 | 29 % |
| april_brother (no cable) | wc | 1m | 45 | 0.375 | −86 | 2.0 | −90 | −85 | 1.536 | 0.075 | 8 % |
| april_brother (no cable) | sdb | coded | 245 | 2.042 | −89 | 3.0 | −98 | −84 | 0.409 | 0.408 | 45 % |
| april_brother (no cable) | sdb | 1m | 28 | 0.233 | −86 | 1.8 | −89 | −84 | 2.668 | 0.047 | 5 % |

`est_interval_s` divided by the sensor's true 0.206 s period gives the average number of
advertising slots per successful reception — a compact loss diagnostic. The legacy dongle's 6.98 s
at `wc` means ~34 slots per reception.

## Caveats

- **One run per cell.** The headline effects (17 dB, 32×, 4-of-4 consistent direction) are far
  beyond plausible noise, but the smaller `sdb/coded` cable gap (+0.07) is **not** significant on
  its own and needs repeats.
- **Mounting labels confirmed by the operator** (2026-08-10): `usb2_april_brother_dongle` is the
  **with-cable** series, `usb2_no_cable_april_brother_dongle` the direct-plug one. Finding 2 rests
  on this and it is not an inference.
- **The legacy dongle's cable status is not encoded in its label**, and its test set is incomplete
  (no `sdb`, no `wc/1m`) — presumably abandoned once it was clearly outclassed. Completing it has
  little value.
- **`table` saturates** at the 0.90 ceiling and discriminates nothing. Future A/B tests should use
  range-limited positions only.
- **New location labels.** `table` / `wc` / `sdb` are not the July room set
  (`salon` / `salle_a_manger` / `chambre_coco` / `chambre_maman`), so this run is not directly
  comparable to `phy_data.csv`.
- **Antenna attribution is inference.** The vendor page states "onboard external antenna" for the
  April Brother; the Nordic page does not state its antenna type. The PCB-trace attribution for the
  PCA10059 comes from general knowledge of that board, not from a cited datasheet.

## Next steps

**Re-run the original rooms with April Brother + cable + Coded.** This is the high-value test.
`chambre_maman` measured PDR **0.04** in July with the legacy dongle; a +17 dB improvement exceeds
the entire margin it was missing, so that room may now be serviceable — which would change the
deployment plan from "relocate the gateway or buy a second one" to "done".

```bash
for room in salon salle_a_manger chambre_coco chambre_maman; do
  for i in 1 2 3; do
    sudo venv/bin/python tools/rssi_range_test.py \
      --mounting ab_dongle_cable --distance "$room" --phy coded \
      --secs 120 --interval 0.2 --note "run$i" --out rooms_ab.csv
  done
done
venv/bin/python tools/rssi_range_test.py --analyze rooms_ab.csv --baseline ab_dongle_cable
```

Three repeats give real error bars; Coded-only keeps it to ~6 min per room per repeat.

**Also worth doing:**

1. **Pass `--interval 0.206`** in future runs so PDR is calibrated to 1.00 and directly readable.
2. **Keep the dongle on a USB 2.0 port.** The July data showed 0.89 vs 0.45 PDR between the USB 2.0
   and USB 3.0 ports at `salle_a_manger` — consistent with USB 3.0 SuperSpeed broadband noise in
   the 2.4 GHz band.
3. **Elevate the cable-mounted dongle** (~1.5–2 m, clear of walls and metal, antenna vertical).
   Given that antenna environment is the dominant variable in both findings, this is likely the
   largest remaining free gain.
4. **Silence the Pi's onboard 2.4 GHz radios** — `hci0` is UP and idle (`sudo hciconfig hci0 down`);
   prefer 5 GHz or Ethernet for the host.
