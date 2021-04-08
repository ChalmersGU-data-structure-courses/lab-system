import general
import random

def swap(xs, i, j):
    x = xs[i]
    xs[i] = xs[j]
    xs[j] = x

class QuestionQuicksort:
    def is_good(self):
        ys = list(self.array)
        pivot = ys[0]

        lower = len([y for y in ys if y < pivot])
        higher = len([y for y in ys if y > pivot])
        if abs(lower - higher) != 2:
            return False

        lo = 1
        hi = len(ys) - 1
        swaps = 0

        while True:
            lucky = True
            while lo <= hi:
                if ys[lo] < pivot:
                    lo = lo + 1
                    lucky = False
                else:
                    break

            while lo <= hi:
                if ys[hi] > pivot:
                    hi = hi - 1
                    lucky = False
                else:
                    break

            if not lo <= hi:
                break

            if lucky:
                return False

            swap(ys, lo, hi)
            swaps = swaps + 1
            lo = lo + 1
            hi = hi - 1

        return swaps == 2

    def __init__(self, seed):
        self.r = random.Random(seed)
        self.n = 9

        while True:
            self.array = self.r.sample(range(1, 20), self.n)
            if self.is_good():
                break

    # Doesn't handle the case where one partition is empty.
    def solution(self, ys, partitions):
        pivot = ys[0]
        lo = 1
        hi = len(ys) - 1
        while True:
            while lo <= hi:
                def f(lo, msg):
                    yield f'{ys[lo]} < {pivot}? {msg}'
                if ys[lo] < pivot:
                    yield from f(lo, 'Yes, we advance lo.')
                    lo = lo + 1
                else:
                    yield from f(lo, 'No.')
                    break

            while lo <= hi:
                def f(hi, msg):
                    yield f'{ys[hi]} > {pivot}? {msg}'
                if ys[hi] > pivot:
                    yield from f(hi, 'Yes, we advance hi.')
                    hi = hi - 1
                else:
                    yield from f(hi, 'No.')
                    break

            if not lo <= hi:
                break

            yield f'We swap {ys[lo]} and {ys[hi]} and advance lo and hi.'
            swap(ys, lo, hi)
            lo = lo + 1
            hi = hi - 1

        yield f'Finally, we swap the pivot {pivot} with {ys[hi]}.'
        swap(ys, 0, hi)
        for a, b in (0, hi), (hi, hi + 1), (hi + 1, len(ys)):
            partitions.append(ys[a : b])

    def replacements(self, solution):
        yield ('array_to_partition', str(self.array))

        if not solution:
            return

        yield('quick_sol_lo', str(1))
        yield('quick_sol_hi', str(len(self.array) - 1))
        yield('quick_sol_pivot', str(self.array[0]))

        ys = list(self.array)
        partitions = []
        msgs = list(self.solution(ys, partitions))
        k = 16 # TODO: only need 14 (change Google document)
        assert len(msgs) <= k, f'Have {len(msgs)} messages.'
        for i in range(k):
            yield (f'quick_sol_{i}', msgs[i] if i < len(msgs) else '')
        for i in range(3):
            yield (f'quick_sol_partition_{i}', ', '.join(map(str, partitions[i])))

class QuestionMergeSort:
    def is_good(self):
        ys = list(self.array)
        pivot = ys[0]

    def __init__(self, seed):
        patterns = [
            [0, 1, 1, 0, 0, 1, 1, 0, 1],
            [0, 1, 1, 0, 1, 1, 0, 0, 1],
            [0, 1, 1, 0, 1, 0, 0, 1, 1],
            [1, 0, 0, 1, 1, 0, 1, 1, 0],
            [1, 0, 1, 1, 0, 0, 1, 1, 0],
        ]

        self.r = random.Random(seed)
        pattern = self.r.choice(patterns)

        xs = sorted(self.r.sample(range(1, 20), len(pattern)))
        self.lists = [[], []]
        for i in range(len(pattern)):
            self.lists[pattern[i]].append(xs[i])

    def replacements(self, solution):
        for i in range(len(self.lists)):
            yield (f'merge_{i}', str(self.lists[i]))

        if not solution:
            return

        indices = [0 for _ in self.lists]
        def resolve(i):
            return self.lists[i][indices[i]]

        output = []
        step = 0
        while True:
            valid = [indices[i] < len(self.lists[i]) for i in range(len(self.lists))]
            if not any(valid):
                break

            if all(valid):
                msg = f'Comparing {resolve(0)} and {resolve(1)}. '
                choice = 0 if resolve(0) < resolve(1) else 1
            else:
                msg = ''
                choice = 0 if valid[0] else 1

            yield (f'merge_sol_{step}', f'{msg}Writing {resolve(choice)}.')
            output.append(resolve(choice))
            indices[choice] = indices[choice] + 1
            step = step + 1

        yield ('merge_sol_output', str(output))
