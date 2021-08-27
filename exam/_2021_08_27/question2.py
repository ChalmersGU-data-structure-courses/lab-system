import collections
import itertools
import random

# General purpose functions

def identity(x):
    return x

def zip_with(f, *xss):
    return itertools.starmap(f, zip(*xss))

def applys(fs, *xss):
    return zip_with(lambda f, x: f(x), fs, *xss)

def on_first(f):
    return lambda xs: applys((f, identity), xs)

def on_second(f):
    return lambda xs: applys((identity, f), xs)

def multidict(xs):
    r = collections.defaultdict(list)
    for (k, v) in xs:
        r[k].append(v)
    return r

# Specific functions.

def format_array(xs):
    return '[{}]'.format(', '.join(xs))

def range_length(rg):
    (a, b) = rg
    return b - a

# Convert an iterable or iterator of numbers into a sorted list of ranges.
# A range is an integral interval [a, b) (inclusive-exclusive).
def rangify(xs):
    starts = set()
    ends = set()
    for x in xs:
        starts.add(x)
        ends.add(x + 1)
    
    def f():
        for x in starts:
            if not x in ends:
                yield (x, True)
        for x in ends:
            if not x in starts:
                yield (x, False)

    def g(it):
        def get(b):
            (x, b1) = next(it)
            assert b1 == b
            return x

        while True:
            try:
                s = get(True)
            except StopIteration:
                return
            e = get(False)
            yield (s, e)

    return list(g(iter(sorted(f(), key = lambda y: y[0]))))

# Uses the Unicode en-dash.
def format_range(r):
    (s, e) = r
    e = e - 1
    return f'{s}' if e == s else f'{s}–{e}'

def format_ranges(rs):
    if not rs:
        return 'no possible values'

    return ', '.join(map(format_range, rs))

def partition_sizes(xs, pivot):
    return (
        len([x for x in xs if x < pivot]),
        len([x for x in xs if x > pivot])
    )

def median(xs):
    ys = sorted(xs)
    return ys[(len(ys) - 1) // 2]

def median_of_three_indices(n):
    return [0, (n - 1) // 2, n - 1]

def first(xs):
    return xs[0]

def median_of_three(xs):
    return median(xs[i] for i in median_of_three_indices(len(xs)))

# # Strategy
#
# We consider the numbers 0, ..., n-2 for n = 9.
# We fix a good subset of two numbers that act as middle and last number for median-of-three pivot selection ({1, 5}).
# We fix good problems (desired size of left partition):
# * L = 2: a range with two numbers excluded, i.e. three ranges,
# * L = 4: single range,
# * L = 6: no solution for median-of-three.
# 
# We randomly map the numbers 0, ..., n-2 in an order-preserving way into the desired range.
# We control for:
# * distance between neighbours and range ends,
# * difference between smallest and largest number,
# * total number of (non-trivial ranges in) solutions.
#
# We then separately permute the positions of the middle and last number and the remaining numbers.
# We control for:
# * number of inversions.
#
# Other randomizations:
# * possible inversion of all values in the considered range,
# * permutation of problems.

def sample_sorted_apart(r, rg, min_distance, min_distance_border, k):
    (low, high) = rg
    for i, x in enumerate(sorted(r.choices(range(low, high - (k - 1) * min_distance - 2 * min_distance_border), k = k))):
        yield x + i * min_distance + min_distance_border

def shuffled(r, xs):
    ys = list(xs)
    r.shuffle(ys)
    return ys

def inversions(xs):
    count = 0
    for i in range(len(xs)):
        for j in range(i + 1, len(xs)):
            if xs[i] > xs[j]:
                count = count + 1
    return count

class Generator:
    def __init__(self, seed, version = None):
        self.n = 9
        self.range = (0, 30)
        self.num_problems = 3
        self.varying = 0

        self.for_median_ranks = [1, 5]
        self.problems = [2, 4, 6] # sizes of the left partition

        self.r = random.Random(seed)
        self.values = self.build_permutation_controlled(self.choose_numbers_controlled())
        self.problems_shuffled = shuffled(self.r, self.problems)

        # wasn't used
        #self.invert = self.r.choice([False, True])

    def build_permutation(self, xs):
        ys = multidict(map(on_first(lambda i: i in self.for_median_ranks), enumerate(xs)))
        it = iter(shuffled(self.r, ys[False]))
        jt = iter(shuffled(self.r, ys[True]))
        for i in range(self.n):
            if i != self.varying:
                yield next(jt if i in median_of_three_indices(self.n) else it)

    def build_permutation_controlled(self, xs):
        while True:
            rs = list(self.build_permutation(xs))
            c = inversions(rs)
            c_max = len(rs) * (len(rs) - 1) / 2
            if c >= 0.45 * c_max - 1 and c <= 0.55 * c_max + 1:
                return rs

    # Values does not yet include a position for the varying value.
    # This position is given by 'varying'.
    def solve(self, values, varying, select_pivot, left_size):
        for x in range(*self.range):
            xs = list(values)
            xs.insert(varying, x)
            if len(frozenset(xs)) == len(xs):
                if partition_sizes(xs, select_pivot(xs))[0] == left_size:
                    yield x

    def sample_sorted_apart_controlled(self):
        while True:
            rs = list(sample_sorted_apart(self.r, self.range, 2, 1, self.n - 1))
            effective_range = (rs[-1] + 1) - rs[0]
            if effective_range in range(range_length(self.range) - 4, range_length(self.range) - 2):
                return rs

    class Statistics:
        def __init__(self, outer_self, xs, select_pivot):
            self.total_num_solutions = 0
            self.non_trivial_ranges = list()
            for problem in outer_self.problems:
                solutions = list(outer_self.solve(xs, 0, select_pivot, problem))
                #if not (outer_self.range[0] in solutions or outer_self.range[1] - 1 in solutions):
                self.total_num_solutions += len(solutions)
                self.non_trivial_ranges.extend(filter(lambda rg: range_length(rg) > 1, rangify(solutions)))

    def choose_numbers_controlled(self):
        while True:
            xs = self.sample_sorted_apart_controlled()

            stats_first = Generator.Statistics(self, xs,
                lambda values: values[self.varying])
            stats_median_of_three = Generator.Statistics(self, xs,
                lambda values: median(values[i] for i in [0, *[j + 1 for j in self.for_median_ranks]]))

            if all([
                len(stats_first.non_trivial_ranges) + len(stats_median_of_three.non_trivial_ranges) == 5,
                stats_first.total_num_solutions + stats_median_of_three.total_num_solutions == 17,
                stats_first.total_num_solutions in range(6, 9),
                stats_median_of_three.total_num_solutions in range(8, 11),
            ]):
                return xs

    def replacements(self, solution = False):
        formatted_values = [str(v) for v in self.values]
        formatted_values.insert(self.varying, 'X')
        yield ('array', format_array(formatted_values))
        yield ('range', format_range(self.range))

        for i, problem in enumerate(self.problems_shuffled):
            yield (f'{i}_L', str(problem))
            yield (f'{i}_R', str(self.n - problem - 1))

            if solution:
                for part, select_pivot in [('A', first), ('B', median_of_three)]:
                    yield (f'{part}_{i}_solution', format_ranges(rangify(self.solve(self.values, self.varying, select_pivot, problem))))

                yield ('array_ordered', ' < '.join(map(str, self.values)))

                for_median = sorted(self.values[k] for k in self.for_median_ranks)
                for (i, x) in enumerate(for_median):
                    yield (f'median_{i}', x)

                    yield (f'median_0_larger', len([() for x in self.values if x > for_median[0]])
                    yield (f'median_1_smaller', len([() for x in self.values if x < for_median[1]])
