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
import asyncore
import errno
import ftplib
import os
import urllib
import urlparse
import stat
import threading
import time
import random
from warnings import warn

try:
    import medusa
    import medusa.filesys
    import medusa.ftp_server
except ImportError:
    _have_medusa = False
else:
    _have_medusa = True


from bzrlib.transport import (
    Transport,
    Server,
    split_url,
    )
from bzrlib.errors import (TransportNotPossible, TransportError,
                           NoSuchFile, FileExists, DirectoryNotEmpty)
from bzrlib.trace import mutter, warning


_FTP_cache = {}
def _find_FTP(hostname, port, username, password, is_active):
    """Find an ftplib.FTP instance attached to this triplet."""
    key = (hostname, port, username, password, is_active)
    alt_key = (hostname, port, username, '********', is_active)
    if key not in _FTP_cache:
        mutter("Constructing FTP instance against %r" % (alt_key,))
        conn = ftplib.FTP()

        conn.connect(host=hostname, port=port)
        conn.login(user=username, passwd=password)
        conn.set_pasv(not is_active)

        _FTP_cache[key] = conn

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


_number_of_retries = 2
_sleep_between_retries = 5

class FtpTransport(Transport):
    """This is the transport agent for ftp:// access."""

    def __init__(self, base, _provided_instance=None):
        """Set the base path where files will be stored."""
        assert base.startswith('ftp://') or base.startswith('aftp://')

        self.is_active = base.startswith('aftp://')
        if self.is_active:
            # urlparse won't handle aftp://
            base = base[1:]
        if not base.endswith('/'):
            base += '/'
        (self._proto, self._username,
            self._password, self._host,
            self._port, self._path) = split_url(base)
        base = self._unparse_url()

        super(FtpTransport, self).__init__(base)
        self._FTP_instance = _provided_instance

    def _unparse_url(self, path=None):
        if path is None:
            path = self._path
        path = urllib.quote(path)
        netloc = urllib.quote(self._host)
        if self._username is not None:
            netloc = '%s@%s' % (urllib.quote(self._username), netloc)
        if self._port is not None:
            netloc = '%s:%d' % (netloc, self._port)
        return urlparse.urlunparse(('ftp', netloc, path, '', '', ''))

    def _get_FTP(self):
        """Return the ftplib.FTP instance for this object."""
        if self._FTP_instance is not None:
            return self._FTP_instance
        
        try:
            self._FTP_instance = _find_FTP(self._host, self._port,
                                           self._username, self._password,
                                           self.is_active)
            return self._FTP_instance
        except ftplib.error_perm, e:
            raise TransportError(msg="Error setting up connection: %s"
                                    % str(e), orig_error=e)

    def _translate_perm_error(self, err, path, extra=None):
        """Try to translate an ftplib.error_perm exception."""
        s = str(err).lower()
        if not extra:
            extra = str(err)
        if ('no such file' in s
            or 'could not open' in s):
            raise NoSuchFile(path, extra=extra)
        if ('file exists' in s):
            raise FileExists(self.abspath(relpath), extra=s)
        raise
        # TODO: jam 20060516 Consider re-raising the error wrapped in 
        #       something like TransportError, but this loses the traceback
        #raise TransportError(msg='Error for path: %s' % (path,), orig_error=e)

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
        relpath_parts = relpath.split('/')
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
        return '/'.join(basepath) or '/'
    
    def abspath(self, relpath):
        """Return the full url to the given relative path.
        This can be supplied with a string or a list
        """
        path = self._abspath(relpath)
        return self._unparse_url(path)

    def has(self, relpath):
        """Does the target location exist?

        XXX: I assume we're never asked has(dirname) and thus I use
        the FTP size command and assume that if it doesn't raise,
        all is good.
        """
        try:
            f = self._get_FTP()
            s = f.size(self._abspath(relpath))
            mutter("FTP has: %s", self._abspath(relpath))
            return True
        except ftplib.error_perm:
            mutter("FTP has not: %s", self._abspath(relpath))
            return False

    def get(self, relpath, decode=False, retries=0):
        """Get the file at the given relative path.

        :param relpath: The relative path to the file
        :param retries: Number of retries after temporary failures so far
                        for this operation.

        We're meant to return a file-like object which bzr will
        then read from. For now we do this via the magic of StringIO
        """
        # TODO: decode should be deprecated
        try:
            mutter("FTP get: %s", self._abspath(relpath))
            f = self._get_FTP()
            ret = StringIO()
            f.retrbinary('RETR '+self._abspath(relpath), ret.write, 8192)
            ret.seek(0)
            return ret
        except ftplib.error_perm, e:
            raise NoSuchFile(self.abspath(relpath), extra=str(e))
        except ftplib.error_temp, e:
            if retries > _number_of_retries:
                raise TransportError(msg="FTP temporary error during GET %s. Aborting."
                                     % self.abspath(relpath),
                                     orig_error=e)
            else:
                warning("FTP temporary error: %s. Retrying.", str(e))
                self._FTP_instance = None
                return self.get(relpath, decode, retries+1)
        except EOFError, e:
            if retries > _number_of_retries:
                raise TransportError("FTP control connection closed during GET %s."
                                     % self.abspath(relpath),
                                     orig_error=e)
            else:
                warning("FTP control connection closed. Trying to reopen.")
                time.sleep(_sleep_between_retries)
                self._FTP_instance = None
                return self.get(relpath, decode, retries+1)

    def put(self, relpath, fp, mode=None, retries=0):
        """Copy the file-like or string object into the location.

        :param relpath: Location to put the contents, relative to base.
        :param fp:       File-like or string object.
        :param retries: Number of retries after temporary failures so far
                        for this operation.

        TODO: jam 20051215 ftp as a protocol seems to support chmod, but ftplib does not
        """
        tmp_abspath = '%s.tmp.%.9f.%d.%d' % (self._abspath(relpath), time.time(),
                        os.getpid(), random.randint(0,0x7FFFFFFF))
        if not hasattr(fp, 'read'):
            fp = StringIO(fp)
        try:
            mutter("FTP put: %s", self._abspath(relpath))
            f = self._get_FTP()
            try:
                f.storbinary('STOR '+tmp_abspath, fp)
                f.rename(tmp_abspath, self._abspath(relpath))
            except (ftplib.error_temp,EOFError), e:
                warning("Failure during ftp PUT. Deleting temporary file.")
                try:
                    f.delete(tmp_abspath)
                except:
                    warning("Failed to delete temporary file on the"
                            " server.\nFile: %s", tmp_abspath)
                    raise e
                raise
        except ftplib.error_perm, e:
            self._translate_perm_error(self.abspath(relpath), e, extra='could not store')
        except ftplib.error_temp, e:
            if retries > _number_of_retries:
                raise TransportError("FTP temporary error during PUT %s. Aborting."
                                     % self.abspath(relpath), orig_error=e)
            else:
                warning("FTP temporary error: %s. Retrying.", str(e))
                self._FTP_instance = None
                self.put(relpath, fp, mode, retries+1)
        except EOFError:
            if retries > _number_of_retries:
                raise TransportError("FTP control connection closed during PUT %s."
                                     % self.abspath(relpath), orig_error=e)
            else:
                warning("FTP control connection closed. Trying to reopen.")
                time.sleep(_sleep_between_retries)
                self._FTP_instance = None
                self.put(relpath, fp, mode, retries+1)

    def mkdir(self, relpath, mode=None):
        """Create a directory at the given path."""
        try:
            mutter("FTP mkd: %s", self._abspath(relpath))
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

    def rmdir(self, rel_path):
        """Delete the directory at rel_path"""
        try:
            mutter("FTP rmd: %s", self._abspath(rel_path))

            f = self._get_FTP()
            f.rmd(self._abspath(rel_path))
        except ftplib.error_perm, e:
            if str(e).endswith("Directory not empty"):
                raise DirectoryNotEmpty(self._abspath(rel_path), extra=str(e))
            else:
                raise TransportError(msg="Cannot remove directory at %s" % \
                        self._abspath(rel_path), extra=str(e))

    def append(self, relpath, f, mode=None):
        """Append the text in the file-like object into the final
        location.
        """
        if self.has(relpath):
            ftp = self._get_FTP()
            result = ftp.size(self._abspath(relpath))
        else:
            result = 0

        mutter("FTP appe to %s", self._abspath(relpath))
        self._try_append(relpath, f.read(), mode)

        return result

    def _try_append(self, relpath, text, mode=None, retries=0):
        """Try repeatedly to append the given text to the file at relpath.
        
        This is a recursive function. On errors, it will be called until the
        number of retries is exceeded.
        """
        try:
            abspath = self._abspath(relpath)
            mutter("FTP appe (try %d) to %s", retries, abspath)
            ftp = self._get_FTP()
            ftp.voidcmd("TYPE I")
            cmd = "APPE %s" % abspath
            conn = ftp.transfercmd(cmd)
            conn.sendall(text)
            conn.close()
            if mode is not None:
                self._setmode(relpath, mode)
            ftp.getresp()
        except ftplib.error_perm, e:
            self._translate_perm_error(e, abspath, extra='error appending')
        except ftplib.error_temp, e:
            if retries > _number_of_retries:
                raise TransportError("FTP temporary error during APPEND %s." \
                        "Aborting." % abspath, orig_error=e)
            else:
                warning("FTP temporary error: %s. Retrying.", str(e))
                self._FTP_instance = None
                self._try_append(relpath, text, mode, retries+1)

    def _setmode(self, relpath, mode):
        """Set permissions on a path.

        Only set permissions if the FTP server supports the 'SITE CHMOD'
        extension.
        """
        try:
            mutter("FTP site chmod: setting permissions to %s on %s",
                str(mode), self._abspath(relpath))
            ftp = self._get_FTP()
            cmd = "SITE CHMOD %s %s" % (self._abspath(relpath), str(mode))
            ftp.sendcmd(cmd)
        except ftplib.error_perm, e:
            # Command probably not available on this server
            warning("FTP Could not set permissions to %s on %s. %s",
                    str(mode), self._abspath(relpath), str(e))

    # TODO: jam 20060516 I believe ftp allows you to tell an ftp server
    #       to copy something to another machine. And you may be able
    #       to give it its own address as the 'to' location.
    #       So implement a fancier 'copy()'

    def move(self, rel_from, rel_to):
        """Move the item at rel_from to the location at rel_to"""
        try:
            mutter("FTP mv: %s => %s", self._abspath(rel_from),
                                       self._abspath(rel_to))
            f = self._get_FTP()
            f.rename(self._abspath(rel_from), self._abspath(rel_to))
        except ftplib.error_perm, e:
            raise TransportError(orig_error=e)

    rename = move

    def delete(self, relpath):
        """Delete the item at relpath"""
        abspath = self._abspath(relpath)
        try:
            mutter("FTP rm: %s", abspath)
            f = self._get_FTP()
            f.delete(abspath)
        except ftplib.error_perm, e:
            self._translate_perm_error(e, abspath, 'error deleting')

    def listable(self):
        """See Transport.listable."""
        return True

    def list_dir(self, relpath):
        """See Transport.list_dir."""
        try:
            mutter("FTP nlst: %s", self._abspath(relpath))
            f = self._get_FTP()
            basepath = self._abspath(relpath)
            paths = f.nlst(basepath)
            # If FTP.nlst returns paths prefixed by relpath, strip 'em
            if paths and paths[0].startswith(basepath):
                paths = [path[len(basepath)+1:] for path in paths]
            # Remove . and .. if present, and return
            return [path for path in paths if path not in (".", "..")]
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
            mutter("FTP stat: %s", self._abspath(relpath))
            f = self._get_FTP()
            return FtpStatResult(f, self._abspath(relpath))
        except ftplib.error_perm, e:
            if "no such file" in str(e).lower():
                raise NoSuchFile("Error storing %s: %s"
                                 % (self.abspath(relpath), str(e)), extra=e)
            else:
                raise FtpTransportError(orig_error=e)

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


class _test_authorizer(object):
    """A custom Authorizer object for running the test suite.

    The reason we cannot use dummy_authorizer, is because it sets the
    channel to readonly, which we don't always want to do.
    """

    def __init__(self, root):
        self.root = root

    def authorize(self, channel, username, password):
        """Return (success, reply_string, filesystem)"""
        if not _have_medusa:
            return 0, 'No Medusa.', None

        channel.persona = -1, -1
        if username == 'anonymous':
            channel.read_only = 1
        else:
            channel.read_only = 0

        return 1, 'OK.', medusa.filesys.os_filesystem(self.root)


if _have_medusa:
    class _ftp_channel(medusa.ftp_server.ftp_channel):
        """Customized ftp channel"""

        def log_info(self, message, type='info'):
            """Redirect logging requests."""
            mutter('_ftp_channel %s: %s', type, message)
            
        def cmd_rnfr(self, line):
            """Prepare for renaming a file."""
            self._renaming = line[1]
            self.respond('350 Ready for RNTO')
            # TODO: jam 20060516 in testing, the ftp server seems to
            #       check that the file already exists, or it sends
            #       550 RNFR command failed

        def cmd_rnto(self, line):
            """Rename a file based on the target given.

            rnto must be called after calling rnfr.
            """
            if not self._renaming:
                self.respond('503 RNFR required first.')
            pfrom = self.filesystem.translate(self._renaming)
            pto = self.filesystem.translate(line[1])
            try:
                os.rename(pfrom, pto)
            except OSError, e:
                # TODO: jam 20060516 return custom responses based on
                #       why the command failed
                self.respond('550 RNTO failed')
            except:
                self.respond('550 RNTO failed')
                # For a test server, we will go ahead and just die
                raise
            self.respond('250 Rename successful.')


    class _ftp_server(medusa.ftp_server.ftp_server):
        """Customize the behavior of the Medusa ftp_server.

        There are a few warts on the ftp_server, based on how it expects
        to be used.
        """
        _renaming = None
        ftp_channel_class = _ftp_channel

        def __init__(self, *args, **kwargs):
            mutter('Initializing _ftp_server: %r, %r', args, kwargs)
            medusa.ftp_server.ftp_server.__init__(self, *args, **kwargs)

        def log_info(self, message, type='info'):
            """Override the asyncore.log_info so we don't stipple the screen."""
            mutter('_ftp_server %s: %s', type, message)


class FtpServer(Server):
    """Common code for SFTP server facilities."""

    def __init__(self):
        self._root = None
        self._ftp_server = None
        self._port = None
        self._async_thread = None
        # ftp server logs
        self.logs = []

    def get_url(self):
        """Calculate an ftp url to this server."""
        return 'ftp://foo:bar@localhost:%d/' % (self._port)

#    def get_bogus_url(self):
#        """Return a URL which cannot be connected to."""
#        return 'ftp://127.0.0.1:1'

    def log(self, message):
        """This is used by medusa.ftp_server to log connections, etc."""
        self.logs.append(message)

    def setUp(self):

        if not _have_medusa:
            raise RuntimeError('Must have medusa to run the FtpServer')

        self._root = os.getcwdu()
        self._ftp_server = _ftp_server(
            authorizer=_test_authorizer(root=self._root),
            ip='localhost',
            port=0, # bind to a random port
            resolver=None,
            logger_object=self # Use FtpServer.log() for messages
            )
        self._port = self._ftp_server.getsockname()[1]
        # Don't let it loop forever, or handle an infinite number of requests.
        # In this case it will run for 100s, or 1000 requests
        self._async_thread = threading.Thread(target=asyncore.loop,
                kwargs={'timeout':0.1, 'count':1000})
        self._async_thread.setDaemon(True)
        self._async_thread.start()

    def tearDown(self):
        """See bzrlib.transport.Server.tearDown."""
        # have asyncore release the channel
        self._ftp_server.del_channel()
        asyncore.close_all()
        self._async_thread.join()


def get_test_permutations():
    """Return the permutations to be used in testing."""
    if not _have_medusa:
        warn("You must install medusa (http://www.amk.ca/python/code/medusa.html) for FTP tests")
        return []
    else:
        return [(FtpTransport, FtpServer)]
