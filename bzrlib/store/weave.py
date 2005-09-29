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
from bzrlib.store import Store
from bzrlib.atomicfile import AtomicFile
from bzrlib.errors import NoSuchFile

from cStringIO import StringIO



class WeaveStore(Store):
    """Collection of several weave files in a directory.

    This has some shortcuts for reading and writing them.
    """
    def __init__(self, transport):
        self._transport = transport
        self._cache = {}
	self.enable_cache = False


    def filename(self, file_id):
        """Return the path relative to the transport root."""
        return file_id + '.weave'

    def _get(self, file_id):
        return self._transport.get(self.filename(file_id))

    def _put(self, file_id, f):
        return self._transport.put(self.filename(file_id), f)


    def get_weave(self, file_id):
        if self.enable_cache:
            if file_id in self._cache:
                return self._cache[file_id]
        w = read_weave(self._get(file_id))
        if self.enable_cache:
            self._cache[file_id] = w
        return w


    def get_lines(self, file_id, rev_id):
        """Return text from a particular version of a weave.

        Returned as a list of lines."""
        w = self.get_weave(file_id)
        return w.get(w.lookup(rev_id))
    

    def get_weave_or_empty(self, file_id):
        """Return a weave, or an empty one if it doesn't exist.""" 
        try:
            inf = self._get(file_id)
        except NoSuchFile:
            return Weave(weave_name=file_id)
        else:
            return read_weave(inf)
    

    def put_weave(self, file_id, weave):
        """Write back a modified weave"""
        if self.enable_cache:
            self._cache[file_id] = weave

        sio = StringIO()
        write_weave_v5(weave, sio)
        sio.seek(0)

        self._put(file_id, sio)


    def add_text(self, file_id, rev_id, new_lines, parents):
        w = self.get_weave_or_empty(file_id)
        parent_idxs = map(w.lookup, parents)
        w.add(rev_id, parent_idxs, new_lines)
        self.put_weave(file_id, w)
        
     
