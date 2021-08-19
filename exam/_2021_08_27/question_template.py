# To write a generator for question N, copy this file to questionN.py in the same directory and fill out the below class.
import random

class Generator:
    # Use 'seed' to initialize random number generation.
    # For pregenerated problems, use the version number (ranges from 0 to number of versions) to select the problem.
    def __init__(self, seed, version = None):
        self.r = random.Random(seed)

    # A generator function returning key-value string replacement pairs.
    # The boolean parameter 'solution' indicates if this is for the exam or solution document.
    # This function is called only once per class instance, so it is safe to mutate self.r.
    def replacements(self, solution = False):
        yield ('key_0', 'A') # Replaces '{{QN:key_0}}' by 'A'
        yield ('key_1', 'B')
        if solution:
            yield ('key_solution_0', 'B')
