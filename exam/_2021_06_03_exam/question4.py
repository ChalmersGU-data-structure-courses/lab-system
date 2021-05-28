
import itertools
import random

SIZE = 10 # size of the array
HOLES = [2, 3, 9] # positions for "?" unknown values
INSERT = 1 # position where the inserted element should end up

STARTVALUES = [1, 2, 3] # possible values for the first element
INCREASE = [2, 3, 4, 5] # possible diffs between one value and its child
HOLE_INC = [2, 3] # possible diff between one value and its child, if one of them is a hole
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


def question4(seed=None):
    rnd = random.Random(seed)
    array = None
    while not (array and test_unique_values(array)):
        array = [rnd.choice(STARTVALUES)]
        while len(array) < SIZE:
            i = len(array)
            prev = array[parent(i)]
            choices = (INSERT_INC if i == INSERT or parent(i) == INSERT else
                       HOLE_INC   if i in HOLES or parent(i) in HOLES   else
                       INCREASE)
            increase = rnd.choice(choices)
            array.append(array[parent(i)] + increase)

    min_insert_val = array[parent(INSERT)] + 1
    max_insert_val = array[INSERT] - 1

    answer = {'solution': {
        'array': [],
        'insert': f"{min_insert_val}..{max_insert_val}",
        }
    }
    for i, val in enumerate(array):
        solval = val
        if i in HOLES:
            parentval = array[parent(i)] if i > 0 else -1
            leftval = array[leftchild(i)] if leftchild(i) < len(array) else 100
            rightval = array[rightchild(i)] if rightchild(i) < len(array) else 100
            solval = f"{parentval+1}..{min(leftval,rightval)-1}"
            val = "?"
        answer[f'v{i}'] = val
        answer['solution']['array'].append(solval)
    return answer


if __name__=='__main__':
    print(question4())

