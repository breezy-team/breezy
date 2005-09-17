#!/usr/bin/env python
"""\
An implementation of the Transport object for http access.
"""

from bzrlib.transport import Transport, register_transport, \
    TransportNotPossible, NoSuchFile, NonRelativePath, \
    TransportError
import os, errno
from cStringIO import StringIO
import urllib2
import urlparse

from bzrlib.errors import BzrError, BzrCheckError
from bzrlib.branch import Branch, BZR_BRANCH_FORMAT
from bzrlib.trace import mutter

# velocitynet.com.au transparently proxies connections and thereby
# breaks keep-alive -- sucks!


def get_url(url):
    import urllib2
    mutter("get_url %s" % url)
    url_f = urllib2.urlopen(url)
    return url_f

class HttpTransportError(TransportError):
    pass

class HttpTransport(Transport):
    """This is the transport agent for http:// access.
    
    TODO: Implement pipelined versions of all of the *_multi() functions.
    """

    def __init__(self, base):
        """Set the base path where files will be stored."""
        assert base.startswith('http://') or base.startswith('https://')
        super(HttpTransport, self).__init__(base)
        # In the future we might actually connect to the remote host
        # rather than using get_url
        # self._connection = None
        (self._proto, self._host,
            self._path, self._parameters,
            self._query, self._fragment) = urlparse.urlparse(self.base)

    def should_cache(self):
        """Return True if the data pulled across should be cached locally.
        """
        return True

    def clone(self, offset=None):
        """Return a new HttpTransport with root at self.base + offset
        For now HttpTransport does not actually connect, so just return
        a new HttpTransport object.
        """
        if offset is None:
            return HttpTransport(self.base)
        else:
            return HttpTransport(self.abspath(offset))

    def abspath(self, relpath):
        """Return the full url to the given relative path.
        This can be supplied with a string or a list
        """
        if isinstance(relpath, basestring):
            relpath = [relpath]
        basepath = self._path.split('/')
        if len(basepath) > 0 and basepath[-1] == '':
            basepath = basepath[:-1]

        for p in relpath:
            if p == '..':
                if len(basepath) < 0:
                    # In most filesystems, a request for the parent
                    # of root, just returns root.
                    continue
                basepath.pop()
            elif p == '.':
                continue # No-op
            else:
                basepath.append(p)

        # Possibly, we could use urlparse.urljoin() here, but
        # I'm concerned about when it chooses to strip the last
        # portion of the path, and when it doesn't.
        path = '/'.join(basepath)
        return urlparse.urlunparse((self._proto,
                self._host, path, '', '', ''))

    def relpath(self, abspath):
        if not abspath.startswith(self.base):
            raise NonRelativePath('path %r is not under base URL %r'
                           % (abspath, self.base))
        pl = len(self.base)
        return abspath[pl:].lstrip('/')

    def has(self, relpath):
        """Does the target location exist?

        TODO: HttpTransport.has() should use a HEAD request,
        not a full GET request.

        TODO: This should be changed so that we don't use
        urllib2 and get an exception, the code path would be
        cleaner if we just do an http HEAD request, and parse
        the return code.
        """
        try:
            f = get_url(self.abspath(relpath))
            # Without the read and then close()
            # we tend to have busy sockets.
            f.read()
            f.close()
            return True
        except BzrError:
            return False
        except urllib2.URLError:
            return False
        except IOError, e:
            if e.errno == errno.ENOENT:
                return False
            raise HttpTransportError(orig_error=e)

    def get(self, relpath, decode=False):
        """Get the file at the given relative path.

        :param relpath: The relative path to the file
        """
        try:
            return get_url(self.abspath(relpath))
        except BzrError, e:
            raise NoSuchFile(orig_error=e)
        except urllib2.URLError, e:
            raise NoSuchFile(orig_error=e)
        except IOError, e:
            raise NoSuchFile(orig_error=e)
        except Exception,e:
            raise HttpTransportError(orig_error=e)

    def put(self, relpath, f):
        """Copy the file-like or string object into the location.

        :param relpath: Location to put the contents, relative to base.
        :param f:       File-like or string object.
        """
        raise TransportNotPossible('http PUT not supported')

    def mkdir(self, relpath):
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

    def copy_to(self, relpaths, other, pb=None):
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
            return super(HttpTransport, self).copy_to(relpaths, other, pb=pb)

    def move(self, rel_from, rel_to):
        """Move the item at rel_from to the location at rel_to"""
        raise TransportNotPossible('http does not support move()')

    def delete(self, relpath):
        """Delete the item at relpath"""
        raise TransportNotPossible('http does not support delete()')

    def async_get(self, relpath):
        """Make a request for an file at the given location, but
        don't worry about actually getting it yet.

        :rtype: AsyncFile
        """
        raise NotImplementedError

    def list_dir(self, relpath):
        """Return a list of all files at the given location.
        WARNING: many transports do not support this, so trying avoid using
        it if at all possible.
        """
        raise TransportNotPossible('http does not support list_dir()')

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

register_transport('http://', HttpTransport)
register_transport('https://', HttpTransport)

