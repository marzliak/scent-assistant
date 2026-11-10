# Scent Master BLEWIFI: offline protocol research

**Status: research only; this does not add Home Assistant device support.**

**Observed:** November 10, 2026. Package identities below are pinned specimens,
not a claim about every current store rollout or firmware.

Related to issue #52. This investigation is limited to static package analysis
and synthetic offline tests, not HA installation, BLE scan/connection, device
commands, cloud login/binding, reset or firmware validation. In particular, this
is not a proposed fix consisting of a name prefix or a guessed default PIN.

## Artifacts and evidence level

| Inspected candidate | Identity and origin | Verification limit |
|---|---|---|
| Scent Master Pro | `com.xxiot.bx.scent`, 1.0.43 / 14300, Android artifact linked by the Scent Master Pro distribution landing (`xxiot.tech`; operator not established) | Local v1/v2/v3 signature verification (with v1 META-INF warnings) and ZIP verification; not direct Play/iOS byte equivalence |
| Original Scent Master | `cn.czyugang.ic.aromatherapymanager`, 1.4.12 / 46, third-party mirror XAPK | Base identity and signatures of all 20 APKs (base included) verified under one key; split-dependent base, not a standalone installer |

Pro APK SHA-256: `62267ac42c03fb64e5d31233ffc6c830241174f0137cac7c3a1644e030929c92`.
Original base APK SHA-256: `506879d5b8358194039fc298c63e801bb737768a50dd9968391216bfd0e51af6`.
Their signing certificates are different. Neither common branding nor a download
redirect proves wire compatibility. The reporter's installed iOS version and
actual firmware/GATT layout remain unconfirmed.

Distribution references: [Pro landing](https://www.xxiot.tech/xfgj_pro_download/app_download.html),
[Google Play Pro listing](https://play.google.com/store/apps/details?id=com.xxiot.bx.scent),
[Apple Pro listing](https://apps.apple.com/us/app/scent-master-pro/id6499073832),
[original mirror listing](https://apkpure.net/scent-master/cn.czyugang.ic.aromatherapymanager/download).
The legacy manual-disclosed download endpoint currently redirects to Pro;
this is not evidence that the original APK was obtained from that endpoint.
No proprietary APKs, decompiled source or raw device identifiers are redistributed here.

## What the pinned Pro code establishes

The relevant source is the packaged WeChat/SaaA mini-app, not the bundled
Skyline Flutter SDK. Static anchors are mini-app modules 29/37 in
`appservice.app.js`, module 368 in `page_ble/chunk_1.appservice.js`, and module 376
in `page_ble/chunk_0.appservice.js`. Composite `app-service.js` views repeat
those modules and are not independent corroboration.

- The local scan uses substring matches for `BXXXJ-` or `YGZK-XXJ`; connection
  then selects a distinct `-BLEWIFI-` path. `BXXXJ-BLEWIFI-U` satisfies these
  code gates, but suffix `-U` does not establish a firmware or subtype.
- This path selects service `FEB3`, notify `FED6`, write `FED5`, all in the
  Bluetooth base UUID, and requests **write without response**. Other local
  families use the shared `FFE0/FFE1/FFE2` tuple. These are code facts, not the
  reporter's measured GATT properties. Wi-Fi setup reuses UUIDs but is a separate path.
- The entered PIN is compared locally with advertisement-derived data before
  the traced connection; no PIN/login frame is demonstrated on that path.
  When the advertisement's four PIN bytes decode to an empty string after NUL
  removal, the vendor substitutes `9999`; the reference reproduces this local
  fallback. It is a source-derived value, not a trial password or verified
  factory setting, and is not sent to a device.
  This does not establish firmware authentication or justify credential trials.
- TX query: `55 10 command 00 checksum`. Setter:
  `55 10 command 05 payload_length payload checksum`. The checksum is the
  unsigned sum of bytes after `55`, excluding the checksum itself, modulo 256.
- Reached non-music BLEWIFI initialization queries are `F1`, `F2` and `DB`.
  The vendor page also writes local clock values and fixed `07=01` on opening;
  opening its control page is therefore **not read-only**.
- F1 supplies schedule 1 plus raw fan and an uninterpreted `power_raw` value.
  F2 has four consumed 10-byte records for schedules 2–5, not five records.
  Unmapped bytes remain opaque; `power_raw` is not a demonstrated global-power bit.

## Critical limit: global power is not established

The local page's `totalSwitchOpen()` emits fixed `07=01`. A matching local
**global-OFF** action has not been established. The true on/off pair found in
the network page uses cloud transport, so it must not be copied into BLE by analogy.

On the Pro local path, `0x11` enables **schedule 1** (`0x10 + schedule number` for
all five schedule toggles). Do not reinterpret it as global power merely because
a different device family uses similar framing. Changing schedules to simulate
power-off would also change the user's program and is not this investigation's fix.

A bounded original-Android cross-check independently finds
`CommandLaunchMotor.generateCommand()` assembling command 7 / mode 5 with fixed
payload `01`, and `CommandModeSwitch.generateCommand()` selecting `modeType + 16`.
These reinforce the specific caution; they are not an exhaustive old-app UI audit
or proof of firmware/iOS equivalence.

## Reference implementation and tests

`tests/scent_master_reference.py` is an independently written stdlib-only
reference. It contains **no transport, network client, app execution, automatic
initialization, Home Assistant import or global-OFF API**. It only returns
bytes or decoded data to its caller.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -X dev -W error::ResourceWarning -m unittest discover -s tests -t . -v
```

The reference tests use **synthetic/code-derived vectors, never captures**.
They check literal query/setter bytes, checksum overflow, signed-byte conversion,
all F2 records/fields, family/subtype gates, malformed input and privacy of the
default advertisement representation. Existing Scent Tech tests remain separate
regression coverage; neither suite is a device test or a real HA/Recorder test.

Intentional defensive differences: require complete advertisement fields,
exact four-digit PIN comparisons and explicit non-music subtype 00/01;
reject unsupported inputs and short semantic bodies. Duration builders enforce
wire widths, not every firmware's accepted UI menu. GBK decoding is a stdlib
reference, not a copied vendor character table.

RX is **one complete notification callback**, not a byte stream. Header/checksum
and known semantic fields are checked, but RX metadata at offsets `3:5` is opaque.
Full length semantics, fragmentation/coalescing, acknowledgements, persistence,
units and actual actuation remain unverified. Review reproduced a checksum-valid
concatenation accepted by this decoder: callers must not use it as a production
stream framer or assume that checksum validation isolates one message. A
checksum-valid response is not proof that an actuator changed. Unknown fields
are not fabricated.

PIN, serial and nickname are hidden from the advertisement's default `repr`,
but raw advertisements, attributes, `asdict()` or payloads can still contain
sensitive information. Do not log or post them. No universal anonymity is claimed.

## Smallest missing evidence

1. Exact installed iOS app link/version, or a cropped app-about view without
   account/device details. A historic display name or migrating QR is insufficient.
2. Sanitized target GATT service/characteristic UUIDs and properties. Do not post
   complete advertisements: the traced app reads PIN/serial data from them.
3. In a separately agreed stock-app test, correlate actual BLE writes/notifications
   and physical effect for the desired global-power operation. Distinguish automatic
   clock/enable writes from the user action; do not guess an OFF packet, reset,
   provision, bind or try passwords.

Until then this remains a research artifact, not supported-device discovery or
permission to send the generated bytes to a device.
