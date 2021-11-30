import random

class Question:
    def __init__(self, seed):
        self.r = random.Random(seed)

        self.n = self.r.choice(['n', 'm', 'k', 'd'])
        if random.choice([False, True]):
            self.n = self.n.upper()

        self.x = self.r.choice(['x', 'y', 'z'])

    def replacements(self, solution):
        yield from [
            ('n', self.n),
            ('x', self.x),
        ]