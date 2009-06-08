import random
import time
import sys
import optparse
from bzrlib import branch, graph, ui, trace
from bzrlib.ui import text

p = optparse.OptionParser()
p.add_option('--one')
opts, args = p.parse_args(sys.argv[1:])
trace.enable_default_logging()
ui.ui_factory = text.TextUIFactory()

if len(args) >= 1:
    b = branch.Branch.open(args[0])
else:
    b = branch.Branch.open('.')
b.lock_read()
try:
    g = b.repository.get_graph()
    parent_map = dict(p for p in g.iter_ancestry([b.last_revision()])
                         if p[1] is not None)
finally:
    b.unlock()

print 'Found %d nodes' % (len(parent_map),)

def all_heads_comp(g, combinations):
    pb = ui.ui_factory.nested_progress_bar()
    try:
        for idx, combo in enumerate(combinations):
            pb.update('proc', idx, len(combinations))
            g.heads(combo)
    finally:
        pb.finished()
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

for revision_id, parent_ids in parent_map.iteritems():
    if parent_ids is not None and len(parent_ids) > 1:
        combinations.append(parent_ids)
if len(combinations) > 500:
    combinations = random.sample(combinations, 500)

print '      %d combinations' % (len(combinations),)
t1 = time.clock()
known_g = graph.KnownGraph(parent_map)
all_heads_comp(known_g, combinations)
t2 = time.clock()
print "Known: %.3fs" % (t2-t1,)
print "  %s" % (graph._counters,)
simple_g = graph.Graph(graph.DictParentsProvider(parent_map))
all_heads_comp(simple_g, combinations)
t3 = time.clock()
print "Orig: %.3fs" % (t3-t2,)
