import http.server
from pathlib import Path

import util.url


class HTTPSServer(http.server.HTTPServer):
    def __init__(
        self,
        netloc: util.url.Netloc,
        RequestHandlerClass: http.server.BaseHTTPRequestHandler,
        cert_dir: Path | None = None,
    ):
        address = (netloc.host, netloc.port)
        super().__init__(address, RequestHandlerClass)

        ssl_context = util.openssl.generate_context(cert_dir)
        self.socket = ssl_context.wrap_socket(
            self.socket,
            server_side=True,
            do_handshake_on_connect=False,
        )
