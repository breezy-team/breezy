#!/usr/bin/env python3
import optparse
import random
import sys

from breezy import (
    branch,
    commands,
    graph,
    osutils,
    trace,
    ui,
)
from breezy.ui import text

p = optparse.OptionParser()
p.add_option("--quick", default=False, action="store_true")
p.add_option("--max-combinations", default=500, type=int)
p.add_option("--lsprof", default=None, type=str)
opts, args = p.parse_args(sys.argv[1:])

trace.enable_default_logging()
ui.ui_factory = text.TextUIFactory()

begin = osutils.perf_counter()
b = branch.Branch.open(args[0]) if len(args) >= 1 else branch.Branch.open(".")
with b.lock_read():
    g = b.repository.get_graph()
    parent_map = dict(
        p for p in g.iter_ancestry([b.last_revision()]) if p[1] is not None
    )
end = osutils.perf_counter()

print(f"Found {len(parent_map)} nodes, loaded in {end - begin:.3f}s")


def all_heads_comp(g, combinations):
    h = []
    with ui.ui_factory.nested_progress_bar() as pb:
        for idx, combo in enumerate(combinations):
            if idx & 0x1F == 0:
                pb.update("proc", idx, len(combinations))
            h.append(g.heads(combo))
    return h


combinations = []
# parents = parent_map.keys()
# for p1 in parents:
#     for p2 in random.sample(parents, 10):
#         combinations.append((p1, p2))
# Times for random sampling of 10x1150 of bzrtools
#   Graph        KnownGraph
#   96.1s   vs   25.7s  :)
# Times for 500 'merge parents' from bzr.dev
#   25.6s   vs   45.0s  :(

for _revision_id, parent_ids in parent_map.iteritems():
    if parent_ids is not None and len(parent_ids) > 1:
        combinations.append(parent_ids)
# The largest portion of the graph that has to be walked for a heads() check
# combinations = [('john@arbash-meinel.com-20090312021943-tu6tcog48aiujx4s',
#                  'john@arbash-meinel.com-20090312130552-09xa2xsitf6rilzc')]
if opts.max_combinations > 0 and len(combinations) > opts.max_combinations:
    combinations = random.sample(combinations, opts.max_combinations)

print(f"      {len(combinations)} combinations")


def combi_graph(graph_klass, comb):
    # DEBUG
    graph._counters[1] = 0
    graph._counters[2] = 0

    begin = osutils.perf_counter()
    g = graph_klass(parent_map)
    if opts.lsprof is not None:
        heads = commands.apply_lsprofiled(opts.lsprof, all_heads_comp, g, comb)
    else:
        heads = all_heads_comp(g, comb)
    end = osutils.perf_counter()
    return {"elapsed": (end - begin), "graph": g, "heads": heads}


def report(name, g):
    print(f"{name}: {g['elapsed']:.3f}s")
    counters_used = False
    for c in graph._counters:
        if c:
            counters_used = True
    if counters_used:
        print(f"  {graph._counters}")


known_python = combi_graph(graph.KnownGraph, combinations)
report("Known", known_python)


def _simple_graph(parent_map):
    return graph.Graph(graph.DictParentsProvider(parent_map))


if opts.quick:
    print(f"ratio: {known_python['elapsed'] / known_pyrex['elapsed']:.1f}:1 faster")
else:
    orig = combi_graph(_simple_graph, combinations)
    report("Orig", orig)

    print(f"ratio: {orig['elapsed'] / known_pyrex['elapsed']:.1f}:1 faster")
