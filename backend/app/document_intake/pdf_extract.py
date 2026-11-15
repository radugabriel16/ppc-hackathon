"""Private parser process. Never emit text to application logs."""
import io
import sys

from pypdf import PdfReader


def main():
    if sys.platform.startswith('linux'):
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    raw = sys.stdin.buffer.read(20 * 1024 * 1024 + 1)
    if len(raw) > 20 * 1024 * 1024:
        return 1
    reader = PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 20:
        return 1
    text = reader.pages[0].extract_text() or ''
    if len(text) > 250000:
        return 1
    sys.stdout.buffer.write(text.encode('utf-8'))
    return 0


if __name__ == '__main__':
    try:
        code = main()
    except Exception:
        code = 1
    raise SystemExit(code)
