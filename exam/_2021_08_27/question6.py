import pathlib
import random
import tempfile
import subprocess
import os

A, B, C, D, E, F, G, H = NODES = "ABCDEFGH"

dotgraph_header = """
graph Q6 {
rankdir=LR;
size="6,2";
ratio="fill";
node [shape = circle];
"""

def pp_any_of_list(items):
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return ' or '.join(items)
    return 'Any of ' + ', '.join(items[:-1]) + ' or ' + items[-1]


def all_shortest_paths(goal, graph, distances):
    if distances[goal] == 0:
        yield [goal]
    else:
        for a, b, dist in graph:
            node = a if goal==b else b if goal==a else None
            if node is not None:
                dist_ = distances[goal] - distances[node]
                if dist == dist_:
                    for path in all_shortest_paths(node, graph, distances):
                        yield path + [goal]
                

class Generator:
    def __init__(self, seed, version = None):
        self.r = random.Random(seed)
        self.graph = self.generate_graph()
        self.eccs = self.calc_eccentricities()
        self.asked_index = (len(self.eccs)-1) // 2
        self.asked_node = self.eccs[self.asked_index][1]

    def replacements(self, solution = False):
        yield ('node', self.asked_node)
        if not solution:
            return

        ecc, node, furthest = self.eccs[self.asked_index]
        yield ('a-eccentricity', ecc)
        yield ('a-furthest-node', pp_any_of_list(furthest))
        distances = {n:d for n,d in self.run_dijkstra(node)}
        shortest_paths = []
        for goal in furthest:
            for path in all_shortest_paths(goal, self.graph, distances):
                shortest_paths.append('-'.join(path))
        yield ('a-shortest-path', pp_any_of_list(shortest_paths))

        min_ecc = self.eccs[0][0]
        min_nodes = [n for ecc,n,_ in self.eccs if ecc == min_ecc]
        yield ('b-min-eccentricity', min_ecc)
        yield ('b-min-node', pp_any_of_list(min_nodes))

        max_ecc = self.eccs[-1][0]
        max_nodes = [n for ecc,n,_ in self.eccs if ecc == max_ecc]
        yield ('b-max-eccentricity', max_ecc)
        yield ('b-max-node', pp_any_of_list(max_nodes))

    def replacements_img(self, solution = False):
        (fd, name) = tempfile.mkstemp(suffix = '.png')
        os.close(fd)
        path = pathlib.Path(name)
        dotgraph = dotgraph_header + "\n".join(f'{a}--{b}[label="{w}"];' for a,b,w in self.graph) + "}"
        with open(path, 'wb') as PNG:
            subprocess.run(['dot', '-Tpng', '-Gdpi=300'], input=dotgraph, text=True, stdout=PNG)
        yield ('kix.xjn609dsdw9n', path)

    def generate_graph(self):
        smallW = lambda: self.r.choice([1,2,3])
        bigW = lambda: self.r.choice([5,6,7])
        graph = []
        if self.r.choice([True, False]):
            graph += [(A, B, smallW()), (B, D, smallW()), (C, D, bigW()),
                      (self.r.choice([B, C]), E, bigW())]
        else:
            graph += [(A, D, bigW()), (B, C, smallW()), (C, D, smallW()),
                      (self.r.choice([A, C]), E, bigW())]
        graph += [(D, E, smallW())]
        if self.r.choice([True, False]):
            graph += [(E, F, smallW()), (F, G, smallW()), (E, H, bigW()),
                      (D, self.r.choice([F, H]), smallW())]
        else:
            graph += [(E, F, bigW()), (E, G, smallW()), (G, H, smallW()),
                      (D, self.r.choice([F, G]), smallW())]
        return graph

    # stolen from Christian
    def run_dijkstra(self, start):
        queue = [(0, start)]
        visited = set()
        while queue:
            k_min = min(k for k, a in queue)
            entries = [(k, a) for k, a in queue if k == k_min]
            k, a = entries[0]
            for x,y,w in self.graph:
                if a in [x,y]:
                    b = y if a == x else x
                    queue.append((k + w, b))
            visited.add(a)
            queue = sorted([(k, b) for (k, b) in queue if b not in visited])
            yield (a, k)

    def calc_eccentricities(self):
        eccs = []
        for node in NODES:
            ecc, furthest = self.eccentricity(node)
            eccs.append((ecc, node, furthest))
        eccs.sort()
        return eccs

    def eccentricity(self, node):
        dists = list(self.run_dijkstra(node))
        ecc = dists[-1][1]
        furthest = [a for a,k in dists if k == ecc]
        return ecc, furthest

if __name__ == "__main__":
    g = Generator(None)
    print(g.graph)
    print("\n".join(f'{e}: {n} --> {" ".join(f)}' for e,n,f in g.eccs))
    print(f"Asked node: {g.asked_node}")
    print()
    for i, f in g.replacements(solution=True):
        print(i, f)
    print()
    for i, f in g.replacements_img():
        print(i, f)
        subprocess.run(['open', f])
