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

class Generator:
    def __init__(self, seed, version = None):
        self.r = random.Random(seed)
        self.graph = self.generate_graph()
        self.eccs = self.calc_eccentricities()
        asked_index = (len(self.eccs)-1) // 2
        self.asked_node = self.eccs[asked_index][1]

    def replacements(self, solution = False):
        yield ('node', self.asked_node)
        if solution:
            yield ('solution', 'B')

    def replacements_img(self, solution = False):
        (fd, name) = tempfile.mkstemp(suffix = '.png')
        os.close(fd)
        path = pathlib.Path(name)
        dotgraph = dotgraph_header + "\n".join(f'{a}--{b}[label="{w}"];' for a,b,w in self.graph) + "}"
        with open(path, 'wb') as PNG:
            subprocess.run(['dot', '-Tpng'], input=dotgraph, text=True, stdout=PNG)
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
    for i, f in g.replacements_img():
        print(i, f)
        subprocess.run(['open', f])
