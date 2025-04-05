# Copyright (C) 2005-2011 Canonical Ltd
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

import codecs
import errno
import os
import sys
import time

from .lazy_import import lazy_import

lazy_import(
    globals(),
    """
# We need to import both shutil and rmtree as we export the later on posix
# and need the former on windows
import shutil
from shutil import rmtree
import socket

from breezy import (
    config,
    )
""",
)


from . import _osutils_rs, errors

# On win32, O_BINARY is used to indicate the file should
# be opened in binary mode, rather than text mode.
# On other platforms, O_BINARY doesn't exist, because
# they always open in binary mode, so it is okay to
# OR with 0 on those platforms.
# O_NOINHERIT and O_TEXT exists only on win32 too.
O_BINARY = getattr(os, "O_BINARY", 0)
O_TEXT = getattr(os, "O_TEXT", 0)
O_NOINHERIT = getattr(os, "O_NOINHERIT", 0)


UnsupportedTimezoneFormat = _osutils_rs.UnsupportedTimezoneFormat

make_readonly = _osutils_rs.make_readonly
chmod_if_possible = _osutils_rs.chmod_if_possible
make_writable = _osutils_rs.make_writable

minimum_path_selection = _osutils_rs.minimum_path_selection


from ._osutils_rs import get_umask, kind_marker, lexists, quotefn  # noqa: F401


def fancy_rename(old, new, rename_func, unlink_func):
    """A fancy rename, when you don't have atomic rename.

    :param old: The old path, to rename from
    :param new: The new path, to rename to
    :param rename_func: The potentially non-atomic rename function
    :param unlink_func: A way to delete the target file if the full rename
        succeeds
    """
    from .transport import NoSuchFile

    # sftp rename doesn't allow overwriting, so play tricks:
    base = os.path.basename(new)
    dirname = os.path.dirname(new)
    # callers use different encodings for the paths so the following MUST
    # respect that. We rely on python upcasting to unicode if new is unicode
    # and keeping a str if not.
    tmp_name = "tmp.%s.%.9f.%d.%s" % (base, time.time(), os.getpid(), rand_chars(10))
    tmp_name = pathjoin(dirname, tmp_name)

    # Rename the file out of the way, but keep track if it didn't exist
    # We don't want to grab just any exception
    # something like EACCES should prevent us from continuing
    # The downside is that the rename_func has to throw an exception
    # with an errno = ENOENT, or NoSuchFile
    file_existed = False
    try:
        rename_func(new, tmp_name)
    except NoSuchFile:
        pass
    except (FileNotFoundError, NotADirectoryError):
        pass
    except OSError:
        # RBC 20060103 abstraction leakage: the paramiko SFTP clients rename
        # function raises an IOError with errno is None when a rename fails.
        # This then gets caught here.
        raise
    except Exception as e:
        if getattr(e, "errno", None) is None or e.errno not in (
            errno.ENOENT,
            errno.ENOTDIR,
        ):
            raise
    else:
        file_existed = True

    success = False
    try:
        # This may throw an exception, in which case success will
        # not be set.
        rename_func(old, new)
        success = True
    except FileNotFoundError:
        # source and target may be aliases of each other (e.g. on a
        # case-insensitive filesystem), so we may have accidentally renamed
        # source by when we tried to rename target
        if file_existed and old.lower() == new.lower():
            # source and target are the same file on a case-insensitive
            # filesystem, so we don't generate an exception
            pass
        else:
            raise
    finally:
        if file_existed:
            # If the file used to exist, rename it back into place
            # otherwise just delete it from the tmp location
            if success:
                unlink_func(tmp_name)
            else:
                rename_func(tmp_name, new)


_posix_normpath = _osutils_rs.posix.normpath
_win32_normpath = _osutils_rs.win32.normpath
_win32_fixdrive = _osutils_rs.win32.fixdrive
_win32_fix_separators = _osutils_rs.win32.fix_separators
_win32_abspath = _osutils_rs.win32.abspath


def _win32_realpath(path):
    import ntpath

    # Real ntpath.realpath doesn't have a problem with a unicode cwd
    return _win32_fixdrive(_win32_fix_separators(ntpath.realpath(path)))


_win32_getcwd = _osutils_rs.win32.getcwd


def _win32_rename(old, new):
    """We expect to be able to atomically replace 'new' with old.

    On win32, if new exists, it must be moved out of the way first,
    and then deleted.
    """
    try:
        fancy_rename(old, new, rename_func=os.rename, unlink_func=os.unlink)
    except OSError as e:
        if e.errno in (errno.EPERM, errno.EACCES, errno.EBUSY, errno.EINVAL):
            # If we try to rename a non-existant file onto cwd, we get
            # EPERM or EACCES instead of ENOENT, this will raise ENOENT
            # if the old path doesn't exist, sometimes we get EACCES
            # On Linux, we seem to get EBUSY, on Mac we get EINVAL
            os.lstat(old)
        raise


def _rename_wrap_exception(rename_func):
    """Adds extra information to any exceptions that come from rename().

    The exception has an updated message and 'old_filename' and 'new_filename'
    attributes.
    """

    def _rename_wrapper(old, new):
        try:
            rename_func(old, new)
        except OSError as e:
            detailed_error = OSError(
                e.errno, e.strerror + f" [occurred when renaming '{old}' to '{new}']"
            )
            detailed_error.old_filename = old
            detailed_error.new_filename = new
            raise detailed_error from e

    return _rename_wrapper


# Default rename wraps os.rename()
rename = _rename_wrap_exception(os.rename)

# Default is to just use the python builtins, but these can be rebound on
# particular platforms.
abspath = _osutils_rs.abspath
realpath = _osutils_rs.realpath
normalizepath = _osutils_rs.normalizepath
pathjoin = _osutils_rs.pathjoin
normpath = _osutils_rs.normpath
_get_home_dir = _osutils_rs.get_home_dir



getcwd = os.getcwd
dirname = os.path.dirname
basename = os.path.basename
split = os.path.split
splitext = os.path.splitext
# These were already lazily imported into local scope
# rmtree = shutil.rmtree
lstat = os.lstat
fstat = os.fstat

_win32_normpath = _osutils_rs.win32.normpath
_win32_getcwd = _osutils_rs.win32.getcwd

getuser_unicode = _osutils_rs.get_user_name


if sys.platform == "win32":
    rename = _rename_wrap_exception(_win32_rename)

    def _win32_delete_readonly(function, path, excinfo):
        """Error handler for shutil.rmtree function [for win32]
        Helps to remove files and dirs marked as read-only.
        """
        exception = excinfo[1]
        if (
            function in (os.unlink, os.remove, os.rmdir)
            and isinstance(exception, OSError)
            and exception.errno == errno.EACCES
        ):
            make_writable(path)
            function(path)
        else:
            raise

    def rmtree(path, ignore_errors=False, onerror=_win32_delete_readonly):
        """Replacer for shutil.rmtree: could remove readonly dirs/files."""
        return shutil.rmtree(path, ignore_errors, onerror)


def get_terminal_encoding(trace=False):
    """Find the best encoding for printing to the screen.

    This attempts to check both sys.stdout and sys.stdin to see
    what encoding they are in, and if that fails it falls back to
    osutils.get_user_encoding().
    The problem is that on Windows, locale.getpreferredencoding()
    is not the same encoding as that used by the console:
    http://mail.python.org/pipermail/python-list/2003-May/162357.html

    On my standard US Windows XP, the preferred encoding is
    cp1252, but the console is cp437

    :param trace: If True trace the selected encoding via mutter().
    """
    from .trace import mutter

    output_encoding = getattr(sys.stdout, "encoding", None)
    if not output_encoding:
        input_encoding = getattr(sys.stdin, "encoding", None)
        if not input_encoding:
            output_encoding = get_user_encoding()
            if trace:
                mutter(
                    "encoding stdout as osutils.get_user_encoding() %r", output_encoding
                )
        else:
            output_encoding = input_encoding
            if trace:
                mutter("encoding stdout as sys.stdin encoding %r", output_encoding)
    else:
        if trace:
            mutter("encoding stdout as sys.stdout encoding %r", output_encoding)
    if output_encoding == "cp0":
        # invalid encoding (cp0 means 'no codepage' on Windows)
        output_encoding = get_user_encoding()
        if trace:
            mutter(
                "cp0 is invalid encoding."
                " encoding stdout as osutils.get_user_encoding() %r",
                output_encoding,
            )
    # check encoding
    try:
        codecs.lookup(output_encoding)
    except LookupError:
        sys.stderr.write(
            "brz: warning:"
            f" unknown terminal encoding {output_encoding}.\n"
            f"  Using encoding {get_user_encoding()} instead.\n"
        )
        output_encoding = get_user_encoding()

    return output_encoding


isdir = _osutils_rs.isdir
is_inside = _osutils_rs.is_inside
is_inside_any = _osutils_rs.is_inside_any
is_inside_or_parent_of_any = _osutils_rs.is_inside_or_parent_of_any
pumpfile = _osutils_rs.pumpfile
pump_string_file = _osutils_rs.pump_string_file


file_iterator = _osutils_rs.file_iterator
sha_file = _osutils_rs.sha_file
size_sha_file = _osutils_rs.size_sha_file
sha_file_by_name = _osutils_rs.sha_file_by_name
sha_strings = _osutils_rs.sha_strings
sha_string = _osutils_rs.sha_string
compare_files = _osutils_rs.compare_files
local_time_offset = _osutils_rs.local_time_offset
format_date = _osutils_rs.format_date
format_date_with_offset_in_original_timezone = (
    _osutils_rs.format_date_with_offset_in_original_timezone
)
format_local_date = _osutils_rs.format_local_date
compact_date = _osutils_rs.compact_date
format_highres_date = _osutils_rs.format_highres_date
unpack_highres_date = _osutils_rs.unpack_highres_date

rand_chars = _osutils_rs.rand_chars

# TODO: We could later have path objects that remember their list
# decomposition (might be too tricksy though.)

splitpath = _osutils_rs.splitpath
joinpath = _osutils_rs.joinpath


parent_directories = _osutils_rs.parent_directories


_extension_load_failures = []


def failed_to_load_extension(exception):
    """Handle failing to load a binary extension.

    This should be called from the ImportError block guarding the attempt to
    import the native extension.  If this function returns, the pure-Python
    implementation should be loaded instead::

    >>> try:
    >>>     import breezy._fictional_extension_pyx
    >>> except ModuleNotFoundError as e:
    >>>     breezy.osutils.failed_to_load_extension(e)
    >>>     import breezy._fictional_extension_py
    """
    # NB: This docstring is just an example, not a doctest, because doctest
    # currently can't cope with the use of lazy imports in this namespace --
    # mbp 20090729

    # This currently doesn't report the failure at the time it occurs, because
    # they tend to happen very early in startup when we can't check config
    # files etc, and also we want to report all failures but not spam the user
    # with 10 warnings.
    exception_str = str(exception)
    if exception_str not in _extension_load_failures:
        from .trace import mutter

        mutter(f"failed to load compiled extension: {exception_str}")
        _extension_load_failures.append(exception_str)


def report_extension_load_failures():
    if not _extension_load_failures:
        return
    if config.GlobalConfig().suppress_warning("missing_extensions"):
        return
    # the warnings framework should by default show this only once
    from .trace import warning

    warning(
        "brz: warning: some compiled extensions could not be loaded; "
        "see ``brz help missing-extensions``"
    )
    # we no longer show the specific missing extensions here, because it makes
    # the message too long and scary - see
    # https://bugs.launchpad.net/bzr/+bug/430529


import contextlib

from ._osutils_rs import (  # noqa: F401
    _accessible_normalized_filename,
    _inaccessible_normalized_filename,
    check_legal_path,
    chunks_to_lines,
    chunks_to_lines_iter,
    delete_any,
    get_host_name,
    link_or_copy,
    local_concurrency,
    normalized_filename,
    normalizes_filenames,
    split_lines,
)

readlink = _osutils_rs.readlink
contains_whitespace = _osutils_rs.contains_whitespace
contains_linebreaks = _osutils_rs.contains_linebreaks
relpath = _osutils_rs.relpath


def _cicp_canonical_relpath(base, path):
    """Return the canonical path relative to base.

    Like relpath, but on case-insensitive-case-preserving file-systems, this
    will return the relpath as stored on the file-system rather than in the
    case specified in the input string, for all existing portions of the path.

    This will cause O(N) behaviour if called for every path in a tree; if you
    have a number of paths to convert, you should use canonical_relpaths().
    """
    # TODO: it should be possible to optimize this for Windows by using the
    # win32 API FindFiles function to look for the specified name - but using
    # os.listdir() still gives us the correct, platform agnostic semantics in
    # the short term.

    rel = relpath(base, path)
    # '.' will have been turned into ''
    if not rel:
        return rel

    abs_base = abspath(base)
    current = abs_base

    # use an explicit iterator so we can easily consume the rest on early exit.
    bit_iter = iter(rel.split("/"))
    for bit in bit_iter:
        lbit = bit.lower()
        try:
            next_entries = os.scandir(current)
        except OSError:  # enoent, eperm, etc
            # We can't find this in the filesystem, so just append the
            # remaining bits.
            current = pathjoin(current, bit, *list(bit_iter))
            break
        for entry in next_entries:
            if lbit == entry.name.lower():
                current = entry.path
                break
        else:
            # got to the end, nothing matched, so we just return the
            # non-existing bits as they were specified (the filename may be
            # the target of a move, for example).
            current = pathjoin(current, bit, *list(bit_iter))
            break
    return current[len(abs_base) :].lstrip("/")


# XXX - TODO - we need better detection/integration of case-insensitive
# file-systems; Linux often sees FAT32 devices (or NFS-mounted OSX
# filesystems), for example, so could probably benefit from the same basic
# support there.  For now though, only Windows and OSX get that support, and
# they get it for *all* file-systems!
if sys.platform in ("win32", "darwin"):
    canonical_relpath = _cicp_canonical_relpath
else:
    canonical_relpath = relpath


def canonical_relpaths(base, paths):
    """Create an iterable to canonicalize a sequence of relative paths.

    The intent is for this implementation to use a cache, vastly speeding
    up multiple transformations in the same directory.
    """
    # but for now, we haven't optimized...
    return [canonical_relpath(base, p) for p in paths]


def safe_unicode(unicode_or_utf8_string):
    """Coerce unicode_or_utf8_string into unicode.

    If it is unicode, it is returned.
    Otherwise it is decoded from utf-8. If decoding fails, the exception is
    wrapped in a BzrBadParameterNotUnicode exception.
    """
    if isinstance(unicode_or_utf8_string, str):
        return unicode_or_utf8_string
    try:
        return unicode_or_utf8_string.decode("utf8")
    except UnicodeDecodeError as e:
        raise errors.BzrBadParameterNotUnicode(unicode_or_utf8_string) from e


def safe_utf8(unicode_or_utf8_string):
    """Coerce unicode_or_utf8_string to a utf8 string.

    If it is a str, it is returned.
    If it is Unicode, it is encoded into a utf-8 string.
    """
    if isinstance(unicode_or_utf8_string, bytes):
        # TODO: jam 20070209 This is overkill, and probably has an impact on
        #       performance if we are dealing with lots of apis that want a
        #       utf-8 revision id
        try:
            # Make sure it is a valid utf-8 string
            unicode_or_utf8_string.decode("utf-8")
        except UnicodeDecodeError as e:
            raise errors.BzrBadParameterNotUnicode(unicode_or_utf8_string) from e
        return unicode_or_utf8_string
    return unicode_or_utf8_string.encode("utf-8")


def set_signal_handler(signum, handler, restart_syscall=True):
    """A wrapper for signal.signal that also calls siginterrupt(signum, False)
    on platforms that support that.

    :param restart_syscall: if set, allow syscalls interrupted by a signal to
        automatically restart (by calling `signal.siginterrupt(signum,
        False)`).  May be ignored if the feature is not available on this
        platform or Python version.
    """
    try:
        import signal

        siginterrupt = signal.siginterrupt
    except ImportError:
        # This python implementation doesn't provide signal support, hence no
        # handler exists
        return None
    except AttributeError:
        # siginterrupt doesn't exist on this platform, or for this version
        # of Python.
        def siginterrupt(signum, flag):
            return None

    if restart_syscall:

        def sig_handler(*args):
            # Python resets the siginterrupt flag when a signal is
            # received.  <http://bugs.python.org/issue8354>
            # As a workaround for some cases, set it back the way we want it.
            siginterrupt(signum, False)
            # Now run the handler function passed to set_signal_handler.
            handler(*args)
    else:
        sig_handler = handler
    old_handler = signal.signal(signum, sig_handler)
    if restart_syscall:
        siginterrupt(signum, False)
    return old_handler


default_terminal_width = 80
"""The default terminal width for ttys.

This is defined so that higher levels can share a common fallback value when
terminal_width() returns None.
"""

# Keep some state so that terminal_width can detect if _terminal_size has
# returned a different size since the process started.  See docstring and
# comments of terminal_width for details.
# _terminal_size_state has 3 possible values: no_data, unchanged, and changed.
_terminal_size_state = "no_data"
_first_terminal_size = None


def terminal_width():
    """Return terminal width.

    None is returned if the width can't established precisely.

    The rules are:
    - if BRZ_COLUMNS is set, returns its value
    - if there is no controlling terminal, returns None
    - query the OS, if the queried size has changed since the last query,
      return its value,
    - if COLUMNS is set, returns its value,
    - if the OS has a value (even though it's never changed), return its value.

    From there, we need to query the OS to get the size of the controlling
    terminal.
    """
    # Note to implementors: if changing the rules for determining the width,
    # make sure you've considered the behaviour in these cases:
    #  - M-x shell in emacs, where $COLUMNS is set and TIOCGWINSZ returns 0,0.
    #  - brz log | less, in bash, where $COLUMNS not set and TIOCGWINSZ returns
    #    0,0.
    #  - (add more interesting cases here, if you find any)
    # Some programs implement "Use $COLUMNS (if set) until SIGWINCH occurs",
    # but we don't want to register a signal handler because it is impossible
    # to do so without risking EINTR errors in Python <= 2.6.5 (see
    # <http://bugs.python.org/issue8354>).  Instead we check TIOCGWINSZ every
    # time so we can notice if the reported size has changed, which should have
    # a similar effect.

    # If BRZ_COLUMNS is set, take it, user is always right
    # Except if they specified 0 in which case, impose no limit here
    try:
        width = int(os.environ["BRZ_COLUMNS"])
    except (KeyError, ValueError):
        width = None
    if width is not None:
        if width > 0:
            return width
        else:
            return None

    isatty = getattr(sys.stdout, "isatty", None)
    if isatty is None or not isatty():
        # Don't guess, setting BRZ_COLUMNS is the recommended way to override.
        return None

    # Query the OS
    try:
        width, _height = os_size = _terminal_size()
    except OSError:
        width = os_size = None
    global _first_terminal_size, _terminal_size_state
    if _terminal_size_state == "no_data":
        _first_terminal_size = os_size
        _terminal_size_state = "unchanged"
    elif _terminal_size_state == "unchanged" and _first_terminal_size != os_size:
        _terminal_size_state = "changed"

    # If the OS claims to know how wide the terminal is, and this value has
    # ever changed, use that.
    if _terminal_size_state == "changed" and width is not None and width > 0:
        return width

    # If COLUMNS is set, use it.
    try:
        return int(os.environ["COLUMNS"])
    except (KeyError, ValueError):
        pass

    # Finally, use an unchanged size from the OS, if we have one.
    if _terminal_size_state == "unchanged" and width is not None and width > 0:
        return width

    # The width could not be determined.
    return None


_terminal_size = _osutils_rs.terminal_size
supports_executable = _osutils_rs.supports_executable
supports_hardlinks = _osutils_rs.supports_hardlinks
supports_symlinks = _osutils_rs.supports_symlinks
supports_posix_readonly = _osutils_rs.supports_posix_readonly
set_or_unset_env = _osutils_rs.set_or_unset_env
IterableFile = _osutils_rs.IterableFile


def walkdirs(top, prefix="", fsdecode=os.fsdecode):
    """Yield data about all the directories in a tree.

    This yields all the data about the contents of a directory at a time.
    After each directory has been yielded, if the caller has mutated the list
    to exclude some directories, they are then not descended into.

    The data yielded is of the form:
    ((directory-relpath, directory-path-from-top),
    [(relpath, basename, kind, lstat, path-from-top), ...]),
     - directory-relpath is the relative path of the directory being returned
       with respect to top. prefix is prepended to this.
     - directory-path-from-root is the path including top for this directory.
       It is suitable for use with os functions.
     - relpath is the relative path within the subtree being walked.
     - basename is the basename of the path
     - kind is the kind of the file now. If unknown then the file is not
       present within the tree - but it may be recorded as versioned. See
       versioned_kind.
     - lstat is the stat data *if* the file was statted.
     - planned, not implemented:
       path_from_tree_root is the path from the root of the tree.

    :param prefix: Prefix the relpaths that are yielded with 'prefix'. This
        allows one to walk a subtree but get paths that are relative to a tree
        rooted higher up.
    :return: an iterator over the dirs.
    """
    # TODO there is a bit of a smell where the results of the directory-
    # summary in this, and the path from the root, may not agree
    # depending on top and prefix - i.e. ./foo and foo as a pair leads to
    # potentially confusing output. We should make this more robust - but
    # not at a speed cost. RBC 20060731
    _directory = "directory"
    pending = [(safe_unicode(prefix), "", _directory, None, safe_unicode(top))]
    while pending:
        # 0 - relpath, 1- basename, 2- kind, 3- stat, 4-toppath
        relroot, _, _, _, top = pending.pop()
        relprefix = relroot + "/" if relroot else ""
        top + "/"

        dirblock = []
        try:
            for entry in os.scandir(top):
                name = fsdecode(entry.name)
                statvalue = entry.stat(follow_symlinks=False)
                kind = file_kind_from_stat_mode(statvalue.st_mode)
                dirblock.append((relprefix + name, name, kind, statvalue, entry.path))
        except NotADirectoryError:
            pass
        dirblock.sort()
        yield (relroot, top), dirblock

        # push the user specified dirs from dirblock
        pending.extend(d for d in reversed(dirblock) if d[2] == _directory)


class DirReader:
    """An interface for reading directories."""

    def top_prefix_to_starting_dir(self, top, prefix=""):
        """Converts top and prefix to a starting dir entry.

        :param top: A utf8 path
        :param prefix: An optional utf8 path to prefix output relative paths
            with.
        :return: A tuple starting with prefix, and ending with the native
            encoding of top.
        """
        raise NotImplementedError(self.top_prefix_to_starting_dir)

    def read_dir(self, prefix, top):
        """Read a specific dir.

        :param prefix: A utf8 prefix to be preprended to the path basenames.
        :param top: A natively encoded path to read.
        :return: A list of the directories contents. Each item contains:
            (utf8_relpath, utf8_name, kind, lstatvalue, native_abspath)
        """
        raise NotImplementedError(self.read_dir)


_selected_dir_reader = None


def _walkdirs_utf8(top, prefix="", fs_enc=None):
    """Yield data about all the directories in a tree.

    This yields the same information as walkdirs() only each entry is yielded
    in utf-8. On platforms which have a filesystem encoding of utf8 the paths
    are returned as exact byte-strings.

    :return: yields a tuple of (dir_info, [file_info])
        dir_info is (utf8_relpath, path-from-top)
        file_info is (utf8_relpath, utf8_name, kind, lstat, path-from-top)
        if top is an absolute path, path-from-top is also an absolute path.
        path-from-top might be unicode or utf8, but it is the correct path to
        pass to os functions to affect the file in question. (such as os.lstat)
    """
    global _selected_dir_reader
    if _selected_dir_reader is None:
        if fs_enc is None:
            fs_enc = sys.getfilesystemencoding()
        if fs_enc in ("utf-8", "ascii"):
            try:
                from ._readdir_pyx import UTF8DirReader

                _selected_dir_reader = UTF8DirReader()
            except ModuleNotFoundError as e:
                failed_to_load_extension(e)
                pass

    if _selected_dir_reader is None:
        # Fallback to the python version
        _selected_dir_reader = UnicodeDirReader()

    # 0 - relpath, 1- basename, 2- kind, 3- stat, 4-toppath
    # But we don't actually uses 1-3 in pending, so set them to None
    pending = [[_selected_dir_reader.top_prefix_to_starting_dir(top, prefix)]]
    read_dir = _selected_dir_reader.read_dir
    _directory = "directory"
    while pending:
        relroot, _, _, _, top = pending[-1].pop()
        if not pending[-1]:
            pending.pop()
        dirblock = sorted(read_dir(relroot, top))
        yield (relroot, top), dirblock
        # push the user specified dirs from dirblock
        next = [d for d in reversed(dirblock) if d[2] == _directory]
        if next:
            pending.append(next)


class UnicodeDirReader(DirReader):
    """A dir reader for non-utf8 file systems, which transcodes."""

    __slots__ = ["_utf8_encode"]

    def __init__(self):
        self._utf8_encode = codecs.getencoder("utf8")

    def top_prefix_to_starting_dir(self, top, prefix=""):
        """See DirReader.top_prefix_to_starting_dir."""
        return (safe_utf8(prefix), None, None, None, safe_unicode(top))

    def read_dir(self, prefix, top):
        """Read a single directory from a non-utf8 file system.

        top, and the abspath element in the output are unicode, all other paths
        are utf8. Local disk IO is done via unicode calls to listdir etc.

        This is currently the fallback code path when the filesystem encoding is
        not UTF-8. It may be better to implement an alternative so that we can
        safely handle paths that are not properly decodable in the current
        encoding.

        See DirReader.read_dir for details.
        """
        _utf8_encode = self._utf8_encode

        relprefix = prefix + b"/" if prefix else b""
        top_slash = top + "/"

        dirblock = []
        append = dirblock.append
        for entry in os.scandir(safe_utf8(top)):
            name = os.fsdecode(entry.name)
            abspath = top_slash + name
            name_utf8 = _utf8_encode(name, "surrogateescape")[0]
            statvalue = entry.stat(follow_symlinks=False)
            kind = file_kind_from_stat_mode(statvalue.st_mode)
            append((relprefix + name_utf8, name_utf8, kind, statvalue, abspath))
        return sorted(dirblock)


copy_ownership_from_path = _osutils_rs.copy_ownership_from_path
copy_tree = _osutils_rs.copy_tree
get_user_encoding = _osutils_rs.get_user_encoding


def get_diff_header_encoding():
    return get_terminal_encoding()


# We must not read/write any more than 64k at a time from/to a socket so we
# don't risk "no buffer space available" errors on some platforms.  Windows in
# particular is likely to throw WSAECONNABORTED or WSAENOBUFS if given too much
# data at once.
MAX_SOCKET_CHUNK = 64 * 1024

_end_of_stream_errors: list[int] = [errno.ECONNRESET, errno.EPIPE, errno.EINVAL]
for _eno in ["WSAECONNRESET", "WSAECONNABORTED"]:
    with contextlib.suppress(AttributeError):
        _end_of_stream_errors.append(getattr(errno, _eno))


def read_bytes_from_socket(sock, report_activity=None, max_read_size=MAX_SOCKET_CHUNK):
    """Read up to max_read_size of bytes from sock and notify of progress.

    Translates "Connection reset by peer" into file-like EOF (return an
    empty string rather than raise an error), and repeats the recv if
    interrupted by a signal.
    """
    while True:
        try:
            data = sock.recv(max_read_size)
        except OSError as e:
            eno = e.args[0]
            if eno in _end_of_stream_errors:
                # The connection was closed by the other side.  Callers expect
                # an empty string to signal end-of-stream.
                return b""
            elif eno == errno.EINTR:
                # Retry the interrupted recv.
                continue
            raise
        else:
            if report_activity is not None:
                report_activity(len(data), "read")
            return data


def recv_all(socket, count):
    """Receive an exact number of bytes.

    Regular Socket.recv() may return less than the requested number of bytes,
    depending on what's in the OS buffer.  MSG_WAITALL is not available
    on all platforms, but this should work everywhere.  This will return
    less than the requested amount if the remote end closes.

    This isn't optimized and is intended mostly for use in testing.
    """
    b = b""
    while len(b) < count:
        new = read_bytes_from_socket(socket, None, count - len(b))
        if new == b"":
            break  # eof
        b += new
    return b


def send_all(sock, bytes, report_activity=None):
    """Send all bytes on a socket.

    Breaks large blocks in smaller chunks to avoid buffering limitations on
    some platforms, and catches EINTR which may be thrown if the send is
    interrupted by a signal.

    This is preferred to socket.sendall(), because it avoids portability bugs
    and provides activity reporting.

    :param report_activity: Call this as bytes are read, see
        Transport._report_activity
    """
    sent_total = 0
    byte_count = len(bytes)
    view = memoryview(bytes)
    while sent_total < byte_count:
        try:
            sent = sock.send(view[sent_total : sent_total + MAX_SOCKET_CHUNK])
        except OSError as e:
            if e.args[0] in _end_of_stream_errors:
                raise ConnectionResetError("Error trying to write to socket", e) from e
            if e.args[0] != errno.EINTR:
                raise
        else:
            if sent == 0:
                raise ConnectionResetError(f"Sending to {sock} returned 0 bytes")
            sent_total += sent
            if report_activity is not None:
                report_activity(sent, "write")


def connect_socket(address):
    # Slight variation of the socket.create_connection() function (provided by
    # python-2.6) that can fail if getaddrinfo returns an empty list. We also
    # provide it for previous python versions. Also, we don't use the timeout
    # parameter (provided by the python implementation) so we don't implement
    # it either).
    err = socket.error("getaddrinfo returns an empty list")
    host, port = address
    for res in socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM):
        af, socktype, proto, canonname, sa = res
        sock = None
        try:
            sock = socket.socket(af, socktype, proto)
            sock.connect(sa)
            return sock

        except OSError as e:
            err = e
            # 'err' is now the most recent error
            if sock is not None:
                sock.close()
    raise err


dereference_path = _osutils_rs.dereference_path


file_kind_from_stat_mode = _osutils_rs.kind_from_mode


MIN_ABS_PATHLENGTH = _osutils_rs.MIN_ABS_PATHLENGTH


getchar = _osutils_rs.getchar


class UnicodeOrBytesToBytesWriter(codecs.StreamWriter):
    """A stream writer that doesn't decode str arguments."""

    def __init__(self, encode, stream, errors="strict"):
        codecs.StreamWriter.__init__(self, stream, errors)
        self.encode = encode

    def write(self, object):
        if isinstance(object, str):
            self.stream.write(object)
        else:
            data, _ = self.encode(object, self.errors)
            self.stream.write(data)


available_backup_name = _osutils_rs.available_backup_name


def set_fd_cloexec(fd):
    """Set a Unix file descriptor's FD_CLOEXEC flag.  Do nothing if platform
    support for this is not available.
    """
    try:
        import fcntl

        old = fcntl.fcntl(fd, fcntl.F_GETFD)
        fcntl.fcntl(fd, fcntl.F_SETFD, old | fcntl.FD_CLOEXEC)
    except (ModuleNotFoundError, AttributeError):
        # Either the fcntl module or specific constants are not present
        pass


find_executable_on_path = _osutils_rs.find_executable_on_path


is_local_pid_dead = _osutils_rs.is_local_pid_dead
_maybe_ignored = ["EAGAIN", "EINTR", "ENOTSUP", "EOPNOTSUPP", "EACCES"]
_fdatasync_ignored = [
    getattr(errno, name)
    for name in _maybe_ignored
    if getattr(errno, name, None) is not None
]


def fdatasync(fileno):
    """Flush file contents to disk if possible.

    :param fileno: Integer OS file handle.
    :raises TransportNotPossible: If flushing to disk is not possible.
    """
    fn = getattr(os, "fdatasync", getattr(os, "fsync", None))
    if fn is not None:
        try:
            fn(fileno)
        except OSError as e:
            # See bug #1075108, on some platforms fdatasync exists, but can
            # raise ENOTSUP. However, we are calling fdatasync to be helpful
            # and reduce the chance of corruption-on-powerloss situations. It
            # is not a mandatory call, so it is ok to suppress failures.
            from .trace import mutter

            mutter(f"ignoring error calling fdatasync: {e}")
            if getattr(e, "errno", None) not in _fdatasync_ignored:
                raise


ensure_empty_directory_exists = _osutils_rs.ensure_empty_directory_exists
read_mtab = _osutils_rs.read_mtab
get_fs_type = _osutils_rs.get_fs_type
perf_counter = time.perf_counter
