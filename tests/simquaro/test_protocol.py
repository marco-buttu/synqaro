"""Boundary tests use literal wire fixtures, independently of the encoder."""

from dataclasses import FrozenInstanceError
from decimal import Decimal, localcontext
import tracemalloc
import unittest

from simquaro.config import ReceiverConfig
from simquaro.errors import ERROR_CATALOG, ProtocolError, render_error
from simquaro.protocol import (
    NumericToken, Request, Response, encode_response, parse_frequency,
    parse_request, parse_response, recover_request_id,
)


class CodecTests(unittest.TestCase):
    def assert_error(self, frame, code, request_id=1):
        with self.assertRaises(ProtocolError) as caught:
            parse_request(frame)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.request_id, request_id)
        return caught.exception

    def test_request_id_leading_zeros_and_named_fields(self):
        frame = b"#get <id=0001>: name=frequency\n"
        self.assertEqual(recover_request_id(frame), 1)
        self.assertEqual(parse_request(frame), Request(
            "get", 1, {"id": NumericToken("0001")}, {"name": "frequency"}))

    def test_syntax_leaves_unknown_request_verbs_for_receiver_validation(self):
        self.assertEqual(parse_request(b"#future <id=1>: value=[], enabled=false\n").fields,
                         {"value": [], "enabled": False})

    def test_numeric_spellings_are_preserved_and_immutable(self):
        for text in ("5", "+5", "-5", "0.5", "005.50", "5.5e0", "1E-6", "2e+3"):
            with self.subTest(text=text):
                value = parse_request(f"#set <id=1>: value={text}\n".encode()).fields["value"]
                self.assertEqual(value, NumericToken(text))
        token = NumericToken("5")
        with self.assertRaises(FrozenInstanceError):
            token.text = "6"
        for text in (".5", "5.", "1e", "NaN", "Inf", "Infinity", "١", "5\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                NumericToken(text)

    def test_nonnumeric_unquoted_tokens_remain_strings(self):
        for text in (".5", "5.", "1e", "NaN", "Inf", "Infinity"):
            with self.subTest(text=text):
                request = parse_request(f"#set <id=1>: value={text}\n".encode())
                self.assertEqual(request.fields["value"], text)

    def test_quoted_numbers_lists_and_escapes_keep_types(self):
        request = parse_request(
            b'#set <id = 1, client_id="a,<>:b"> : value=[1, "a,b", true], '
            b'number="100", flag="true", text="quote\\\" slash\\\\"\n')
        self.assertEqual(request.metadata["client_id"], "a,<>:b")
        self.assertEqual(request.fields, {"value": [NumericToken("1"), "a,b", True],
                                         "number": "100", "flag": "true",
                                         "text": 'quote" slash\\'})

    def test_exact_response_bytes_use_safe_scalar_strings(self):
        self.assertEqual(encode_response(Response("ok", 1, {
            "name": "frequency", "value": NumericToken("5.5"), "unit": "GHz",
            "sampled_at": "2026-10-23T10:15:30.123456789123Z",
        })), b"#ok <id=1>: name=frequency, value=5.5, unit=GHz, sampled_at=2026-10-23T10:15:30.123456789123Z\n")
        self.assertEqual(encode_response(Response("accepted", 2, {})), b"#accepted <id=2>\n")
        self.assertEqual(encode_response(Response("ok", 1, {
            "number": "100", "flag": "true", "items": [NumericToken("1"), "a,b", True],
            "text": 'quote" slash\\', "empty": "", "delimiters": "a<>:=[]",
        })), b'#ok <id=1>: number="100", flag="true", items=[1, "a,b", true], text="quote\\\" slash\\\\", empty="", delimiters="a<>:=[]"\n')

    def test_response_parsing_preserves_strings_timestamps_and_unknown_error(self):
        response = parse_response(b'#error <id=12>: code=FUTURE_ERROR, description="read failed", number="100", sampled_at=2026-10-23T10:15:30.123456789123Z\n')
        self.assertEqual(response.request_id, 12)
        self.assertEqual(response.fields["code"], "FUTURE_ERROR")
        self.assertEqual(response.fields["number"], "100")
        self.assertEqual(response.fields["sampled_at"], "2026-10-23T10:15:30.123456789123Z")
        self.assertEqual(parse_response(encode_response(response)), response)

    def test_reserved_uncorrelated_invalid_id_has_exact_wire_form(self):
        response = Response("error", None, {"code": "INVALID_ID"})
        self.assertEqual(encode_response(response), b"#error: code=INVALID_ID\n")
        self.assertEqual(parse_response(b"#error: code=INVALID_ID\n"), response)
        self.assertEqual(parse_response(b'#error : code = "INVALID_ID" \n'), response)
        for response in (Response("ok", None, {}), Response("error", None, {"code": "BUSY"}),
                         Response("error", 1, {"code": "INVALID_ID"})):
            with self.subTest(response=response), self.assertRaises(ProtocolError):
                encode_response(response)

    def test_malformed_fields_retain_a_reliable_id(self):
        for suffix in (b"name=frequency value=5", b"value=[1,[2]]", b"value=[1,]",
                       b"value=", b"value=\"bad\\n\"", b"name=frequency,", b"Name=x",
                       b"value=unquoted space", b"value=bad>value", b"value=bad\\value"):
            with self.subTest(suffix=suffix):
                frame = b"#set <id=1>: " + suffix + b"\n"
                self.assertEqual(recover_request_id(frame), 1)
                self.assert_error(frame, "MALFORMED_REQUEST")

    def test_duplicates_distinguish_fields_from_ambiguous_metadata_id(self):
        error = self.assert_error(b"#set <id=1>: value=5, value=6\n", "DUPLICATE_PARAMETER")
        self.assertEqual(error.fields, {"parameter": "value"})
        error = self.assert_error(b"#get <id=1, client_id=a, client_id=b>\n", "DUPLICATE_PARAMETER")
        self.assertEqual(error.fields, {"parameter": "client_id"})
        for metadata in (b"id=1, id=1", b"id=1, id=bad", b"id=1, id=2"):
            frame = b"#get <" + metadata + b">\n"
            self.assertIsNone(recover_request_id(frame))
            self.assert_error(frame, "INVALID_ID", None)

    def test_id_requires_unquoted_decimal_digits_within_uint32_range(self):
        for text in ("0", "4294967296", "+1", "-1", "1.0", "1e0", '"1"', "true"):
            with self.subTest(text=text):
                self.assert_error(f"#get <id={text}>\n".encode(), "INVALID_ID", None)
        self.assertEqual(parse_request(b"#status <id=4294967295>\n").request_id, 4294967295)
        # A long spelling of a small number must not hit Python's int conversion limit.
        self.assertEqual(recover_request_id(b"#get <id=" + b"0" * 4000 + b"1>\n"), 1)

    def test_controls_non_ascii_and_garbage_are_rejected(self):
        for bad in (b"\t", b"\r", b"\x00", b"\x1f", b"\x7f", b"\xff"):
            with self.subTest(bad=bad):
                self.assert_error(b'#set <id=1>: value="bad' + bad + b'"\n', "MALFORMED_REQUEST")
        for frame in (b"garbage\n", b"#get: name=frequency\n", b"#get <client_id=\"id=1\">\n"):
            self.assertIsNone(recover_request_id(frame))
            self.assert_error(frame, "INVALID_ID", None)

    def test_frame_bounds_apply_to_both_parsing_and_encoding(self):
        base = b"#get <id=1>: value="
        frame = base + b"a" * (4095 - len(base)) + b"\n"
        self.assertEqual(len(frame), 4096)
        self.assertEqual(len(parse_request(frame).fields["value"]), 4076)
        for bad in (frame[:-1], frame + b"a", frame[:-1] + b"a\n", b"#get <id=1>\n\n"):
            with self.subTest(length=len(bad)), self.assertRaises(ProtocolError):
                parse_request(bad)
        with self.assertRaises(ProtocolError):
            encode_response(Response("ok", 1, {"value": "a" * 4096}))

    def test_invalid_responses_are_local_protocol_errors(self):
        for frame in (b"#ok <id=1>: value=5, value=6\n", b"#ok <id=1>: value=[[]]\n",
                      b"#future <id=1>\n", b"#error <id=1>: code=bad\n",
                      b"#error <id=1>\n", b"#ok: code=INVALID_ID\n",
                      b"#error <id=1>: code=INVALID_ID\n"):
            with self.subTest(frame=frame), self.assertRaises(ProtocolError):
                parse_response(frame)
        for value in (5, Decimal("5"), [True, [False]], "bad\n", "é"):
            with self.subTest(value=value), self.assertRaises(ProtocolError):
                encode_response(Response("ok", 1, {"value": value}))

    def test_encoder_rejects_large_values_before_building_large_wire_strings(self):
        for value in ('"' * 1_000_000, ["x" * 4000] * 1000):
            with self.subTest(kind=type(value).__name__):
                tracemalloc.start()
                try:
                    with self.assertRaises(ProtocolError):
                        encode_response(Response("ok", 1, {"value": value}))
                    _, peak = tracemalloc.get_traced_memory()
                finally:
                    tracemalloc.stop()
                self.assertLess(peak, 128_000)


class FrequencyTests(unittest.TestCase):
    def test_exact_grid_rounding_and_equivalent_spellings(self):
        config = ReceiverConfig()
        for text, expected in (("5.1234565", "5.123457"), ("5.123456499999999999999999999", "5.123456"),
                               ("005.50", "5.500000"), ("5.5e0", "5.500000"),
                               ("1", "1.000000"), ("10", "10.000000")):
            with self.subTest(text=text), localcontext() as context:
                context.prec = 3  # Caller decimal settings cannot alter protocol rounding.
                self.assertEqual(parse_frequency(NumericToken(text), config), Decimal(expected))

    def test_original_range_is_checked_before_rounding(self):
        for text in ("0.9999999", "10.00000001", "-5", "0", "1e1000000", "1e-1000000"):
            with self.subTest(text=text), self.assertRaises(ProtocolError) as caught:
                parse_frequency(NumericToken(text), ReceiverConfig())
            self.assertEqual(caught.exception.code, "OUT_OF_RANGE")
            self.assertEqual(caught.exception.fields, {"parameter": "value", "min": NumericToken("1"),
                                                       "max": NumericToken("10"), "unit": "GHz"})

    def test_wrong_types_are_not_implicitly_converted(self):
        for value in ("5", True, False, [NumericToken("5")]):
            with self.subTest(value=value), self.assertRaises(ProtocolError) as caught:
                parse_frequency(value, ReceiverConfig())
            self.assertEqual(caught.exception.code, "INVALID_TYPE")
            self.assertEqual(caught.exception.fields, {"parameter": "value", "expected": "number"})

    def test_huge_exponent_is_explicitly_rejected_without_expanding_it(self):
        with self.assertRaises(ProtocolError) as caught:
            parse_frequency(NumericToken("1e" + "9" * 4000), ReceiverConfig())
        self.assertEqual(caught.exception.code, "INVALID_PARAMETER")
        self.assertEqual(caught.exception.fields, {"parameter": "value", "reason": "UNREPRESENTABLE_VALUE"})


class ErrorCatalogTests(unittest.TestCase):
    def test_catalog_renders_context_and_action_and_preserves_unknown_code(self):
        error = ProtocolError("MISSING_PARAMETER", {"parameter": "value"}, request_id=17)
        self.assertEqual(error.request_id, 17)
        self.assertIn("value", str(error))
        self.assertIn("Supply", str(error))
        text = render_error("FUTURE_ERROR", {"description": "line\n" + "x" * 5000})
        self.assertIn("FUTURE_ERROR", text)
        self.assertIn("Unrecognized", text)
        self.assertNotIn("\n", text)
        self.assertLessEqual(len(text), 1024)
        for code in ("INVALID_ID", "ID_NOT_INCREASING", "DUPLICATE_PARAMETER", "STOP_TIMEOUT",
                     "CLOCK_UNTRUSTED", "FREQUENCY_LOCK_FAILED", "SCAN_TIMEOUT"):
            with self.subTest(code=code):
                definition = ERROR_CATALOG[code]
                self.assertTrue(definition.message)
                self.assertTrue(definition.action)
                self.assertIn(definition.message, render_error(code, {}))

    def test_catalog_renders_numeric_tokens_and_flat_lists_as_values(self):
        text = render_error("OUT_OF_RANGE", {"parameter": "value", "min": NumericToken("1"),
                                            "max": NumericToken("10"), "unit": "GHz"})
        self.assertIn("min=1, max=10, unit=GHz", text)
        self.assertIn("values=[1, true, text]", render_error("FUTURE_ERROR", {
            "values": [NumericToken("1"), True, "text"]}))


if __name__ == "__main__":
    unittest.main()
