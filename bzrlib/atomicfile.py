# Copyright (C) 2004, 2005 by Canonical Ltd

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



class AtomicFile(object):
    """A file that does an atomic-rename to move into place.

    This also causes hardlinks to break when it's written out.

    Open this as for a regular file, then use commit() to move into
    place or abort() to cancel.

    An encoding can be specified; otherwise the default is ascii.
    """

    def __init__(self, filename, mode='wb', encoding=None):
        if mode != 'wb' and mode != 'wt':
            raise ValueError("invalid AtomicFile mode %r" % mode)

        import os, socket
        self.tmpfilename = '%s.%d.%s.tmp' % (filename, os.getpid(),
                                             socket.gethostname())
        self.realfilename = filename
        
        self.f = open(self.tmpfilename, mode)

        if encoding:
            import codecs
            self.f = codecs.EncodedFile(self.f, encoding)
        
        self.write = self.f.write
        self.closed = property(self.f.closed)

    def commit(self):
        """Close the file and move to final name."""
        import sys, os
        
        self.f.close()
        if sys.platform == 'win32':
            # windows cannot rename over an existing file
            try:
                os.remove(self.realfilename)
            except OSError, e:
                import errno
                if e.errno != errno.ENOENT:
                    raise
        os.rename(self.tmpfilename, self.realfilename)

    def abort(self):
        """Discard temporary file without committing changes."""
        import os
        self.f.close()
        os.remove(self.tmpfilename)

    def close(self):
        """Discard the file unless already committed."""
        if not self.closed:
            self.abort()
        
        
