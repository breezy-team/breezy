# Bazaar-NG -- distributed version control
#
# Copyright (C) 2005 by Canonical Ltd
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

from shutil import copyfile
from stat import (S_ISREG, S_ISDIR, S_ISLNK, ST_MODE, ST_SIZE,
                  S_ISCHR, S_ISBLK, S_ISFIFO, S_ISSOCK)
from cStringIO import StringIO
import errno
import os
import re
import sha
import string
import sys
import time
import types
import tempfile

import bzrlib
from bzrlib.errors import (BzrError,
                           BzrBadParameterNotUnicode,
                           NoSuchFile,
                           PathNotChild,
                           IllegalPath,
                           )
from bzrlib.trace import mutter


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
    if _QUOTE_RE == None:
        _QUOTE_RE = re.compile(r'([^a-zA-Z0-9.,:/\\_~-])')
        
    if _QUOTE_RE.search(f):
        return '"' + f + '"'
    else:
        return f


def file_kind(f):
    mode = os.lstat(f)[ST_MODE]
    if S_ISREG(mode):
        return 'file'
    elif S_ISDIR(mode):
        return 'directory'
    elif S_ISLNK(mode):
        return 'symlink'
    elif S_ISCHR(mode):
        return 'chardev'
    elif S_ISBLK(mode):
        return 'block'
    elif S_ISFIFO(mode):
        return 'fifo'
    elif S_ISSOCK(mode):
        return 'socket'
    else:
        return 'unknown'


def kind_marker(kind):
    if kind == 'file':
        return ''
    elif kind == 'directory':
        return '/'
    elif kind == 'symlink':
        return '@'
    else:
        raise BzrError('invalid file kind %r' % kind)

def lexists(f):
    if hasattr(os.path, 'lexists'):
        return os.path.lexists(f)
    try:
        if hasattr(os, 'lstat'):
            os.lstat(f)
        else:
            os.stat(f)
        return True
    except OSError,e:
        if e.errno == errno.ENOENT:
            return False;
        else:
            raise BzrError("lstat/stat of (%r): %r" % (f, e))

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
    except (NoSuchFile,), e:
        pass
    except IOError, e:
        # RBC 20060103 abstraction leakage: the paramiko SFTP clients rename
        # function raises an IOError with errno == None when a rename fails.
        # This then gets caught here.
        if e.errno not in (None, errno.ENOENT, errno.ENOTDIR):
            raise
    except Exception, e:
        if (not hasattr(e, 'errno') 
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

# Default is to just use the python builtins
abspath = os.path.abspath
realpath = os.path.realpath
pathjoin = os.path.join
normpath = os.path.normpath
getcwd = os.getcwdu
mkdtemp = tempfile.mkdtemp
rename = os.rename
dirname = os.path.dirname
basename = os.path.basename

MIN_ABS_PATHLENGTH = 1

if os.name == "posix":
    # In Python 2.4.2 and older, os.path.abspath and os.path.realpath
    # choke on a Unicode string containing a relative path if
    # os.getcwd() returns a non-sys.getdefaultencoding()-encoded
    # string.
    _fs_enc = sys.getfilesystemencoding()
    def abspath(path):
        return os.path.abspath(path.encode(_fs_enc)).decode(_fs_enc)

    def realpath(path):
        return os.path.realpath(path.encode(_fs_enc)).decode(_fs_enc)

if sys.platform == 'win32':
    # We need to use the Unicode-aware os.path.abspath and
    # os.path.realpath on Windows systems.
    def abspath(path):
        return os.path.abspath(path).replace('\\', '/')

    def realpath(path):
        return os.path.realpath(path).replace('\\', '/')

    def pathjoin(*args):
        return os.path.join(*args).replace('\\', '/')

    def normpath(path):
        return os.path.normpath(path).replace('\\', '/')

    def getcwd():
        return os.getcwdu().replace('\\', '/')

    def mkdtemp(*args, **kwargs):
        return tempfile.mkdtemp(*args, **kwargs).replace('\\', '/')

    def rename(old, new):
        fancy_rename(old, new, rename_func=os.rename, unlink_func=os.unlink)

    MIN_ABS_PATHLENGTH = 3

def normalizepath(f):
    if hasattr(os.path, 'realpath'):
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
    
    >>> is_inside('src', pathjoin('src', 'foo.c'))
    True
    >>> is_inside('src', 'srccontrol')
    False
    >>> is_inside('src', pathjoin('src', 'a', 'a', 'a', 'foo.c'))
    True
    >>> is_inside('foo.c', 'foo.c')
    True
    >>> is_inside('foo.c', '')
    False
    >>> is_inside('', 'foo.c')
    True
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
    if hasattr(f, 'tell'):
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
    if t == None:
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
        if offset == None:
            offset = 0
        tt = time.gmtime(t + offset)
    elif timezone == 'local':
        tt = time.localtime(t)
        offset = local_time_offset(t)
    else:
        raise BzrError("unsupported timezone format %r" % timezone,
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
    if os.path.exists("/dev/urandom"):
        rand_bytes = file('/dev/urandom', 'rb').read
    # Otherwise, use this hack as a last resort
    else:
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
    """Turn string into list of parts.

    >>> splitpath('a')
    ['a']
    >>> splitpath('a/b')
    ['a', 'b']
    >>> splitpath('a/./b')
    ['a', 'b']
    >>> splitpath('a/.b')
    ['a', '.b']
    >>> splitpath('a/../b')
    Traceback (most recent call last):
    ...
    BzrError: sorry, '..' not allowed in path
    """
    assert isinstance(p, types.StringTypes)

    # split on either delimiter because people might use either on
    # Windows
    ps = re.split(r'[\\/]', p)

    rps = []
    for f in ps:
        if f == '..':
            raise BzrError("sorry, %r not allowed in path" % f)
        elif (f == '.') or (f == ''):
            pass
        else:
            rps.append(f)
    return rps

def joinpath(p):
    assert isinstance(p, list)
    for f in p:
        if (f == '..') or (f == None) or (f == ''):
            raise BzrError("sorry, %r not allowed in path" % f)
    return pathjoin(*p)


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
        copyfile(src, dest)
        return
    try:
        os.link(src, dest)
    except (OSError, IOError), e:
        if e.errno != errno.EXDEV:
            raise
        copyfile(src, dest)

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
    if hasattr(os, 'symlink'):
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
        # XXX This should raise a NotChildPath exception, as its not tied
        # to branch anymore.
        raise PathNotChild(rp, base)

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
        raise BzrBadParameterNotUnicode(unicode_or_utf8_string)


def terminal_width():
    """Return estimated terminal width."""

    # TODO: Do something smart on Windows?

    # TODO: Is there anything that gets a better update when the window
    # is resized while the program is running? We could use the Python termcap
    # library.
    try:
        return int(os.environ['COLUMNS'])
    except (IndexError, KeyError, ValueError):
        return 80

def supports_executable():
    return sys.platform != "win32"


def strip_trailing_slash(path):
    """Strip trailing slash, except for root paths.
    The definition of 'root path' is platform-dependent.
    """
    if len(path) != MIN_ABS_PATHLENGTH and path[-1] == '/':
        return path[:-1]
    else:
        return path


_validWin32PathRE = re.compile(r'^([A-Za-z]:[/\\])?[^:<>*"?\|]*$')


def check_legal_path(path):
    """Check whether the supplied path is legal.  
    This is only required on Windows, so we don't test on other platforms
    right now.
    """
    if sys.platform != "win32":
        return
    if _validWin32PathRE.match(path) is None:
        raise IllegalPath(path)
