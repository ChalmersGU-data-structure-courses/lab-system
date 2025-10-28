import socket

import util.url


def get_connect_info(netloc: util.url.NetLoc, callback):
    """
    Returns the value of the given callback function applied to a socket
    connected via UDP (connection-less) to the given net location.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(netloc.host, netloc.port)
        return callback(s)


def get_local_ip_routing_to(netloc: util.url.NetLoc):
    """
    Get the net location (ip address) of the local interface routing to the given netloc.
    No attempt at connection is made.
    This assumes that all socket protocols use the same route.

    Inspired by: https://stackoverflow.com/a/28950776
    """
    return get_connect_info(netloc, lambda s: s.getsockname()[0])
