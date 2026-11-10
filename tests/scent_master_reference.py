"""Independent, strictly offline BLEWIFI reference codec.

Proof: static packaged mini-app in Scent Master Pro 1.0.43 only. No captures.
This module performs no I/O and imports no network, BLE, subprocess or app code.
All notification inputs are complete callback values, never a byte stream.
See docs/research/scent-master-blewifi.md for source anchors and limitations.
"""
from dataclasses import dataclass, field
from typing import Iterable

SERVICE_UUID = "0000FEB3-0000-1000-8000-00805F9B34FB"
NOTIFY_UUID = "0000FED6-0000-1000-8000-00805F9B34FB"
WRITE_UUID = "0000FED5-0000-1000-8000-00805F9B34FB"
WRITE_WITH_RESPONSE = False


class ProtocolError(ValueError):
    """Invalid or unsupported offline input, not a device error."""


def octets(values: Iterable[int]) -> bytes:
    """Normalize signed-byte representations without accepting wider integers."""
    result = []
    for value in values:
        if type(value) is not int or not -128 <= value <= 255:
            raise ProtocolError("expected signed or unsigned octets")
        result.append(value & 0xFF)
    return bytes(result)


def _range(value: int, low: int, high: int, label: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ProtocolError(f"invalid {label}")
    return value


def _bool(value: bool) -> bool:
    if type(value) is not bool:
        raise ProtocolError("expected boolean")
    return value


def _local_blewifi_name(name: str) -> None:
    # App discovery uses substring matches, not startswith. No suffix-U inference.
    if not isinstance(name, str) or "-BLEWIFI-" not in name or not (
        "BXXXJ-" in name or "YGZK-XXJ" in name
    ):
        raise ProtocolError("outside the statically traced local BLEWIFI route")


@dataclass(frozen=True)
class Advertisement:
    name: str
    serial_bytes: bytes = field(repr=False)
    nickname: str = field(repr=False)
    pin: str = field(repr=False)
    device_type: int
    setup_state_raw: int

    def pin_matches(self, supplied: object) -> bool:
        # Deliberately stricter than JS loose equality; never sends a PIN.
        return (isinstance(supplied, str) and len(supplied) == 4
                and all("0" <= ch <= "9" for ch in supplied)
                and supplied == self.pin)


def parse_advertisement(name: str, raw: Iterable[int]) -> Advertisement:
    _local_blewifi_name(name)
    data = octets(raw)
    # App's >22 guard is weaker than its subsequent slices; reject partial fields.
    if len(data) < 27:
        raise ProtocolError("incomplete BLEWIFI advertisement fields")
    try:
        nickname = data[7:23].replace(b"\0", b"").decode("gbk")
        pin = data[23:27].replace(b"\0", b"").decode("gbk") or "9999"
    except UnicodeDecodeError as error:
        raise ProtocolError("undecodable advertisement text") from error
    return Advertisement(name, data[1:7], nickname, pin,
                         data[27] if len(data) == 28 else 0, data[0])


def _tx(command: int, data: bytes | None = None) -> bytes:
    # READ: header, direction, command, 00. SET: ..., 05, data_length, data.
    prefix = bytes((0x55, 0x10, command, 0)) if data is None else bytes(
        (0x55, 0x10, command, 5, len(data))) + data
    return prefix + bytes((sum(prefix[1:]) & 0xFF,))


@dataclass(frozen=True)
class Schedule:
    slot: int
    enabled_raw: int | None
    weekday_mask: int
    start_hour: int
    start_minute: int
    stop_hour: int
    stop_minute: int
    work_seconds: int
    pause_seconds: int


def _schedule(slot: int, body: bytes, enabled: int | None) -> Schedule:
    if len(body) < 9:
        raise ProtocolError("incomplete nine-byte schedule")
    return Schedule(slot, enabled, body[0], body[1], body[2], body[3], body[4],
                    int.from_bytes(body[5:7], "big"),
                    int.from_bytes(body[7:9], "big"))


@dataclass(frozen=True)
class Notification:
    command: int
    metadata: bytes  # Offsets 3:5: meaning/length semantics NOT established.
    body: bytes
    schedules: tuple[Schedule, ...] = ()
    fan_raw: int | None = None
    power_raw: int | None = None  # syncBattery() naming, NOT global on/off.
    switch_raw: int | None = None
    unparsed: bytes = b""


class BLEWifiCodec:
    """Non-music BLEWIFI subtype 00/01 only; no transport or auto-init action.

    Name gates reproduce static app eligibility, not verified device identity.
    device_type must be supplied explicitly, normally from the advertisement.
    There is intentionally no login/PIN packet or speculative global-OFF API.
    """
    def __init__(self, name: str, device_type: int):
        _local_blewifi_name(name)
        if "-BLEWIFI-M" in name:
            raise ProtocolError("music-box variant intentionally not implemented")
        self.device_type = _range(device_type, 0, 1, "device subtype")
        self.name = name

    def query(self, command: int) -> bytes:
        _range(command, 0, 255, "command")
        if command not in {0xDB, 0xF1, 0xF2}:
            raise ProtocolError("query not reached by the non-music BLEWIFI init path")
        return _tx(command)

    def enable_control(self) -> bytes:
        """Exact auto-init totalSwitchOpen() command; physical meaning unverified."""
        return _tx(7, b"\x01")

    def set_fan_level(self, level: int) -> bytes:
        if self.device_type != 0:
            raise ProtocolError("fan UI not established for this subtype")
        return _tx(6, bytes((_range(level, 0, 2, "fan level"),)))

    def set_schedule_switch(self, slot: int, enabled: bool,
                            current_enabled: bool | None = None) -> bytes | None:
        _range(slot, 1, 5, "slot")
        _bool(enabled)
        if current_enabled is not None and _bool(current_enabled) == enabled:
            return None  # modelSwitchChange() suppresses unchanged state.
        return _tx(0x10 + slot, bytes((int(enabled),)))

    def set_schedule(self, slot: int, weekday_mask: int, start_hour: int,
                     start_minute: int, stop_hour: int, stop_minute: int,
                     work_seconds: int, pause_seconds: int) -> bytes:
        _range(slot, 1, 5, "slot")
        _range(weekday_mask, 1, 127, "weekday mask")
        _range(start_hour, 0, 23, "start hour")
        _range(stop_hour, 0, 23, "stop hour")
        _range(start_minute, 0, 59, "start minute")
        _range(stop_minute, 0, 59, "stop minute")
        if (start_hour, start_minute) >= (stop_hour, stop_minute):
            raise ProtocolError("start must precede stop within the same day")
        # Wire-width validation only: app UI duration menus vary by subtype.
        _range(work_seconds, 1, 65535, "work seconds")
        _range(pause_seconds, 1, 65535, "pause seconds")
        body = bytes((weekday_mask, start_hour, start_minute, stop_hour, stop_minute))
        body += work_seconds.to_bytes(2, "big") + pause_seconds.to_bytes(2, "big")
        return _tx(slot, body)

    def set_clock(self, iso_weekday: int, hour: int, minute: int, second: int) -> bytes:
        """Caller-supplied local wall clock; does not read or convert host time."""
        _range(iso_weekday, 1, 7, "weekday")
        body = bytes((1 << (iso_weekday - 1), _range(hour, 0, 23, "hour"),
                      _range(minute, 0, 59, "minute"),
                      _range(second, 0, 59, "second")))
        return _tx(0, body)

    def parse_notification(self, value: Iterable[int]) -> Notification:
        raw = octets(value)
        if len(raw) < 6 or raw[:2] != b"\x55\x11":
            raise ProtocolError("expected one complete local reply callback")
        if sum(raw[1:-1]) & 0xFF != raw[-1]:
            raise ProtocolError("reply checksum mismatch")
        command, metadata, body = raw[2], raw[3:5], raw[5:-1]
        schedules: tuple[Schedule, ...] = ()
        fan = power = switch = None
        unparsed = body
        if command == 0xF1:
            if len(body) < 13:
                raise ProtocolError("incomplete F1 semantic fields")
            schedules = (_schedule(1, body[1:10], body[0]),)
            fan, power = body[11], body[12]
            unparsed = body[10:11] + body[13:]
        elif command == 0xF2:
            if len(body) < 40:
                raise ProtocolError("incomplete F2 four-record table")
            schedules = tuple(_schedule(slot, body[offset + 1:offset + 10],
                                        body[offset])
                              for slot, offset in enumerate(range(0, 40, 10), 2))
            unparsed = body[40:]
        elif 1 <= command <= 5:
            schedules = (_schedule(command, body, None),)
            unparsed = body[9:]
        elif command in {6, 0x26, 0x11, 0x12, 0x13, 0x14, 0x15}:
            if not body:
                raise ProtocolError("missing scalar status")
            if command == 6:
                fan = body[0]
            elif command == 0x26:
                power = body[0]
            else:
                switch = body[0]
            unparsed = body[1:]
        # Unknown commands remain opaque; valid checksum is NOT an actuation ACK.
        return Notification(command, metadata, body, schedules, fan, power,
                            switch, unparsed)
