# Copyright (C) 2005-2010 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Implementation of Transport over ftp.

Written by Daniel Silverstone <dsilvers@digital-scurf.org> with serious
cargo-culting from the sftp transport and the http transport.

It provides the ftp:// and aftp:// protocols where ftp:// is passive ftp
and aftp:// is active ftp. Most people will want passive ftp for traversing
NAT and other firewalls, so it's best to use it unless you explicitly want
active, in which case aftp:// will be your friend.
"""

from __future__ import absolute_import

from cStringIO import StringIO
import ftplib
import getpass
import os
import random
import socket
import stat
import time

from bzrlib import (
    config,
    errors,
    osutils,
    urlutils,
    )
from bzrlib.symbol_versioning import (
    DEPRECATED_PARAMETER,
    deprecated_in,
    deprecated_passed,
    warn,
    )
from bzrlib.trace import mutter, warning
from bzrlib.transport import (
    AppendBasedFileStream,
    ConnectedTransport,
    _file_streams,
    register_urlparse_netloc_protocol,
    Server,
    )


register_urlparse_netloc_protocol('aftp')


class FtpPathError(errors.PathError):
    """FTP failed for path: %(path)s%(extra)s"""


class FtpStatResult(object):

    def __init__(self, f, abspath):
        try:
            self.st_size = f.size(abspath)
            self.st_mode = stat.S_IFREG
        except ftplib.error_perm:
            pwd = f.pwd()
            try:
                f.cwd(abspath)
                self.st_mode = stat.S_IFDIR
            finally:
                f.cwd(pwd)


_number_of_retries = 2
_sleep_between_retries = 5

# FIXME: there are inconsistencies in the way temporary errors are
# handled. Sometimes we reconnect, sometimes we raise an exception. Care should
# be taken to analyze the implications for write operations (read operations
# are safe to retry). Overall even some read operations are never
# retried. --vila 20070720 (Bug #127164)
class FtpTransport(ConnectedTransport):
    """This is the transport agent for ftp:// access."""

    def __init__(self, base, _from_transport=None):
        """Set the base path where files will be stored."""
        if not (base.startswith('ftp://') or base.startswith('aftp://')):
            raise ValueError(base)
        super(FtpTransport, self).__init__(base,
                                           _from_transport=_from_transport)
        self._unqualified_scheme = 'ftp'
        if self._parsed_url.scheme == 'aftp':
            self.is_active = True
        else:
            self.is_active = False

        # Most modern FTP servers support the APPE command. If ours doesn't, we
        # (re)set this flag accordingly later.
        self._has_append = True

    def _get_FTP(self):
        """Return the ftplib.FTP instance for this object."""
        # Ensures that a connection is established
        connection = self._get_connection()
        if connection is None:
            # First connection ever
            connection, credentials = self._create_connection()
            self._set_connection(connection, credentials)
        return connection

    connection_class = ftplib.FTP

    def _create_connection(self, credentials=None):
        """Create a new connection with the provided credentials.

        :param credentials: The credentials needed to establish the connection.

        :return: The created connection and its associated credentials.

        The input credentials are only the password as it may have been
        entered interactively by the user and may be different from the one
        provided in base url at transport creation time.  The returned
        credentials are username, password.
        """
        if credentials is None:
            user, password = self._user, self._password
        else:
            user, password = credentials

        auth = config.AuthenticationConfig()
        if user is None:
            user = auth.get_user('ftp', self._host, port=self._port,
                                 default=getpass.getuser())
        mutter("Constructing FTP instance against %r" %
               ((self._host, self._port, user, '********',
                self.is_active),))
        try:
            connection = self.connection_class()
            connection.connect(host=self._host, port=self._port)
            self._login(connection, auth, user, password)
            connection.set_pasv(not self.is_active)
            # binary mode is the default
            connection.voidcmd('TYPE I')
        except socket.error, e:
            raise errors.SocketConnectionError(self._host, self._port,
                                               msg='Unable to connect to',
                                               orig_error= e)
        except ftplib.error_perm, e:
            raise errors.TransportError(msg="Error setting up connection:"
                                        " %s" % str(e), orig_error=e)
        return connection, (user, password)

    def _login(self, connection, auth, user, password):
        # '' is a valid password
        if user and user != 'anonymous' and password is None:
            password = auth.get_password('ftp', self._host,
                                         user, port=self._port)
        connection.login(user=user, passwd=password)

    def _reconnect(self):
        """Create a new connection with the previously used credentials"""
        credentials = self._get_credentials()
        connection, credentials = self._create_connection(credentials)
        self._set_connection(connection, credentials)

    def disconnect(self):
        connection = self._get_connection()
        if connection is not None:
            connection.close()

    def _translate_ftp_error(self, err, path, extra=None,
                              unknown_exc=FtpPathError):
        """Try to translate an ftplib exception to a bzrlib exception.

        :param err: The error to translate into a bzr error
        :param path: The path which had problems
        :param extra: Extra information which can be included
        :param unknown_exc: If None, we will just raise the original exception
                    otherwise we raise unknown_exc(path, extra=extra)
        """
        # ftp error numbers are very generic, like "451: Requested action aborted,
        # local error in processing" so unfortunately we have to match by
        # strings.
        s = str(err).lower()
        if not extra:
            extra = str(err)
        else:
            extra += ': ' + str(err)
        if ('no such file' in s
            or 'could not open' in s
            or 'no such dir' in s
            or 'could not create file' in s # vsftpd
            or 'file doesn\'t exist' in s
            or 'rnfr command failed.' in s # vsftpd RNFR reply if file not found
            or 'file/directory not found' in s # filezilla server
            # Microsoft FTP-Service RNFR reply if file not found
            or (s.startswith('550 ') and 'unable to rename to' in extra)
            # if containing directory doesn't exist, suggested by
            # <https://bugs.launchpad.net/bzr/+bug/224373>
            or (s.startswith('550 ') and "can't find folder" in s)
            ):
            raise errors.NoSuchFile(path, extra=extra)
        elif ('file exists' in s):
            raise errors.FileExists(path, extra=extra)
        elif ('not a directory' in s):
            raise errors.PathError(path, extra=extra)
        elif 'directory not empty' in s:
            raise errors.DirectoryNotEmpty(path, extra=extra)

        mutter('unable to understand error for path: %s: %s', path, err)

        if unknown_exc:
            raise unknown_exc(path, extra=extra)
        # TODO: jam 20060516 Consider re-raising the error wrapped in
        #       something like TransportError, but this loses the traceback
        #       Also, 'sftp' has a generic 'Failure' mode, which we use failure_exc
        #       to handle. Consider doing something like that here.
        #raise TransportError(msg='Error for path: %s' % (path,), orig_error=e)
        raise

    def has(self, relpath):
        """Does the target location exist?"""
        # FIXME jam 20060516 We *do* ask about directories in the test suite
        #       We don't seem to in the actual codebase
        # XXX: I assume we're never asked has(dirname) and thus I use
        # the FTP size command and assume that if it doesn't raise,
        # all is good.
        abspath = self._remote_path(relpath)
        try:
            f = self._get_FTP()
            mutter('FTP has check: %s => %s', relpath, abspath)
            s = f.size(abspath)
            mutter("FTP has: %s", abspath)
            return True
        except ftplib.error_perm, e:
            if ('is a directory' in str(e).lower()):
                mutter("FTP has dir: %s: %s", abspath, e)
                return True
            mutter("FTP has not: %s: %s", abspath, e)
            return False

    def get(self, relpath, retries=0):
        """Get the file at the given relative path.

        :param relpath: The relative path to the file
        :param retries: Number of retries after temporary failures so far
                        for this operation.

        We're meant to return a file-like object which bzr will
        then read from. For now we do this via the magic of StringIO
        """
        try:
            mutter("FTP get: %s", self._remote_path(relpath))
            f = self._get_FTP()
            ret = StringIO()
            f.retrbinary('RETR '+self._remote_path(relpath), ret.write, 8192)
            ret.seek(0)
            return ret
        except ftplib.error_perm, e:
            raise errors.NoSuchFile(self.abspath(relpath), extra=str(e))
        except ftplib.error_temp, e:
            if retries > _number_of_retries:
                raise errors.TransportError(msg="FTP temporary error during GET %s. Aborting."
                                     % self.abspath(relpath),
                                     orig_error=e)
            else:
                warning("FTP temporary error: %s. Retrying.", str(e))
                self._reconnect()
                return self.get(relpath, retries+1)
        except EOFError, e:
            if retries > _number_of_retries:
                raise errors.TransportError("FTP control connection closed during GET %s."
                                     % self.abspath(relpath),
                                     orig_error=e)
            else:
                warning("FTP control connection closed. Trying to reopen.")
                time.sleep(_sleep_between_retries)
                self._reconnect()
                return self.get(relpath, retries+1)

    def put_file(self, relpath, fp, mode=None, retries=0):
        """Copy the file-like or string object into the location.

        :param relpath: Location to put the contents, relative to base.
        :param fp:       File-like or string object.
        :param retries: Number of retries after temporary failures so far
                        for this operation.

        TODO: jam 20051215 ftp as a protocol seems to support chmod, but
        ftplib does not
        """
        abspath = self._remote_path(relpath)
        tmp_abspath = '%s.tmp.%.9f.%d.%d' % (abspath, time.time(),
                        os.getpid(), random.randint(0,0x7FFFFFFF))
        bytes = None
        if getattr(fp, 'read', None) is None:
            # hand in a string IO
            bytes = fp
            fp = StringIO(bytes)
        else:
            # capture the byte count; .read() may be read only so
            # decorate it.
            class byte_counter(object):
                def __init__(self, fp):
                    self.fp = fp
                    self.counted_bytes = 0
                def read(self, count):
                    result = self.fp.read(count)
                    self.counted_bytes += len(result)
                    return result
            fp = byte_counter(fp)
        try:
            mutter("FTP put: %s", abspath)
            f = self._get_FTP()
            try:
                f.storbinary('STOR '+tmp_abspath, fp)
                self._rename_and_overwrite(tmp_abspath, abspath, f)
                self._setmode(relpath, mode)
                if bytes is not None:
                    return len(bytes)
                else:
                    return fp.counted_bytes
            except (ftplib.error_temp, EOFError), e:
                warning("Failure during ftp PUT of %s: %s. Deleting temporary file."
                    % (tmp_abspath, e, ))
                try:
                    f.delete(tmp_abspath)
                except:
                    warning("Failed to delete temporary file on the"
                            " server.\nFile: %s", tmp_abspath)
                    raise e
                raise
        except ftplib.error_perm, e:
            self._translate_ftp_error(e, abspath, extra='could not store',
                                       unknown_exc=errors.NoSuchFile)
        except ftplib.error_temp, e:
            if retries > _number_of_retries:
                raise errors.TransportError(
                    "FTP temporary error during PUT %s: %s. Aborting."
                    % (self.abspath(relpath), e), orig_error=e)
            else:
                warning("FTP temporary error: %s. Retrying.", str(e))
                self._reconnect()
                self.put_file(relpath, fp, mode, retries+1)
        except EOFError:
            if retries > _number_of_retries:
                raise errors.TransportError("FTP control connection closed during PUT %s."
                                     % self.abspath(relpath), orig_error=e)
            else:
                warning("FTP control connection closed. Trying to reopen.")
                time.sleep(_sleep_between_retries)
                self._reconnect()
                self.put_file(relpath, fp, mode, retries+1)

    def mkdir(self, relpath, mode=None):
        """Create a directory at the given path."""
        abspath = self._remote_path(relpath)
        try:
            mutter("FTP mkd: %s", abspath)
            f = self._get_FTP()
            try:
                f.mkd(abspath)
            except ftplib.error_reply, e:
                # <https://bugs.launchpad.net/bzr/+bug/224373> Microsoft FTP
                # server returns "250 Directory created." which is kind of
                # reasonable, 250 meaning "requested file action OK", but not what
                # Python's ftplib expects.
                if e[0][:3] == '250':
                    pass
                else:
                    raise
            self._setmode(relpath, mode)
        except ftplib.error_perm, e:
            self._translate_ftp_error(e, abspath,
                unknown_exc=errors.FileExists)

    def open_write_stream(self, relpath, mode=None):
        """See Transport.open_write_stream."""
        self.put_bytes(relpath, "", mode)
        result = AppendBasedFileStream(self, relpath)
        _file_streams[self.abspath(relpath)] = result
        return result

    def recommended_page_size(self):
        """See Transport.recommended_page_size().

        For FTP we suggest a large page size to reduce the overhead
        introduced by latency.
        """
        return 64 * 1024

    def rmdir(self, rel_path):
        """Delete the directory at rel_path"""
        abspath = self._remote_path(rel_path)
        try:
            mutter("FTP rmd: %s", abspath)
            f = self._get_FTP()
            f.rmd(abspath)
        except ftplib.error_perm, e:
            self._translate_ftp_error(e, abspath, unknown_exc=errors.PathError)

    def append_file(self, relpath, f, mode=None):
        """Append the text in the file-like object into the final
        location.
        """
        text = f.read()
        abspath = self._remote_path(relpath)
        if self.has(relpath):
            ftp = self._get_FTP()
            result = ftp.size(abspath)
        else:
            result = 0

        if self._has_append:
            mutter("FTP appe to %s", abspath)
            self._try_append(relpath, text, mode)
        else:
            self._fallback_append(relpath, text, mode)

        return result

    def _try_append(self, relpath, text, mode=None, retries=0):
        """Try repeatedly to append the given text to the file at relpath.

        This is a recursive function. On errors, it will be called until the
        number of retries is exceeded.
        """
        try:
            abspath = self._remote_path(relpath)
            mutter("FTP appe (try %d) to %s", retries, abspath)
            ftp = self._get_FTP()
            cmd = "APPE %s" % abspath
            conn = ftp.transfercmd(cmd)
            conn.sendall(text)
            conn.close()
            self._setmode(relpath, mode)
            ftp.getresp()
        except ftplib.error_perm, e:
            # Check whether the command is not supported (reply code 502)
            if str(e).startswith('502 '):
                warning("FTP server does not support file appending natively. "
                        "Performance may be severely degraded! (%s)", e)
                self._has_append = False
                self._fallback_append(relpath, text, mode)
            else:
                self._translate_ftp_error(e, abspath, extra='error appending',
                    unknown_exc=errors.NoSuchFile)
        except ftplib.error_temp, e:
            if retries > _number_of_retries:
                raise errors.TransportError(
                    "FTP temporary error during APPEND %s. Aborting."
                    % abspath, orig_error=e)
            else:
                warning("FTP temporary error: %s. Retrying.", str(e))
                self._reconnect()
                self._try_append(relpath, text, mode, retries+1)

    def _fallback_append(self, relpath, text, mode = None):
        remote = self.get(relpath)
        remote.seek(0, os.SEEK_END)
        remote.write(text)
        remote.seek(0)
        return self.put_file(relpath, remote, mode)

    def _setmode(self, relpath, mode):
        """Set permissions on a path.

        Only set permissions if the FTP server supports the 'SITE CHMOD'
        extension.
        """
        if mode:
            try:
                mutter("FTP site chmod: setting permissions to %s on %s",
                       oct(mode), self._remote_path(relpath))
                ftp = self._get_FTP()
                cmd = "SITE CHMOD %s %s" % (oct(mode),
                                            self._remote_path(relpath))
                ftp.sendcmd(cmd)
            except ftplib.error_perm, e:
                # Command probably not available on this server
                warning("FTP Could not set permissions to %s on %s. %s",
                        oct(mode), self._remote_path(relpath), str(e))

    # TODO: jam 20060516 I believe ftp allows you to tell an ftp server
    #       to copy something to another machine. And you may be able
    #       to give it its own address as the 'to' location.
    #       So implement a fancier 'copy()'

    def rename(self, rel_from, rel_to):
        abs_from = self._remote_path(rel_from)
        abs_to = self._remote_path(rel_to)
        mutter("FTP rename: %s => %s", abs_from, abs_to)
        f = self._get_FTP()
        return self._rename(abs_from, abs_to, f)

    def _rename(self, abs_from, abs_to, f):
        try:
            f.rename(abs_from, abs_to)
        except (ftplib.error_temp, ftplib.error_perm), e:
            self._translate_ftp_error(e, abs_from,
                ': unable to rename to %r' % (abs_to))

    def move(self, rel_from, rel_to):
        """Move the item at rel_from to the location at rel_to"""
        abs_from = self._remote_path(rel_from)
        abs_to = self._remote_path(rel_to)
        try:
            mutter("FTP mv: %s => %s", abs_from, abs_to)
            f = self._get_FTP()
            self._rename_and_overwrite(abs_from, abs_to, f)
        except ftplib.error_perm, e:
            self._translate_ftp_error(e, abs_from,
                extra='unable to rename to %r' % (rel_to,),
                unknown_exc=errors.PathError)

    def _rename_and_overwrite(self, abs_from, abs_to, f):
        """Do a fancy rename on the remote server.

        Using the implementation provided by osutils.
        """
        osutils.fancy_rename(abs_from, abs_to,
            rename_func=lambda p1, p2: self._rename(p1, p2, f),
            unlink_func=lambda p: self._delete(p, f))

    def delete(self, relpath):
        """Delete the item at relpath"""
        abspath = self._remote_path(relpath)
        f = self._get_FTP()
        self._delete(abspath, f)

    def _delete(self, abspath, f):
        try:
            mutter("FTP rm: %s", abspath)
            f.delete(abspath)
        except ftplib.error_perm, e:
            self._translate_ftp_error(e, abspath, 'error deleting',
                unknown_exc=errors.NoSuchFile)

    def external_url(self):
        """See bzrlib.transport.Transport.external_url."""
        # FTP URL's are externally usable.
        return self.base

    def listable(self):
        """See Transport.listable."""
        return True

    def list_dir(self, relpath):
        """See Transport.list_dir."""
        basepath = self._remote_path(relpath)
        mutter("FTP nlst: %s", basepath)
        f = self._get_FTP()
        try:
            try:
                paths = f.nlst(basepath)
            except ftplib.error_perm, e:
                self._translate_ftp_error(e, relpath,
                                           extra='error with list_dir')
            except ftplib.error_temp, e:
                # xs4all's ftp server raises a 450 temp error when listing an
                # empty directory. Check for that and just return an empty list
                # in that case. See bug #215522
                if str(e).lower().startswith('450 no files found'):
                    mutter('FTP Server returned "%s" for nlst.'
                           ' Assuming it means empty directory',
                           str(e))
                    return []
                raise
        finally:
            # Restore binary mode as nlst switch to ascii mode to retrieve file
            # list
            f.voidcmd('TYPE I')

        # If FTP.nlst returns paths prefixed by relpath, strip 'em
        if paths and paths[0].startswith(basepath):
            entries = [path[len(basepath)+1:] for path in paths]
        else:
            entries = paths
        # Remove . and .. if present
        return [urlutils.escape(entry) for entry in entries
                if entry not in ('.', '..')]

    def iter_files_recursive(self):
        """See Transport.iter_files_recursive.

        This is cargo-culted from the SFTP transport"""
        mutter("FTP iter_files_recursive")
        queue = list(self.list_dir("."))
        while queue:
            relpath = queue.pop(0)
            st = self.stat(relpath)
            if stat.S_ISDIR(st.st_mode):
                for i, basename in enumerate(self.list_dir(relpath)):
                    queue.insert(i, relpath+"/"+basename)
            else:
                yield relpath

    def stat(self, relpath):
        """Return the stat information for a file."""
        abspath = self._remote_path(relpath)
        try:
            mutter("FTP stat: %s", abspath)
            f = self._get_FTP()
            return FtpStatResult(f, abspath)
        except ftplib.error_perm, e:
            self._translate_ftp_error(e, abspath, extra='error w/ stat')

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
    from bzrlib.tests import ftp_server
    return [(FtpTransport, ftp_server.FTPTestServer)]
