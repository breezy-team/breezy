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

import urllib, urllib2

from bzrlib.errors import BzrError
from bzrlib.trace import mutter
from bzrlib.transport.http import HttpTransportBase, extract_auth, HttpServer
from bzrlib.errors import (TransportNotPossible, NoSuchFile,
                           TransportError, ConnectionError)


class HttpTransport(HttpTransportBase):
    """Python urllib transport for http and https.
    """

    # TODO: Implement pipelined versions of all of the *_multi() functions.

    def __init__(self, base):
        """Set the base path where files will be stored."""
        super(HttpTransport, self).__init__(base)

    def _get_url(self, url):
        mutter("get_url %s" % url)
        manager = urllib2.HTTPPasswordMgrWithDefaultRealm()
        url = extract_auth(url, manager)
        auth_handler = urllib2.HTTPBasicAuthHandler(manager)
        opener = urllib2.build_opener(auth_handler)
        url_f = opener.open(url)
        return url_f

    def should_cache(self):
        """Return True if the data pulled across should be cached locally.
        """
        return True

    def has(self, relpath):
        """Does the target location exist?

        TODO: HttpTransport.has() should use a HEAD request,
        not a full GET request.

        TODO: This should be changed so that we don't use
        urllib2 and get an exception, the code path would be
        cleaner if we just do an http HEAD request, and parse
        the return code.
        """
        path = relpath
        try:
            path = self.abspath(relpath)
            f = self._get_url(path)
            # Without the read and then close()
            # we tend to have busy sockets.
            f.read()
            f.close()
            return True
        except urllib2.URLError, e:
            mutter('url error code: %s for has url: %r', e.code, path)
            if e.code == 404:
                return False
            raise
        except IOError, e:
            mutter('io error: %s %s for has url: %r', 
                e.errno, errno.errorcode.get(e.errno), path)
            if e.errno == errno.ENOENT:
                return False
            raise TransportError(orig_error=e)

    def get(self, relpath):
        """Get the file at the given relative path.

        :param relpath: The relative path to the file
        """
        path = relpath
        try:
            path = self.abspath(relpath)
            return self._get_url(path)
        except urllib2.HTTPError, e:
            mutter('url error code: %s for has url: %r', e.code, path)
            if e.code == 404:
                raise NoSuchFile(path, extra=e)
            raise
        except (BzrError, IOError), e:
            if hasattr(e, 'errno'):
                mutter('io error: %s %s for has url: %r', 
                    e.errno, errno.errorcode.get(e.errno), path)
                if e.errno == errno.ENOENT:
                    raise NoSuchFile(path, extra=e)
            raise ConnectionError(msg = "Error retrieving %s: %s" 
                             % (self.abspath(relpath), str(e)),
                             orig_error=e)

    def copy_to(self, relpaths, other, mode=None, pb=None):
        """Copy a set of entries from self into another Transport.

        :param relpaths: A list/generator of entries to be copied.

        TODO: if other is LocalTransport, is it possible to
              do better than put(get())?
        """
        # At this point HttpTransport might be able to check and see if
        # the remote location is the same, and rather than download, and
        # then upload, it could just issue a remote copy_this command.
        if isinstance(other, HttpTransport):
            raise TransportNotPossible('http cannot be the target of copy_to()')
        else:
            return super(HttpTransport, self).copy_to(relpaths, other, mode=mode, pb=pb)

    def move(self, rel_from, rel_to):
        """Move the item at rel_from to the location at rel_to"""
        raise TransportNotPossible('http does not support move()')

    def delete(self, relpath):
        """Delete the item at relpath"""
        raise TransportNotPossible('http does not support delete()')

def get_test_permutations():
    """Return the permutations to be used in testing."""
    # XXX: There are no HTTPS transport provider tests yet.
    return [(HttpTransport, HttpServer),
            ]
