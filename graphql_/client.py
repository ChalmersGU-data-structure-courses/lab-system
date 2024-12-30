import functools
import itertools

import gql
import more_itertools
from gql.dsl import DSLSchema

from graphql_.tools import labelled, query, with_processing


def retrieve_all_from_cursor(callback, cursor=None):
    """
    The callback function takes a cursor and returns a pair (results, cursor).
    Here:
    * results is an iterable of results up until the next cursor,
    * cursor is the next cursor, or None if the end was reached.

    Returns an iterable of all the results.
    """
    while True:
        (results, cursor) = callback(cursor)
        yield from results
        if cursor is None:
            break


class ClientBase:
    def __init__(self, transport, path_schema):
        self.transport = transport
        self.client = gql.Client(
            transport=self.transport,
            schema=path_schema.read_text(),
        )
        self.ds = DSLSchema(self.client.schema)

        self.queue_queries = []
        self.queue_results = []

    @functools.cached_property
    def session(self):
        return self.client.connect_sync()

    def close(self):
        if "session" in self.__dict__:
            self.session.close()
            del self.session

    # pylint: disable-next=redefined-outer-name
    def execute(self, query, values=None):
        (query, process) = with_processing(query)
        # print(print_ast(query))
        return process(self.session.execute(query, variable_values=values))

    def execute_queries(self, queries):
        def name(i):
            return f"q{i}"

        queries = more_itertools.countable(queries)
        result = self.execute_query(
            **{name(i): query for (i, query) in enumerate(queries)}
        )
        for i in more_itertools.take(queries.items_seen, itertools.count()):
            yield result[name(i)]

    # pylint: disable-next=redefined-outer-name
    def queue_query(self, query, process=None):
        (query, process) = with_processing(query)

        i = len(self.queue_queries)
        self.queue_queries.append(query)
        results = self.queue_results

        def access_result():
            return process(results[i])

        return access_result

    def flush_queue(self):
        if self.queue_queries:
            self.queue_results.extend(
                self.execute(labelled(query)(*self.queue_queries))
            )
        self.queue_queries = []
        self.queue_results = []
