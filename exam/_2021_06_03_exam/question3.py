from enum import Enum, auto
import itertools
import random

class Node:
    def __init__(self, value, l, r):
        self.height = 1 + max(height(l), height(r))
        self.value = value
        self.l = l
        self.r = r

    def __str__(self):
        return f'[{self.l} < {self.value} < {self.r}]'

def height(node):
    return node.height if node else 0

def format_tree(node, prefix_node = '', prefix_subtree = ''):
    if not node:
        return f'{prefix_node}<empty>\n'
    return ''.join([
        f'{prefix_node}{node.value} [height {node.height - 1}]\n',
        format_tree(node.l, prefix_subtree + '|-- ', prefix_subtree + '|   '),
        format_tree(node.r, prefix_subtree + '|-- ', prefix_subtree + '|   '),
    ])

def format_tree_alt_helper(node, prefix_node, prefix_left, prefix_right):
    if node:
        yield from format_tree_alt_helper(node.l, *map(lambda x: prefix_left + x, ['┌── ', '    ', '│   ']))
        yield f'{prefix_node}{node.value} [height {node.height - 1}]\n'
        yield from format_tree_alt_helper(node.r, *map(lambda x: prefix_right + x, ['└── ', '│   ', '    ']))

def format_tree_alt(node):
    return ''.join(format_tree_alt_helper(node, '', '', ''))

def balancing(node):
    return height(node.l) - height(node.r) if node else 0

def is_balanced(node, threshold):
    return abs(balancing(node)) <= threshold

def rotate_left(node):
    return Node(node.r.value, Node(node.value, node.l, node.r.l), node.r.r)

def rotate_right(node):
    return Node(node.l.value, node.l.l, Node(node.value, node.l.r, node.r))

class Rebalance(Enum):
    LEFT_LEFT = auto()
    LEFT_RIGHT = auto()
    RIGHT_LEFT = auto()
    RIGHT_RIGHT = auto()

format_rebalance = {
    Rebalance.LEFT_LEFT: 'left-left case',
    Rebalance.LEFT_RIGHT: 'left-right case',
    Rebalance.RIGHT_LEFT: 'right-left case',
    Rebalance.RIGHT_RIGHT: 'right-right case',
}

rb_trivial = [None]
rb_easy = [Rebalance.LEFT_RIGHT, Rebalance.RIGHT_LEFT]
rb_hard = [Rebalance.LEFT_LEFT, Rebalance.RIGHT_RIGHT]

def balance(node, threshold):
    if is_balanced(node, threshold):
        return (None, node)

    rb_value = node.value
    if balancing(node) > 0:
        d = balancing(node.l)
        assert d != 0
        if d < 0:
            rb = Rebalance.LEFT_RIGHT
            node = Node(node.value, rotate_left(node.l), node.r)
        else:
            rb = Rebalance.LEFT_LEFT
        node = rotate_right(node)
    else:
        d = balancing(node.r)
        assert d != 0
        if d > 0:
            rb = Rebalance.RIGHT_LEFT
            node = Node(node.value, node.l, rotate_right(node.r))
        else:
            rb = Rebalance.RIGHT_RIGHT
        node = rotate_left(node)
    return ((rb, rb_value), node)

def insert(node, value, threshold):
    if not node:
        return (None, Node(value, None, None))

    if node.value == value:
        return (None, node)

    if value < node.value:
        (rb, l) = insert(node.l, value, threshold)
        node = Node(node.value, l, node.r)
    else:
        (rb, r) = insert(node.r, value, threshold)
        node = Node(node.value, node.l, r)
    if not rb:
        (rb, node) = balance(node, threshold)

    assert is_balanced(node, threshold)
    return (rb, node)

def only_rebalancing_type(rb):
    return rb and rb[0]

def check_balanced(node, threshold):
    if node:
        check_balanced(node.l)
        check_balanced(node.r)
        assert is_balanced(node, threshold)

def rebalancings(vs, threshold):
    node = None
    for v in vs:
        (rb, node) = insert(node, v, threshold)
        yield rb

def has_right_rebalancing(vs, rbss, threshold):
    node = None
    for (v, rbs) in zip(vs, rbss):
        (rb, node) = insert(node, v, threshold)
        if only_rebalancing_type(rb) in rbs:
            return False
    return True

def ilen(it):
    return sum(1 for _ in it)

def find_good_cases(n, threshold):
    for vs in itertools.permutations(range(n)):
        rbs = [only_rebalancing_type(rb) for rb in rebalancings(vs, threshold)]
        easy = ilen(filter(lambda x: x in rb_easy, rbs))
        hard = ilen(filter(lambda x: x in rb_hard, rbs))
        if easy == 1 and hard == 1:
            yield vs

threshold = 2

good_cases = list(find_good_cases(6, threshold))

class Generator:
    def __init__(self, seed):
        self.seed = seed
        r = random.Random(seed)
        self.case = r.choice(good_cases)
        self.sorted_values = sorted(r.sample([k + 1 for k in range(9)], len(self.case)))
        self.values = [self.sorted_values[self.case[i]] for i in range(len(self.case))]

    @staticmethod
    def format_rebalancing(rb, rb_value):
        return f', we have to rebalance at node {rb_value} ({format_rebalance[rb]})'

    def replacements(self, solution = False):
        yield ('tree', ', '.join([str(value) for value in self.values]))

        if solution:
            node = None
            for (i, v) in enumerate(self.values):
                yield(f'el_{i}', str(v))
                (rb, node) = insert(node, v, threshold)
                yield (f'desc_{i}', Generator.format_rebalancing(*rb) if rb else '')
                yield (f'tree_{i}', format_tree_alt(node).rstrip())
                #print(format_tree_alt(node))

#list(Generator(3).replacements(True))
