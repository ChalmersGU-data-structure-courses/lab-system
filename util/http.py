import http.server
from pathlib import Path

import util.url


class HTTPSServer(http.server.HTTPServer):
    def __init__(
        self,
        netloc: util.url.Netloc,
        RequestHandlerClass: http.server.BaseHTTPRequestHandler,
        dir_cert: Path | None = None,
        update_cert: bool = False,
    ):
        address = (netloc.host, netloc.port)
        super().__init__(address, RequestHandlerClass)

        ssl_context = util.openssl.generate_context(dir_cert, update=update_cert)
        self.socket = ssl_context.wrap_socket(
            self.socket,
            server_side=True,
            do_handshake_on_connect=False,
        )
