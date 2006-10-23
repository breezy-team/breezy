# Bazaar -- distributed version control
#
# Copyright (C) 2005 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from cStringIO import StringIO
import os
import re
import stat
from stat import (S_ISREG, S_ISDIR, S_ISLNK, ST_MODE, ST_SIZE,
                  S_ISCHR, S_ISBLK, S_ISFIFO, S_ISSOCK)
import sys
import time

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import errno
from ntpath import (abspath as _nt_abspath,
                    join as _nt_join,
                    normpath as _nt_normpath,
                    realpath as _nt_realpath,
                    splitdrive as _nt_splitdrive,
                    )
import posixpath
import sha
import shutil
from shutil import (
    rmtree,
    )
import string
import tempfile
from tempfile import (
    mkdtemp,
    )
import unicodedata

from bzrlib import (
    errors,
    )
""")

import bzrlib
from bzrlib.symbol_versioning import (
    deprecated_function,
    zero_nine,
    )
from bzrlib.trace import mutter


# On win32, O_BINARY is used to indicate the file should
# be opened in binary mode, rather than text mode.
# On other platforms, O_BINARY doesn't exist, because
# they always open in binary mode, so it is okay to
# OR with 0 on those platforms
O_BINARY = getattr(os, 'O_BINARY', 0)


def make_readonly(filename):
    """Make a filename read-only."""
    mod = os.stat(filename).st_mode
    mod = mod & 0777555
    os.chmod(filename, mod)


def make_writable(filename):
    mod = os.stat(filename).st_mode
    mod = mod | 0200
    os.chmod(filename, mod)


_QUOTE_RE = None


def quotefn(f):
    """Return a quoted filename filename

    This previously used backslash quoting, but that works poorly on
    Windows."""
    # TODO: I'm not really sure this is the best format either.x
    global _QUOTE_RE
    if _QUOTE_RE is None:
        _QUOTE_RE = re.compile(r'([^a-zA-Z0-9.,:/\\_~-])')
        
    if _QUOTE_RE.search(f):
        return '"' + f + '"'
    else:
        return f


_directory_kind = 'directory'

_formats = {
    stat.S_IFDIR:_directory_kind,
    stat.S_IFCHR:'chardev',
    stat.S_IFBLK:'block',
    stat.S_IFREG:'file',
    stat.S_IFIFO:'fifo',
    stat.S_IFLNK:'symlink',
    stat.S_IFSOCK:'socket',
}


def file_kind_from_stat_mode(stat_mode, _formats=_formats, _unknown='unknown'):
    """Generate a file kind from a stat mode. This is used in walkdirs.

    Its performance is critical: Do not mutate without careful benchmarking.
    """
    try:
        return _formats[stat_mode & 0170000]
    except KeyError:
        return _unknown


def file_kind(f, _lstat=os.lstat, _mapper=file_kind_from_stat_mode):
    try:
        return _mapper(_lstat(f).st_mode)
    except OSError, e:
        if getattr(e, 'errno', None) == errno.ENOENT:
            raise errors.NoSuchFile(f)
        raise


def get_umask():
    """Return the current umask"""
    # Assume that people aren't messing with the umask while running
    # XXX: This is not thread safe, but there is no way to get the
    #      umask without setting it
    umask = os.umask(0)
    os.umask(umask)
    return umask


def kind_marker(kind):
    if kind == 'file':
        return ''
    elif kind == _directory_kind:
        return '/'
    elif kind == 'symlink':
        return '@'
    else:
        raise errors.BzrError('invalid file kind %r' % kind)

lexists = getattr(os.path, 'lexists', None)
if lexists is None:
    def lexists(f):
        try:
            if getattr(os, 'lstat') is not None:
                os.lstat(f)
            else:
                os.stat(f)
            return True
        except OSError,e:
            if e.errno == errno.ENOENT:
                return False;
            else:
                raise errors.BzrError("lstat/stat of (%r): %r" % (f, e))


def fancy_rename(old, new, rename_func, unlink_func):
    """A fancy rename, when you don't have atomic rename.
    
    :param old: The old path, to rename from
    :param new: The new path, to rename to
    :param rename_func: The potentially non-atomic rename function
    :param unlink_func: A way to delete the target file if the full rename succeeds
    """

    # sftp rename doesn't allow overwriting, so play tricks:
    import random
    base = os.path.basename(new)
    dirname = os.path.dirname(new)
    tmp_name = u'tmp.%s.%.9f.%d.%s' % (base, time.time(), os.getpid(), rand_chars(10))
    tmp_name = pathjoin(dirname, tmp_name)

    # Rename the file out of the way, but keep track if it didn't exist
    # We don't want to grab just any exception
    # something like EACCES should prevent us from continuing
    # The downside is that the rename_func has to throw an exception
    # with an errno = ENOENT, or NoSuchFile
    file_existed = False
    try:
        rename_func(new, tmp_name)
    except (errors.NoSuchFile,), e:
        pass
    except IOError, e:
        # RBC 20060103 abstraction leakage: the paramiko SFTP clients rename
        # function raises an IOError with errno is None when a rename fails.
        # This then gets caught here.
        if e.errno not in (None, errno.ENOENT, errno.ENOTDIR):
            raise
    except Exception, e:
        if (getattr(e, 'errno', None) is None
            or e.errno not in (errno.ENOENT, errno.ENOTDIR)):
            raise
    else:
        file_existed = True

    success = False
    try:
        # This may throw an exception, in which case success will
        # not be set.
        rename_func(old, new)
        success = True
    finally:
        if file_existed:
            # If the file used to exist, rename it back into place
            # otherwise just delete it from the tmp location
            if success:
                unlink_func(tmp_name)
            else:
                rename_func(tmp_name, new)


# In Python 2.4.2 and older, os.path.abspath and os.path.realpath
# choke on a Unicode string containing a relative path if
# os.getcwd() returns a non-sys.getdefaultencoding()-encoded
# string.
_fs_enc = sys.getfilesystemencoding()
def _posix_abspath(path):
    # jam 20060426 rather than encoding to fsencoding
    # copy posixpath.abspath, but use os.getcwdu instead
    if not posixpath.isabs(path):
        path = posixpath.join(getcwd(), path)
    return posixpath.normpath(path)


def _posix_realpath(path):
    return posixpath.realpath(path.encode(_fs_enc)).decode(_fs_enc)


def _win32_fixdrive(path):
    """Force drive letters to be consistent.

    win32 is inconsistent whether it returns lower or upper case
    and even if it was consistent the user might type the other
    so we force it to uppercase
    running python.exe under cmd.exe return capital C:\\
    running win32 python inside a cygwin shell returns lowercase c:\\
    """
    drive, path = _nt_splitdrive(path)
    return drive.upper() + path


def _win32_abspath(path):
    # Real _nt_abspath doesn't have a problem with a unicode cwd
    return _win32_fixdrive(_nt_abspath(unicode(path)).replace('\\', '/'))


def _win32_realpath(path):
    # Real _nt_realpath doesn't have a problem with a unicode cwd
    return _win32_fixdrive(_nt_realpath(unicode(path)).replace('\\', '/'))


def _win32_pathjoin(*args):
    return _nt_join(*args).replace('\\', '/')


def _win32_normpath(path):
    return _win32_fixdrive(_nt_normpath(unicode(path)).replace('\\', '/'))


def _win32_getcwd():
    return _win32_fixdrive(os.getcwdu().replace('\\', '/'))


def _win32_mkdtemp(*args, **kwargs):
    return _win32_fixdrive(tempfile.mkdtemp(*args, **kwargs).replace('\\', '/'))


def _win32_rename(old, new):
    """We expect to be able to atomically replace 'new' with old.

    On win32, if new exists, it must be moved out of the way first,
    and then deleted. 
    """
    try:
        fancy_rename(old, new, rename_func=os.rename, unlink_func=os.unlink)
    except OSError, e:
        if e.errno in (errno.EPERM, errno.EACCES, errno.EBUSY, errno.EINVAL):
            # If we try to rename a non-existant file onto cwd, we get 
            # EPERM or EACCES instead of ENOENT, this will raise ENOENT 
            # if the old path doesn't exist, sometimes we get EACCES
            # On Linux, we seem to get EBUSY, on Mac we get EINVAL
            os.lstat(old)
        raise


def _mac_getcwd():
    return unicodedata.normalize('NFKC', os.getcwdu())


# Default is to just use the python builtins, but these can be rebound on
# particular platforms.
abspath = _posix_abspath
realpath = _posix_realpath
pathjoin = os.path.join
normpath = os.path.normpath
getcwd = os.getcwdu
rename = os.rename
dirname = os.path.dirname
basename = os.path.basename
# These were already imported into local scope
# mkdtemp = tempfile.mkdtemp
# rmtree = shutil.rmtree

MIN_ABS_PATHLENGTH = 1


if sys.platform == 'win32':
    abspath = _win32_abspath
    realpath = _win32_realpath
    pathjoin = _win32_pathjoin
    normpath = _win32_normpath
    getcwd = _win32_getcwd
    mkdtemp = _win32_mkdtemp
    rename = _win32_rename

    MIN_ABS_PATHLENGTH = 3

    def _win32_delete_readonly(function, path, excinfo):
        """Error handler for shutil.rmtree function [for win32]
        Helps to remove files and dirs marked as read-only.
        """
        type_, value = excinfo[:2]
        if function in (os.remove, os.rmdir) \
            and type_ == OSError \
            and value.errno == errno.EACCES:
            make_writable(path)
            function(path)
        else:
            raise

    def rmtree(path, ignore_errors=False, onerror=_win32_delete_readonly):
        """Replacer for shutil.rmtree: could remove readonly dirs/files"""
        return shutil.rmtree(path, ignore_errors, onerror)
elif sys.platform == 'darwin':
    getcwd = _mac_getcwd


def get_terminal_encoding():
    """Find the best encoding for printing to the screen.

    This attempts to check both sys.stdout and sys.stdin to see
    what encoding they are in, and if that fails it falls back to
    bzrlib.user_encoding.
    The problem is that on Windows, locale.getpreferredencoding()
    is not the same encoding as that used by the console:
    http://mail.python.org/pipermail/python-list/2003-May/162357.html

    On my standard US Windows XP, the preferred encoding is
    cp1252, but the console is cp437
    """
    output_encoding = getattr(sys.stdout, 'encoding', None)
    if not output_encoding:
        input_encoding = getattr(sys.stdin, 'encoding', None)
        if not input_encoding:
            output_encoding = bzrlib.user_encoding
            mutter('encoding stdout as bzrlib.user_encoding %r', output_encoding)
        else:
            output_encoding = input_encoding
            mutter('encoding stdout as sys.stdin encoding %r', output_encoding)
    else:
        mutter('encoding stdout as sys.stdout encoding %r', output_encoding)
    return output_encoding


def normalizepath(f):
    if getattr(os.path, 'realpath', None) is not None:
        F = realpath
    else:
        F = abspath
    [p,e] = os.path.split(f)
    if e == "" or e == "." or e == "..":
        return F(f)
    else:
        return pathjoin(F(p), e)


def backup_file(fn):
    """Copy a file to a backup.

    Backups are named in GNU-style, with a ~ suffix.

    If the file is already a backup, it's not copied.
    """
    if fn[-1] == '~':
        return
    bfn = fn + '~'

    if has_symlinks() and os.path.islink(fn):
        target = os.readlink(fn)
        os.symlink(target, bfn)
        return
    inf = file(fn, 'rb')
    try:
        content = inf.read()
    finally:
        inf.close()
    
    outf = file(bfn, 'wb')
    try:
        outf.write(content)
    finally:
        outf.close()


def isdir(f):
    """True if f is an accessible directory."""
    try:
        return S_ISDIR(os.lstat(f)[ST_MODE])
    except OSError:
        return False


def isfile(f):
    """True if f is a regular file."""
    try:
        return S_ISREG(os.lstat(f)[ST_MODE])
    except OSError:
        return False

def islink(f):
    """True if f is a symlink."""
    try:
        return S_ISLNK(os.lstat(f)[ST_MODE])
    except OSError:
        return False

def is_inside(dir, fname):
    """True if fname is inside dir.
    
    The parameters should typically be passed to osutils.normpath first, so
    that . and .. and repeated slashes are eliminated, and the separators
    are canonical for the platform.
    
    The empty string as a dir name is taken as top-of-tree and matches 
    everything.
    """
    # XXX: Most callers of this can actually do something smarter by 
    # looking at the inventory
    if dir == fname:
        return True
    
    if dir == '':
        return True

    if dir[-1] != '/':
        dir += '/'

    return fname.startswith(dir)


def is_inside_any(dir_list, fname):
    """True if fname is inside any of given dirs."""
    for dirname in dir_list:
        if is_inside(dirname, fname):
            return True
    else:
        return False


def is_inside_or_parent_of_any(dir_list, fname):
    """True if fname is a child or a parent of any of the given files."""
    for dirname in dir_list:
        if is_inside(dirname, fname) or is_inside(fname, dirname):
            return True
    else:
        return False


def pumpfile(fromfile, tofile):
    """Copy contents of one file to another."""
    BUFSIZE = 32768
    while True:
        b = fromfile.read(BUFSIZE)
        if not b:
            break
        tofile.write(b)


def file_iterator(input_file, readsize=32768):
    while True:
        b = input_file.read(readsize)
        if len(b) == 0:
            break
        yield b


def sha_file(f):
    if getattr(f, 'tell', None) is not None:
        assert f.tell() == 0
    s = sha.new()
    BUFSIZE = 128<<10
    while True:
        b = f.read(BUFSIZE)
        if not b:
            break
        s.update(b)
    return s.hexdigest()



def sha_strings(strings):
    """Return the sha-1 of concatenation of strings"""
    s = sha.new()
    map(s.update, strings)
    return s.hexdigest()


def sha_string(f):
    s = sha.new()
    s.update(f)
    return s.hexdigest()


def fingerprint_file(f):
    s = sha.new()
    b = f.read()
    s.update(b)
    size = len(b)
    return {'size': size,
            'sha1': s.hexdigest()}


def compare_files(a, b):
    """Returns true if equal in contents"""
    BUFSIZE = 4096
    while True:
        ai = a.read(BUFSIZE)
        bi = b.read(BUFSIZE)
        if ai != bi:
            return False
        if ai == '':
            return True


def local_time_offset(t=None):
    """Return offset of local zone from GMT, either at present or at time t."""
    # python2.3 localtime() can't take None
    if t is None:
        t = time.time()
        
    if time.localtime(t).tm_isdst and time.daylight:
        return -time.altzone
    else:
        return -time.timezone

    
def format_date(t, offset=0, timezone='original', date_fmt=None, 
                show_offset=True):
    ## TODO: Perhaps a global option to use either universal or local time?
    ## Or perhaps just let people set $TZ?
    assert isinstance(t, float)
    
    if timezone == 'utc':
        tt = time.gmtime(t)
        offset = 0
    elif timezone == 'original':
        if offset is None:
            offset = 0
        tt = time.gmtime(t + offset)
    elif timezone == 'local':
        tt = time.localtime(t)
        offset = local_time_offset(t)
    else:
        raise errors.BzrError("unsupported timezone format %r" % timezone,
                              ['options are "utc", "original", "local"'])
    if date_fmt is None:
        date_fmt = "%a %Y-%m-%d %H:%M:%S"
    if show_offset:
        offset_str = ' %+03d%02d' % (offset / 3600, (offset / 60) % 60)
    else:
        offset_str = ''
    return (time.strftime(date_fmt, tt) +  offset_str)


def compact_date(when):
    return time.strftime('%Y%m%d%H%M%S', time.gmtime(when))
    

def format_delta(delta):
    """Get a nice looking string for a time delta.

    :param delta: The time difference in seconds, can be positive or negative.
        positive indicates time in the past, negative indicates time in the
        future. (usually time.time() - stored_time)
    :return: String formatted to show approximate resolution
    """
    delta = int(delta)
    if delta >= 0:
        direction = 'ago'
    else:
        direction = 'in the future'
        delta = -delta

    seconds = delta
    if seconds < 90: # print seconds up to 90 seconds
        if seconds == 1:
            return '%d second %s' % (seconds, direction,)
        else:
            return '%d seconds %s' % (seconds, direction)

    minutes = int(seconds / 60)
    seconds -= 60 * minutes
    if seconds == 1:
        plural_seconds = ''
    else:
        plural_seconds = 's'
    if minutes < 90: # print minutes, seconds up to 90 minutes
        if minutes == 1:
            return '%d minute, %d second%s %s' % (
                    minutes, seconds, plural_seconds, direction)
        else:
            return '%d minutes, %d second%s %s' % (
                    minutes, seconds, plural_seconds, direction)

    hours = int(minutes / 60)
    minutes -= 60 * hours
    if minutes == 1:
        plural_minutes = ''
    else:
        plural_minutes = 's'

    if hours == 1:
        return '%d hour, %d minute%s %s' % (hours, minutes,
                                            plural_minutes, direction)
    return '%d hours, %d minute%s %s' % (hours, minutes,
                                         plural_minutes, direction)

def filesize(f):
    """Return size of given open file."""
    return os.fstat(f.fileno())[ST_SIZE]


# Define rand_bytes based on platform.
try:
    # Python 2.4 and later have os.urandom,
    # but it doesn't work on some arches
    os.urandom(1)
    rand_bytes = os.urandom
except (NotImplementedError, AttributeError):
    # If python doesn't have os.urandom, or it doesn't work,
    # then try to first pull random data from /dev/urandom
    try:
        rand_bytes = file('/dev/urandom', 'rb').read
    # Otherwise, use this hack as a last resort
    except (IOError, OSError):
        # not well seeded, but better than nothing
        def rand_bytes(n):
            import random
            s = ''
            while n:
                s += chr(random.randint(0, 255))
                n -= 1
            return s


ALNUM = '0123456789abcdefghijklmnopqrstuvwxyz'
def rand_chars(num):
    """Return a random string of num alphanumeric characters
    
    The result only contains lowercase chars because it may be used on 
    case-insensitive filesystems.
    """
    s = ''
    for raw_byte in rand_bytes(num):
        s += ALNUM[ord(raw_byte) % 36]
    return s


## TODO: We could later have path objects that remember their list
## decomposition (might be too tricksy though.)

def splitpath(p):
    """Turn string into list of parts."""
    assert isinstance(p, basestring)

    # split on either delimiter because people might use either on
    # Windows
    ps = re.split(r'[\\/]', p)

    rps = []
    for f in ps:
        if f == '..':
            raise errors.BzrError("sorry, %r not allowed in path" % f)
        elif (f == '.') or (f == ''):
            pass
        else:
            rps.append(f)
    return rps

def joinpath(p):
    assert isinstance(p, list)
    for f in p:
        if (f == '..') or (f is None) or (f == ''):
            raise errors.BzrError("sorry, %r not allowed in path" % f)
    return pathjoin(*p)


@deprecated_function(zero_nine)
def appendpath(p1, p2):
    if p1 == '':
        return p2
    else:
        return pathjoin(p1, p2)
    

def split_lines(s):
    """Split s into lines, but without removing the newline characters."""
    lines = s.split('\n')
    result = [line + '\n' for line in lines[:-1]]
    if lines[-1]:
        result.append(lines[-1])
    return result


def hardlinks_good():
    return sys.platform not in ('win32', 'cygwin', 'darwin')


def link_or_copy(src, dest):
    """Hardlink a file, or copy it if it can't be hardlinked."""
    if not hardlinks_good():
        shutil.copyfile(src, dest)
        return
    try:
        os.link(src, dest)
    except (OSError, IOError), e:
        if e.errno != errno.EXDEV:
            raise
        shutil.copyfile(src, dest)

def delete_any(full_path):
    """Delete a file or directory."""
    try:
        os.unlink(full_path)
    except OSError, e:
    # We may be renaming a dangling inventory id
        if e.errno not in (errno.EISDIR, errno.EACCES, errno.EPERM):
            raise
        os.rmdir(full_path)


def has_symlinks():
    if getattr(os, 'symlink', None) is not None:
        return True
    else:
        return False
        

def contains_whitespace(s):
    """True if there are any whitespace characters in s."""
    for ch in string.whitespace:
        if ch in s:
            return True
    else:
        return False


def contains_linebreaks(s):
    """True if there is any vertical whitespace in s."""
    for ch in '\f\n\r':
        if ch in s:
            return True
    else:
        return False


def relpath(base, path):
    """Return path relative to base, or raise exception.

    The path may be either an absolute path or a path relative to the
    current working directory.

    os.path.commonprefix (python2.4) has a bad bug that it works just
    on string prefixes, assuming that '/u' is a prefix of '/u2'.  This
    avoids that problem.
    """

    assert len(base) >= MIN_ABS_PATHLENGTH, ('Length of base must be equal or'
        ' exceed the platform minimum length (which is %d)' % 
        MIN_ABS_PATHLENGTH)

    rp = abspath(path)

    s = []
    head = rp
    while len(head) >= len(base):
        if head == base:
            break
        head, tail = os.path.split(head)
        if tail:
            s.insert(0, tail)
    else:
        raise errors.PathNotChild(rp, base)

    if s:
        return pathjoin(*s)
    else:
        return ''


def safe_unicode(unicode_or_utf8_string):
    """Coerce unicode_or_utf8_string into unicode.

    If it is unicode, it is returned.
    Otherwise it is decoded from utf-8. If a decoding error
    occurs, it is wrapped as a If the decoding fails, the exception is wrapped 
    as a BzrBadParameter exception.
    """
    if isinstance(unicode_or_utf8_string, unicode):
        return unicode_or_utf8_string
    try:
        return unicode_or_utf8_string.decode('utf8')
    except UnicodeDecodeError:
        raise errors.BzrBadParameterNotUnicode(unicode_or_utf8_string)


_platform_normalizes_filenames = False
if sys.platform == 'darwin':
    _platform_normalizes_filenames = True


def normalizes_filenames():
    """Return True if this platform normalizes unicode filenames.

    Mac OSX does, Windows/Linux do not.
    """
    return _platform_normalizes_filenames


def _accessible_normalized_filename(path):
    """Get the unicode normalized path, and if you can access the file.

    On platforms where the system normalizes filenames (Mac OSX),
    you can access a file by any path which will normalize correctly.
    On platforms where the system does not normalize filenames 
    (Windows, Linux), you have to access a file by its exact path.

    Internally, bzr only supports NFC/NFKC normalization, since that is 
    the standard for XML documents.

    So return the normalized path, and a flag indicating if the file
    can be accessed by that path.
    """

    return unicodedata.normalize('NFKC', unicode(path)), True


def _inaccessible_normalized_filename(path):
    __doc__ = _accessible_normalized_filename.__doc__

    normalized = unicodedata.normalize('NFKC', unicode(path))
    return normalized, normalized == path


if _platform_normalizes_filenames:
    normalized_filename = _accessible_normalized_filename
else:
    normalized_filename = _inaccessible_normalized_filename


def terminal_width():
    """Return estimated terminal width."""
    if sys.platform == 'win32':
        import bzrlib.win32console
        return bzrlib.win32console.get_console_size()[0]
    width = 0
    try:
        import struct, fcntl, termios
        s = struct.pack('HHHH', 0, 0, 0, 0)
        x = fcntl.ioctl(1, termios.TIOCGWINSZ, s)
        width = struct.unpack('HHHH', x)[1]
    except IOError:
        pass
    if width <= 0:
        try:
            width = int(os.environ['COLUMNS'])
        except:
            pass
    if width <= 0:
        width = 80

    return width


def supports_executable():
    return sys.platform != "win32"


def set_or_unset_env(env_variable, value):
    """Modify the environment, setting or removing the env_variable.

    :param env_variable: The environment variable in question
    :param value: The value to set the environment to. If None, then
        the variable will be removed.
    :return: The original value of the environment variable.
    """
    orig_val = os.environ.get(env_variable)
    if value is None:
        if orig_val is not None:
            del os.environ[env_variable]
    else:
        if isinstance(value, unicode):
            value = value.encode(bzrlib.user_encoding)
        os.environ[env_variable] = value
    return orig_val


_validWin32PathRE = re.compile(r'^([A-Za-z]:[/\\])?[^:<>*"?\|]*$')


def check_legal_path(path):
    """Check whether the supplied path is legal.  
    This is only required on Windows, so we don't test on other platforms
    right now.
    """
    if sys.platform != "win32":
        return
    if _validWin32PathRE.match(path) is None:
        raise errors.IllegalPath(path)


def walkdirs(top, prefix=""):
    """Yield data about all the directories in a tree.
    
    This yields all the data about the contents of a directory at a time.
    After each directory has been yielded, if the caller has mutated the list
    to exclude some directories, they are then not descended into.
    
    The data yielded is of the form:
    ((directory-relpath, directory-path-from-top),
    [(relpath, basename, kind, lstat), ...]),
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
    #TODO there is a bit of a smell where the results of the directory-
    # summary in this, and the path from the root, may not agree 
    # depending on top and prefix - i.e. ./foo and foo as a pair leads to
    # potentially confusing output. We should make this more robust - but
    # not at a speed cost. RBC 20060731
    lstat = os.lstat
    pending = []
    _directory = _directory_kind
    _listdir = os.listdir
    pending = [(prefix, "", _directory, None, top)]
    while pending:
        dirblock = []
        currentdir = pending.pop()
        # 0 - relpath, 1- basename, 2- kind, 3- stat, 4-toppath
        top = currentdir[4]
        if currentdir[0]:
            relroot = currentdir[0] + '/'
        else:
            relroot = ""
        for name in sorted(_listdir(top)):
            abspath = top + '/' + name
            statvalue = lstat(abspath)
            dirblock.append((relroot + name, name,
                file_kind_from_stat_mode(statvalue.st_mode),
                statvalue, abspath))
        yield (currentdir[0], top), dirblock
        # push the user specified dirs from dirblock
        for dir in reversed(dirblock):
            if dir[2] == _directory:
                pending.append(dir)


def copy_tree(from_path, to_path, handlers={}):
    """Copy all of the entries in from_path into to_path.

    :param from_path: The base directory to copy. 
    :param to_path: The target directory. If it does not exist, it will
        be created.
    :param handlers: A dictionary of functions, which takes a source and
        destinations for files, directories, etc.
        It is keyed on the file kind, such as 'directory', 'symlink', or 'file'
        'file', 'directory', and 'symlink' should always exist.
        If they are missing, they will be replaced with 'os.mkdir()',
        'os.readlink() + os.symlink()', and 'shutil.copy2()', respectively.
    """
    # Now, just copy the existing cached tree to the new location
    # We use a cheap trick here.
    # Absolute paths are prefixed with the first parameter
    # relative paths are prefixed with the second.
    # So we can get both the source and target returned
    # without any extra work.

    def copy_dir(source, dest):
        os.mkdir(dest)

    def copy_link(source, dest):
        """Copy the contents of a symlink"""
        link_to = os.readlink(source)
        os.symlink(link_to, dest)

    real_handlers = {'file':shutil.copy2,
                     'symlink':copy_link,
                     'directory':copy_dir,
                    }
    real_handlers.update(handlers)

    if not os.path.exists(to_path):
        real_handlers['directory'](from_path, to_path)

    for dir_info, entries in walkdirs(from_path, prefix=to_path):
        for relpath, name, kind, st, abspath in entries:
            real_handlers[kind](abspath, relpath)


def path_prefix_key(path):
    """Generate a prefix-order path key for path.

    This can be used to sort paths in the same way that walkdirs does.
    """
    return (dirname(path) , path)


def compare_paths_prefix_order(path_a, path_b):
    """Compare path_a and path_b to generate the same order walkdirs uses."""
    key_a = path_prefix_key(path_a)
    key_b = path_prefix_key(path_b)
    return cmp(key_a, key_b)


_cached_user_encoding = None


def get_user_encoding():
    """Find out what the preferred user encoding is.

    This is generally the encoding that is used for command line parameters
    and file contents. This may be different from the terminal encoding
    or the filesystem encoding.

    :return: A string defining the preferred user encoding
    """
    global _cached_user_encoding
    if _cached_user_encoding is not None:
        return _cached_user_encoding

    if sys.platform == 'darwin':
        # work around egregious python 2.4 bug
        sys.platform = 'posix'
        try:
            import locale
        finally:
            sys.platform = 'darwin'
    else:
        import locale

    try:
        _cached_user_encoding = locale.getpreferredencoding()
    except locale.Error, e:
        sys.stderr.write('bzr: warning: %s\n'
                         '  Could not determine what text encoding to use.\n'
                         '  This error usually means your Python interpreter\n'
                         '  doesn\'t support the locale set by $LANG (%s)\n'
                         "  Continuing with ascii encoding.\n"
                         % (e, os.environ.get('LANG')))

    if _cached_user_encoding is None:
        _cached_user_encoding = 'ascii'
    return _cached_user_encoding


def recv_all(socket, bytes):
    """Receive an exact number of bytes.

    Regular Socket.recv() may return less than the requested number of bytes,
    dependning on what's in the OS buffer.  MSG_WAITALL is not available
    on all platforms, but this should work everywhere.  This will return
    less than the requested amount if the remote end closes.

    This isn't optimized and is intended mostly for use in testing.
    """
    b = ''
    while len(b) < bytes:
        new = socket.recv(bytes - len(b))
        if new == '':
            break # eof
        b += new
    return b

