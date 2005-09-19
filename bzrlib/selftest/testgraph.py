from bzrlib.selftest import TestCase
from bzrlib.graph import node_distances, nodes_by_distance

class TestBase(TestCase):
    def edge_add(self, *args):
        for start, end in zip(args[:-1], args[1:]):
            if start not in self.graph:
                self.graph[start] = {}
            if end not in self.graph:
                self.graph[end] = {}
            self.graph[start][end] = 1

    def setUp(self):
        TestCase.setUp(self)
        self.graph = {}
        self.edge_add('A', 'B', 'C', 'D')
        self.edge_add('A', 'E', 'F', 'C')
        self.edge_add('A', 'G', 'H', 'I', 'B')
        self.edge_add('A', 'J', 'K', 'L', 'M', 'N')
        self.edge_add('O', 'N')

    def node_descendants(self):
        descendants = {'A':set()}
        for node in self.graph:
            for ancestor in self.graph[node]:
                if ancestor not in descendants:
                    descendants[ancestor] = set()
                descendants[ancestor].add(node)
        return descendants
    
    def test_distances(self):
        descendants = self.node_descendants()
        distances = node_distances(self.graph, descendants, 'A')
        nodes = nodes_by_distance(distances)
        self.assertEqual(nodes[0], 'D')
        assert nodes[1] in ('N', 'C')
        assert nodes[2] in ('N', 'C')
        assert nodes[3] in ('B', 'M')
        assert nodes[4] in ('B', 'M')


