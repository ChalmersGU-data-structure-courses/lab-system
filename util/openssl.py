import logging
import subprocess

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
