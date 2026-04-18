import contextlib
import logging
import ssl
import subprocess
from pathlib import Path

import util.general

logger = logging.getLogger(__name__)


FILENAME_CERT: str = "cert.pem"
FILENAME_KEY: str = "key.pem"


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


def load_context(file_cert: Path, file_key: Path):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(file_cert, file_key)
    return context


def load_context_from_dir(
    dir: Path,
    filename_cert: str = FILENAME_CERT,
    filename_key: str = FILENAME_KEY,
):
    return load_context(dir / filename_cert, dir / filename_key)


def generate_context(
    dir: Path | None = None,
    update: bool = False,
    filename_cert: str = FILENAME_CERT,
    filename_key: str = FILENAME_KEY,
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
        return load_context(file_cert, file_key)


def detect_cert_dir_lets_encrypt(dir=Path("/etc/letsencrypt/")) -> Path:
    dir = dir / "live"

    def domains():
        for path in dir.iterdir():
            if path.is_dir():
                yield path

    return util.general.from_singleton(domains())
