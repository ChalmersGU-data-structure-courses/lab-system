import random

class Generator:
    def __init__(self, seed):
        self.r = random.Random(seed)

    # A generator function returning key-value replacement pairs.
    # The boolean parameter 'solution' indicates if this is for the exam or solution document.
    # This function is called only once per class instance, so it is safe to mutate self.r.
    def replacements(self, solution = False):
        yield ('key_0', 'A') # Replaces '{{Qn:key_0}}' by 'A'
        yield ('key_1', 'B')
        if solution:
            yield ('key_solution_0', 'B')
