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


"""Weave algorithms benchmark"""

import bzrlib.branch
from bzrlib.weave import Weave
from bzrlib.weavefile import write_weave
from bzrlib.progress import ProgressBar
from random import randrange, randint, seed
import tempfile
import hotshot, hotshot.stats
import sys

WEAVE_NAME = "bench.weave"
NUM_REVS = 2000

seed(0)

def build():
    pb = ProgressBar(show_eta=False)

    wf = Weave()
    lines = []

    parents = []
    for i in xrange(NUM_REVS):
        pb.update('building', i, NUM_REVS)

        for j in range(randint(0, 4)):
            o = randint(0, len(lines))
            lines.insert(o, "new in version %i\n" % i)

        for j in range(randint(0, 2)):
            if lines:
                del lines[randrange(0, len(lines))]

        rev_id = wf.add("%s" % i, parents, lines)
        parents = [rev_id]

    write_weave(wf, file(WEAVE_NAME, 'wb'))

        
#     parents = set()
#     revno = 1
#     rev_history = b.revision_history()
#     for rev_id in rev_history:
#         pb.update('converting inventory', revno, len(rev_history))
#         inv_xml = b.inventory_store[rev_id].readlines()
#         weave_id = wf.add(parents, inv_xml)
#         parents = set([weave_id])       # always just one parent
#         revno += 1

#     pb.update('write weave', None, None)
#     write_weave(wf, file(WEAVE_NAME, 'wb'))

    pb.clear()



def profileit(fn): 
    prof_f = tempfile.NamedTemporaryFile()

    prof = hotshot.Profile(prof_f.name)

    prof.runcall(fn) 
    prof.close()

    stats = hotshot.stats.load(prof_f.name)
    #stats.strip_dirs()
    stats.sort_stats('time')
    ## XXX: Might like to write to stderr or the trace file instead but
    ## print_stats seems hardcoded to stdout
    stats.print_stats(20)
            

if '-p' in sys.argv[1:]:
    opt_p = True
    sys.argv.remove('-p')
else:
    opt_p = False

if len(sys.argv) > 1:
    NUM_REVS = int(sys.argv[1])

if opt_p:
    profileit(build)
else:
    build()
    
