import contextlib
import logging
import ssl
import subprocess
from pathlib import Path

import util.general

logger = logging.getLogger(__name__)


def generate_cert(file_cert, file_key):
    """
    Generates a transient SSL certificate.
    The resulting key and certificate are written to the specified paths (path-like objects).
    """

    def args():
        yield "openssl"
        yield "req"
        yield "-x509"
        yield from ["-newkey", "rsa:4096"]
        yield from ["-out", file_cert]
        yield from ["-keyout", file_key]
        yield from ["-days", str(10000)]
        yield "-nodes"

        # OpenSSL complains if all fields are empty.
        # So we set the common name.
        yield from ["-subj", "/C=/ST=/L=/O=/OU=/CN=anonymous"]

    args = list(args())
    util.general.log_command(logger, args)
    process = subprocess.run(args, text=True, capture_output=True, check=True)
    logger.debug(process.stderr)


def generate_context(
    dir: Path | None = None,
    update: bool = False,
    filename_cert="cert.pem",
    filename_key="key.pem",
):
    stack = contextlib.ExitStack()
    with stack:
        if dir is None:
            dir = stack.enter_context(util.path.temp_dir())

        dir.mkdir(exist_ok=True)
        file_cert = dir / filename_cert
        file_key = dir / filename_key
        if update or not (file_cert.exists() and file_key.exists()):
            util.openssl.generate_cert(file_cert, file_key)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(file_cert, file_key)
        return context
