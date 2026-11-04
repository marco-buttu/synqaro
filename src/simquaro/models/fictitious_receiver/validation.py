"""Exact receiver frequency validation, independent of wire syntax."""

from decimal import Context, Decimal, ROUND_HALF_UP, localcontext
import re

from synqaro_protocol.errors import ProtocolError
from synqaro_protocol.codec import NumericToken, Value
from .config import ReceiverConfig


def parse_frequency(value: Value, config: ReceiverConfig) -> Decimal:
    """Validate original range, then round exactly to the declared GHz grid.

    Numeric spellings have at most 4096 characters. Exponents with magnitude
    above 9,999,999 exceed this codec's capacity and are rejected explicitly;
    smaller exponents are compared without allocating exponent-sized integers.
    """
    if not isinstance(value, NumericToken):
        raise ProtocolError("INVALID_TYPE", {"parameter": "value", "expected": "number"})
    exponent = re.split("[eE]", value.text)
    if len(exponent) == 2 and len(exponent[1].lstrip("+-").lstrip("0")) > 7:
        raise ProtocolError("INVALID_PARAMETER", {"parameter": "value", "reason": "UNREPRESENTABLE_VALUE"})
    number = Decimal(value.text)
    minimum = Decimal(str(config.frequency_min))
    maximum = Decimal(str(config.frequency_max))
    if not minimum <= number <= maximum:
        raise ProtocolError("OUT_OF_RANGE", {"parameter": "value",
                            "min": NumericToken(str(config.frequency_min)),
                            "max": NumericToken(str(config.frequency_max)), "unit": config.frequency_unit})
    resolution = Decimal(str(config.frequency_resolution))
    with localcontext(Context(prec=max(32, len(value.text) + 16), rounding=ROUND_HALF_UP,
                              Emin=-9999999, Emax=9999999)):
        return (number / resolution).to_integral_value(rounding=ROUND_HALF_UP) * resolution
