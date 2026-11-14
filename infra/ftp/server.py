"""Internal-only, authenticated binary/passive FTP service."""
import logging
import os
import sys
from ftplib import FTP
from pathlib import Path

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer


def main() -> None:
    user = os.environ.get("FTP_USER", "filegrid")
    port = int(os.environ.get("FTP_PORT", "2121"))
    password = (Path("/run/secrets") / "ftp_password").read_text().strip()

    if "--healthcheck" in sys.argv:
        with FTP() as client:
            client.connect("127.0.0.1", port, timeout=5)
            client.login(user, password)
            client.voidcmd("TYPE I")
            client.nlst()
        return

    authorizer = DummyAuthorizer()
    authorizer.add_user(user, password, "/data", perm="elradfmwMT")
    handler = FTPHandler
    handler.authorizer = authorizer
    handler.passive_ports = range(30000, 30010)
    # Avoid logging file names/paths or per-transfer activity.
    logging.basicConfig(level=logging.WARNING)
    server = FTPServer(("0.0.0.0", port), handler)
    server.max_cons = 64
    server.max_cons_per_ip = 64
    server.serve_forever()


if __name__ == "__main__":
    main()
