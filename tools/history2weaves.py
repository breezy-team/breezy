#! /usr/bin/python
#
# Copyright (C) 2005 Canonical Ltd
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

"""Experiment in converting existing bzr branches to weaves."""

# To make this properly useful
#
# 1. assign text version ids, and put those text versions into
#    the inventory as they're converted.
#
# 2. keep track of the previous version of each file, rather than
#    just using the last one imported
#
# 3. assign entry versions when files are added, renamed or moved.
#
# 4. when merged-in versions are observed, walk down through them
#    to discover everything, then commit bottom-up
#
# 5. track ancestry as things are merged in, and commit that in each
#    revision
#
# Perhaps it's best to first walk the whole graph and make a plan for
# what should be imported in what order?  Need a kind of topological
# sort of all revisions.  (Or do we, can we just before doing a revision
# see that all its parents have either been converted or abandoned?)


# Cannot import a revision until all its parents have been
# imported.  in other words, we can only import revisions whose
# parents have all been imported.  the first step must be to
# import a revision with no parents, of which there must be at
# least one.  (So perhaps it's useful to store forward pointers
# from a list of parents to their children?)
#
# Another (equivalent?) approach is to build up the ordered
# ancestry list for the last revision, and walk through that.  We
# are going to need that.
#
# We don't want to have to recurse all the way back down the list.
#
# Suppose we keep a queue of the revisions able to be processed at
# any point.  This starts out with all the revisions having no
# parents.
#
# This seems like a generally useful algorithm...
#
# The current algorithm is dumb (O(n**2)?) but will do the job, and
# takes less than a second on the bzr.dev branch.

# This currently does a kind of lazy conversion of file texts, where a
# new text is written in every version.  That's unnecessary but for
# the moment saves us having to worry about when files need new
# versions.


if False:
    try:
        import psyco
        psyco.full()
    except ImportError:
        pass


import tempfile
import hotshot, hotshot.stats
import sys
import logging
import time

from bzrlib.branch import Branch, find_branch
from bzrlib.revfile import Revfile
from bzrlib.weave import Weave
from bzrlib.weavefile import read_weave, write_weave
from bzrlib.progress import ProgressBar
from bzrlib.atomicfile import AtomicFile
from bzrlib.xml4 import serializer_v4
from bzrlib.xml5 import serializer_v5
from bzrlib.trace import mutter, note, warning, enable_default_logging
from bzrlib.osutils import sha_strings



class Convert(object):
    def __init__(self):
        self.total_revs = 0
        self.converted_revs = set()
        self.absent_revisions = set()
        self.text_count = 0
        self.revisions = {}
        self.inventories = {}
        self.convert()
        



    def convert(self):
        enable_default_logging()
        self.pb = ProgressBar()
        self.inv_weave = Weave('__inventory')
        self.anc_weave = Weave('__ancestry')

        last_text_sha = {}

        # holds in-memory weaves for all files
        self.text_weaves = {}

        b = self.branch = Branch('.', relax_version_check=True)

        revno = 1
        rev_history = b.revision_history()
        last_idx = None
        inv_parents = []

        # to_read is a stack holding the revisions we still need to process;
        # appending to it adds new highest-priority revisions
        importorder = []
        self.to_read = [rev_history[-1]]
        self.total_revs = len(rev_history)
        while self.to_read:
            rev_id = self.to_read.pop()
            if (rev_id not in self.revisions
                and rev_id not in self.absent_revisions):
                self._load_one_rev(rev_id)
        self.pb.clear()
        to_import = self._make_order()[:100]
        for i, rev_id in enumerate(to_import):
            self.pb.update('converting revision', i, len(to_import))
            self._convert_one_rev(rev_id)

        print '(not really) upgraded to weaves:'
        print '  %6d revisions and inventories' % len(self.revisions)
        print '  %6d absent revisions removed' % len(self.absent_revisions)
        print '  %6d texts' % self.text_count

        self._write_all_weaves()


    def _write_all_weaves(self):
        i = 0
        write_atomic_weave(self.inv_weave, 'weaves/inventory.weave')
        try:
            for file_id, file_weave in self.text_weaves.items():
                self.pb.update('writing weave', i, len(self.text_weaves))
                write_atomic_weave(file_weave, 'weaves/%s.weave' % file_id)
                i += 1
        finally:
            self.pb.clear()
        ## write_atomic_weave(self.anc_weave, 'weaves/ancestry.weave')

        
    def _load_one_rev(self, rev_id):
        """Load a revision object into memory.

        Any parents not either loaded or abandoned get queued to be
        loaded."""
        self.pb.update('loading revision',
                       len(self.revisions),
                       self.total_revs)
        if rev_id not in self.branch.revision_store:
            self.pb.clear()
            note('revision {%s} not present in branch; '
                 'will not be converted',
                 rev_id)
            self.absent_revisions.add(rev_id)
        else:
            rev_xml = self.branch.revision_store[rev_id].read()
            rev = serializer_v4.read_revision_from_string(rev_xml)
            for parent_id in rev.parent_ids:
                self.total_revs += 1
                self.to_read.append(parent_id)
            self.revisions[rev_id] = rev
            old_inv_xml = self.branch.inventory_store[rev_id].read()
            inv = serializer_v4.read_inventory_from_string(old_inv_xml)
            self.inventories[rev_id] = inv
        

    def _convert_one_rev(self, rev_id):
        """Convert revision and all referenced objects to new format."""
        rev = self.revisions[rev_id]
        inv = self.inventories[rev_id]
        new_inv_xml = serializer_v5.write_inventory_to_string(inv)
        inv_parents = [x for x in self.revisions[rev_id].parent_ids
                       if x not in self.absent_revisions]
        self.inv_weave.add(rev_id, inv_parents,
                           new_inv_xml.splitlines(True))
        # TODO: Upgrade revision XML and write that out
        self._convert_revision_contents(rev, inv)
        self.converted_revs.add(rev_id)


    def _convert_revision_contents(self, rev, inv):
        """Convert all the files within a revision.

        Also upgrade the inventory to refer to the text revision ids."""
        rev_id = rev.revision_id
        for path, ie in inv.iter_entries():
            file_id = ie.file_id
            if ie.kind != 'file':
                continue
            w = self.text_weaves.get(file_id)
            if w is None:
                w = Weave(file_id)
                self.text_weaves[file_id] = w
            file_lines = self.branch.text_store[ie.text_id].readlines()
            assert sha_strings(file_lines) == ie.text_sha1
            assert sum(map(len, file_lines)) == ie.text_size
            file_parents = []
            for parent_id in rev.parent_ids:
                assert parent_id in self.converted_revs
                if self.inventories[parent_id].has_id(file_id):
                    file_parents.append(parent_id)
            w.add(rev_id, file_parents, file_lines)
            ie.text_version = rev_id
            ie.name_version = rev_id
            mutter('import text {%s}\n  from {%s}\n  in revision {%s}',
                   ie.text_id, file_id, rev_id)
            del ie.text_id
                   


    def _make_order(self):
        """Return a suitable order for importing revisions.

        The order must be such that an revision is imported after all
        its (present) parents.
        """
        todo = set(self.revisions.keys())
        done = self.absent_revisions.copy()
        o = []
        while todo:
            # scan through looking for a revision whose parents
            # are all done
            for rev_id in sorted(list(todo)):
                rev = self.revisions[rev_id]
                parent_ids = set(rev.parent_ids)
                if parent_ids.issubset(done):
                    # can take this one now
                    o.append(rev_id)
                    todo.remove(rev_id)
                    done.add(rev_id)
        return o
                

def write_atomic_weave(weave, filename):
    inv_wf = AtomicFile(filename)
    try:
        write_weave(weave, inv_wf)
        inv_wf.commit()
    finally:
        inv_wf.close()

    


def profile_convert(): 
    prof_f = tempfile.NamedTemporaryFile()

    prof = hotshot.Profile(prof_f.name)

    prof.runcall(Convert) 
    prof.close()

    stats = hotshot.stats.load(prof_f.name)
    ##stats.strip_dirs()
    stats.sort_stats('time')
    # XXX: Might like to write to stderr or the trace file instead but
    # print_stats seems hardcoded to stdout
    stats.print_stats(20)


enable_default_logging()

if '-p' in sys.argv[1:]:
    profile_convert()
else:
    Convert()
    
