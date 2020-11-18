# This file patches the http.client module to make it have debug logging.
# Based on: https://stackoverflow.com/a/16337639
import http.client
import logging

httpclient_logger = logging.getLogger("http.client")

def httpclient_log(*args):
    httpclient_logger.log(logging.DEBUG, " ".join(args))

# mask the print() built-in in the http.client module to use logging instead
http.client.print = httpclient_log

# log debug messages
http.client.HTTPConnection.debuglevel = 1
