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
"""Implementation of Transport over ftp.

Written by Daniel Silverstone <dsilvers@digital-scurf.org> with serious
cargo-culting from the sftp transport and the http transport.

It provides the ftp:// and aftp:// protocols where ftp:// is passive ftp
and aftp:// is active ftp. Most people will want passive ftp for traversing
NAT and other firewalls, so it's best to use it unless you explicitly want
active, in which case aftp:// will be your friend.
"""

from cStringIO import StringIO
import errno
import ftplib
import os
import urllib
import urlparse
import stat
from warnings import warn


from bzrlib.transport import Transport
from bzrlib.errors import (TransportNotPossible, TransportError,
                           NoSuchFile, FileExists)
from bzrlib.trace import mutter, warning


_FTP_cache = {}
def _find_FTP(hostname, username, password, is_active):
    """Find an ftplib.FTP instance attached to this triplet."""
    key = "%s|%s|%s|%s" % (hostname, username, password, is_active)
    if key not in _FTP_cache:
        mutter("Constructing FTP instance against %r" % key)
        _FTP_cache[key] = ftplib.FTP(hostname, username, password)
        _FTP_cache[key].set_pasv(not is_active)
    return _FTP_cache[key]    


class FtpTransportError(TransportError):
    pass


class FtpStatResult(object):
    def __init__(self, f, relpath):
        try:
            self.st_size = f.size(relpath)
            self.st_mode = stat.S_IFREG
        except ftplib.error_perm:
            pwd = f.pwd()
            try:
                f.cwd(relpath)
                self.st_mode = stat.S_IFDIR
            finally:
                f.cwd(pwd)


class FtpTransport(Transport):
    """This is the transport agent for ftp:// access."""

    _number_of_retries = 1

    def __init__(self, base, _provided_instance=None):
        """Set the base path where files will be stored."""
        assert base.startswith('ftp://') or base.startswith('aftp://')
        super(FtpTransport, self).__init__(base)
        self.is_active = base.startswith('aftp://')
        if self.is_active:
            base = base[1:]
        (self._proto, self._host,
            self._path, self._parameters,
            self._query, self._fragment) = urlparse.urlparse(self.base)
        self._FTP_instance = _provided_instance

    def _get_FTP(self):
        """Return the ftplib.FTP instance for this object."""
        if self._FTP_instance is not None:
            return self._FTP_instance
        
        try:
            username = ''
            password = ''
            hostname = self._host
            if '@' in hostname:
                username, hostname = hostname.split("@", 1)
            if ':' in username:
                username, password = username.split(":", 1)

            self._FTP_instance = _find_FTP(hostname, username, password,
                                           self.is_active)
            return self._FTP_instance
        except ftplib.error_perm, e:
            raise TransportError(msg="Error setting up connection: %s"
                                    % str(e), orig_error=e)

    def should_cache(self):
        """Return True if the data pulled across should be cached locally.
        """
        return True

    def clone(self, offset=None):
        """Return a new FtpTransport with root at self.base + offset.
        """
        mutter("FTP clone")
        if offset is None:
            return FtpTransport(self.base, self._FTP_instance)
        else:
            return FtpTransport(self.abspath(offset), self._FTP_instance)

    def _abspath(self, relpath):
        assert isinstance(relpath, basestring)
        relpath = urllib.unquote(relpath)
        if isinstance(relpath, basestring):
            relpath_parts = relpath.split('/')
        else:
            # TODO: Don't call this with an array - no magic interfaces
            relpath_parts = relpath[:]
        if len(relpath_parts) > 1:
            if relpath_parts[0] == '':
                raise ValueError("path %r within branch %r seems to be absolute"
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
        return '/'.join(basepath)
    
    def abspath(self, relpath):
        """Return the full url to the given relative path.
        This can be supplied with a string or a list
        """
        path = self._abspath(relpath)
        return urlparse.urlunparse((self._proto,
                self._host, path, '', '', ''))

    def has(self, relpath):
        """Does the target location exist?

        XXX: I assume we're never asked has(dirname) and thus I use
        the FTP size command and assume that if it doesn't raise,
        all is good.
        """
        try:
            f = self._get_FTP()
            s = f.size(self._abspath(relpath))
            mutter("FTP has: %s" % self._abspath(relpath))
            return True
        except ftplib.error_perm:
            mutter("FTP has not: %s" % self._abspath(relpath))
            return False

    def get(self, relpath, decode=False, retries=0):
        """Get the file at the given relative path.

        :param relpath: The relative path to the file
        :param retries: Number of retries after temporary failures so far
                        for this operation.

        We're meant to return a file-like object which bzr will
        then read from. For now we do this via the magic of StringIO
        """
        try:
            mutter("FTP get: %s" % self._abspath(relpath))
            f = self._get_FTP()
            ret = StringIO()
            f.retrbinary('RETR '+self._abspath(relpath), ret.write, 8192)
            ret.seek(0)
            return ret
        except ftplib.error_perm, e:
            raise NoSuchFile(self.abspath(relpath), extra=str(e))
        except ftplib.error_temp, e:
            if retries > 1:
                raise
            else:
                warning("FTP temporary error: %s. Retrying." % str(e))
                self._FTP_instance = None
                return self.get(relpath, decode, retries+1)
        except EOFError:
            if retries > _number_of_retries:
                raise
            else:
                warning("FTP control connection closed. Trying to reopen.")
                self._FTP_instance = None
                return self.get(relpath, decode, retries+1)

    def put(self, relpath, fp, mode=None, retries=0):
        """Copy the file-like or string object into the location.

        :param relpath: Location to put the contents, relative to base.
        :param f:       File-like or string object.
        :param retries: Number of retries after temporary failures so far
                        for this operation.

        TODO: jam 20051215 This should be an atomic put, not overwritting files in place
        TODO: jam 20051215 ftp as a protocol seems to support chmod, but ftplib does not
        """
        if not hasattr(fp, 'read'):
            fp = StringIO(fp)
        try:
            mutter("FTP put: %s" % self._abspath(relpath))
            f = self._get_FTP()
            f.storbinary('STOR '+self._abspath(relpath), fp, 8192)
        except ftplib.error_perm, e:
            if "no such file" in str(e).lower():
                raise NoSuchFile("Error storing %s: %s"
                                 % (self.abspath(relpath), str(e)), extra=e)
            else:
                raise FtpTransportError(orig_error=e)
        except ftplib.error_temp, e:
            if retries > _number_of_retries:
                raise
            else:
                warning("FTP temporary error: %s. Retrying." % str(e))
                self._FTP_instance = None
                self.put(relpath, fp, mode, retries+1)
        except EOFError:
            if retries > _number_of_retries:
                raise
            else:
                warning("FTP connection closed. Trying to reopen.")
                self._FTP_instance = None
                self.put(relpath, fp, mode, retries+1)


    def mkdir(self, relpath, mode=None):
        """Create a directory at the given path."""
        try:
            mutter("FTP mkd: %s" % self._abspath(relpath))
            f = self._get_FTP()
            try:
                f.mkd(self._abspath(relpath))
            except ftplib.error_perm, e:
                s = str(e)
                if 'File exists' in s:
                    raise FileExists(self.abspath(relpath), extra=s)
                else:
                    raise
        except ftplib.error_perm, e:
            raise TransportError(orig_error=e)

    def append(self, relpath, f):
        """Append the text in the file-like object into the final
        location.
        """
        raise TransportNotPossible('ftp does not support append()')

    def copy(self, rel_from, rel_to):
        """Copy the item at rel_from to the location at rel_to"""
        raise TransportNotPossible('ftp does not (yet) support copy()')

    def move(self, rel_from, rel_to):
        """Move the item at rel_from to the location at rel_to"""
        try:
            mutter("FTP mv: %s => %s" % (self._abspath(rel_from),
                                         self._abspath(rel_to)))
            f = self._get_FTP()
            f.rename(self._abspath(rel_from), self._abspath(rel_to))
        except ftplib.error_perm, e:
            raise TransportError(orig_error=e)

    def delete(self, relpath):
        """Delete the item at relpath"""
        try:
            mutter("FTP rm: %s" % self._abspath(relpath))
            f = self._get_FTP()
            f.delete(self._abspath(relpath))
        except ftplib.error_perm, e:
            raise TransportError(orig_error=e)

    def listable(self):
        """See Transport.listable."""
        return True

    def list_dir(self, relpath):
        """See Transport.list_dir."""
        try:
            mutter("FTP nlst: %s" % self._abspath(relpath))
            f = self._get_FTP()
            basepath = self._abspath(relpath)
            # FTP.nlst returns paths prefixed by relpath, strip 'em
            the_list = f.nlst(basepath)
            stripped = [path[len(basepath)+1:] for path in the_list]
            # Remove . and .. if present, and return
            return [path for path in stripped if path not in (".", "..")]
        except ftplib.error_perm, e:
            raise TransportError(orig_error=e)

    def iter_files_recursive(self):
        """See Transport.iter_files_recursive.

        This is cargo-culted from the SFTP transport"""
        mutter("FTP iter_files_recursive")
        queue = list(self.list_dir("."))
        while queue:
            relpath = urllib.quote(queue.pop(0))
            st = self.stat(relpath)
            if stat.S_ISDIR(st.st_mode):
                for i, basename in enumerate(self.list_dir(relpath)):
                    queue.insert(i, relpath+"/"+basename)
            else:
                yield relpath

    def stat(self, relpath):
        """Return the stat information for a file.
        """
        try:
            mutter("FTP stat: %s" % self._abspath(relpath))
            f = self._get_FTP()
            return FtpStatResult(f, self._abspath(relpath))
        except ftplib.error_perm, e:
            raise TransportError(orig_error=e)

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
        return self.lock_read(relpath)


def get_test_permutations():
    """Return the permutations to be used in testing."""
    warn("There are no FTP transport provider tests yet.")
    return []
