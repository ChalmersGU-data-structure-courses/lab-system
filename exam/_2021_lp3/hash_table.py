import itertools
import random

def inc(table, i):
    return (i + 1) % len(table)

def extract(table, i, j):
    r = list()
    while i != j:
        r.append(table[i])
        i = inc(table, i)
    return r

def insert(table, value):
    i = value % len(table)
    while table[i] != -1:
        i = inc(table, i)
    table[i] = value

def find_cluster_end(table, i):
    while True:
        i = inc(table, i)
        if table[i] == -1:
            return i

def find_insertion_orders(table, i):
    j = find_cluster_end(table, i)
    cluster = extract(table, i + 1, j)

    for p in itertools.permutations(cluster):
        scatch = [-1 for _ in range(len(table))]
        for x in p:
            insert(scatch, x)
        if extract(scatch, i + 1, j) == cluster:
            yield(p)

class Question:
    def shift(self, k):
        return (k + self.shift_amount) % self.n

    def randomize(self, k):
        return k + self.r.choice(range(7)) * self.n

    def is_good(self):
        if not (self.table[0] != -1 and self.table[-1] != -1):
            #print('bad wrap')
            return False

        all = [x for x in self.table + self.insert if x != -1]
        if not len(all) == len(set(all)):
            #print('bad dup')
            return False

        lucky = sum([1 for x in all if x < self.n and x >= 0])
        if not lucky == 1:
            #print('bad lucky')
            return False

        total = sum([int(x / self.n) for x in all if x != -1])
        if not total == 20:
            return False

        return True

    def __init__(self, seed):
        self.r = random.Random(seed)
        self.n = 9

        patterns_and_inserts = [
            (([0, 0], [2, 2], [3, 2], [5, 5], [6, 6], [7, 5]), [2, 3]),
            (([0, 0], [6, 6], [7, 6], [2, 2], [3, 3], [4, 2]), [2, 4]),
        ]

        while True:
            pattern, self.insert = self.r.choice(patterns_and_inserts)
            self.shift_amount = self.r.choice(range(self.n))

            for xs in pattern:
                for i in range(len(xs)):
                    xs[i] = self.shift(xs[i])
                xs[1] = self.randomize(xs[1])
            for i in range(len(self.insert)):
                self.insert[i] = self.randomize(self.shift(self.insert[i]))
            self.r.shuffle(self.insert)

            self.table = [-1] * self.n
            for xs in pattern:
                self.table[xs[0]] = xs[1]

            if self.is_good():
                break

    def format_entry(self, x):
        return '' if x == -1 else str(x)

    def replacements(self, solution):
        for i in range(self.n):
            yield (f'entry_{i}', self.format_entry(self.table[i]))
        for i in range(len(self.insert)):
            yield (f'insert_{i}', str(self.insert[i]))

        if not solution:
            return

        cluster_no = 0
        for i in range(len(self.table)):
            if self.table[i] == -1:
                j = find_cluster_end(self.table, i)
                cluster = extract(self.table, i + 1, j)
                yield (f'sol_cluster_{cluster_no}', str(cluster))
                orders = list(find_insertion_orders(self.table, i))

                def format_order(order):
                    return '"{}"'.format(' then '.join(map(str, order)))
                yield (f'sol_cluster_{cluster_no}_orders', {
                    0: 'no possibility',
                    1: f'only possibility {format_order(orders[0])}',
                    2: ' or '.join(map(format_order, orders)),
                }[len(orders)])
                cluster_no = cluster_no + 1

        solution = list(self.table)
        for i in range(len(self.insert)):
            item = self.insert[i]
            hash_value = item % self.n
            j = hash_value
            msgs = []
            while True:
                good = solution[j] == -1
                msgs.append(f'{j} {"free (inserting)" if good else "occupied"}')
                if good:
                    solution[j] = item
                    break
                j = inc(self.table, j)
            yield (f'sol_insert_{i}', f'The hash value of {item} is {hash_value}. Trying cells: {", ".join(msgs)}.')

        for i in range(self.n):
            yield (f'sol_entry_{i}', self.format_entry(solution[i]))
