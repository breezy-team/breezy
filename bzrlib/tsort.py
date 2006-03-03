# (C) 2005, 2006 Canonical Limited.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""Topological sorting routines."""


import bzrlib.errors as errors


def topo_sort(graph):
    """Topological sort a graph.

    graph -- sequence of pairs of node->parents_list.

    The result is a list of node names, such that all parents come before
    their children.

    Nodes at the same depth are returned in sorted order.

    node identifiers can be any hashable object, and are typically strings.
    """
    return TopoSorter(graph).sorted()


class TopoSorter(object):

    def __init__(self, graph):
        """Topological sorting of a graph.
    
        :param graph: sequence of pairs of node_name->parent_names_list.
                      i.e. [('C', ['B']), ('B', ['A']), ('A', [])]
                      For this input the output from the sort or
                      iter_topo_order routines will be:
                      'A', 'B', 'C'
        
        node identifiers can be any hashable object, and are typically strings.

        If you have a graph like [('a', ['b']), ('a', ['c'])] this will only use
        one of the two values for 'a'.

        The graph is sorted lazily: until you iterate or sort the input is
        not processed other than to create an internal representation.

        iteration or sorting may raise GraphCycleError if a cycle is present 
        in the graph.
        """
        # a dict of the graph.
        self._graph = dict(graph)
        ### if debugging:
        # self._original_graph = dict(graph)
        
        # this is a stack storing the depth first search into the graph.
        self._node_name_stack = []
        # at each level of 'recursion' we have to check each parent. This
        # stack stores the parents we have not yet checked for the node at the 
        # matching depth in _node_name_stack
        self._pending_parents_stack = []
        # this is a set of the completed nodes for fast checking whether a
        # parent in a node we are processing on the stack has already been
        # emitted and thus can be skipped.
        self._completed_node_names = set()

    def sorted(self):
        """Sort the graph and return as a list.
        
        After calling this the sorter is empty and you must create a new one.
        """
        return list(self.iter_topo_order())

###        Useful if fiddling with this code.
###        # cross check
###        sorted_names = list(self.iter_topo_order())
###        for index in range(len(sorted_names)):
###            rev = sorted_names[index]
###            for left_index in range(index):
###                if rev in self.original_graph[sorted_names[left_index]]:
###                    print "revision in parent list of earlier revision"
###                    import pdb;pdb.set_trace()

    def iter_topo_order(self):
        """Yield the nodes of the graph in a topological order.
        
        After finishing iteration the sorter is empty and you cannot continue
        iteration.
        """
        while self._graph:
            # now pick a random node in the source graph, and transfer it to the
            # top of the depth first search stack.
            node_name, parents = self._graph.popitem()
            self._push_node(node_name, parents)
            while self._node_name_stack:
                # loop until this call completes.
                parents_to_visit = self._pending_parents_stack[-1]
                # if all parents are done, the revision is done
                if not parents_to_visit:
                    # append the revision to the topo sorted list
                    # all the nodes parents have been added to the output, now
                    # we can add it to the output.
                    yield self._pop_node()
                else:
                    while self._pending_parents_stack[-1]:
                        # recurse depth first into a single parent 
                        next_node_name = self._pending_parents_stack[-1].pop()
                        if next_node_name in self._completed_node_names:
                            # this parent was completed by a child on the
                            # call stack. skip it.
                            continue
                        # otherwise transfer it from the source graph into the
                        # top of the current depth first search stack.
                        try:
                            parents = self._graph.pop(next_node_name)
                        except KeyError:
                            # if the next node is not in the source graph it has
                            # already been popped from it and placed into the
                            # current search stack (but not completed or we would
                            # have hit the continue 4 lines up.
                            # this indicates a cycle.
                            raise errors.GraphCycleError(self._node_name_stack)
                        self._push_node(next_node_name, parents)
                        # and do not continue processing parents until this 'call' 
                        # has recursed.
                        break

    def _push_node(self, node_name, parents):
        """Add node_name to the pending node stack.
        
        Names in this stack will get emitted into the output as they are popped
        off the stack.
        """

        self._node_name_stack.append(node_name)
        self._pending_parents_stack.append(list(parents))

    def _pop_node(self):
        """Pop the top node off the stack 

        The node is appended to the sorted output.
        """
        # we are returning from the flattened call frame:
        # pop off the local variables
        node_name = self._node_name_stack.pop()
        self._pending_parents_stack.pop()

        self._completed_node_names.add(node_name)
        return node_name
