#!/usr/bin/env python3
"""Benchmark tool for graph algorithms.

This script benchmarks KnownGraph vs simple Graph implementations
for computing heads operations.
"""

import os
import sys
import time
from optparse import OptionParser

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import vcsgraph
import vcsgraph.graph as graph

p = OptionParser()
p.add_option("--quick", default=False, action="store_true")
opts, args = p.parse_args(sys.argv[1:])


def load_data(fname):
    """Load graph data from a file.

    Args:
        fname: Path to a file containing graph data. Each line should have
            a revision ID followed by its parent IDs, separated by spaces.

    Returns:
        dict: A parent map mapping revision IDs to tuples of parent IDs.
    """
    with open(fname, "rb") as f:
        lines = f.readlines()
    parent_map = {}
    for line in lines:
        parts = line.split()
        if len(parts) > 1:
            parent_map[parts[0]] = tuple(parts[1:])
        else:
            parent_map[parts[0]] = ()
    return parent_map


def all_heads_comp(graph, combinations):
    """Benchmark computing heads for all key combinations.

    Args:
        graph: A graph object with a heads() method.
        combinations: List of key pairs to compute heads for.

    Returns:
        dict: Results including elapsed time and computed heads.
    """
    heads = {}
    start = time.time()
    for c in combinations:
        heads[c] = graph.heads(c)
    elapsed = time.time() - start
    return {"elapsed": elapsed, "heads": heads}


def combi_graph(graph_klass, combinations):
    """Create a graph and benchmark heads computation.

    Args:
        graph_klass: Graph class or callable to instantiate.
        combinations: List of key pairs to compute heads for.

    Returns:
        dict: Results including elapsed time and computed heads.
    """
    g = graph_klass(parent_map)
    return all_heads_comp(g, combinations)


if len(args) < 1:
    print("Usage: time_graph.py file [key1 key2]")
    sys.exit(1)

parent_map = load_data(args[0])
if len(args) > 2:
    combinations = [(args[1].encode(), args[2].encode())]
else:
    all_keys = sorted(parent_map)
    combinations = []
    for idx, key in enumerate(all_keys):
        # Pick pairs that are likely to have interesting relationships
        other = all_keys[-(idx + 1)]
        if other != key:
            combinations.append((key, other))


def report(name, result):
    """Report benchmark results.

    Args:
        name: Name of the benchmark.
        result: Dict containing 'elapsed' time and 'heads' data.
    """
    print(f"{name}: {result['elapsed']:.3f}s")
    if not opts.quick:
        print(f"  {graph._counters}")


known_python = combi_graph(vcsgraph.KnownGraph, combinations)
report("Known", known_python)


def _simple_graph(parent_map):
    """Create a simple Graph instance from a parent map.

    Args:
        parent_map: Dictionary mapping revision IDs to their parent IDs.

    Returns:
        Graph instance using DictParentsProvider.
    """
    return graph.Graph(graph.DictParentsProvider(parent_map))


if opts.quick:
    print(f"ratio: {known_python['elapsed']:.3f}s")
else:
    orig = combi_graph(_simple_graph, combinations)
    report("Orig", orig)

    print(f"ratio: {orig['elapsed'] / known_python['elapsed']:.1f}:1 faster")
