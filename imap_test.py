import code
import contextlib
from datetime import datetime, timedelta, timezone
import email
import functools
import re
import threading

import imaplib2
import more_itertools

import general
import print_parse
import threading_tools


imaplib2.DFLT_DEBUG_BUF_LVL = 10

@contextlib.contextmanager
def connection_context(host = None, port = None, user = None, password = None):
    connection = imaplib2.IMAP4_SSL(host = host, port = port)
    try:
        connection.login(user, password)
        yield connection
    finally:
        connection.logout()

_months = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')

def outlook_date(x):
    '''
    Cannot seem to set hours and below.
    '''
    return f'{x.day:02}-{_months[x.month - 1]}-{x.year:04}'

def message_set_range(start = None, end = None):
    '''
    Beware that start and end are interchangable!
    Both are inclusive.
    A value of None corresponds to the latest message.
    What a joke.
    '''
    def f(x):
        return '*' if x is None else str(x)

    return f(start) + ':' + f(end)

def message_set_from_identifiers(identifiers):
    return ','.join(str(identifier) for identifier in identifiers)

def extract_result(x):
    (status, result) = x
    if not status == 'OK':
        raise ValueError(f'status {status}')

    return result

# def parse_untagged_response(r):
#     m = re.match(r'(\d+)\s+\((.*)\)', r)
#     return (int(m.group(1)), m.group(2))

def with_use_uids(connection, cmd, use_uids):
    return functools.partial(connection.uid, cmd) if use_uids else getattr(connection, cmd)

def store(connection, message_set, flags = ['Seen'], remove = False, use_uids = True):
    '''
    We do not parse the result.
    For we lack an easy way of interpreting message numbers in the response if use_uids is set.
    '''
    call = with_use_uids(connection, 'store', use_uids)
    extract_result(call(
        message_set,
        ('-' if remove else '+') + 'FLAGS',
        pp_flags.print(flags),
    ))

def store_one(connection, identifier, flags = ['Seen'], remove = False, use_uids = True):
    return store(
        connection,
        message_set_from_identifiers([identifier]),
        flags = flags,
        remove = remove,
        use_uids = use_uids,
    )

def search(connection, *criteria, use_uids = True):
    call = with_use_uids(connection, 'search', use_uids)
    [ids_bytes] = extract_result(call(None, *criteria))
    return [int(s) for s in ids_bytes.split()]

def fetch(connection, message_set, specs, use_uids = True):
    '''
    Arguments:
    * specs:
        List of part specifications.
        This is a parsing function operating on a list of segments.
        The parsing function has an attribute 'parts' for the query part.
    * use_uids: if set, use UIDs instead of message numbers.

    Returns a sorted dictionary.

    Result structure of connection.fetch with (RFC822):
    * List consisting of blocks of length two.
      In each block:
      - the first entry is a tuple of the following:
        + bytes for 'uid (RFC822 {message_length?))'
        + bytes for the email in RFC822 format
      - the second entry is the flags.r

    Result structure of fetching with BODY.PEEK[HEADER.FIELDS (SUBJECT)]:
    * List consisting of blocks of length two.
      In each block:
      - the first entry is a tuple of the following:
        + bytes for 'uid (BODY[HEADER.FIELDS (SUBJECT)] {message_length?}'
        + bytes for 'Subject: ...\r\n\r\n'
      - the second entry is b')'

    When fetching with (FLAGS BODY.PEEK[HEADER.FIELDS (SUBJECT)]),
    the flags are included in the first part of each pair.
    However, when fetching with (BODY.PEEK[HEADER.FIELDS (SUBJECT)] FLAGS),
    the flags are included in the second entry of each block.

    The general result structure of connection.fetch seems to be a chunked list.
    Each chunk consists of a number of query-part-response pairs (both bytes) followed by a suffix (also bytes).
    '''
    call = with_use_uids(connection, 'fetch', use_uids)
    if use_uids:
        specs = [spec_uid, *specs]

    parts = '(' + ' '.join(part for spec in specs for part in spec.parts) + ')'
    result = extract_result(call(message_set, parts))
    result_chunks = more_itertools.split_after(result, lambda x: isinstance(x, bytes))

    def process_result_chunk(result_chunk):
        (*query_part_and_response_list, suffix) = result_chunk
        message_number = None

        def segments():
            for (query_part, response) in query_part_and_response_list:
                yield query_part
                yield response
            yield suffix

        segments = list(segments())
        (message_number, segments[0]) = segments[0].split(b' (', maxsplit = 1)
        segments[-1] = general.remove_suffix(segments[-1], b')')
        return (int(message_number), tuple(spec(segments) for spec in specs))

    it = map(process_result_chunk, result_chunks)
    if use_uids:
        def postprocess(x):
            (message_number, (uid, *results)) = x
            return (uid, results)

        it = map(postprocess, it)

    return general.sdict(sorted(it, key = lambda x: x[0]))

def fetch_one(connection, identifier, specs, use_uids = True):
    return fetch(
        connection,
        message_set_from_identifiers([identifier]),
        *specs,
        use_uids = use_uids,
    )[identifier]

def with_parts(*parts):
    def g(f):
        f.parts = parts
        return f
    return g

def segment_parse_uid(segment):
    match = re.match(br'\s*UID ([\d]+)', segment)
    return (int(match.group(1)), segment[match.end():])

@with_parts('UID')
def spec_uid(segments):
    (uid, segments[0]) = segment_parse_uid(segments[0])
    return uid

pp_flag = print_parse.regex_non_canonical(b'\\{}', br'\\(.*)')

pp_flags = print_parse.compose(
    print_parse.tuple(pp_flag),
    print_parse.join_bytes(),
    print_parse.parens_bytes,
)

def segment_parse_flags(segment):
    print(segment)
    match = re.match(br'\s*FLAGS (\([^)]*\))', segment)
    return (pp_flags.parse(match.group(1)), segment[match.end():])

@with_parts('FLAGS')
def spec_flags(segments):
    (flags, segments[0]) = segment_parse_flags(segments[0])
    return flags

def pop_data(segments):
    segments.pop(0)
    return segments.pop(0)

@with_parts('BODY.PEEK[HEADER]')
def spec_headers(segments):
    return email.parser.BytesHeaderParser().parsebytes(pop_data(segments))

@with_parts('BODY.PEEK[]')
def spec_email(segments):
    return email.parser.BytesParser().parsebytes(pop_data(segments))

def idle_until_new_email(connection):
    waiting = True
    while waiting:
        event = threading.Event()

        def callback(result):
            event.set()

        connection.idle(callback = callback)
        event.wait()
        print('interrupted')
        for (typ, result) in connection.pop_untagged_responses():
            if typ == 'EXISTS':
                print('no longer waiting')
                waiting = False

# def idle_until_new_email(connection, message_number_current):
#     message_number = message_number_current
#     while message_number == message_number_current:
#         connection.idle()
#         for (typ, result) in connection.pop_untagged_responses():
#             if typ == 'EXISTS':
#                 message_number = max(message_number, int(result[0]))
#     return message_number

class ProcessThread(threading.Thread):
    def __init__(self):
        pass


def process_emails_from(connection, date, decide_if_process, process):
    '''
    Arguments:
    * decide_if_process:
        Function taking parsed headers.
        Returns a boolean indicating if this message should be processed.
    * process:
        Function processing a parsed email.
        On completion, the email is marked as 'seen'.
    '''
    def fetch_metadata_after(uid):
        return fetch(connection, message_set_range(uid + 1), [spec_flags, spec_headers])

    uid_start = None
    while True:
        if uid_start is None:
            uids = search(connection, 'since', outlook_date(past))
            if uids:
                uid_start = min(uids)
        if uid_start:
            metadata = fetch(connection, message_set_range(uid_start + 1), [spec_flags, spec_headers])
            for (uid, (flags, headers)) in metadata.items():
                if uid >= uid_start:
                    uid_start = uid + 1
                    if not 'seen' in flags and decide_if_process(headers):
                        [email] = fetch_one(connection, uid, [spec_email])
                        process(email)
                        store_one(connection, uid)

        idle_until_new_email(connection)

now = datetime.now(timezone.utc)
past = now - timedelta(minutes = 6000)

# connection = imaplib2.IMAP4_SSL('imap.chalmers.se', port = 993)
# connection.login('sattler', 'Gw<G#9Q8DV')
# connection.select('INBOX')

#def run():
with connection_context('imap.chalmers.se', user = 'sattler', password = 'Gw<G#9Q8DV') as connection:
    connection.select('INBOX')

    def decide_if_process(headers):
        print(f'new message: {headers["Subject"]}')
        return False

    def process(email):
        pass

    def worker():
        print('worker start')
        idle_until_new_email(connection)
        #process_emails_from(connection, past, decide_if_process, process)
        print('worker end')

    thread = threading.Thread(target = worker)
    with threading_tools.thread_manager(thread):
        print('main body start')
        code.interact(local = locals())
        print('main body end')

#run()

#connection = imaplib2.IMAP4_SSL('imap.chalmers.se', port = 993)
#connection.login('sattler', 'Gw<G#9Q8DV')
#connection.select('INBOX')

#connection = imaplib2.IMAP4_SSL('imap.gmail.com', port = 993)
#connection.login('sattler.christian@gmail.com', 'Jensen#2')
#connection.select('INBOX')

#for mailbox in ['Trash', 'Drafts', 'Sent']:
#    connection.unsubscribe(mailbox)
#connection.subscribe('INBOX')

#uids = search(connection, 'since', outlook_date(past))

#r = fetch(connection, 11163, 'BODY.PEEK[1]')

#r = fetch(connection, message_set_range(12927), [spec_headers, spec_flags, spec_headers])
