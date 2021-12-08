import contextlib
import json
import http.server
import logging
import ssl

import path_tools
import print_parse
import openssl_tools


logger = logging.getLogger(__name__)

def event_type(event):
    '''
    For some reason, GitLab is inconsistent in the field
    name of the event type attribute of a webhook event.
    This function attempts to guess it, returning its value.
    '''
    for key in ['event_type', 'event_name']:
        r = event.get(key)
        if r is not None:
            return r
    raise ValueError(f'no event type found in event {event}')

class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        token = self.headers.get('X-Gitlab-Token')
        if token != self.server.secret_token:
            self.server.logger.warning(
                f'Given secret token {token} does not match '
                f'stored secret token {self.secret_token}. '
                'Ignoring request.'
            )
            return

        print(self.headers)

        # Read data and conclude request.
        data_raw = self.rfile.read(int(self.headers['Content-Length']))
        self.send_response(200)
        self.end_headers()

        # Parse data and call callback.
        self.info = json.loads(data_raw)
        self.server.logger.debug('received hook callback with data:\n' + str(self.info))
        self.server.callback(self.info)

@contextlib.contextmanager
def server_manager(netloc, secret_token, callback, logger = logger):
    '''
    Context manager for an HTTP server that processes webhook notifications from GitLab.
    Only notifications with the correct secret token are considered.

    Arguments:
    * netloc:
        Local network locatio to bind to.
        Only the host and port fields are used.
    * secret_token:
        Secret token to check for incoming webhook notifications.
        Only notifications with the correct secret token are processed.
    * callback:
        Function to call for incoming webhook notifications
        with the correct secret token.
        The argumented passed is the JSON-decoded body of the notification.
    * logger:
        Logger to use in the handler.

    This method does not return.
    '''
    netloc = print_parse.netloc_normalize(netloc)
    address = (netloc.host, netloc.port)

    with path_tools.temp_dir() as dir:
        # Generate an SSL certificate.
        # This is needed for GitLab to connect to our webhook listener.
        # (Only HTTPS listener addresses are allowed, not HTTP.).
        file_cert = dir / 'cert.pem'
        file_key = dir / 'key.pem'
        openssl_tools.generate_cert(file_cert, file_key)

        # Create the server.
        with http.server.HTTPServer(address, Handler) as server:
            server.socket = ssl.wrap_socket(
                server.socket,
                certfile = file_cert,
                keyfile = file_key,
                server_side = True)

            # Set the server attributes used by the handler.
            server.secret_token = secret_token
            server.callback = callback
            server.logger = logger

            yield server
