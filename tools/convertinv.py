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
from bzrlib.weave import Weave
from bzrlib.weavefile import write_weave
from bzrlib.progress import ProgressBar
import tempfile
import hotshot
import sys

def convert():
    WEAVE_NAME = "inventory.weave"

    pb = ProgressBar()

    wf = Weave()

    b = bzrlib.branch.find_branch('.')

    parents = set()
    revno = 1
    rev_history = b.revision_history()
    for rev_id in rev_history:
        pb.update('converting inventory', revno, len(rev_history))
        inv_xml = b.inventory_store[rev_id].readlines()
        weave_id = wf.add(parents, inv_xml)
        parents.add(weave_id)
        revno += 1

    pb.update('write weave', None, None)
    write_weave(wf, file(WEAVE_NAME, 'wb'))

    pb.clear()


def profile_convert(): 
    prof_f = tempfile.NamedTemporaryFile()

    prof = hotshot.Profile(prof_f.name)

    prof.runcall(convert) 
    prof.close()

    import hotshot.stats
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
    
