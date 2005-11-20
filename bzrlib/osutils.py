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

import bzrlib
from bzrlib.errors import BzrError, NotBranchError
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

def normalizepath(f):
    if hasattr(os.path, 'realpath'):
        F = os.path.realpath
    else:
        F = os.path.abspath
    [p,e] = os.path.split(f)
    if e == "" or e == "." or e == "..":
        return F(f)
    else:
        return os.path.join(F(p), e)

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
else:
    # We need to use the Unicode-aware os.path.abspath and
    # os.path.realpath on Windows systems.
    abspath = os.path.abspath
    realpath = os.path.realpath

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

if os.name == 'nt':
    import shutil
    rename = shutil.move
else:
    rename = os.rename


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
    
    The parameters should typically be passed to os.path.normpath first, so
    that . and .. and repeated slashes are eliminated, and the separators
    are canonical for the platform.
    
    The empty string as a dir name is taken as top-of-tree and matches 
    everything.
    
    >>> is_inside('src', os.path.join('src', 'foo.c'))
    True
    >>> is_inside('src', 'srccontrol')
    False
    >>> is_inside('src', os.path.join('src', 'a', 'a', 'a', 'foo.c'))
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

    if dir[-1] != os.sep:
        dir += os.sep

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
    return os.path.join(*p)


def appendpath(p1, p2):
    if p1 == '':
        return p2
    else:
        return os.path.join(p1, p2)
    

def split_lines(s):
    """Split s into lines, but without removing the newline characters."""
    return StringIO(s).readlines()


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
    avoids that problem."""
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
        raise NotBranchError("path %r is not within branch %r" % (rp, base))

    return os.sep.join(s)
