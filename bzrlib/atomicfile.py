# Copyright (C) 2004, 2005 by Canonical Ltd
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


import codecs
import errno
import os
import socket
import sys
from warnings import warn

from bzrlib.osutils import rename

# not forksafe - but we dont fork.
_pid = os.getpid()

class AtomicFile(object):
    """A file that does an atomic-rename to move into place.

    This also causes hardlinks to break when it's written out.

    Open this as for a regular file, then use commit() to move into
    place or abort() to cancel.

    An encoding can be specified; otherwise the default is ascii.
    """

    __slots__ = ['closed', 'f', 'tmpfilename', 'realfilename', 'write']

    def __init__(self, filename, mode='wb', new_mode=0666):
        self.f = None
        assert mode in ('wb', 'wt'), \
            "invalid AtomicFile mode %r" % mode

        # old version:
        #self.tmpfilename = '%s.%d.%s.tmp' % (filename, os.getpid(),
        #                                     socket.gethostname())
        # new version:
        # This is 'broken' on NFS: it wmay collide with another NFS client.
        # however, we use this to write files within a directory that we have
        # locked, so it being racy on NFS is not a concern. The only other
        # files we use this for are .bzr.ignore, which can race anyhow.
        self.tmpfilename = '%s.%d.tmp' % (filename, _pid)

        self.realfilename = filename
        
        # Use a low level fd operation to avoid chmodding later.
        fd = os.open(self.tmpfilename, os.O_EXCL | os.O_CREAT | os.O_WRONLY,
            new_mode)
        # open a normal python file to get the text vs binary support needed
        # for windows.
        self.closed = False
        try:
            self.f = os.fdopen(fd, mode)
        except:
            os.close(fd)
            self.closed = True
            raise
        self.write = self.f.write

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__,
                           self.realfilename)

    def commit(self):
        """Close the file and move to final name."""
        if self.closed:
            raise Exception('%r is already closed' % self)

        f = self.f
        self.f = None
        f.close()
        rename(self.tmpfilename, self.realfilename)

    def abort(self):
        """Discard temporary file without committing changes."""

        if self.f is None:
            raise Exception('%r is already closed' % self)

        f = self.f
        self.f = None
        f.close()
        os.remove(self.tmpfilename)

    def close(self):
        """Discard the file unless already committed."""
        if self.f is not None:
            self.abort()

    def __del__(self):
        if self.f is not None:
            warn("%r leaked" % self)
