"""First-party EMVCo TLV + CRC16/CCITT-FALSE encoder and validator for Individual Bakong KHQR.

Implements NBC's KHQR specification for dynamic Individual QR codes (Tag 29, Point of
Initiation 01=12) with zero third-party relay dependencies.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

CurrencyCode = Literal["USD", "KHR"]

CURRENCY_NUMERIC_TO_ALPHA: dict[str, CurrencyCode] = {
    "840": "USD",
    "116": "KHR",
}
CURRENCY_ALPHA_TO_NUMERIC: dict[CurrencyCode, str] = {
    "USD": "840",
    "KHR": "116",
}


@dataclass(frozen=True)
class GeneratedKHQR:
    qr_payload: str
    qr_md5: str
    bill_number: str
    recipient_bakong_id: str
    amount_minor: int
    currency: CurrencyCode
    created_at_ms: int
    expires_at_ms: int


@dataclass(frozen=True)
class DecodedKHQR:
    payload_format_indicator: str
    point_of_initiation: str
    bakong_account_id: str
    account_information: str | None
    acquiring_bank: str | None
    mcc: str
    currency: CurrencyCode
    amount_minor: int
    country_code: str
    merchant_name: str
    merchant_city: str
    bill_number: str
    created_at_ms: int
    expires_at_ms: int
    crc: str


def compute_crc16_ccitt_false(data: str) -> str:
    """Compute 4-character uppercase hex CRC-16/CCITT-FALSE (poly=0x1021, init=0xFFFF)."""
    crc = 0xFFFF
    polynomial = 0x1021
    for byte in data.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ polynomial) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def compute_khqr_md5(qr_payload: str) -> str:
    """Compute the 32-character lowercase MD5 hex digest over UTF-8 bytes of `qr_payload`."""
    if not qr_payload:
        raise ValueError("qr_payload must not be empty.")
    return hashlib.md5(qr_payload.encode("utf-8")).hexdigest().lower()


def generate_bill_number(prefix: str = "PASS") -> str:
    """Generate a cryptographically unique bill number (<= 25 chars for EMVCo Tag 62.01)."""
    clean_prefix = "".join(ch for ch in prefix.upper() if ch.isalnum())[:6] or "PASS"
    random_part = secrets.token_hex(8).upper()  # 16 hex chars
    bill = f"{clean_prefix}-{random_part}"
    return bill[:25]


def _format_tlv(tag: str, value: str) -> str:
    if len(tag) != 2 or not tag.isdigit():
        raise ValueError(f"Invalid EMVCo tag {tag!r}; expected 2 digits.")
    val_len = len(value)
    if val_len == 0 or val_len > 99:
        raise ValueError(f"TLV value for tag {tag} has invalid length {val_len}.")
    return f"{tag}{val_len:02d}{value}"


def format_amount_from_minor(amount_minor: int, currency: CurrencyCode) -> str:
    """Format integer minor units into an EMVCo Tag 54 amount string using Decimal."""
    if not isinstance(amount_minor, int) or isinstance(amount_minor, bool) or amount_minor <= 0:
        raise ValueError(f"amount_minor must be a positive integer, got {amount_minor!r}.")
    if currency == "USD":
        dollars = (Decimal(amount_minor) / Decimal(100)).quantize(Decimal("0.01"))
        formatted = f"{dollars:.2f}"
    elif currency == "KHR":
        formatted = str(amount_minor)
    else:
        raise ValueError(f"Unsupported currency {currency!r}.")
    if len(formatted) > 13:
        raise ValueError(f"Formatted amount {formatted!r} exceeds 13 characters.")
    return formatted


def parse_amount_to_minor(amount_raw: str | int | float | Decimal, currency: CurrencyCode) -> int:
    """Parse an amount string or Decimal into integer minor units without floating-point drift."""
    if isinstance(amount_raw, float):
        dec = Decimal(str(amount_raw))
    elif isinstance(amount_raw, (int, str, Decimal)):
        try:
            dec = Decimal(str(amount_raw).strip())
        except InvalidOperation as exc:
            raise ValueError(f"Invalid numeric amount {amount_raw!r}.") from exc
    else:
        raise ValueError(f"Unsupported amount type {type(amount_raw).__name__}.")

    if dec <= 0:
        raise ValueError(f"Amount must be positive, got {amount_raw!r}.")

    if currency == "USD":
        minor_dec = dec * Decimal(100)
        if minor_dec != minor_dec.to_integral_value():
            raise ValueError(f"USD amount {amount_raw!r} has more than 2 decimal places.")
        return int(minor_dec)
    if currency == "KHR":
        if dec != dec.to_integral_value():
            raise ValueError(f"KHR amount {amount_raw!r} must be an integer.")
        return int(dec)
    raise ValueError(f"Unsupported currency {currency!r}.")


def parse_tlv_stream(stream: str) -> list[tuple[str, str]]:
    """Parse an EMVCo TLV string strictly into ordered (tag, value) pairs."""
    if not stream:
        raise ValueError("Empty TLV stream.")
    idx = 0
    total = len(stream)
    items: list[tuple[str, str]] = []
    seen_tags: set[str] = set()
    while idx < total:
        if idx + 4 > total:
            raise ValueError(f"Truncated TLV header at offset {idx}.")
        tag = stream[idx : idx + 2]
        len_str = stream[idx + 2 : idx + 4]
        if not tag.isdigit() or not len_str.isdigit():
            raise ValueError(f"Non-numeric TLV header {stream[idx:idx+4]!r} at offset {idx}.")
        length = int(len_str)
        if length <= 0:
            raise ValueError(f"Zero-length TLV field for tag {tag} at offset {idx}.")
        val_start = idx + 4
        val_end = val_start + length
        if val_end > total:
            raise ValueError(
                f"TLV value for tag {tag} (length {length}) exceeds stream length at offset {idx}."
            )
        if tag in seen_tags:
            raise ValueError(f"Duplicate TLV tag {tag} in stream.")
        seen_tags.add(tag)
        items.append((tag, stream[val_start:val_end]))
        idx = val_end
    return items


def build_individual_khqr(
    *,
    bakong_account_id: str,
    merchant_name: str,
    merchant_city: str = "Phnom Penh",
    amount_minor: int,
    currency: CurrencyCode = "USD",
    bill_number: str,
    account_information: str | None = None,
    acquiring_bank: str | None = None,
    created_at: datetime | None = None,
    expiry_seconds: int = 300,
) -> GeneratedKHQR:
    """Build and self-validate a dynamic Individual (Tag 29) Bakong KHQR payload."""
    acct = bakong_account_id.strip()
    if not acct or len(acct) > 32 or "@" not in acct:
        raise ValueError(
            "bakong_account_id must be a valid Bakong ID (1..32 chars containing '@')."
        )

    name = merchant_name.strip()
    if not name or len(name) > 25:
        raise ValueError("merchant_name must be 1..25 characters.")

    city = merchant_city.strip()
    if not city or len(city) > 15:
        raise ValueError("merchant_city must be 1..15 characters.")

    bill = bill_number.strip()
    if not bill or len(bill) > 25:
        raise ValueError("bill_number must be 1..25 characters.")

    if expiry_seconds <= 0 or expiry_seconds > 600:
        raise ValueError("expiry_seconds must be between 1 and 600 seconds.")

    if currency not in CURRENCY_ALPHA_TO_NUMERIC:
        raise ValueError(f"Unsupported currency {currency!r}.")

    now_dt = created_at or datetime.now(UTC)
    created_ms = int(now_dt.timestamp() * 1000)
    expires_ms = created_ms + int(expiry_seconds * 1000)

    # Tag 29: Individual Merchant Account Information
    tag29_sub = _format_tlv("00", acct)
    if account_information and account_information.strip():
        acct_info = account_information.strip()
        if len(acct_info) > 32:
            raise ValueError("account_information cannot exceed 32 characters.")
        tag29_sub += _format_tlv("01", acct_info)
    if acquiring_bank and acquiring_bank.strip():
        acq_bank = acquiring_bank.strip()
        if len(acq_bank) > 32:
            raise ValueError("acquiring_bank cannot exceed 32 characters.")
        tag29_sub += _format_tlv("02", acq_bank)

    amount_str = format_amount_from_minor(amount_minor, currency)

    # Tag 62: Additional Data Field Template (Subtag 01 = Bill Number)
    tag62_sub = _format_tlv("01", bill)

    # Tag 99: Timestamp Template (Subtag 00 = created ms, Subtag 01 = expires ms)
    tag99_sub = _format_tlv("00", str(created_ms)) + _format_tlv("01", str(expires_ms))

    body_without_crc = "".join(
        [
            _format_tlv("00", "01"),  # Payload Format Indicator
            _format_tlv("01", "12"),  # Point of Initiation Method: 12 = Dynamic QR
            _format_tlv("29", tag29_sub),  # Individual KHQR (Tag 29)
            _format_tlv("52", "5999"),  # Merchant Category Code
            _format_tlv("53", CURRENCY_ALPHA_TO_NUMERIC[currency]),
            _format_tlv("54", amount_str),
            _format_tlv("58", "KH"),
            _format_tlv("59", name),
            _format_tlv("60", city),
            _format_tlv("62", tag62_sub),
            _format_tlv("99", tag99_sub),
        ]
    )

    crc_input = f"{body_without_crc}6304"
    crc_hex = compute_crc16_ccitt_false(crc_input)
    full_payload = f"{crc_input}{crc_hex}"

    # Self-verify generated QR before returning
    decoded = decode_and_validate_khqr(full_payload)
    if (
        decoded.bakong_account_id != acct
        or decoded.amount_minor != amount_minor
        or decoded.currency != currency
        or decoded.bill_number != bill
        or decoded.expires_at_ms != expires_ms
    ):
        raise ValueError("KHQR self-validation failed: decoded fields did not match input.")

    return GeneratedKHQR(
        qr_payload=full_payload,
        qr_md5=compute_khqr_md5(full_payload),
        bill_number=bill,
        recipient_bakong_id=acct,
        amount_minor=amount_minor,
        currency=currency,
        created_at_ms=created_ms,
        expires_at_ms=expires_ms,
    )


def decode_and_validate_khqr(qr_payload: str) -> DecodedKHQR:
    """Decode and validate an Individual dynamic KHQR string (EMVCo TLV + CRC16)."""
    if not qr_payload or len(qr_payload) < 20:
        raise ValueError("KHQR payload is empty or too short.")

    top_pairs = parse_tlv_stream(qr_payload)
    if top_pairs[-1][0] != "63":
        raise ValueError("Final TLV tag must be Tag 63 (CRC).")

    crc_value = top_pairs[-1][1]
    if len(crc_value) != 4:
        raise ValueError("CRC tag 63 must have length 4.")

    expected_crc = compute_crc16_ccitt_false(qr_payload[:-4])
    if crc_value.upper() != expected_crc:
        raise ValueError(
            f"CRC16 mismatch: payload has {crc_value!r}, expected {expected_crc!r}."
        )

    tags = dict(top_pairs)
    if tags.get("00") != "01":
        raise ValueError(f"Invalid Payload Format Indicator (Tag 00): {tags.get('00')!r}.")
    if tags.get("01") != "12":
        raise ValueError(
            f"KHQR must be dynamic (Tag 01 = '12'), got {tags.get('01')!r}."
        )
    if "30" in tags:
        raise ValueError("Merchant Tag 30 is not permitted; expected Individual Tag 29.")
    if "29" not in tags:
        raise ValueError("Missing Individual Merchant Account Information (Tag 29).")

    tag29 = dict(parse_tlv_stream(tags["29"]))
    bakong_id = tag29.get("00", "").strip()
    if not bakong_id or len(bakong_id) > 32 or "@" not in bakong_id:
        raise ValueError(f"Invalid Tag 29.00 Bakong Account ID: {bakong_id!r}.")

    acct_info = tag29.get("01")
    acq_bank = tag29.get("02")

    mcc = tags.get("52", "")
    if len(mcc) != 4 or not mcc.isdigit():
        raise ValueError(f"Invalid Tag 52 MCC: {mcc!r}.")

    curr_num = tags.get("53", "")
    if curr_num not in CURRENCY_NUMERIC_TO_ALPHA:
        raise ValueError(f"Unsupported Tag 53 currency code: {curr_num!r}.")
    currency = CURRENCY_NUMERIC_TO_ALPHA[curr_num]

    amount_str = tags.get("54", "")
    if not amount_str:
        raise ValueError("Missing Tag 54 transaction amount.")
    amount_minor = parse_amount_to_minor(amount_str, currency)

    country_code = tags.get("58", "")
    if country_code != "KH":
        raise ValueError(f"Invalid Tag 58 country code: {country_code!r}.")

    merchant_name = tags.get("59", "")
    if not merchant_name or len(merchant_name) > 25:
        raise ValueError(f"Invalid Tag 59 merchant name: {merchant_name!r}.")

    merchant_city = tags.get("60", "")
    if not merchant_city or len(merchant_city) > 15:
        raise ValueError(f"Invalid Tag 60 merchant city: {merchant_city!r}.")

    if "62" not in tags:
        raise ValueError("Missing Tag 62 Additional Data Field (bill number required).")
    tag62 = dict(parse_tlv_stream(tags["62"]))
    bill_number = tag62.get("01", "").strip()
    if not bill_number or len(bill_number) > 25:
        raise ValueError(f"Invalid Tag 62.01 bill number: {bill_number!r}.")

    if "99" not in tags:
        raise ValueError("Missing Tag 99 timestamp data.")
    tag99 = dict(parse_tlv_stream(tags["99"]))
    created_raw = tag99.get("00", "")
    expires_raw = tag99.get("01", "")
    if not created_raw.isdigit() or not expires_raw.isdigit():
        raise ValueError("Tag 99 timestamps must be numeric millisecond strings.")
    created_ms = int(created_raw)
    expires_ms = int(expires_raw)
    if expires_ms <= created_ms:
        raise ValueError("Tag 99 expiry timestamp must be greater than creation timestamp.")

    return DecodedKHQR(
        payload_format_indicator=tags["00"],
        point_of_initiation=tags["01"],
        bakong_account_id=bakong_id,
        account_information=acct_info,
        acquiring_bank=acq_bank,
        mcc=mcc,
        currency=currency,
        amount_minor=amount_minor,
        country_code=country_code,
        merchant_name=merchant_name,
        merchant_city=merchant_city,
        bill_number=bill_number,
        created_at_ms=created_ms,
        expires_at_ms=expires_ms,
        crc=crc_value.upper(),
    )
