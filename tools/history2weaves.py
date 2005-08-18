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
    text_rfs = {}

    b = bzrlib.branch.find_branch('.')

    revno = 1
    rev_history = b.revision_history()
    last_idx = None
    parents = []
    
    for rev_id in rev_history:
        pb.update('converting inventory', revno, len(rev_history))
        
        inv_xml = b.get_inventory_xml(rev_id).readlines()

        new_idx = inv_weave.add(parents, inv_xml)
        parents = [new_idx]

#         tree = b.revision_tree(rev_id)
#         inv = tree.inventory

#         # for each file in the inventory, put it into its own revfile
#         for file_id in inv:
#             ie = inv[file_id]
#             if ie.kind != 'file':
#                 continue
#             if last_text_sha.get(file_id) == ie.text_sha1:
#                 # same as last time
#                 continue
#             last_text_sha[file_id] = ie.text_sha1

#             # new text (though possibly already stored); need to store it
#             text = tree.get_file(file_id).read()
            
#             if file_id not in text_rfs:
#                 text_rfs[file_id] = Revfile('revfiles/' + file_id, 'w')
#             rf = text_rfs[file_id]

#             last = len(rf)
#             if last == 0:
#                 last = None
#             else:
#                 last -= 1
#             rf.add(text, last, compress=True)

        revno += 1

    inv_wf = AtomicFile('inventory.weave')
    try:
        write_weave(inv_weave, inv_wf)
        inv_wf.commit()
    finally:
        inv_wf.close()

    pb.clear()


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
    
