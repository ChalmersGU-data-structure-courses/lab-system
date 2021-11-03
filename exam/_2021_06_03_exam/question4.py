
import random

SIZE = 10 # size of the array
HOLES = [2, 3, 9] # positions for "?" unknown values
INSERT = 1 # position where the inserted element should end up

STARTVALUES = [1, 2, 3] # possible values for the first element
INCREASE = [2, 3, 4, 5, 6] # possible diffs between one value and its child
HOLE_INC = [2, 3, 4] # possible diff between one value and its child, if one of them is a hole
INSERT_INC = [4, 5] # possible diff between one value and its child, if one of them is the INSERT position

def test_unique_values(array):
    insert_values = set(range(array[parent(INSERT)] + 1, array[INSERT])) - set(array)
    return (len(array) == len(set(array)) and len(insert_values) >= 2)


def parent(i):
    return (i - 1) // 2

def leftchild(i):
    return 2 * i + 1

def rightchild(i):
    return 2 * i + 2


def question4(seed = None, solution = False):
    rnd = random.Random(seed)
    array = None
    while not (array and test_unique_values(array)):
        array = [rnd.choice(STARTVALUES)]
        while len(array) < SIZE:
            i = len(array)
            prev = array[parent(i)]
            choices = (INSERT_INC if i == INSERT else
                       HOLE_INC   if i in HOLES or parent(i) in HOLES else
                       INCREASE)
            increase = rnd.choice(choices)
            array.append(prev + increase)

    #min_insert_val = array[parent(INSERT)] + 1
    #max_insert_val = array[INSERT] - 1
    unique_choice_insert_val = min(v for f in [leftchild, rightchild] for v in [array[f(parent(INSERT))]] if v != None) - 1

    #answer = {'solution': {
    #    'array': [],
    #    'insert': f"{min_insert_val}..{max_insert_val}",
    #    }
    #}
    answer = dict()
    for i, val in enumerate(array):
        solval = val
        if i in HOLES:
            #parentval = array[parent(i)] if i > 0 else -1
            #leftval = array[leftchild(i)] if leftchild(i) < len(array) else 100
            #rightval = array[rightchild(i)] if rightchild(i) < len(array) else 100
            # not all choices valid because of uniqueness constraint
            #solval = f"{parentval+1}..{min(leftval,rightval)-1}"
            val = '?'
        answer[f'v{i}'] = str(val)
        if solution:
            answer[f'sol_v{i}'] = str(solval)

    if solution:
        i = len(array)
        array.append(unique_choice_insert_val)
        while array[i] < array[parent(i)]:
            x = array[i]
            array[i] = array[parent(i)]
            array[parent(i)] = x
            i = parent(i)
        for i, val in enumerate(array):
            answer[f'sol_b_v{i}'] = str(array[i])
    return answer

if __name__=='__main__':
    print(question4())

class Generator:
    def __init__(self, seed):
        self.seed = seed

    def replacements(self, solution = False):
        return question4(self.seed, solution).items()
