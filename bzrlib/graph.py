	
def max_distance(node, ancestors, distances):
    """Calculate the max distance to an ancestor.  Return None if"""
    best = None
    if node in distances:
        best = distances[node]
    for ancestor in ancestors[node]:
        if ancestor not in ancestors:
            continue
        if ancestor not in distances:
            return None
        if best is None or distances[ancestor] > best:
            best = distances[ancestor] + 1
    return best

    
def farthest_node(graph, ancestors, start):
    distances = {start: 0}
    lines = set([start])
    while len(lines) > 0:
        new_lines = set()
        for line in lines:
            assert line not in graph[line], "%s refers to itself" % line
            for descendant in graph[line]:
                distance = max_distance(descendant, ancestors, distances)
                if distance is None:
                    continue
                distances[descendant] = distance
                new_lines.add(descendant)
        lines = new_lines

    def by_distance(n):
        return distances[n]
    node_list = distances.keys()
    node_list.sort(key=by_distance, reverse=True)
    return node_list
