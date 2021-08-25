# Modified from 2021-04-07 exam.
# Uses max-heap instead of min-heap. 
import collections
import heapq
import random

# General purpose functions

def multidict(xs):
    r = collections.defaultdict(list)
    for (k, v) in xs:
        r[k].append(v)
    return r

# Specific functions.

def duplication(xs):
    return sorted(len(ys) for ys in multidict((x, x) for x in xs).values())

def swap(xs, i, j):
    x = xs[i]
    xs[i] = xs[j]
    xs[j] = x

# modified to make max_heap
def make_heap(xs):
    r = []
    for x in xs:
        heapq.heappush(r, -x)
    return [-x for x in r]

class AmbiguousRemoval(Exception):
    pass

# This is a generator function that passes through its argument generator functions.
# Does not change xs.
def analyze_removal(xs, start = None, step = None, end = None):
    heap = list(xs)
    first = heap[0]
    last = heap.pop()
    heap[0] = last

    if start:
        yield from start(first, last)

    def valid(k):
        return k < len(heap)

    j = 0
    msgs = list()
    while True:
        l = 2 * j + 1
        r = 2 * j + 2
        ambiguous = False
        if not valid(l):
            next = -1
        elif not valid(r):
            next = l
        else:
            if heap[l] == heap[r]:
                raise AmbiguousRemoval()

            next = l if heap[l] >= heap[r] else r
            child = {l: 'left', r: 'right'}[next]
        if not (next != -1 and heap[next] > heap[j]):
            break

        if step:
            yield from step(heap[j], child, heap[next])

        swap(heap, j, next)
        j = next

    if end:
        yield from end(heap)

class Generator:
    def generate_good_heap(self):
        while True:
            xs = self.r.choices(range(2 * self.n), k = self.n)
            if duplication(xs) != [1] * (self.n - 4) + [2, 2]:
                continue
            xs = make_heap(xs)

            # Some child should equal its parent.
            good_duplication = False
            for i in range(1, self.n):
                if xs[i] == xs[int((i - 1) / 2)]:
                    good_duplication = True
            if not good_duplication:
                continue

            # Ensure exactly 2 swaps when removing the maximum.
            def step(current, child, next):
                yield ()

            try:
                num_swaps = len(list(analyze_removal(xs, step = step)))
            except AmbiguousRemoval:
                continue

            if not num_swaps == 2:
                continue

            return (xs, 'This is a max-heap.')

    def generate_bad_heap(self):
        xs = sorted(self.r.sample(range(2 * self.n), self.n), reverse = True)
        i = self.r.choice(range(int(self.n / 2 + 1), self.n))
        p = int((i - 1) / 2)
        swap(xs, i, p)
        return (xs, f'This is not a max-heap: the element {xs[i]} is larger than its parent {xs[p]}.')

    def generate_ugly_heap(self):
        xs = sorted(self.r.sample(range(2 * self.n), self.n), reverse = False)
        return (xs, f'This is not a max-heap: the root {xs[0]} is not the maximum. (Note that it is a min-heap instead.)')

    def __init__(self, seed = 0, version = None):
        self.r = random.Random(seed)
        self.n = 10

        self.good = self.generate_good_heap()
        self.bad = self.generate_bad_heap()
        self.ugly = self.generate_ugly_heap()

        self.heaps = [self.good, self.bad, self.ugly]
        self.r.shuffle(self.heaps)

    def replacements(self, solution = False):
        for i in range(len(self.heaps)):
            yield (f'heap_{i}', str(self.heaps[i][0]))

        if solution:
            for i in range(len(self.heaps)):
                yield (f'sol_heap_{i}', str(self.heaps[i][1]))

            def start(first, last):
                yield ('sol_remove_swap_delete', f'We swap the root {first} with the last element {last}, delete the new last element {first}, and then sink down the root {last}:')

            i = 0
            def step(current, child, next):
                nonlocal i
                yield(f'sol_remove_sink_{i}', f'We swap {current} with its {child} child {next}.')
                i += 1

            def end(heap):
                yield ('sol_heap', str(heap))

            yield from analyze_removal(list(self.good[0]), start = start, step = step, end = end)
