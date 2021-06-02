def count_inversions(xs):
    r = 0
    for i in range(len(xs)):
        for j in range(i + 1, len(xs)):
            if xs[i] > xs[j]:
                r += 1
    return r

class Generator:
    def __init__(self, seed):
        self.n = 8
        self.r = random.Random(seed)

    def replacements(self, solution = False):
        while True:
            values = self.r.sample([k + 1 for k in range(9)], 8)
            c = count_inversions(values)
            if c == n * (n - 1) // 4: # average amount of inversions
                break
        return values
