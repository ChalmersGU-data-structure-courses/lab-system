import collections
import logging


logger = logging.getLogger(__name__)

Config = collections.namedtuple(
    'Config',
    ['location_name', 'item_name', 'item_formatter', 'logger', 'on_duplicate'],
    defaults = [logger, True],
)
Config.__doc__ = '''
    Configuration for functions in this module.

    Fields:
    * location_name:
        Name of the source location from which the items are parsed.
        Only used for formatting log messages.
    * item_name:
        Name of the type of items to be parsed.
        Only used for formatting log messages.
    * item_formatter:
        Callable to format details of an item for use in a log message.
        Takes as arguments the project and an the item.
        Returns a line-feed-terminated log string describing the item.
        This can be a multi-line string.
        Only used for formatting log messages.
    * logger:
        Logger to use.
        Defaults to module logger.
    * on_duplicate:
        How to handle duplicates if parsing into a dictionary:
        - None: Raise an exception.
        - True: Log a warning and keep the first item.
        - False: Log a warning and keep the second item.
        - callable: use the result from duplicates(key, first_value, second_value).
    '''

def parse_items(config, parser, parser_name, parse_results, items):
    '''
    Parse items using a given parser.

    Arguments:
    * config: parsing configuration, instance of Config.
    * parser_name:
        Name of the parser.
        Only used for formatting log messages.
    * parser:
        Parser called on each items.
        On parse failure, returns None.
    * parsed_items:
        The list or dictionary to populate with parse results from succeeding parses.
        If a dictionary, parse results are of the form (key, value).
        If None, then no parse results are stored.
    * items: Iterable of items to parse.

    This is a generator function that returns yields all unparsed items.
    The generator must be exhausted for all parsable items to have been parsed.

    If an item with key existing in parsed_items is parsed, it is ignored.
    When that happens, a warning is logged.

    You may chain calls to parse_items to parse several item types at the same time.
    '''
    def format(heading, item):
        r = config.item_formatter(item)
        return heading + (' ' if r.splitlines() == 1 else '\n') + r

    if isinstance(parse_results, dict):
        parsed_items = dict()

    for item in items:
        parse_result = parser(item)
        if parse_result is None:
            yield item
            continue

        if parse_result is None:
            pass
        elif isinstance(parse_results, list):
            parse_results.append(parse_result)
        elif isinstance(parse_results, dict):
            (key, value) = parse_result
            value_prev = parse_results.get(key)
            if value_prev is not None:
                item_prev = parsed_items[key]
                if callable(config.on_duplicate):
                    value = config.on_duplicate(key, value_prev, value)
                else:
                    msg = f'Duplicate {parser_name} {config.item_name} with key {key} in {config.location_name}\n'
                    if config.on_duplicate is None:
                        raise ValueError(msg)

                    msg += format(f'First {config.item_name}:', item_prev)
                    msg += format(f'Second {config.item_name}:', item)
                    (item, value, ignore) = {
                        True: (item_prev, value_prev, 'second'),
                        False: (item, value, 'first'),
                    }[config.on_duplicate]
                    msg += f'Ignoring {ignore} {config.item_name}.\n'
                    logger.warning(msg)
            parsed_items[key] = item
            parse_results[key] = value
        else:
            ValueError(f'{parsed_items} is not a list or dictionary')

def log_unrecognized_items(config, items):
    '''
    Log warnings for remaining items (being seen as unrecognized).

    Arguments:
    * config: parsing configuration, instance of Config.
    * items:
        Iterable of items to parse.
        This will be exhausted by this method.
    '''
    for item in items:
        config.logger.warning(
            f'Unrecognized {config.item_name} in {config.location_name}:\n' + config.item_formatter(item)
        )

def parse_all_items(config, parser_data, items):
    '''
    Parse all items using specified parsers.
    On each item, we try all specified parsers.
    If none matches, a warning is logged.

    Arguments:
    * config: parsing configuration, instance of Config.
    * parser_data:
        Iterable of producing triples (parser, parser_name, parse_results)
        for use with parse_item.
    * items:
        Iterable of items to parse.
        This will be exhausted by this method.
    '''
    for (parser, parser_name, parse_results) in parser_data:
        items = parse_items(config, parser, parser_name, parse_results, items)
    log_unrecognized_items(config, items)
