import re
import string

class EscapingFormatter(string.Formatter):
    '''
    A subclass of string.Formatter that allows literal text to be escaped.

    TODO: Propose to Python developers to include this generalization in string.Formatter.
          It is backward-compatible (except if users of string.Formatter have subclassed
          with an instance method already called 'escape_literal').
    '''

    def escape_literal(self, s):
        '''
        This method gets called in 'vformat' to escape literal text.
        The default implementation returns its string argument.
        Subclasses may override this method to achieve custom escaping behaviour.
        '''
        return s

    def vformat(self, format_string, args, kwargs):
        used_args = set()
        result, _ = self._vformat(format_string, args, kwargs, used_args, 2)
        self.check_unused_args(used_args, args, kwargs)
        return result

    def _vformat(self, format_string, args, kwargs, used_args, recursion_depth, auto_arg_index=0):
        '''
        The implementation is copied from CPython.
        The only change: calls to escape_literal for literal text have been added.
        '''
        result = []
        for (literal_text, field_name, format_spec, conversion) in self.parse(format_string):

            # output the literal text
            if literal_text:
                result.append(self.escape_literal(literal_text))

            # if there's a field, output it
            if field_name is not None:
                # this is some markup, find the object and do
                #  the formatting

                # handle arg indexing when empty field_names are given.
                if field_name == '':
                    if auto_arg_index is False:
                        raise ValueError('cannot switch from manual field '
                                         'specification to automatic field '
                                         'numbering')
                    field_name = str(auto_arg_index)
                    auto_arg_index += 1
                elif field_name.isdigit():
                    if auto_arg_index:
                        raise ValueError('cannot switch from manual field '
                                         'specification to automatic field '
                                         'numbering')
                    # disable auto arg incrementing, if it gets
                    # used later on, then an exception will be raised
                    auto_arg_index = False

                # given the field_name, find the object it references
                #  and the argument it came from
                obj, arg_used = self.get_field(field_name, args, kwargs)
                used_args.add(arg_used)

                # do any conversion on the resulting object
                obj = self.convert_field(obj, conversion)

                # expand the format spec, if needed
                format_spec, auto_arg_index = self._vformat(
                    format_spec, args, kwargs,
                    used_args, recursion_depth-1,
                    auto_arg_index=auto_arg_index)

                # format the object and append to the result
                result.append(self.format_field(obj, format_spec))

        return ''.join(result), auto_arg_index        

class RegexEscapingFormatter(EscapingFormatter):
    '''
    A formatter for regular expressions where literal text
    spans are just that and escaped into regular expressions.
    '''

    def escape_literal(self, s):
        return re.escape(s)

regex_escaping_formatter = RegexEscapingFormatter()
