# Copyright (C) 2006 Canonical Ltd
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


from bzrlib import branch, errors
from bzrlib.bzrdir import BzrDir, BzrDirFormat
from bzrlib.branch import Branch
from bzrlib.trace import mutter
from bzrlib.transport.smart import SmartTransport


class RemoteBzrDirFormat(BzrDirFormat):
    """Format representing bzrdirs accessed via a smart server"""
    
    def probe_transport(self, transport):
        mutter("%r probe for bzrdir in %r" % (self, transport))
        if isinstance(transport, SmartTransport):
            return self
        else:
            raise errors.NoSmartServer(transport.base)

    def _open(self, transport):
        return RemoteBzrDir(transport)


class RemoteBzrDir(BzrDir):
    """Control directory on a remote server, accessed by HPSS."""

    def __init__(self, transport):
        BzrDir.__init__(self, transport, RemoteBzrDirFormat)
        self.client = transport.get_smart_client()

    def open_branch(self):
        return RemoteBranch(self, self.client)


class RemoteBranch(branch.BzrBranch5):

    def __init__(self, my_bzrdir, smart_client):
        self.bzrdir = my_bzrdir
        self.client = smart_client


# when first loaded, register this format.
#
# TODO: Actually this needs to be done earlier; we can hold off on loading
# this code until it's needed though.

# We can't use register_control_format because it adds it at a lower priority
# than the existing branches, whereas this should take priority.
BzrDirFormat._control_formats.insert(0, RemoteBzrDirFormat())
