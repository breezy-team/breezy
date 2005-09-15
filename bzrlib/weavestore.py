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

# Author: Martin Pool <mbp@canonical.com>


import os
import errno

from bzrlib.weavefile import read_weave, write_weave_v5
from bzrlib.weave import Weave
from bzrlib.atomicfile import AtomicFile


class WeaveStore(object):
    """Collection of several weave files."""
    def __init__(self, dir):
        self._dir = dir


    def filename(self, file_id):
        return self._dir + os.sep + file_id + '.weave'


    def get_weave(self, file_id):
        return read_weave(file(self.filename(file_id), 'rb'))


    def get_lines(self, file_id, rev_id):
        """Return text from a particular version of a weave.

        Returned as a list of lines."""
        w = self.get_weave(file_id)
        return w.get(w.lookup(rev_id))
    

    def get_weave_or_empty(self, file_id):
        """Return a weave, or an empty one if it doesn't exist.""" 
        try:
            inf = file(self.filename(file_id), 'rb')
        except IOError, e:
            if e.errno == errno.ENOENT:
                return Weave(weave_name=file_id)
            else:
                raise
        else:
            return read_weave(inf)
    

    def put_weave(self, file_id, weave):
        """Write back a modified weave"""
        weave_fn = self.filename(file_id)
        af = AtomicFile(weave_fn)
        try:
            write_weave_v5(weave, af)
            af.commit()
        finally:
            af.close()


    def add_text(self, file_id, rev_id, new_lines, parents):
        w = self.get_weave_or_empty(file_id)
        parent_idxs = map(w.lookup, parents)
        w.add(rev_id, parent_idxs, new_lines)
        self.put_weave(file_id, w)
        
     
