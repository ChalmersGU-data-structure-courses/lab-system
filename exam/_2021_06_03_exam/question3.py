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

def balancing(node):
    return height(node.l) - height(node.r) if node else 0

def is_balanced(node, threshold = 1):
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

rb_trivial = [None]
rb_easy = [Rebalance.LEFT_RIGHT, Rebalance.RIGHT_LEFT]
rb_hard = [Rebalance.LEFT_LEFT, Rebalance.RIGHT_RIGHT]

def balance(node, threshold = 1):
    #print(f'balancing {node} with threshold {threshold}')
    if is_balanced(node, threshold = threshold):
        rb = None
    elif balancing(node) > 0:
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
    return (rb, node)

def insert(node, value, threshold = 2):
    #print(f'inserting {value} into {node}')
    if not node:
        return (None, Node(value, None, None))

    if node.value == value:
        return (None, node)

    if value < node.value:
        (rb, l) = insert(node.l, value, threshold = threshold)
        node = Node(node.value, l, node.r)
    else:
        (rb, r) = insert(node.r, value, threshold = threshold)
        node = Node(node.value, node.l, r)
    if not rb:
        (rb, node) = balance(node, threshold = threshold)

    assert is_balanced(node, threshold = threshold)
    return (rb, node)

def check_balanced(node, threshold = 2):
    if node:
        check_balanced(node.l)
        check_balanced(node.r)
        assert is_balanced(node, threshold = threshold)

# node = None
# for v in [1, 2, 3, 4, 5, 6, 7]: #[7, 6, 5, 4, 3, 2, 1]:
#     (rb, node) = insert(node, v, threshold = 2)
#     print()
#     print(rb)
#     print(node)
#     check_balanced(node, threshold = 2)

def rebalancings(vs, threshold = 2):
    node = None
    for v in vs:
        (rb, node) = insert(node, v, threshold = threshold)
        yield rb

def has_right_rebalancing(vs, rbss, threshold = 2):
    node = None
    for (v, rbs) in zip(vs, rbss):
        (rb, node) = insert(node, v, threshold = threshold)
        if not rb in rbs:
            return False
    return True

def ilen(it):
    return sum(1 for _ in it)

def find_good_cases(n, threshold = 2):
    for vs in itertools.permutations(range(n)):
        rbs = list(rebalancings(vs))
        easy = ilen(filter(lambda x: x in rb_easy, rbs))
        hard = ilen(filter(lambda x: x in rb_hard, rbs))
        if easy == 1 and hard == 1:
            yield vs

good_cases = list(find_good_cases(6, threshold = 2))

class Generator:
    def __init__(self, seed):
        self.seed = seed
        r = random.Random(seed)
        self.case = r.choice(good_cases)
        self.sorted_values = sorted(r.sample([k + 1 for k in range(9)], len(self.case)))
        self.values = [self.sorted_values[self.case[i]] for i in range(len(self.case))]

    def replacements(self, solution = False):
        yield ('tree', ', '.join([str(value) for value in values]))
