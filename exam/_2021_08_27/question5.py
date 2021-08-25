import random

class Generator:
    def __init__(self, seed, version = None):
        self.r = random.Random(seed)
        self.version = version

    def replacements(self, solution = False):
        keys = ["a", "b", "c", "d", "e"]
        values = ["", "1", "2", "3", "4"]
        assert len(keys) == len(values)

        permuted = self.r.sample(["", "1", "2", "3", "4"], 5)
        yield from zip(keys, permuted)
