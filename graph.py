import graphviz
import math
import random
import os
import pathlib
import string
import tempfile

scale = [1, 0.8]

nodes = [
    (0, 0),
    (2, 0),
    (1, 1),
    (3, 1),
    (0, 2),
    (2, 1.7),
    (2, 3),
]

def pos(a, i):
    return scale[i] * nodes[a][i]

edges = [
    ((0, 2), False),
    ((1, 0), False),
    ((1, 3), False),
    ((2, 1), False),
    ((2, 4), True),
    ((2, 5), False),
    ((3, 2), False),
    ((4, 0), True),
    ((4, 6), False),
    ((5, 3), False),
    ((5, 6), False),
    ((6, 2), True),
    ((6, 3), False),
]

outgoing = dict((a, []) for a in range(len(nodes)))
for (a, b), _ in edges:
    outgoing[a].append(b)

weights = range(1, 7)

class InstanceException(Exception):
    pass

class Instance:
    def __init__(self, seed):
        self.r = random.Random(seed)
        self.weights = dict((e, self.r.choice(weights)) for e, _ in edges)
        self.start = self.r.choice(range(len(nodes)))
        self.names = self.r.sample(string.ascii_uppercase[0:len(nodes)], k = len(nodes))

    def run_dijkstra(self):
        queue = [(0, self.start)]
        visited = set()
        while queue:
            k_min = min(k for (k, a) in queue)
            entries = [(k, a) for (k, a) in queue if k == k_min]
            if len(entries) != 1:
                raise InstanceException
            (k, a) = entries[0]
            for b in outgoing[a]:
                queue.append((k + self.weights[(a, b)], b))
            visited.add(a)
            queue = sorted([(k, b) for (k, b) in queue if b not in visited])
            yield (a, k, list(queue))

    def compute_measures(self):
        r = list(self.run_dijkstra())
        self.work_size = sum(len(queue) for (a, k, queue) in r)
        self.average_weight = sum(self.weights.values()) / len(edges)
        self.visit_order = [a for (a, _, _) in r]

    def is_good(self):
        try:
            self.compute_measures()
        except InstanceException:
            return False

        return 15 <= self.work_size <= 17 and self.average_weight <= sum(weights) / len(weights) + 0.5

    def dot(self):
        dot = graphviz.Digraph(engine = 'neato', format = 'png')
        dot.attr(dpi = '300')
        for a in range(len(nodes)):
            dot.node(
                str(a),
                self.names[a],
                pos = '{},{}!'.format(pos(a, 0), pos(a, 1)),
                style = 'filled',
                shape = 'circle',
                fillcolor = 'orange',
                fontname = 'Arial',
                fontsize = '14',
                width = '0.4',
                fixedsize = 'true',
            )
        for ((a, b), flipped) in edges:
            d = [pos(a, i) - pos(b, i) for i in [0, 1]]
            angle = math.atan2(d[1], d[0])
            angle_side = angle + math.tau / 4
            f = (-1 if flipped else 1) * -0.09
            dot.edge(
                str(a), str(b),
                #label = '{}'.format(str(self.weights[(a, b)])),
                #labelangle = '90',#str(angle / math.tau * 360),
                #labeldistance = str(1000),
            )
            m = [(pos(a, i) + pos(b, i)) / 2 for i in [0, 1]]
            dot.node(
                name = '{},{}'.format(a, b),
                label = str(self.weights[(a, b)]),
                shape = 'none',
                pos = '{},{}!'.format(m[0] + f * math.cos(angle_side), m[1] + f * math.sin(angle_side)),
                fontname = 'Arial',
                fontsize = '12',
            )
        return dot

def next_good_instance(seed):
    while True:
        instance = Instance(seed)
        if instance.is_good():
            return instance
        seed = seed + '1'

class QuestionDijkstra:
    def __init__(self, seed):
        self.r = random.Random(seed)
        self.instance = next_good_instance(seed)

    def write_graph(self, path):
        self.instance.dot().render(str(path))

    def starting_node(self):
        return self.instance.names[self.instance.start]

    def replacements(self, solution):
        yield ('starting_node', self.instance.names[self.instance.start])

        if solution:
            for (i, (a, k, queue)) in enumerate(self.instance.run_dijkstra()):
                yield (f'sol_{i}_node', self.instance.names[a])
                yield (f'sol_{i}_cost', str(k))
                yield (f'sol_{i}_entries', ', '.join(f'{self.instance.names[b]}:{m}' for (m, b) in queue))

    def replacements_img(self, solution):
        (fd, name) = tempfile.mkstemp(suffix = '.png')
        os.close(fd)
        path = pathlib.Path(name)
        with tempfile.TemporaryDirectory() as dir:
            pathlib.Path(self.instance.dot().render(directory = dir)).rename(path)
        yield ('kix.gq7jtslsbc2f', path)

#q = QuestionDijkstra('1')
#print(q.instance.weights[(0, 2)], q.instance.weights[(1, 0)], q.instance.weights[(4, 0)])
