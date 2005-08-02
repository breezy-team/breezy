#!/usr/bin/env python
"""\
An implementation of the Transport object for http access.
"""

from bzrlib.transport import Transport, register_transport, \
    TransportNotPossible, NoSuchFile, NonRelativePath, \
    TransportError
import os, errno, time, asyncore
from cStringIO import StringIO
import urllib2

from bzrlib.errors import BzrError, BzrCheckError
from bzrlib.branch import Branch, BZR_BRANCH_FORMAT
from bzrlib.trace import mutter

from effbot.org.http_client import do_request

class HttpTransportError(TransportError):
    pass

class simple_wait_consumer(object):
    """This is a consumer object for effbot.org downloading.

    Basically, it takes a management object, which it expects to
    fill itself (eventually) if it waits long enough.
    So it loops to wait for the download to finish, until it
    finally gets closed.
    """
    def __init__(self, url, extra_headers=None):
        self.buffer = StringIO()
        self.done = False
        self.ok = True
        self.status = None
        self.url = url
        do_request(self.url, self)

    def get(self):
        while not self.done:
            asyncore.poll(0.1)
        # Try and break cyclical loops
        if self.ok:
            self.buffer.seek(0)
            return self.buffer
        else:
            raise HttpTransportError('Download of %r failed: %r' 
                    % (self.url, self.status))

    def feed(self, data):
        self.buffer.write(data)

    def close(self):
        self.done = True

    def http(self, ok, connection, **args):
        mutter('simple-wait-consumer: %s' % connection)
        self.ok = ok
        if not ok:
            self.done = True
        self.status = connection.status

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
        baseurl = self.base.rstrip('/')
        return '/'.join([baseurl] + relpath)

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
        """
        try:
            f = get_url(self.abspath(relpath))
            return True
        except BzrError:
            return False
        except urllib2.URLError:
            return False
        except IOError, e:
            if e.errno == errno.ENOENT:
                return False
            raise HttpTransportError(orig_error=e)

    def _get(self, consumer):
        """Return the consumer's value"""
        return consumer.get()

    def get(self, relpath):
        """Get the file at the given relative path.

        :param relpath: The relative path to the file
        """
        c = simple_wait_consumer(self.abspath(relpath))
        return c.get()

    def get_multi(self, relpaths, pb=None):
        """Get a list of file-like objects, one for each entry in relpaths.

        :param relpaths: A list of relative paths.
        :param decode:  If True, assume the file is utf-8 encoded and
                        decode it into Unicode
        :param pb:  An optional ProgressBar for indicating percent done.
        :return: A list or generator of file-like objects
        """
        consumers = []
        for relpath in relpaths:
            consumers.append(simple_wait_consumer(self.abspath(relpath)))
        total = self._get_total(consumers)
        count = 0
        for c in consumers:
            self._update_pb(pb, 'get', count, total)
            yield c.get()
            count += 1

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

