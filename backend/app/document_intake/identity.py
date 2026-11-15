"""CNP values exist only transiently; lookup uses a dedicated HMAC secret."""
import hashlib
import hmac
import re
import secrets
from datetime import date
from pathlib import Path

from app.core.settings import get_settings
from app.documents.encryption import DocumentKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

CONTROL = '279146358279'
COUNTIES = set(range(1, 47)) | {51, 52, 70}  # 70: nationally generated SIIEASC CNPs


def valid_cnp(value: str) -> bool:
    if re.fullmatch(r'[1-9][0-9]{12}', value) is None:
        return False
    first, year = int(value[0]), int(value[1:3])
    century = {1: 1900, 2: 1900, 3: 1800, 4: 1800, 5: 2000, 6: 2000}.get(first)
    # Resident/foreign identifiers do not encode a century; accept a real calendar
    # date in either contemporary century, including the leap-year distinction.
    centuries = [century] if century else [1900, 2000]
    valid_date = False
    for base in centuries:
        try:
            date(base + year, int(value[3:5]), int(value[5:7]))
            valid_date = True
        except ValueError:
            continue
    checksum = sum(int(n) * int(k) for n, k in zip(value[:12], CONTROL)) % 11
    return valid_date and int(value[7:9]) in COUNTIES and int(value[9:12]) > 0 and int(value[-1]) == (1 if checksum == 10 else checksum)


def fingerprint(value: str) -> str:
    secret = bytes.fromhex((Path(get_settings().secrets_dir) / 'cnp_hmac_key').read_text().strip())
    if len(secret) != 32:
        raise ValueError('CNP lookup requires a 256-bit secret')
    return hmac.new(secret, value.encode('ascii'), hashlib.sha256).hexdigest()


def masked(value: str) -> str:
    return value[:1] + '********' + value[-4:]


def encrypt_customer_value(value: str, customer_id, *, field: str) -> bytes:
    nonce = secrets.token_bytes(12)
    aad = customer_id.bytes + (b':cnp' if field == 'cnp' else b'')
    return nonce + AESGCM(DocumentKey.load(get_settings()).value).encrypt(
        nonce, value.encode('utf-8'), aad
    )


def decrypt_customer_value(value: bytes, customer_id, *, field: str) -> str:
    aad = customer_id.bytes + (b':cnp' if field == 'cnp' else b'')
    return AESGCM(DocumentKey.load(get_settings()).value).decrypt(
        value[:12], value[12:], aad
    ).decode('utf-8')


def customer_name(client) -> str:
    if client.external_code.startswith('CUSTOMER-'):
        return decrypt_customer_value(client.name_enc, client.id, field='name')
    return client.external_code


def demo_cnp(number: int) -> str:
    prefix = f'501010140{number:03d}'
    check = sum(int(n) * int(k) for n, k in zip(prefix, CONTROL)) % 11
    return prefix + str(1 if check == 10 else check)
