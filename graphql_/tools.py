import logging
import types

from gql.dsl import DSLQuery, dsl_gql

import util.general


logger = logging.getLogger(__name__)


def query(*args, **kwargs):
    return dsl_gql(DSLQuery(*args, **kwargs))


def query_with_variables(var, *args, **kwargs):
    query = DSLQuery(*args, **kwargs)
    query.variable_definitions = var
    return dsl_gql(query)


def wrap_query_execution(f, field):
    return lambda *fields: f(field.select(*fields))[field.name]


def wrap_query_execution_many(f, field_iter):
    for field in field_iter:
        f = wrap_query_execution(f, field)
    return f


def with_processing(query):
    return query if isinstance(query, tuple) else (query, util.general.identity)


def only_query(query):
    (query, process) = with_processing(query)
    return query


def only_process(query):
    (query, process) = with_processing(query)
    return process


def distribute(f):
    def g(*args, **kwargs):
        def process(r):
            def update(label, process):
                r[label] = process(r[label])

            for arg in args:
                (query, process_inner) = with_processing(arg)
                update(query.name, process_inner)
            for label, arg in kwargs.items():
                update(label, only_process(arg))
            return types.SimpleNamespace(**r)

        return (
            f(
                *map(only_query, args),
                **{label: only_query(arg) for (label, arg) in kwargs.items()},
            ),
            process,
        )

    return g


def tupling(f):
    def g(*args):
        def process(r):
            def g(arg):
                (query, process_inner) = with_processing(arg)
                return process_inner(r[query.name])

            return tuple(map(g, args))

        return (f(*map(only_query, args)), process)

    return g


def lift(f):
    def g(arg):
        (query, process_inner) = with_processing(arg)

        def process(r):
            return process_inner(r[query.name])

        return (f(query), process)

    return g


def over_list(arg):
    (query, process_inner) = with_processing(arg)

    def process(xs):
        for i in range(len(xs)):
            xs[i] = process_inner(xs[i])
        return xs

    return (query, process)


def over_list_unique(arg):
    (query, process_inner) = with_processing(arg)

    def process(xs):
        (x,) = xs
        return process_inner(x)

    return (query, process)


def nodes(field):
    def f(arg):
        return lift(field.select)(over_list(arg))

    return f


def nodes_unique(field):
    def f(arg):
        return lift(field.select)(over_list_unique(arg))

    return f


def labelled(f):
    def g(*args):
        n = len(args)

        def name(i):
            return f"q{i}"

        def process(r):
            return [only_process(args[i])(r[name(i)]) for i in range(n)]

        return (f(**{name(i): only_query(args[i]) for i in range(n)}), process)

    return g
