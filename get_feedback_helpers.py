import re

def implicit_group(pattern):
    return f'(?:{pattern})'

pattern_linebreak = implicit_group(r'\r*\n')
pattern_stars = implicit_group(r'\*{10,}')
pattern_question_begin = implicit_group(f'/{pattern_stars}{pattern_linebreak}')
pattern_question_end = implicit_group(f'{pattern_stars}/?{pattern_linebreak}?')
pattern_question_line = implicit_group(f'\\*\\*[^\\n]*{pattern_linebreak}')
pattern_question = f'{pattern_question_begin}({pattern_question_line}*){pattern_question_end}'

def parse_answers_iter(content, only_appendix = False):
    matches = list(re.finditer(pattern_question, content))
    in_appendix = False
    for i in range(len(matches)):
        lines = list(map(lambda line: line.lstrip('**').strip(), matches[i].group(1).splitlines()))
        if lines[0].startswith('Appendix'):
            in_appendix = True
            del lines[0]
            while not lines[0].strip():
                del lines[0]
        if not only_appendix or in_appendix:
            yield (
                tuple(lines),
                content[matches[i].end() : len(content) if i + 1 == len(matches) else matches[i + 1].start()].strip(),
            )

def parse_answers_list(content):
    return list((q, a) for q, a in parse_answers_iter(content))

def parse_answers(content):
    return dict((q[0][0], (q, a)) for q, a in parse_answers_iter(content))
