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



class Convert(object):
    def __init__(self):
        self.total_revs = 0
        self.converted_revs = set()
        self.absent_revisions = set()
        self.text_count = 0
        self.revisions = {}
        self.convert()
        



    def convert(self):
        enable_default_logging()
        self.pb = ProgressBar()
        self.inv_weave = Weave('__inventory')
        self.anc_weave = Weave('__ancestry')

        last_text_sha = {}

        # holds in-memory weaves for all files
        text_weaves = {}

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
        to_import = self._make_order()
        for rev_id in to_import:
            self._import_one_rev(rev_id)

        # self._convert_one_rev(self.to_read.pop())
        
        print 'upgraded to weaves:'
        print '  %6d revisions and inventories' % len(self.revisions)
        print '  %6d absent revisions removed' % len(self.absent_revisions)
        print '  %6d texts' % self.text_count

        self._write_all_weaves()


    def _write_all_weaves(self):
        i = 0
        return ############################################
        # TODO: commit them all atomically at the end, not one by one
        write_atomic_weave(self.inv_weave, 'weaves/inventory.weave')
        write_atomic_weave(self.anc_weave, 'weaves/ancestry.weave')
        for file_id, file_weave in text_weaves.items():
            self.pb.update('writing weave', i, len(text_weaves))
            write_atomic_weave(file_weave, 'weaves/%s.weave' % file_id)
            i += 1

        self.pb.clear()

        
    def _load_one_rev(self, rev_id):
        """Load a revision object into memory.

        Any parents not either loaded or abandoned get queued to be
        loaded."""
        self.pb.update('loading revision',
                       len(self.converted_revs),
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


    def _import_one_rev(self, rev_id):
        """Convert rev_id and all referenced file texts to new format."""
        


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

    def _convert_one_rev(self, rev_id):
        self._bump_progress()
        b = self.branch

        if rev_id not in b.revision_store:
            self.pb.clear()
            note('revision {%s} not present in branch; '
                 'will not be converted',
                 rev_id)
            self.absent_revisions.add(rev_id)
            return
        
        rev_xml = b.revision_store[rev_id].read()
        inv_xml = b.inventory_store[rev_id].read()

        rev = serializer_v4.read_revision_from_string(rev_xml)
        inv = serializer_v4.read_inventory_from_string(inv_xml)

        self.converted_revs.add(rev_id)
        
        return ##########################################

        new_idx = self.inv_weave.add(rev_id, inv_parents, inv_xml)
        inv_parents = [new_idx]

        tree = b.revision_tree(rev_id)
        inv = tree.inventory

        # for each file in the inventory, put it into its own revfile
        for file_id in inv:
            ie = inv[file_id]
            if ie.kind != 'file':
                continue
            if last_text_sha.get(file_id) == ie.text_sha1:
                # same as last time
                continue
            last_text_sha[file_id] = ie.text_sha1

            # new text (though possibly already stored); need to store it
            text_lines = tree.get_file(file_id).readlines()

            # if the file's created for the first time in this
            # revision then make a new weave; else find the old one
            if file_id not in text_weaves:
                text_weaves[file_id] = Weave()

            w = text_weaves[file_id]

            # base the new text version off whatever was last
            # (actually it'd be better to track this, to allow for
            # files that are deleted and then reappear)
            last = len(w)
            if last == 0:
                parents = []
            else:
                parents = [last-1]

            w.add(rev_id, parents, text_lines)
            text_count += 1

        revno += 1
        


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
            

if '-p' in sys.argv[1:]:
    profile_convert()
else:
    Convert()
    
