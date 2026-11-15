"""Content-only classification; filenames and PDF metadata are never consulted."""
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass

from app.core.settings import get_settings
from app.document_intake.identity import valid_cnp

MAX_BYTES = 20 * 1024 * 1024
TITLES = {'CERERE DE RACORDARE': 'REQUEST_FORM', 'AVIZ DE RACORDARE': 'CONNECTION_APPROVAL'}


@dataclass(frozen=True)
class Parsed:
    detected_type: str | None = None
    cnp: str | None = None
    reason: str | None = None


def normalize(text):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c)).upper().split())


def classify(text: str) -> Parsed:
    lines = [normalize(line) for line in text.splitlines()]
    # Headers can move or wrap. The first narrative paragraph ends the title area.
    stop = next((i for i, line in enumerate(lines) if re.match(r'^(SUBSEMNAT|SOLICIT|IN CALITATE|DECLAR|SUNT DE ACORD|PENTRU LOCUL)', line)), None)
    if stop is None:
        stop = next((i for i, line in enumerate(lines) if len(line) > 110), min(len(lines), 10))
    header = lines[:min(stop, 12)]
    phrases = {normalize(' '.join(header[i:j])) for i in range(len(header)) for j in range(i+1, min(i+3, len(header))+1)}
    found = {kind for title, kind in TITLES.items() if title in phrases}
    if all(title in ' '.join(header) for title in TITLES):
        found = set(TITLES.values())
    identities = {normalize(x) for x in get_settings().intake_identity_markers.split('|') if x.strip()}
    if identities & phrases:
        if found:
            return Parsed(reason='AMBIGUOUS_TYPE')
        return Parsed('ID', reason='IDENTITY_DOCUMENT')
    if len(found) > 1:
        return Parsed(reason='AMBIGUOUS_TYPE')
    if not found:
        return Parsed(reason='UNRECOGNIZED_TYPE')
    kind = found.pop()
    tail = lines[stop:]
    paragraph = []
    for line in tail:
        if paragraph and (not line or re.match(r'^(VA ROG|DECLAR|SUNT DE ACORD|PENTRU LOCUL|LUCRARILE|CONFIRM|PRIN SEMNAREA)', line)):
            break
        if line:
            paragraph.append(line)
    first = ' '.join(paragraph)
    # Capture the entire contiguous digit token so a 14-digit value cannot be
    # accepted as a 13-digit prefix. Dotted C.N.P. and a following newline work.
    tokens = re.findall(r'\bC\.?\s*N\.?\s*P\.?\s*[:\-]?\s*([0-9]+)(?![0-9])', first)
    unique = set(tokens)
    if len(unique) > 1:
        return Parsed(kind, reason='CNP_AMBIGUOUS')
    if not tokens:
        return Parsed(kind, reason='CNP_INVALID' if re.search(r'\bC\.?\s*N\.?\s*P\.?', first) else 'CNP_MISSING')
    value = tokens[0]
    if not valid_cnp(value):
        return Parsed(kind, reason='CNP_INVALID')
    return Parsed(kind, value)


def media_type(data: bytes) -> str:
    if data.startswith(b'%PDF-'):
        return 'application/pdf'
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    return 'application/octet-stream'


def parse(data: bytes) -> Parsed:
    media = media_type(data)
    if len(data) > MAX_BYTES:
        return Parsed(reason='PARSE_ERROR')
    if media in {'image/png', 'image/jpeg'}:
        return Parsed(reason='NO_EXTRACTABLE_TEXT')
    if media != 'application/pdf':
        return Parsed(reason='UNSUPPORTED_FORMAT')
    try:
        # A killable subprocess inside a bounded threadpool gives an actual hard
        # parser timeout; abandoning a Python thread alone cannot stop pypdf.
        result = subprocess.run([sys.executable, '-m', 'app.document_intake.pdf_extract'],
            input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, check=True)
        text = result.stdout.decode('utf-8')
        if not text.strip():
            return Parsed(reason='NO_EXTRACTABLE_TEXT')
        return classify(text)
    except (subprocess.SubprocessError, UnicodeError, OSError):
        return Parsed(reason='PARSE_ERROR')
