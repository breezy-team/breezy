# Copyright (C) 2005, 2006 Canonical Ltd

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

"""Base implementation of Transport over http.

There are separate implementation modules for each http client implementation.
"""

import errno
from cStringIO import StringIO
import urlparse
import urllib

from bzrlib.transport import Transport, register_transport
from bzrlib.errors import (TransportNotPossible, NoSuchFile, 
                           TransportError, ConnectionError)
from bzrlib.errors import BzrError, BzrCheckError
from bzrlib.branch import Branch
from bzrlib.trace import mutter


def extract_auth(url, password_manager):
    """
    Extract auth parameters from am HTTP/HTTPS url and add them to the given
    password manager.  Return the url, minus those auth parameters (which
    confuse urllib2).
    """
    assert url.startswith('http://') or url.startswith('https://')
    scheme, host = url.split('//', 1)
    if '/' in host:
        host, path = host.split('/', 1)
        path = '/' + path
    else:
        path = ''
    port = ''
    if '@' in host:
        auth, host = host.split('@', 1)
        if ':' in auth:
            username, password = auth.split(':', 1)
        else:
            username, password = auth, None
        if ':' in host:
            host, port = host.split(':', 1)
            port = ':' + port
        # FIXME: if password isn't given, should we ask for it?
        if password is not None:
            username = urllib.unquote(username)
            password = urllib.unquote(password)
            password_manager.add_password(None, host, username, password)
    url = scheme + '//' + host + port + path
    return url
    

class HttpTransportBase(Transport):
    """Base class for http implementations.

    Does URL parsing, etc, but not any network IO."""
    def __init__(self, base):
        """Set the base path where files will be stored."""
        assert base.startswith('http://') or base.startswith('https://')
        super(HttpTransportBase, self).__init__(base)
        (self._proto, self._host,
            self._path, self._parameters,
            self._query, self._fragment) = urlparse.urlparse(self.base)

    def abspath(self, relpath):
        """Return the full url to the given relative path.
        This can be supplied with a string or a list
        """
        assert isinstance(relpath, basestring)
        if isinstance(relpath, basestring):
            relpath_parts = relpath.split('/')
        else:
            # TODO: Don't call this with an array - no magic interfaces
            relpath_parts = relpath[:]
        if len(relpath_parts) > 1:
            if relpath_parts[0] == '':
                raise ValueError("path %r within branch %r seems to be absolute"
                                 % (relpath, self._path))
            if relpath_parts[-1] == '':
                raise ValueError("path %r within branch %r seems to be a directory"
                                 % (relpath, self._path))
        basepath = self._path.split('/')
        if len(basepath) > 0 and basepath[-1] == '':
            basepath = basepath[:-1]
        for p in relpath_parts:
            if p == '..':
                if len(basepath) == 0:
                    # In most filesystems, a request for the parent
                    # of root, just returns root.
                    continue
                basepath.pop()
            elif p == '.' or p == '':
                continue # No-op
            else:
                basepath.append(p)
        # Possibly, we could use urlparse.urljoin() here, but
        # I'm concerned about when it chooses to strip the last
        # portion of the path, and when it doesn't.
        path = '/'.join(basepath)
        return urlparse.urlunparse((self._proto,
                self._host, path, '', '', ''))

    def stat(self, relpath):
        """Return the stat information for a file.
        """
        raise TransportNotPossible('http does not support stat()')

    def lock_read(self, relpath):
        """Lock the given file for shared (read) access.
        :return: A lock object, which should be passed to Transport.unlock()
        """
        # The old RemoteBranch ignore lock for reading, so we will
        # continue that tradition and return a bogus lock object.
        class BogusLock(object):
            def __init__(self, path):
                self.path = path
            def unlock(self):
                pass
        return BogusLock(relpath)

    def lock_write(self, relpath):
        """Lock the given file for exclusive (write) access.
        WARNING: many transports do not support this, so trying avoid using it

        :return: A lock object, which should be passed to Transport.unlock()
        """
        raise TransportNotPossible('http does not support lock_write()')

    def clone(self, offset=None):
        """Return a new HttpTransport with root at self.base + offset
        For now HttpTransport does not actually connect, so just return
        a new HttpTransport object.
        """
        if offset is None:
            return self.__class__(self.base)
        else:
            return self.__class__(self.abspath(offset))

    def listable(self):
        """Returns false - http has no reliable way to list directories."""
        # well, we could try DAV...
        return False

    def put(self, relpath, f, mode=None):
        """Copy the file-like or string object into the location.

        :param relpath: Location to put the contents, relative to base.
        :param f:       File-like or string object.
        """
        raise TransportNotPossible('http PUT not supported')

    def mkdir(self, relpath, mode=None):
        """Create a directory at the given path."""
        raise TransportNotPossible('http does not support mkdir()')

    def append(self, relpath, f):
        """Append the text in the file-like object into the final
        location.
        """
        raise TransportNotPossible('http does not support append()')

    def copy(self, rel_from, rel_to):
        """Copy the item at rel_from to the location at rel_to"""
        raise TransportNotPossible('http does not support copy()')

