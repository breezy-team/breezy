#!/usr/bin/env python
"""\
An implementation of the Transport object for http access.
"""

from bzrlib.transport import Transport, protocol_handlers, TransportNotPossibleError
import os
from cStringIO import StringIO
import urllib2

from errors import BzrError, BzrCheckError
from branch import Branch, BZR_BRANCH_FORMAT
from trace import mutter

# velocitynet.com.au transparently proxies connections and thereby
# breaks keep-alive -- sucks!


ENABLE_URLGRABBER = True


if ENABLE_URLGRABBER:
    import urlgrabber
    import urlgrabber.keepalive
    urlgrabber.keepalive.DEBUG = 0
    def get_url(path, compressed=False):
        try:
            url = path
            if compressed:
                url += '.gz'
            mutter("grab url %s" % url)
            url_f = urlgrabber.urlopen(url, keepalive=1, close_connection=0)
            if not compressed:
                return url_f
            else:
                return gzip.GzipFile(fileobj=StringIO(url_f.read()))
        except urllib2.URLError, e:
            raise BzrError("remote fetch failed: %r: %s" % (url, e))
else:
    def get_url(url, compressed=False):
        import urllib2
        if compressed:
            url += '.gz'
        mutter("get_url %s" % url)
        url_f = urllib2.urlopen(url)
        if compressed:
            return gzip.GzipFile(fileobj=StringIO(url_f.read()))
        else:
            return url_f

def _find_remote_root(url):
    """Return the prefix URL that corresponds to the branch root."""
    orig_url = url
    while True:
        try:
            ff = get_url(url + '/.bzr/branch-format')

            fmt = ff.read()
            ff.close()

            fmt = fmt.rstrip('\r\n')
            if fmt != BZR_BRANCH_FORMAT.rstrip('\r\n'):
                raise BzrError("sorry, branch format %r not supported at url %s"
                               % (fmt, url))
            
            return url
        except urllib2.URLError:
            pass

        try:
            idx = url.rindex('/')
        except ValueError:
            raise BzrError('no branch root found for URL %s' % orig_url)

        url = url[:idx]        
        

class HttpTransport(Transport):
    """This is the transport agent for local filesystem access."""

    def __init__(self, base):
        """Set the base path where files will be stored."""
        assert base.startswith('http://') or base.startswith('https://')
        super(HttpTransport, self).__init__(base)
        # In the future we might actually connect to the remote host
        # rather than using get_url
        # self._connection = None

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
        return '/'.join([self.base] + relpath)

    def relpath(self, abspath):
        if not abspath.startswith(self.base):
            raise BzrError('path %r is not under base URL %r'
                           % (abspath, self.base))
        pl = len(self.base)
        return abspath[pl:].lstrip('/')

    def has(self, relpath):
        try:
            f = get_url(self.abspath(relpath))
            return True
        except urllib2.URLError:
            return False

    def get(self, relpath, decode=False):
        """Get the file at the given relative path.

        :param relpath: The relative path to the file
        :param decode:  If True, assume the file is utf-8 encoded and
                        decode it into Unicode
        """
        if decode:
            import codecs
            return codecs.getreader('utf-8')(get_url(self.abspath(relpath)))
        else:
            return get_url(self.abspath(relpath))

    def put(self, relpath, f, encode=False):
        """Copy the file-like or string object into the location.

        :param relpath: Location to put the contents, relative to base.
        :param f:       File-like or string object.
        :param encode:  If True, translate the contents into utf-8 encoded text.
        """
        raise TransportNotPossibleError('http does not support put()')

    def mkdir(self, relpath):
        """Create a directory at the given path."""
        raise TransportNotPossibleError('http does not support mkdir()')

    def append(self, relpath, f):
        """Append the text in the file-like object into the final
        location.
        """
        raise TransportNotPossibleError('http does not support append()')

    def copy(self, rel_from, rel_to):
        """Copy the item at rel_from to the location at rel_to"""
        raise TransportNotPossibleError('http does not support copy()')

    def move(self, rel_from, rel_to):
        """Move the item at rel_from to the location at rel_to"""
        raise TransportNotPossibleError('http does not support move()')

    def delete(self, relpath):
        """Delete the item at relpath"""
        raise TransportNotPossibleError('http does not support delete()')

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
        raise TransportNotPossibleError('http does not support list_dir()')

    def stat(self, relpath):
        """Return the stat information for a file.
        """
        raise TransportNotPossibleError('http does not support stat()')

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
        raise TransportNotPossibleError('http does not support lock_write()')

# If nothing else matches, try the LocalTransport
protocol_handlers['http://'] = HttpTransport
protocol_handlers['https://'] = HttpTransport

