# Copyright (C) 2010 Canonical Ltd.
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
#
# Author: Mattias Eriksson

"""Implementation of Transport over gio.

Written by Mattias Eriksson <snaggen@acc.umu.se> based on the ftp transport.

It provides the gio+XXX:// protocols where XXX is any of the protocols
supported by gio.
"""

import os
import random
import stat
import time
from io import BytesIO
from urllib.parse import urlparse, urlunparse

from .. import config, debug, errors, osutils, ui, urlutils
from ..tests.test_server import TestServer
from ..trace import mutter
from . import ConnectedTransport, FileExists, FileStream, NoSuchFile, _file_streams

try:
    import glib
except ModuleNotFoundError as e:
    raise errors.DependencyNotPresent("glib", e) from e
try:
    import gio
except ModuleNotFoundError as e:
    raise errors.DependencyNotPresent("gio", e) from e


class GioLocalURLServer(TestServer):
    """A pretend server for local transports, using file:// urls.

    Of course no actual server is required to access the local filesystem, so
    this just exists to tell the test code how to get to it.
    """

    def start_server(self):
        """Start the server (no-op for local filesystem access)."""
        pass

    def get_url(self):
        """See Transport.Server.get_url."""
        return "gio+" + urlutils.local_path_to_url("")


class GioFileStream(FileStream):
    """A file stream object returned by open_write_stream.

    This version uses GIO to perform writes.
    """

    def __init__(self, transport, relpath):
        """Initialize the GIO file stream.

        Args:
            transport: The GIO transport instance.
            relpath: Relative path to the file.
        """
        FileStream.__init__(self, transport, relpath)
        self.gio_file = transport._get_GIO(relpath)
        self.stream = self.gio_file.create()

    def _close(self):
        self.stream.close()

    def write(self, bytes):
        """Write bytes to the stream.

        Args:
            bytes: Data to write.

        Raises:
            BzrError: If the write operation fails.
        """
        try:
            # Using pump_string_file seems to make things crash
            osutils.pumpfile(BytesIO(bytes), self.stream)
        except gio.Error as e:
            # self.transport._translate_gio_error(e,self.relpath)
            raise errors.BzrError(str(e)) from e


class GioStatResult:
    """Stat result wrapper for GIO file information."""

    def __init__(self, f):
        """Initialize stat result from a GIO file.

        Args:
            f: GIO file object to get information from.
        """
        info = f.query_info("standard::size,standard::type")
        self.st_size = info.get_size()
        type = info.get_file_type()
        if type == gio.FILE_TYPE_REGULAR:
            self.st_mode = stat.S_IFREG
        elif type == gio.FILE_TYPE_DIRECTORY:
            self.st_mode = stat.S_IFDIR


class GioTransport(ConnectedTransport):
    """This is the transport agent for gio+XXX:// access."""

    def __init__(self, base, _from_transport=None):
        """Initialize the GIO transport and make sure the url is correct."""
        if not base.startswith("gio+"):
            raise ValueError(base)

        (scheme, netloc, path, params, query, fragment) = urlparse(
            base[len("gio+") :], allow_fragments=False
        )
        if "@" in netloc:
            user, netloc = netloc.rsplit("@", 1)
        # Seems it is not possible to list supported backends for GIO
        # so a hardcoded list it is then.
        gio_backends = ["dav", "file", "ftp", "obex", "sftp", "ssh", "smb"]
        if scheme not in gio_backends:
            raise urlutils.InvalidURL(
                base,
                extra="GIO support is only available for " + ", ".join(gio_backends),
            )

        # Remove the username and password from the url we send to GIO
        # by rebuilding the url again.
        u = (scheme, netloc, path, "", "", "")
        self.url = urlunparse(u)

        # And finally initialize super
        super().__init__(base, _from_transport=_from_transport)

    def _relpath_to_url(self, relpath):
        full_url = urlutils.join(self.url, relpath)
        if isinstance(full_url, str):
            raise urlutils.InvalidURL(full_url)
        return full_url

    def _get_GIO(self, relpath):
        """Return the ftplib.GIO instance for this object."""
        # Ensures that a connection is established
        connection = self._get_connection()
        if connection is None:
            # First connection ever
            connection, credentials = self._create_connection()
            self._set_connection(connection, credentials)
        fileurl = self._relpath_to_url(relpath)
        file = gio.File(fileurl)
        return file

    def _auth_cb(self, op, message, default_user, default_domain, flags):
        # really use breezy.auth get_password for this
        # or possibly better gnome-keyring?
        auth = config.AuthenticationConfig()
        parsed_url = urlutils.URL.from_string(self.url)
        user = None
        if (
            flags & gio.ASK_PASSWORD_NEED_USERNAME
            and flags & gio.ASK_PASSWORD_NEED_DOMAIN
        ):
            prompt = f"{parsed_url.scheme.upper()}" + " %(host)s DOMAIN\\username"
            user_and_domain = auth.get_user(
                parsed_url.scheme,
                parsed_url.host,
                port=parsed_url.port,
                ask=True,
                prompt=prompt,
            )
            (domain, user) = user_and_domain.split("\\", 1)
            op.set_username(user)
            op.set_domain(domain)
        elif flags & gio.ASK_PASSWORD_NEED_USERNAME:
            user = auth.get_user(
                parsed_url.scheme, parsed_url.host, port=parsed_url.port, ask=True
            )
            op.set_username(user)
        elif flags & gio.ASK_PASSWORD_NEED_DOMAIN:
            # Don't know how common this case is, but anyway
            # a DOMAIN and a username prompt should be the
            # same so I will missuse the ui_factory get_username
            # a little bit here.
            prompt = f"{parsed_url.scheme.upper()}" + " %(host)s DOMAIN"
            domain = ui.ui_factory.get_username(prompt=prompt)
            op.set_domain(domain)

        if flags & gio.ASK_PASSWORD_NEED_PASSWORD:
            if user is None:
                user = op.get_username()
            password = auth.get_password(
                parsed_url.scheme, parsed_url.host, user, port=parsed_url.port
            )
            op.set_password(password)
        op.reply(gio.MOUNT_OPERATION_HANDLED)

    def _mount_done_cb(self, obj, res):
        try:
            obj.mount_enclosing_volume_finish(res)
            self.loop.quit()
        except gio.Error as e:
            self.loop.quit()
            raise errors.BzrError(
                "Failed to mount the given location: " + str(e)
            ) from e

    def _create_connection(self, credentials=None):
        if credentials is None:
            user, password = self._parsed_url.user, self._parsed_url.password
        else:
            user, password = credentials

        try:
            connection = gio.File(self.url)
            try:
                connection.find_enclosing_mount()
            except gio.Error as e:
                if e.code == gio.ERROR_NOT_MOUNTED:
                    self.loop = glib.MainLoop()
                    ui.ui_factory.show_message(f"Mounting {self.url} using GIO")
                    op = gio.MountOperation()
                    if user:
                        op.set_username(user)
                    if password:
                        op.set_password(password)
                    op.connect("ask-password", self._auth_cb)
                    connection.mount_enclosing_volume(op, self._mount_done_cb)
                    self.loop.run()
        except gio.Error as e:
            raise errors.TransportError(
                msg="Error setting up connection: {}".format(str(e)), orig_error=e
            ) from e
        return connection, (user, password)

    def disconnect(self):
        """Disconnect from the transport.

        Note: GIO handles connection management internally, so this is a no-op.
        """
        # FIXME: Nothing seems to be necessary here, which sounds a bit strange
        # -- vila 20100601
        pass

    def _reconnect(self):
        # FIXME: This doesn't seem to be used -- vila 20100601
        """Create a new connection with the previously used credentials."""
        credentials = self._get_credentials()
        connection, credentials = self._create_connection(credentials)
        self._set_connection(connection, credentials)

    def _remote_path(self, relpath):
        return self._parsed_url.clone(relpath).path

    def has(self, relpath):
        """Does the target location exist?"""
        try:
            if debug.debug_flag_enabled("gio"):
                mutter("GIO has check: %s", relpath)
            f = self._get_GIO(relpath)
            st = GioStatResult(f)
            return bool(stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode))
        except gio.Error as e:
            if e.code == gio.ERROR_NOT_FOUND:
                return False
            else:
                self._translate_gio_error(e, relpath)

    def get(self, relpath, retries=0):
        """Get the file at the given relative path.

        :param relpath: The relative path to the file
        :param retries: Number of retries after temporary failures so far
                        for this operation.

        We're meant to return a file-like object which bzr will
        then read from. For now we do this via the magic of BytesIO
        """
        try:
            if debug.debug_flag_enabled("gio"):
                mutter("GIO get: %s", relpath)
            f = self._get_GIO(relpath)
            fin = f.read()
            buf = fin.read()
            fin.close()
            return BytesIO(buf)
        except gio.Error as e:
            # If we get a not mounted here it might mean
            # that a bad path has been entered (or that mount failed)
            if e.code == gio.ERROR_NOT_MOUNTED:
                raise errors.PathError(
                    relpath,
                    extra="Failed to get file, make sure the path is correct. "
                    + str(e),
                ) from e
            else:
                self._translate_gio_error(e, relpath)

    def put_file(self, relpath, fp, mode=None):
        """Copy the file-like object into the location.

        :param relpath: Location to put the contents, relative to base.
        :param fp:       File-like or string object.
        """
        if debug.debug_flag_enabled("gio"):
            mutter("GIO put_file {}".format(relpath))
        tmppath = "%s.tmp.%.9f.%d.%d" % (
            relpath,
            time.time(),
            os.getpid(),
            random.randint(0, 0x7FFFFFFF),  # noqa: S311
        )
        f = None
        fout = None
        try:
            closed = True
            try:
                f = self._get_GIO(tmppath)
                fout = f.create()
                closed = False
                length = self._pump(fp, fout)
                fout.close()
                closed = True
                self.stat(tmppath)
                dest = self._get_GIO(relpath)
                f.move(dest, flags=gio.FILE_COPY_OVERWRITE)
                f = None
                if mode is not None:
                    self._setmode(relpath, mode)
                return length
            except gio.Error as e:
                self._translate_gio_error(e, relpath)
        finally:
            if not closed and fout is not None:
                fout.close()
            if f is not None and f.query_exists():
                f.delete()

    def mkdir(self, relpath, mode=None):
        """Create a directory at the given path."""
        try:
            if debug.debug_flag_enabled("gio"):
                mutter("GIO mkdir: {}".format(relpath))
            f = self._get_GIO(relpath)
            f.make_directory()
            self._setmode(relpath, mode)
        except gio.Error as e:
            self._translate_gio_error(e, relpath)

    def open_write_stream(self, relpath, mode=None):
        """See Transport.open_write_stream."""
        if debug.debug_flag_enabled("gio"):
            mutter("GIO open_write_stream {}".format(relpath))
        if mode is not None:
            self._setmode(relpath, mode)
        result = GioFileStream(self, relpath)
        _file_streams[self.abspath(relpath)] = result
        return result

    def recommended_page_size(self):
        """See Transport.recommended_page_size().

        For FTP we suggest a large page size to reduce the overhead
        introduced by latency.
        """
        if debug.debug_flag_enabled("gio"):
            mutter("GIO recommended_page")
        return 64 * 1024

    def rmdir(self, relpath):
        """Delete the directory at rel_path."""
        try:
            if debug.debug_flag_enabled("gio"):
                mutter("GIO rmdir {}".format(relpath))
            st = self.stat(relpath)
            if stat.S_ISDIR(st.st_mode):
                f = self._get_GIO(relpath)
                f.delete()
            else:
                raise errors.NotADirectory(relpath)
        except gio.Error as e:
            self._translate_gio_error(e, relpath)
        except errors.NotADirectory as e:
            # just pass it forward
            raise e
        except Exception as e:
            mutter(f"failed to rmdir {relpath}: {e}")
            raise errors.PathError(relpath) from e

    def append_file(self, relpath, file, mode=None):
        """Append the text in the file-like object into the final
        location.
        """
        # GIO append_to seems not to append but to truncate
        # Work around this.
        if debug.debug_flag_enabled("gio"):
            mutter("GIO append_file: {}".format(relpath))
        tmppath = "%s.tmp.%.9f.%d.%d" % (
            relpath,
            time.time(),
            os.getpid(),
            random.randint(0, 0x7FFFFFFF),  # noqa: S311
        )
        try:
            result = 0
            fo = self._get_GIO(tmppath)
            fi = self._get_GIO(relpath)
            fout = fo.create()
            try:
                info = GioStatResult(fi)
                result = info.st_size
                fin = fi.read()
                self._pump(fin, fout)
                fin.close()
            # This separate except is to catch and ignore the
            # gio.ERROR_NOT_FOUND for the already existing file.
            # It is valid to open a non-existing file for append.
            # This is caused by the broken gio append_to...
            except gio.Error as e:
                if e.code != gio.ERROR_NOT_FOUND:
                    self._translate_gio_error(e, relpath)
            length = self._pump(file, fout)
            fout.close()
            info = GioStatResult(fo)
            if info.st_size != result + length:
                raise errors.BzrError(
                    "Failed to append size after "
                    "(%d) is not original (%d) + written (%d) total (%d)"
                    % (info.st_size, result, length, result + length)
                )
            fo.move(fi, flags=gio.FILE_COPY_OVERWRITE)
            return result
        except gio.Error as e:
            self._translate_gio_error(e, relpath)

    def _setmode(self, relpath, mode):
        """Set permissions on a path.

        Only set permissions on Unix systems
        """
        if debug.debug_flag_enabled("gio"):
            mutter("GIO _setmode {}".format(relpath))
        if mode:
            try:
                f = self._get_GIO(relpath)
                f.set_attribute_uint32(gio.FILE_ATTRIBUTE_UNIX_MODE, mode)
            except gio.Error as e:
                if e.code == gio.ERROR_NOT_SUPPORTED:
                    # Command probably not available on this server
                    mutter(
                        "GIO Could not set permissions to %s on %s. %s",
                        oct(mode),
                        self._remote_path(relpath),
                        str(e),
                    )
                else:
                    self._translate_gio_error(e, relpath)

    def rename(self, rel_from, rel_to):
        """Rename without special overwriting."""
        try:
            if debug.debug_flag_enabled("gio"):
                mutter("GIO move (rename): %s => %s", rel_from, rel_to)
            f = self._get_GIO(rel_from)
            t = self._get_GIO(rel_to)
            f.move(t)
        except gio.Error as e:
            self._translate_gio_error(e, rel_from)

    def move(self, rel_from, rel_to):
        """Move the item at rel_from to the location at rel_to."""
        try:
            if debug.debug_flag_enabled("gio"):
                mutter("GIO move: %s => %s", rel_from, rel_to)
            f = self._get_GIO(rel_from)
            t = self._get_GIO(rel_to)
            f.move(t, flags=gio.FILE_COPY_OVERWRITE)
        except gio.Error as e:
            self._translate_gio_error(e, relfrom)

    def delete(self, relpath):
        """Delete the item at relpath."""
        try:
            if debug.debug_flag_enabled("gio"):
                mutter("GIO delete: %s", relpath)
            f = self._get_GIO(relpath)
            f.delete()
        except gio.Error as e:
            self._translate_gio_error(e, relpath)

    def external_url(self):
        """See breezy.transport.Transport.external_url."""
        if debug.debug_flag_enabled("gio"):
            mutter("GIO external_url", self.base)
        # GIO external url
        return self.base

    def listable(self):
        """See Transport.listable."""
        if debug.debug_flag_enabled("gio"):
            mutter("GIO listable")
        return True

    def list_dir(self, relpath):
        """See Transport.list_dir."""
        if debug.debug_flag_enabled("gio"):
            mutter("GIO list_dir")
        try:
            entries = []
            f = self._get_GIO(relpath)
            children = f.enumerate_children(gio.FILE_ATTRIBUTE_STANDARD_NAME)
            for child in children:
                entries.append(urlutils.escape(child.get_name()))
            return entries
        except gio.Error as e:
            self._translate_gio_error(e, relpath)

    def iter_files_recursive(self):
        """See Transport.iter_files_recursive.

        This is cargo-culted from the SFTP transport
        """
        if debug.debug_flag_enabled("gio"):
            mutter("GIO iter_files_recursive")
        queue = list(self.list_dir("."))
        while queue:
            relpath = queue.pop(0)
            st = self.stat(relpath)
            if stat.S_ISDIR(st.st_mode):
                for i, basename in enumerate(self.list_dir(relpath)):
                    queue.insert(i, relpath + "/" + basename)
            else:
                yield relpath

    def stat(self, relpath):
        """Return the stat information for a file."""
        try:
            if debug.debug_flag_enabled("gio"):
                mutter("GIO stat: %s", relpath)
            f = self._get_GIO(relpath)
            return GioStatResult(f)
        except gio.Error as e:
            self._translate_gio_error(e, relpath, extra="error w/ stat")

    def lock_read(self, relpath):
        """Lock the given file for shared (read) access.
        :return: A lock object, which should be passed to Transport.unlock().
        """
        if debug.debug_flag_enabled("gio"):
            mutter("GIO lock_read", relpath)

        class BogusLock:
            # The old RemoteBranch ignore lock for reading, so we will
            # continue that tradition and return a bogus lock object.

            def __init__(self, path):
                self.path = path

            def unlock(self):
                pass

        return BogusLock(relpath)

    def lock_write(self, relpath):
        """Lock the given file for exclusive (write) access.
        WARNING: many transports do not support this, so trying avoid using it.

        :return: A lock object, whichshould be passed to Transport.unlock()
        """
        if debug.debug_flag_enabled("gio"):
            mutter("GIO lock_write", relpath)
        return self.lock_read(relpath)

    def _translate_gio_error(self, err, path, extra=None):
        if debug.debug_flag_enabled("gio"):
            mutter("GIO Error: %s %s", err, path)
        if extra is None:
            extra = str(err)
        if err.code == gio.ERROR_NOT_FOUND:
            raise NoSuchFile(path, extra=extra)
        elif err.code == gio.ERROR_EXISTS:
            raise FileExists(path, extra=extra)
        elif err.code == gio.ERROR_NOT_DIRECTORY:
            raise errors.NotADirectory(path, extra=extra)
        elif err.code == gio.ERROR_NOT_EMPTY:
            raise errors.DirectoryNotEmpty(path, extra=extra)
        elif err.code == gio.ERROR_BUSY:
            raise errors.ResourceBusy(path, extra=extra)
        elif err.code == gio.ERROR_PERMISSION_DENIED:
            raise errors.PermissionDenied(path, extra=extra)
        elif err.code == gio.ERROR_HOST_NOT_FOUND:
            raise errors.PathError(path, extra=extra)
        elif err.code == gio.ERROR_IS_DIRECTORY:
            raise errors.PathError(path, extra=extra)
        else:
            mutter("unable to understand error for path: %s: %s", path, err)
            raise errors.PathError(path, extra="Unhandled gio error: " + str(err))


def get_test_permutations():
    """Return the permutations to be used in testing."""
    return [(GioTransport, GioLocalURLServer)]
