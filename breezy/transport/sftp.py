# Copyright (C) 2005-2011, 2016, 2017 Canonical Ltd
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

"""Implementation of Transport over SFTP, using paramiko."""

# TODO: Remove the transport-based lock_read and lock_write methods.  They'll
# then raise TransportNotPossible, which will break remote access to any
# formats which rely on OS-level locks.  That should be fine as those formats
# are pretty old, but these combinations may have to be removed from the test
# suite.  Those formats all date back to 0.7; so we should be able to remove
# these methods when we officially drop support for those formats.

import bisect
import errno
import itertools
import os
import random
import stat
import sys
import time

from .. import config, debug, errors, urlutils
from .._transport_rs import sftp as _sftp_rs
from ..errors import LockError, PathError
from ..osutils import fancy_rename, pumpfile
from ..trace import mutter, warning
from ..transport import (
    ConnectedTransport,
    FileExists,
    FileFileStream,
    NoSuchFile,
    _file_streams,
    ssh,
)

SFTPError = _sftp_rs.SFTPError


class WriteStream:
    """Simple write stream wrapper for SFTP file objects."""

    def __init__(self, f):
        """Initialize write stream.

        Args:
            f: SFTP file object to wrap.
        """
        self.f = f

    def write(self, data):
        """Write data to the stream.

        Args:
            data: Bytes to write.

        Returns:
            int: Number of bytes written.
        """
        self.f.write(data)
        return len(data)


class SFTPLock:
    """This fakes a lock in a remote location.

    A present lock is indicated just by the existence of a file.  This
    doesn't work well on all transports and they are only used in
    deprecated storage formats.
    """

    __slots__ = ["lock_file", "lock_path", "path", "transport"]

    def __init__(self, path, transport):
        """Initialize SFTP lock.

        Args:
            path: Path to lock.
            transport: SFTP transport to use.

        Raises:
            LockError: If the file is already locked.
        """
        self.lock_file = None
        self.path = path
        self.lock_path = path + ".write-lock"
        self.transport = transport
        try:
            # RBC 20060103 FIXME should we be using private methods here ?
            abspath = transport._remote_path(self.lock_path)
            self.lock_file = transport._sftp_open_exclusive(abspath)
        except FileExists as err:
            raise LockError(f"File {self.path!r} already locked") from err

    def unlock(self):
        """Release the lock by closing and deleting the lock file."""
        if not self.lock_file:
            return
        self.lock_file.close()
        self.lock_file = None
        try:
            self.transport.delete(self.lock_path)
        except NoSuchFile:
            # What specific errors should we catch here?
            pass


class _SFTPReadvHelper:
    """A class to help with managing the state of a readv request."""

    def __init__(self, original_offsets, relpath, _report_activity):
        """Create a new readv helper.

        :param original_offsets: The original requests given by the caller of
            readv()
        :param relpath: The name of the file (if known)
        :param _report_activity: A Transport._report_activity bound method,
            to be called as data arrives.
        """
        self.original_offsets = list(original_offsets)
        self.relpath = relpath
        self._report_activity = _report_activity

    def _get_requests(self):
        """Break up the offsets into individual requests over sftp.

        The SFTP spec only requires implementers to support 32kB requests. We
        could try something larger (openssh supports 64kB), but then we have to
        handle requests that fail.
        So instead, we just break up our maximum chunks into 32kB chunks, and
        asyncronously requests them.
        Newer versions of paramiko would do the chunking for us, but we want to
        start processing results right away, so we do it ourselves.
        """
        # TODO: Because we issue async requests, we don't 'fudge' any extra
        #       data.  I'm not 100% sure that is the best choice.

        # The first thing we do, is to collapse the individual requests as much
        # as possible, so we don't issues requests <32kB
        sorted_offsets = sorted(self.original_offsets)
        coalesced = list(
            ConnectedTransport._coalesce_offsets(
                sorted_offsets, limit=0, fudge_factor=0
            )
        )
        requests = [(c_offset.start, c_offset.length) for c_offset in coalesced]

        if debug.debug_flag_enabled("sftp"):
            mutter(
                "SFTP.readv(%s) %s offsets => %s coalesced => %s requests",
                self.relpath,
                len(sorted_offsets),
                len(coalesced),
                len(requests),
            )
        return requests

    def request_and_yield_offsets(self, fp):
        """Request the data from the remote machine, yielding the results.

        :param fp: A Paramiko SFTPFile object that supports readv.
        :return: Yield the data requested by the original readv caller, one by
            one.
        """
        requests = self._get_requests()
        offset_iter = iter(self.original_offsets)
        cur_offset, cur_size = next(offset_iter)
        # paramiko .readv() yields strings that are in the order of the requests
        # So we track the current request to know where the next data is
        # being returned from.
        input_start = None
        last_end = None
        buffered_data = []
        buffered_len = 0

        # This is used to buffer chunks which we couldn't process yet
        # It is (start, end, data) tuples.
        data_chunks = []
        # Create an 'unlimited' data stream, so we stop based on requests,
        # rather than just because the data stream ended. This lets us detect
        # short readv.
        data_stream = itertools.chain(fp.readv(requests), itertools.repeat(None))
        for (start, length), data in zip(requests, data_stream):
            if data is None and cur_coalesced is not None:
                raise errors.ShortReadvError(self.relpath, start, length, len(data))
            if len(data) != length:
                raise errors.ShortReadvError(self.relpath, start, length, len(data))
            self._report_activity(length, "read")
            if last_end is None:
                # This is the first request, just buffer it
                buffered_data = [data]
                buffered_len = length
                input_start = start
            elif start == last_end:
                # The data we are reading fits neatly on the previous
                # buffer, so this is all part of a larger coalesced range.
                buffered_data.append(data)
                buffered_len += length
            else:
                # We have an 'interrupt' in the data stream. So we know we are
                # at a request boundary.
                if buffered_len > 0:
                    # We haven't consumed the buffer so far, so put it into
                    # data_chunks, and continue.
                    buffered = b"".join(buffered_data)
                    data_chunks.append((input_start, buffered))
                input_start = start
                buffered_data = [data]
                buffered_len = length
            last_end = start + length
            if input_start == cur_offset and cur_size <= buffered_len:
                # Simplify the next steps a bit by transforming buffered_data
                # into a single string. We also have the nice property that
                # when there is only one string ''.join([x]) == x, so there is
                # no data copying.
                buffered = b"".join(buffered_data)
                # Clean out buffered data so that we keep memory
                # consumption low
                del buffered_data[:]
                buffered_offset = 0
                # TODO: We *could* also consider the case where cur_offset is in
                #       in the buffered range, even though it doesn't *start*
                #       the buffered range. But for packs we pretty much always
                #       read in order, so you won't get any extra data in the
                #       middle.
                while (
                    input_start == cur_offset
                    and (buffered_offset + cur_size) <= buffered_len
                ):
                    # We've buffered enough data to process this request, spit it
                    # out
                    cur_data = buffered[buffered_offset : buffered_offset + cur_size]
                    # move the direct pointer into our buffered data
                    buffered_offset += cur_size
                    # Move the start-of-buffer pointer
                    input_start += cur_size
                    # Yield the requested data
                    yield cur_offset, cur_data
                    try:
                        cur_offset, cur_size = next(offset_iter)
                    except StopIteration:
                        return
                # at this point, we've consumed as much of buffered as we can,
                # so break off the portion that we consumed
                if buffered_offset == len(buffered_data):
                    # No tail to leave behind
                    buffered_data = []
                    buffered_len = 0
                else:
                    buffered = buffered[buffered_offset:]
                    buffered_data = [buffered]
                    buffered_len = len(buffered)
        # now that the data stream is done, close the handle
        fp.close()
        if buffered_len:
            buffered = b"".join(buffered_data)
            del buffered_data[:]
            data_chunks.append((input_start, buffered))
        if data_chunks:
            if debug.debug_flag_enabled("sftp"):
                mutter(
                    "SFTP readv left with %d out-of-order bytes",
                    sum(len(x[1]) for x in data_chunks),
                )
            # We've processed all the readv data, at this point, anything we
            # couldn't process is in data_chunks. This doesn't happen often, so
            # this code path isn't optimized
            # We use an interesting process for data_chunks
            # Specifically if we have "bisect_left([(start, len, entries)],
            #                                       (qstart,)])
            # If start == qstart, then we get the specific node. Otherwise we
            # get the previous node
            while True:
                idx = bisect.bisect_left(data_chunks, (cur_offset,))
                if idx < len(data_chunks) and data_chunks[idx][0] == cur_offset:
                    # The data starts here
                    data = data_chunks[idx][1][:cur_size]
                elif idx > 0:
                    # The data is in a portion of a previous page
                    idx -= 1
                    sub_offset = cur_offset - data_chunks[idx][0]
                    data = data_chunks[idx][1]
                    data = data[sub_offset : sub_offset + cur_size]
                else:
                    # We are missing the page where the data should be found,
                    # something is wrong
                    data = ""
                if len(data) != cur_size:
                    raise AssertionError(
                        "We must have miscalulated."
                        " We expected %d bytes, but only found %d"
                        % (cur_size, len(data))
                    )
                yield cur_offset, data
                try:
                    cur_offset, cur_size = next(offset_iter)
                except StopIteration:
                    return


class SFTPTransport(ConnectedTransport):
    """Transport implementation for SFTP access."""

    # TODO: jam 20060717 Conceivably these could be configurable, either
    #       by auto-tuning at run-time, or by a configuration (per host??)
    #       but the performance curve is pretty flat, so just going with
    #       reasonable defaults.
    _max_readv_combine = 200
    # Having to round trip to the server means waiting for a response,
    # so it is better to download extra bytes.
    # 8KiB had good performance for both local and remote network operations
    _bytes_to_read_before_seek = 8192

    def _pump(self, infile, outfile):
        return pumpfile(infile, WriteStream(outfile))

    def _remote_path(self, relpath):
        """Return the path to be passed along the sftp protocol for relpath.

        :param relpath: is a urlencoded string.
        """
        remote_path = self._parsed_url.clone(relpath).path
        # the initial slash should be removed from the path, and treated as a
        # homedir relative path (the path begins with a double slash if it is
        # absolute).  see draft-ietf-secsh-scp-sftp-ssh-uri-03.txt
        # RBC 20060118 we are not using this as its too user hostile. instead
        # we are following lftp and using /~/foo to mean '~/foo'
        # vila--20070602 and leave absolute paths begin with a single slash.
        if remote_path.startswith("/~/"):
            remote_path = remote_path[3:]
        elif remote_path == "/~":
            remote_path = ""
        return remote_path

    def _create_connection(self, credentials=None):
        """Create a new connection with the provided credentials.

        :param credentials: The credentials needed to establish the connection.

        :return: The created connection and its associated credentials.

        The credentials are only the password as it may have been entered
        interactively by the user and may be different from the one provided
        in base url at transport creation time.
        """
        password = self._parsed_url.password if credentials is None else credentials

        vendor = ssh._get_ssh_vendor()
        user = self._parsed_url.user
        if user is None:
            auth = config.AuthenticationConfig()
            user = auth.get_user("ssh", self._parsed_url.host, self._parsed_url.port)
        connection = vendor.connect_sftp(
            self._parsed_url.user,
            password,
            self._parsed_url.host,
            self._parsed_url.port,
        )
        return connection, (user, password)

    def disconnect(self):
        """Disconnect the current SFTP connection."""
        connection = self._get_connection()
        if connection is not None:
            connection.close()

    def _get_sftp(self):
        """Ensures that a connection is established."""
        connection = self._get_connection()
        if connection is None:
            # First connection ever
            connection, credentials = self._create_connection()
            self._set_connection(connection, credentials)
        return connection

    def has(self, relpath):
        """Does the target location exist?"""
        try:
            self._get_sftp().stat(self._remote_path(relpath))
            # stat result is about 20 bytes, let's say
            self._report_activity(20, "read")
            return True
        except NoSuchFile:
            return False

    def get(self, relpath):
        """Get the file at the given relative path.

        :param relpath: The relative path to the file
        """
        try:
            path = self._remote_path(relpath)
            f = self._get_sftp().file(path, mode="rb")
            size = f.stat().st_size
            if getattr(f, "prefetch", None) is not None:
                f.prefetch(size)
            return f
        except (OSError, SFTPError) as e:
            self._translate_io_exception(
                e, path, ": error retrieving", failure_exc=errors.ReadError
            )

    def get_bytes(self, relpath):
        """Get the contents of a file as a byte string.

        Args:
            relpath: Path to the file relative to transport root.

        Returns:
            bytes: The file contents.
        """
        # reimplement this here so that we can report how many bytes came back
        with self.get(relpath) as f:
            bytes = f.read()
            self._report_activity(len(bytes), "read")
            return bytes

    def _readv(self, relpath, offsets):
        """See Transport.readv()."""
        # We overload the default readv() because we want to use a file
        # that does not have prefetch enabled.
        # Also, if we have a new paramiko, it implements an async readv()
        if not offsets:
            return

        try:
            path = self._remote_path(relpath)
            fp = self._get_sftp().file(path, mode="rb")
            readv = getattr(fp, "readv", None)
            if readv:
                return self._sftp_readv(fp, offsets, relpath)
            if debug.debug_flag_enabled("sftp"):
                mutter("seek and read %s offsets", len(offsets))
            return self._seek_and_read(fp, offsets, relpath)
        except (OSError, SFTPError) as e:
            self._translate_io_exception(e, path, ": error retrieving")

    def recommended_page_size(self):
        """See Transport.recommended_page_size().

        For SFTP we suggest a large page size to reduce the overhead
        introduced by latency.
        """
        return 64 * 1024

    def _sftp_readv(self, fp, offsets, relpath):
        """Use the readv() member of fp to do async readv.

        Then read them using paramiko.readv(). paramiko.readv()
        does not support ranges > 64K, so it caps the request size, and
        just reads until it gets all the stuff it wants.
        """
        helper = _SFTPReadvHelper(offsets, relpath, self._report_activity)
        return helper.request_and_yield_offsets(fp)

    def put_file(self, relpath, f, mode=None):
        """Copy the file-like object into the location.

        :param relpath: Location to put the contents, relative to base.
        :param f:       File-like object.
        :param mode: The final mode for the file
        """
        final_path = self._remote_path(relpath)
        return self._put(final_path, f, mode=mode)

    def _put(self, abspath, f, mode=None):
        """Helper function so both put() and copy_abspaths can reuse the code."""
        tmp_abspath = "%s.tmp.%.9f.%d.%d" % (
            abspath,
            time.time(),
            os.getpid(),
            random.randint(0, 0x7FFFFFFF),  # noqa: S311
        )
        fout = self._sftp_open_exclusive(tmp_abspath, mode=mode)
        closed = False
        try:
            try:
                length = self._pump(f, fout)
            except (OSError, SFTPError) as e:
                self._translate_io_exception(e, tmp_abspath)
            # XXX: This doesn't truly help like we would like it to.
            #      The problem is that openssh strips sticky bits. So while we
            #      can properly set group write permission, we lose the group
            #      sticky bit. So it is probably best to stop chmodding, and
            #      just tell users that they need to set the umask correctly.
            #      The attr.st_mode = mode, in _sftp_open_exclusive
            #      will handle when the user wants the final mode to be more
            #      restrictive. And then we avoid a round trip. Unless
            #      paramiko decides to expose an async chmod()

            # This is designed to chmod() right before we close.
            # Because we set_pipelined() earlier, theoretically we might
            # avoid the round trip for fout.close()
            if mode is not None:
                self._get_sftp().chmod(tmp_abspath, mode)
            fout.close()
            closed = True
            self._rename_and_overwrite(tmp_abspath, abspath)
            return length
        except Exception as e:
            # If we fail, try to clean up the temporary file
            # before we throw the exception
            # but don't let another exception mess things up
            # Write out the traceback, because otherwise
            # the catch and throw destroys it
            import traceback

            mutter(traceback.format_exc())
            try:
                if not closed:
                    fout.close()
                self._get_sftp().remove(tmp_abspath)
            except BaseException:
                # raise the saved except
                raise e from None
            # raise the original with its traceback if we can.
            raise

    def _put_non_atomic_helper(
        self, relpath, writer, mode=None, create_parent_dir=False, dir_mode=None
    ):
        abspath = self._remote_path(relpath)

        # TODO: jam 20060816 paramiko doesn't publicly expose a way to
        #       set the file mode at create time. If it does, use it.
        #       But for now, we just chmod later anyway.

        def _open_and_write_file():
            """Try to open the target file, raise error on failure."""
            fout = None
            try:
                try:
                    fout = self._get_sftp().file(abspath, mode="wb")

                    writer(fout)
                except (SFTPError, OSError) as e:
                    self._translate_io_exception(e, abspath, ": unable to open")

                # This is designed to chmod() right before we close.
                # Because we set_pipelined() earlier, theoretically we might
                # avoid the round trip for fout.close()
                if mode is not None:
                    self._get_sftp().chmod(abspath, mode)
            finally:
                if fout is not None:
                    fout.close()

        if not create_parent_dir:
            _open_and_write_file()
            return

        # Try error handling to create the parent directory if we need to
        try:
            _open_and_write_file()
        except NoSuchFile:
            # Try to create the parent directory, and then go back to
            # writing the file
            parent_dir = os.path.dirname(abspath)
            self._mkdir(parent_dir, dir_mode)
            _open_and_write_file()

    def put_file_non_atomic(
        self, relpath, f, mode=None, create_parent_dir=False, dir_mode=None
    ):
        """Copy the file-like object into the target location.

        This function is not strictly safe to use. It is only meant to
        be used when you already know that the target does not exist.
        It is not safe, because it will open and truncate the remote
        file. So there may be a time when the file has invalid contents.

        :param relpath: The remote location to put the contents.
        :param f:       File-like object.
        :param mode:    Possible access permissions for new file.
                        None means do not set remote permissions.
        :param create_parent_dir: If we cannot create the target file because
                        the parent directory does not exist, go ahead and
                        create it, and then try again.
        """

        def writer(fout):
            self._pump(f, fout)

        self._put_non_atomic_helper(
            relpath,
            writer,
            mode=mode,
            create_parent_dir=create_parent_dir,
            dir_mode=dir_mode,
        )

    def put_bytes_non_atomic(
        self,
        relpath: str,
        raw_bytes: bytes,
        mode=None,
        create_parent_dir=False,
        dir_mode=None,
    ):
        """Write bytes to a file non-atomically.

        This is not safe if the target already exists as it will truncate it.

        Args:
            relpath: Path relative to transport root.
            raw_bytes: Bytes to write.
            mode: File permissions.
            create_parent_dir: Whether to create parent directory if needed.
            dir_mode: Permissions for created parent directories.

        Raises:
            TypeError: If raw_bytes is not bytes.
        """
        if not isinstance(raw_bytes, bytes):
            raise TypeError(f"raw_bytes must be a plain string, not {type(raw_bytes)}")

        def writer(fout):
            fout.write(raw_bytes)

        self._put_non_atomic_helper(
            relpath,
            writer,
            mode=mode,
            create_parent_dir=create_parent_dir,
            dir_mode=dir_mode,
        )

    def iter_files_recursive(self):
        """Walk the relative paths of all files in this transport."""
        # progress is handled by list_dir
        queue = list(self.list_dir("."))
        while queue:
            relpath = queue.pop(0)
            st = self.stat(relpath)
            if stat.S_ISDIR(st.st_mode):
                for i, basename in enumerate(self.list_dir(relpath)):
                    queue.insert(i, relpath + "/" + basename)
            else:
                yield relpath

    def _mkdir(self, abspath, mode=None):
        local_mode = 511 if mode is None else mode
        try:
            self._report_activity(len(abspath), "write")
            self._get_sftp().mkdir(abspath, local_mode)
            self._report_activity(1, "read")
            if mode is not None:
                # chmod a dir through sftp will erase any sgid bit set
                # on the server side.  So, if the bit mode are already
                # set, avoid the chmod.  If the mode is not fine but
                # the sgid bit is set, report a warning to the user
                # with the umask fix.
                stat = self._get_sftp().lstat(abspath)
                mode = mode & 0o777  # can't set special bits anyway
                if mode != stat.st_mode & 0o777:
                    if stat.st_mode & 0o6000:
                        warning(
                            f"About to chmod {abspath} over sftp, which will result"
                            " in its suid or sgid bits being cleared.  If"
                            " you want to preserve those bits, change your "
                            f" environment on the server to use umask 0{0o777 - mode:03o}."
                        )
                    self._get_sftp().chmod(abspath, mode=mode)
        except (SFTPError, OSError) as e:
            self._translate_io_exception(
                e, abspath, ": unable to mkdir", failure_exc=FileExists
            )

    def mkdir(self, relpath, mode=None):
        """Create a directory at the given path."""
        self._mkdir(self._remote_path(relpath), mode=mode)

    def open_write_stream(self, relpath, mode=None):
        """See Transport.open_write_stream."""
        # initialise the file to zero-length
        # this is three round trips, but we don't use this
        # api more than once per write_group at the moment so
        # it is a tolerable overhead. Better would be to truncate
        # the file after opening. RBC 20070805
        self.put_bytes_non_atomic(relpath, b"", mode)
        abspath = self._remote_path(relpath)
        # TODO: jam 20060816 paramiko doesn't publicly expose a way to
        #       set the file mode at create time. If it does, use it.
        #       But for now, we just chmod later anyway.
        handle = None
        try:
            handle = self._get_sftp().file(abspath, mode="wb")
        except (SFTPError, OSError) as e:
            self._translate_io_exception(e, abspath, ": unable to open")
        _file_streams[self.abspath(relpath)] = handle
        return FileFileStream(self, relpath, handle)

    def _translate_io_exception(self, e, path, more_info="", failure_exc=PathError):
        """Translate a paramiko or IOError into a friendlier exception.

        :param e: The original exception
        :param path: The path in question when the error is raised
        :param more_info: Extra information that can be included,
                          such as what was going on
        :param failure_exc: Paramiko has the super fun ability to raise completely
                           opaque errors that just set "e.args = ('Failure',)" with
                           no more information.
                           If this parameter is set, it defines the exception
                           to raise in these cases.
        """
        # paramiko seems to generate detailless errors.
        self._translate_error(e, path, raise_generic=False)
        if getattr(e, "args", None) is not None:
            if e.args == ("No such file or directory",) or e.args == ("No such file",):
                raise NoSuchFile(path, str(e) + more_info)
            if e.args == ("mkdir failed",) or e.args[0].startswith(
                "syserr: File exists"
            ):
                raise FileExists(path, str(e) + more_info)
            # strange but true, for the paramiko server.
            if e.args == ("Failure",):
                raise failure_exc(path, str(e) + more_info)
            # Can be something like args = ('Directory not empty:
            # '/srv/bazaar.launchpad.net/blah...: '
            # [Errno 39] Directory not empty',)
            if (
                e.args[0].startswith("Directory not empty: ")
                or getattr(e, "errno", None) == errno.ENOTEMPTY
            ):
                raise errors.DirectoryNotEmpty(path, str(e))
            if e.args == ("Operation unsupported",):
                raise errors.TransportNotPossible()
            mutter("Raising exception with args %s", e.args)
        if getattr(e, "errno", None) is not None:
            mutter("Raising exception with errno %s", e.errno)
        raise e

    def append_file(self, relpath, f, mode=None):
        """Append the text in the file-like object into the final
        location.
        """
        try:
            path = self._remote_path(relpath)
            fout = self._get_sftp().file(path, "ab")
            if mode is not None:
                self._get_sftp().chmod(path, mode)
            result = fout.tell()
            self._pump(f, fout)
            return result
        except (OSError, SFTPError) as e:
            self._translate_io_exception(e, relpath, ": unable to append")

    def rename(self, rel_from, rel_to):
        """Rename without special overwriting."""
        try:
            self._get_sftp().rename(
                self._remote_path(rel_from), self._remote_path(rel_to)
            )
        except (OSError, SFTPError) as e:
            self._translate_io_exception(
                e, rel_from, f": unable to rename to {rel_to!r}"
            )

    def _rename_and_overwrite(self, abs_from, abs_to):
        """Do a fancy rename on the remote server.

        Using the implementation provided by osutils.
        """
        try:
            sftp = self._get_sftp()
            fancy_rename(
                abs_from, abs_to, rename_func=sftp.rename, unlink_func=sftp.remove
            )
        except (OSError, SFTPError) as e:
            self._translate_io_exception(
                e, abs_from, f": unable to rename to {abs_to!r}"
            )

    def move(self, rel_from, rel_to):
        """Move the item at rel_from to the location at rel_to."""
        path_from = self._remote_path(rel_from)
        path_to = self._remote_path(rel_to)
        self._rename_and_overwrite(path_from, path_to)

    def delete(self, relpath):
        """Delete the item at relpath."""
        path = self._remote_path(relpath)
        try:
            self._get_sftp().remove(path)
        except (OSError, SFTPError) as e:
            self._translate_io_exception(e, path, ": unable to delete")

    def external_url(self):
        """See breezy.transport.Transport.external_url."""
        # the external path for SFTP is the base
        return self.base

    def listable(self):
        """Return True if this store supports listing."""
        return True

    def list_dir(self, relpath):
        """Return a list of all files at the given location."""
        # does anything actually use this?
        # -- Unknown
        # This is at least used by copy_tree for remote upgrades.
        # -- David Allouche 2006-08-11
        path = self._remote_path(relpath)
        try:
            entries = self._get_sftp().listdir(path)
            self._report_activity(sum(map(len, entries)), "read")
        except (OSError, SFTPError) as e:
            self._translate_io_exception(e, path, ": failed to list_dir")
        return [urlutils.escape(entry) for entry in entries]

    def rmdir(self, relpath):
        """See Transport.rmdir."""
        path = self._remote_path(relpath)
        try:
            return self._get_sftp().rmdir(path)
        except (OSError, SFTPError) as e:
            self._translate_io_exception(e, path, ": failed to rmdir")

    def stat(self, relpath):
        """Return the stat information for a file."""
        path = self._remote_path(relpath)
        try:
            return self._get_sftp().lstat(path)
        except (OSError, SFTPError) as e:
            self._translate_io_exception(e, path, ": unable to stat")

    def readlink(self, relpath):
        """See Transport.readlink."""
        path = self._remote_path(relpath)
        try:
            return self._get_sftp().readlink(self._remote_path(path))
        except (OSError, SFTPError) as e:
            self._translate_io_exception(e, path, ": unable to readlink")

    def symlink(self, source, link_name):
        """See Transport.symlink."""
        try:
            conn = self._get_sftp()
            conn.symlink(source, self._remote_path(link_name))
        except (OSError, SFTPError) as e:
            self._translate_io_exception(
                e, link_name, f": unable to create symlink to {source!r}"
            )

    def lock_read(self, relpath):
        """Lock the given file for shared (read) access.
        :return: A lock object, which has an unlock() member function.
        """

        # FIXME: there should be something clever i can do here...
        class BogusLock:
            def __init__(self, path):
                self.path = path

            def unlock(self):
                pass

            def __exit__(self, exc_type, exc_val, exc_tb):
                return False

            def __enter__(self):
                pass

        return BogusLock(relpath)

    def lock_write(self, relpath):
        """Lock the given file for exclusive (write) access.
        WARNING: many transports do not support this, so trying avoid using it.

        :return: A lock object, which has an unlock() member function
        """
        # This is a little bit bogus, but basically, we create a file
        # which should not already exist, and if it does, we assume
        # that there is a lock, and if it doesn't, the we assume
        # that we have taken the lock.
        return SFTPLock(relpath, self)

    def _sftp_open_exclusive(self, abspath, mode=None):
        """Open a remote path exclusively.

        SFTP supports O_EXCL (SFTP_FLAG_EXCL), which fails if
        the file already exists. However it does not expose this
        at the higher level of SFTPClient.open(), so we have to
        sneak away with it.

        WARNING: This breaks the SFTPClient abstraction, so it
        could easily break against an updated version of paramiko.

        :param abspath: The remote absolute path where the file should be opened
        :param mode: The mode permissions bits for the new file
        """
        attr = _sftp_rs.SFTPAttributes()
        if mode is not None:
            attr.st_mode = mode | stat.S_IFREG
        else:
            attr.st_mode = stat.S_IFREG | 0o644
        flags = (
            _sftp_rs.SFTP_FLAG_WRITE
            | _sftp_rs.SFTP_FLAG_CREAT
            | _sftp_rs.SFTP_FLAG_EXCL
            | _sftp_rs.SFTP_FLAG_TRUNC
        )
        try:
            return self._get_sftp().open(abspath, flags, attr)
        except (SFTPError, OSError) as e:
            self._translate_io_exception(
                e, abspath, ": unable to open", failure_exc=FileExists
            )

    def _can_roundtrip_unix_modebits(self):
        return sys.platform != "win32"


def get_test_permutations():
    """Return the permutations to be used in testing."""
    from ..tests import stub_sftp

    return [
        (SFTPTransport, stub_sftp.SFTPAbsoluteServer),
        (SFTPTransport, stub_sftp.SFTPHomeDirServer),
        (SFTPTransport, stub_sftp.SFTPSiblingAbsoluteServer),
    ]
