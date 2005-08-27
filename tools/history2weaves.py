#! /usr/bin/python

# Copyright (C) 2005 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Experiment in converting existing bzr branches to weaves."""

try:
    import psyco
    psyco.full()
except ImportError:
    pass


import bzrlib.branch
from bzrlib.revfile import Revfile
from bzrlib.weave import Weave
from bzrlib.weavefile import read_weave, write_weave
from bzrlib.progress import ProgressBar
from bzrlib.atomicfile import AtomicFile
import tempfile
import hotshot, hotshot.stats
import sys

def convert():
    pb = ProgressBar()

    inv_weave = Weave()

    last_text_sha = {}

    # holds in-memory weaves for all files
    text_weaves = {}

    b = bzrlib.branch.find_branch('.')

    revno = 1
    rev_history = b.revision_history()
    last_idx = None
    inv_parents = []
    text_count = 0
    
    for rev_id in rev_history:
        pb.update('converting revision', revno, len(rev_history))
        
        inv_xml = b.get_inventory_xml(rev_id).readlines()

        new_idx = inv_weave.add(rev_id, inv_parents, inv_xml)
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

    pb.clear()
    print '%6d revisions and inventories' % revno
    print '%6d texts' % text_count

    i = 0
    # TODO: commit them all atomically at the end, not one by one
    write_atomic_weave(inv_weave, 'weaves/inventory.weave')
    for file_id, file_weave in text_weaves.items():
        pb.update('writing weave', i, len(text_weaves))
        write_atomic_weave(file_weave, 'weaves/%s.weave' % file_id)
        i += 1

    pb.clear()


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

    prof.runcall(convert) 
    prof.close()

    stats = hotshot.stats.load(prof_f.name)
    #stats.strip_dirs()
    stats.sort_stats('time')
    ## XXX: Might like to write to stderr or the trace file instead but
    ## print_stats seems hardcoded to stdout
    stats.print_stats(20)
            

if '-p' in sys.argv[1:]:
    profile_convert()
else:
    convert()
    
