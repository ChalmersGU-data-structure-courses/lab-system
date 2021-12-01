import itertools
import random

def count_inversions(xs):
    r = 0
    for i in range(len(xs)):
        for j in range(i + 1, len(xs)):
            if xs[i] > xs[j]:
                r += 1
    return r

class CachingIterator:
    def advance(self):
        try:
            self.v = next(self.it)
        except StopIteration:
            self.v = None

    def __init__(self, it):
        self.it = iter(it)
        self.advance()

    def value(self):
        return self.v

    def next(self):
        '''
        Stores the next value and returns the previous value.
        '''
        old = self.v
        self.advance()
        return old

def singularize(xs):
    for x in xs:
        yield [x]

def merge(xs, ys):
    ix = CachingIterator(xs)
    iy = CachingIterator(ys)
    while not (ix.value() is None and iy.value() is None):
        yield (ix if iy.value() is None or (ix.value() is not None and ix.value() <= iy.value()) else iy).next()

def merge_sort_bottom_up_step(xss):
    it = iter(xss)
    while True:
        tss = []
        try:
            for i in range(2):
                tss.append(next(it))
            yield list(merge(*tss))
        except StopIteration:
            if tss:
                yield tss[0]
            return

class Generator:
    def __init__(self, seed):
        self.n = 8
        self.r = random.Random(seed)

    def replacements(self, solution = False):
        while True:
            values = self.r.sample([k + 1 for k in range(9)], self.n)
            c = count_inversions(values)
            if c == self.n * (self.n - 1) // 4:  # average amount of inversions
                break
        yield ('merge', '[' + ', '.join([str(value) for value in values]) + ']')

        if solution:
            xss = list(singularize(values))
            for i in itertools.count(0):
                yield (f'sol_step_{i}', str(xss))
                if len(xss) == 1:
                    break
                xss = list(merge_sort_bottom_up_step(xss))
            yield ('sol_output', str(xss[0]))
            pass
