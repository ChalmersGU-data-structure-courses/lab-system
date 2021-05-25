
import itertools
import random


NEDGES = 9
NCHEAP = 5  # setting to 6 makes the problem harder for the students

def test_unique_path(weights, path):
    for n in range(1, len(weights) + 1):
        for comb in itertools.combinations(weights, n):
            if sum(comb) == sum(path):
                if set(path) != set(comb):
                    # print(f"Retrying: {' + '.join(map(str,path))} == {' + '.join(map(str,comb))} == {sum(path)}")
                    return False
    return True


def question6(seed=None):
    rnd = random.Random(seed)
    weights = None
    while not (weights and test_unique_path(weights, path)):
        # numbers 1 2 ... 9
        weights = list(range(1, NCHEAP + NEDGES))
        # remove a random number until the length == NCHEAP
        while len(weights) > NCHEAP:
            del weights[rnd.randrange(0, len(weights))]
        # the path will be the even-numbered elements 
        path = weights[0::2]

    path_cost = sum(path)
    mst_cost = sum(weights[:5])

    # add some expensive distractor edges
    weights.append(path_cost)
    while len(weights) < NEDGES:
        weights.append(weights[-1] + rnd.randrange(1, 4))


    return {
        'weights': ', '.join(map(str, weights)),
        'path_cost': path_cost,
        'mst_cost': mst_cost,
    }


if __name__=='__main__':
    print(question6())

