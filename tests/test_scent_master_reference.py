"""Only synthetic/code-derived vectors, NEVER device or application captures.

Run: python3 -B -m unittest -v tests.test_scent_master_reference (repository root).
The test program does not import, execute or evaluate any vendor JavaScript.
"""
import ast
from pathlib import Path
from typing import cast
import unittest

from .scent_master_reference import (BLEWifiCodec, ProtocolError, SERVICE_UUID,
                             NOTIFY_UUID, WRITE_UUID, WRITE_WITH_RESPONSE,
                             octets, parse_advertisement)

VECTOR_PROVENANCE = "synthetic/code-derived; no captured traffic"
NAME = "BXXXJ-BLEWIFI-U"


def synthetic_reply(command, body=b"", metadata=b"\0\0"):
    # Offsets 3:5 are deliberately opaque placeholders, not captured values.
    prefix = b"\x55\x11" + bytes((command,)) + metadata + body
    return prefix + bytes((sum(prefix[1:]) & 255,))


def synthetic_adv(pin=b"3141", subtype=b"\0", nickname=b"OFFLINE"):
    # All-zero serial, synthetic label and synthetic PIN; no reporter identifiers.
    return b"\0" + b"\0" * 6 + nickname.ljust(16, b"\0") + pin + subtype


def row(slot):
    return bytes((slot % 2, 1 << (slot - 1), 6 + slot, 10 + slot,
                  18 + slot, 20 + slot, 1, slot, 2, slot + 1))


class CodecTests(unittest.TestCase):
    def setUp(self):
        self.codec = BLEWifiCodec(NAME, 0)

    def test_gatt_roles_and_no_response(self):
        self.assertEqual(SERVICE_UUID, "0000FEB3-0000-1000-8000-00805F9B34FB")
        self.assertEqual(NOTIFY_UUID, "0000FED6-0000-1000-8000-00805F9B34FB")
        self.assertEqual(WRITE_UUID, "0000FED5-0000-1000-8000-00805F9B34FB")
        self.assertIs(WRITE_WITH_RESPONSE, False)

    def test_literal_query_vectors(self):
        for command, expected in [(0xF1, "5510f10001"),
                                  (0xF2, "5510f20002"),
                                  (0xDB, "5510db00eb")]:
            with self.subTest(command=command):
                self.assertEqual(self.codec.query(command).hex(), expected)

    def test_enable_control_vector_only(self):
        self.assertEqual(self.codec.enable_control().hex(), "5510070501011e")
        self.assertFalse(hasattr(self.codec, "set_power"))
        self.assertFalse(hasattr(self.codec, "login"))

    def test_fan_vectors(self):
        self.assertEqual(self.codec.set_fan_level(0).hex(), "5510060501001c")
        self.assertEqual(self.codec.set_fan_level(2).hex(), "5510060501021e")

    def test_slot_switch_vectors(self):
        first = self.codec.set_schedule_switch(1, True)
        last = self.codec.set_schedule_switch(5, False)
        assert first is not None and last is not None
        self.assertEqual(first.hex(), "55101105010128")
        self.assertEqual(last.hex(), "5510150501002b")

    def test_unchanged_switch_emits_nothing(self):
        for value in [False, True]:
            with self.subTest(value=value):
                self.assertIsNone(self.codec.set_schedule_switch(3, value, value))

    def test_clock_literal_vector(self):
        self.assertEqual(self.codec.set_clock(1, 12, 34, 56).hex(),
                         "5510000504010c223880")

    def test_clock_all_weekdays(self):
        for day in range(1, 8):
            with self.subTest(day=day):
                self.assertEqual(self.codec.set_clock(day, 0, 0, 0)[5],
                                 1 << (day - 1))

    def test_schedule_literal_vector_and_big_endian(self):
        value = self.codec.set_schedule(2, 31, 8, 30, 18, 45, 300, 900)
        self.assertEqual(value.hex(), "55100205091f081e122d012c038458")
        self.assertEqual(value[10:14], b"\x01\x2c\x03\x84")

    def test_all_queries_have_no_length_byte(self):
        for command in [219, 241, 242]:
            with self.subTest(command=command):
                value = self.codec.query(command)
                self.assertEqual(len(value), 5)
                self.assertEqual(value[:4], bytes((85, 16, command, 0)))
                self.assertEqual(value[-1], (16 + command) & 255)

    def test_signed_normalization_and_checksum_overflow(self):
        self.assertEqual(octets([-128, -15, -1, 0, 127, 255]),
                         bytes((128, 241, 255, 0, 127, 255)))
        self.assertEqual(self.codec.query(241)[-1], 1)
        signed = [x if x < 128 else x - 256 for x in synthetic_reply(241, row(1) + b"\x88\x02\x64")]
        self.assertEqual(self.codec.parse_notification(signed).command, 241)

    def test_advertisement_pin_is_local_and_configurable(self):
        adv = parse_advertisement(NAME, synthetic_adv())
        self.assertEqual(adv.serial_bytes, bytes(6))
        self.assertEqual(adv.nickname, "OFFLINE")
        self.assertEqual(adv.pin, "3141")
        self.assertTrue(adv.pin_matches("3141"))
        self.assertFalse(adv.pin_matches("2718"))
        self.assertFalse(adv.pin_matches(3141))
        self.assertFalse(adv.pin_matches("3141 "))

    def test_advertisement_repr_omits_private_fields(self):
        adv = parse_advertisement(NAME, synthetic_adv(nickname=b"PRIVATE_LABEL"))
        summary = repr(adv)
        for text in ["3141", "PRIVATE_LABEL", "serial_bytes", "nickname", "pin="]:
            with self.subTest(text=text):
                self.assertNotIn(text, summary)
        self.assertEqual(adv.pin, "3141")

    def test_advertisement_type_27_28_29_length_behavior(self):
        for data, expected in [(synthetic_adv(subtype=b""), 0),
                               (synthetic_adv(subtype=b"\x01"), 1),
                               (synthetic_adv(subtype=b"\x01\x02"), 0)]:
            with self.subTest(length=len(data)):
                self.assertEqual(parse_advertisement(NAME, data).device_type, expected)

    def test_advertisement_zero_text_fallback(self):
        adv = parse_advertisement(NAME, synthetic_adv(pin=bytes(4), nickname=b""))
        self.assertEqual(adv.pin, "9999")  # Source fallback, NOT a trial password.
        self.assertEqual(adv.nickname, "")

    def test_advertisement_short_rejected(self):
        for length in [0, 22, 23, 26]:
            with self.subTest(length=length), self.assertRaises(ProtocolError):
                parse_advertisement(NAME, bytes(length))

    def test_foreign_and_setup_only_routes_rejected(self):
        for name in ["NAMSTE", "BXXXJ-TJ-A", "YGZK-BLEWIFI-U", "OTHER-BLEWIFI-U"]:
            with self.subTest(name=name), self.assertRaises(ProtocolError):
                BLEWifiCodec(name, 0)

    def test_music_unknown_and_invalid_subtypes_rejected(self):
        for name, subtype in [("BXXXJ-BLEWIFI-M", 0), (NAME, 2), (NAME, -1),
                               (NAME, True)]:
            with self.subTest(name=name, subtype=subtype), self.assertRaises(ProtocolError):
                BLEWifiCodec(name, subtype)

    def test_type01_fan_gate_but_shared_framing(self):
        codec = BLEWifiCodec(NAME, 1)
        with self.assertRaises(ProtocolError):
            codec.set_fan_level(1)
        self.assertEqual(codec.query(241), self.codec.query(241))

    def test_f1_minimum_semantic_fields_and_opaque_reserved_byte(self):
        body = row(1) + b"\x88\x02\x64"
        result = self.codec.parse_notification(synthetic_reply(241, body))
        self.assertEqual(len(result.schedules), 1)
        self.assertEqual(result.schedules[0].slot, 1)
        self.assertEqual(result.schedules[0].enabled_raw, 1)
        self.assertEqual(result.schedules[0].work_seconds, 257)
        self.assertEqual(result.schedules[0].pause_seconds, 514)
        self.assertEqual(result.fan_raw, 2)
        self.assertEqual(result.power_raw, 100)
        self.assertEqual(result.unparsed, b"\x88")
        self.assertIsNone(result.switch_raw)

    def test_f1_source_slice_33_bytes_retains_unknown_tail(self):
        body = row(1) + b"\x88\x01\x5a" + bytes(range(20))
        self.assertEqual(len(body), 33)
        result = self.codec.parse_notification(synthetic_reply(241, body))
        self.assertEqual(result.unparsed, b"\x88" + bytes(range(20)))

    def test_f2_all_four_records_and_opaque_ten_byte_tail(self):
        body = b"".join(row(slot) for slot in range(2, 6)) + bytes(range(10))
        result = self.codec.parse_notification(synthetic_reply(242, body))
        self.assertEqual([s.slot for s in result.schedules], [2, 3, 4, 5])
        for item in result.schedules:
            with self.subTest(slot=item.slot):
                self.assertEqual(item.enabled_raw, item.slot % 2)
                self.assertEqual(item.weekday_mask, 1 << (item.slot - 1))
                self.assertEqual(item.start_hour, 6 + item.slot)
                self.assertEqual(item.start_minute, 10 + item.slot)
                self.assertEqual(item.stop_hour, 18 + item.slot)
                self.assertEqual(item.stop_minute, 20 + item.slot)
                self.assertEqual(item.work_seconds, 256 + item.slot)
                self.assertEqual(item.pause_seconds, 513 + item.slot)
        self.assertEqual(result.unparsed, bytes(range(10)))

    def test_individual_schedule_and_scalar_response_paths(self):
        result = self.codec.parse_notification(synthetic_reply(2, row(2)[1:]))
        self.assertEqual(result.schedules[0].slot, 2)
        self.assertIsNone(result.schedules[0].enabled_raw)
        for command in [6, 38, 17, 18, 19, 20, 21]:
            with self.subTest(command=command):
                result = self.codec.parse_notification(synthetic_reply(command, b"\x01"))
                self.assertEqual(result.command, command)
                self.assertEqual(result.fan_raw if command == 6 else result.power_raw
                                 if command == 38 else result.switch_raw, 1)

    def test_reply_metadata_not_assumed_to_be_a_length(self):
        result = self.codec.parse_notification(synthetic_reply(6, b"\x02", b"\xa5\xf0"))
        self.assertEqual(result.metadata, b"\xa5\xf0")
        self.assertEqual(result.fan_raw, 2)

    def test_unknown_reply_not_claimed_to_prove_actuation(self):
        result = self.codec.parse_notification(synthetic_reply(7, b"\x01"))
        self.assertEqual(result.unparsed, b"\x01")
        self.assertIsNone(result.switch_raw)
        self.assertFalse(hasattr(result, "actuation_confirmed"))

    def test_bad_checksum_rejected(self):
        value = synthetic_reply(6, b"\x02")
        with self.assertRaises(ProtocolError):
            self.codec.parse_notification(value[:-1] + bytes((value[-1] ^ 1,)))

    def test_wrong_direction_and_header_rejected(self):
        for prefix in [b"\x54\x11", b"\x55\x10", b"\x55\x12"]:
            with self.subTest(prefix=prefix), self.assertRaises(ProtocolError):
                value = prefix + b"\x06\0\0\x01"
                self.codec.parse_notification(value + bytes((sum(value[1:]) & 255,)))

    def test_short_semantic_payloads_rejected(self):
        for command, width in [(241, 13), (242, 40), (1, 9), (6, 1), (17, 1), (38, 1)]:
            with self.subTest(command=command), self.assertRaises(ProtocolError):
                self.codec.parse_notification(synthetic_reply(command, bytes(width - 1)))

    def test_fragments_not_reassembled(self):
        value = synthetic_reply(242, b"".join(row(s) for s in range(2, 6)))
        for part in [value[:20], value[20:]]:
            with self.subTest(size=len(part)), self.assertRaises(ProtocolError):
                self.codec.parse_notification(part)
        self.assertEqual(len(self.codec.parse_notification(value).schedules), 4)

    def test_invalid_octets_rejected(self):
        for value in [-129, 256, 1.0, True, "01"]:
            with self.subTest(value=value), self.assertRaises(ProtocolError):
                octets([value])

    def test_invalid_commands_levels_slots_and_boolean_rejected(self):
        for action in [lambda: self.codec.query(7), lambda: self.codec.query(-1),
                       lambda: self.codec.query(1), lambda: self.codec.query(38),
                       lambda: self.codec.set_fan_level(3),
                       lambda: self.codec.set_schedule_switch(0, True),
                       lambda: self.codec.set_schedule_switch(6, False),
                       lambda: self.codec.set_schedule_switch(1, cast(bool, 1))]:
            with self.subTest(action=action), self.assertRaises(ProtocolError):
                action()

    def test_invalid_clock_values_rejected(self):
        for values in [(0, 0, 0, 0), (8, 0, 0, 0), (1, 24, 0, 0),
                       (1, 0, 60, 0), (1, 0, 0, 60)]:
            with self.subTest(values=values), self.assertRaises(ProtocolError):
                self.codec.set_clock(*values)

    def test_invalid_schedule_values_rejected(self):
        original = [2, 31, 8, 30, 18, 45, 300, 900]
        for index, value in [(0, 6), (1, 0), (1, 128), (2, 24), (3, 60),
                             (4, 7), (5, 60), (6, 0), (7, 65536)]:
            arguments = original.copy()
            arguments[index] = value
            with self.subTest(index=index, value=value), self.assertRaises(ProtocolError):
                self.codec.set_schedule(*arguments)

    def test_codec_imports_are_inert_stdlib_only(self):
        code = Path(__file__).with_name("scent_master_reference.py").read_text()
        tree = ast.parse(code)
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertEqual(imports, {"dataclasses", "typing"})
        self.assertFalse(any(isinstance(node, ast.Import) for node in ast.walk(tree)))
        calls = {node.func.id for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertTrue(calls.isdisjoint({"open", "exec", "eval", "__import__"}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
