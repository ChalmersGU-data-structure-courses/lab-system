import general
import heapq
import random

def duplication(xs):
    return sorted(len(ys) for ys in general.group_by(lambda x: x, xs).values())

def swap(xs, i, j):
    x = xs[i]
    xs[i] = xs[j]
    xs[j] = x

def make_heap(xs):
    r = []
    for x in xs:
        heapq.heappush(r, x)
    return r

class Question:
    # TODO: enforce that removing the minimum takes same amount of swaps
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

            return (xs, 'This is a heap.')

    def generate_bad_heap(self):
        xs = sorted(self.r.sample(range(2 * self.n), self.n))
        i = self.r.choice(range(int(self.n / 2 + 1), self.n))
        p = int((i - 1) / 2)
        swap(xs, i, p)
        return (xs, f'This is not a heap: the element {xs[i]} is less than its parent {xs[p]}.')

    def generate_ugly_heap(self):
        xs = sorted(self.r.sample(range(2 * self.n), self.n), reverse = True)
        return (xs, f'This is not a heap: the root {xs[0]} is not the minimum. (Note that it is a max-heap instead.)')

    def __init__(self, seed):
        self.r = random.Random(seed)
        self.n = 10

        self.good = self.generate_good_heap()
        self.bad = self.generate_bad_heap()
        self.ugly = self.generate_ugly_heap()

        self.heaps = [self.good, self.bad, self.ugly]
        self.r.shuffle(self.heaps)

    def replacement(self):
        for i in range(len(self.heaps)):
            yield (f'heap_{i}', str(self.heaps[i][0]))

    def replacement_sol(self):
        yield from self.replacement()

        for i in range(len(self.heaps)):
            yield (f'sol_heap_{i}', str(self.heaps[i][1]))

        heap = self.good[0]
        first = heap[0]
        last = heap.pop()
        heap[0] = last
        yield ('sol_remove_swap_delete', f'We swap the root {first} with the last element {last}, delete the new last element {first}, and then sink down the root {last}:')

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
                next = l if heap[l] <= heap[r] else r
                ambiguous = heap[l] == heap[r]
                child = {l: 'left', r: 'right'}[next]
            if not (next != -1 and heap[next] < heap[j]):
                break
            msgs.append(f'We swap {heap[j]} with its {child} child {heap[next]}.{" Note: we could also have chosen its right child!" if ambiguous else ""}')
            swap(heap, j, next)
            j = next
        for i in range(3):
            yield (f'sol_remove_sink_{i}', msgs[i] if i < len(msgs) else '')
        yield ('sol_heap', str(heap))
