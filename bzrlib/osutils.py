# Bazaar-NG -- distributed version control

# Copyright (C) 2005 by Canonical Ltd

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

import os, types, re, time, errno
from stat import S_ISREG, S_ISDIR, S_ISLNK, ST_MODE, ST_SIZE

from errors import bailout, BzrError
from trace import mutter
import bzrlib

def make_readonly(filename):
    """Make a filename read-only."""
    # TODO: probably needs to be fixed for windows
    mod = os.stat(filename).st_mode
    mod = mod & 0777555
    os.chmod(filename, mod)


def make_writable(filename):
    mod = os.stat(filename).st_mode
    mod = mod | 0200
    os.chmod(filename, mod)


_QUOTE_RE = re.compile(r'([^a-zA-Z0-9.,:/_~-])')
def quotefn(f):
    """Return shell-quoted filename"""
    ## We could be a bit more terse by using double-quotes etc
    f = _QUOTE_RE.sub(r'\\\1', f)
    if f[0] == '~':
        f[0:1] = r'\~' 
    return f


def file_kind(f):
    mode = os.lstat(f)[ST_MODE]
    if S_ISREG(mode):
        return 'file'
    elif S_ISDIR(mode):
        return 'directory'
    elif S_ISLNK(mode):
        return 'symlink'
    else:
        raise BzrError("can't handle file kind with mode %o of %r" % (mode, f)) 



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


def pumpfile(fromfile, tofile):
    """Copy contents of one file to another."""
    tofile.write(fromfile.read())


def uuid():
    """Return a new UUID"""
    
    ## XXX: Could alternatively read /proc/sys/kernel/random/uuid on
    ## Linux, but we need something portable for other systems;
    ## preferably an implementation in Python.
    try:
        return chomp(file('/proc/sys/kernel/random/uuid').readline())
    except IOError:
        return chomp(os.popen('uuidgen').readline())


def chomp(s):
    if s and (s[-1] == '\n'):
        return s[:-1]
    else:
        return s


def sha_file(f):
    import sha
    ## TODO: Maybe read in chunks to handle big files
    if hasattr(f, 'tell'):
        assert f.tell() == 0
    s = sha.new()
    s.update(f.read())
    return s.hexdigest()


def sha_string(f):
    import sha
    s = sha.new()
    s.update(f)
    return s.hexdigest()



def fingerprint_file(f):
    import sha
    s = sha.new()
    b = f.read()
    s.update(b)
    size = len(b)
    return {'size': size,
            'sha1': s.hexdigest()}


def _auto_user_id():
    """Calculate automatic user identification.

    Returns (realname, email).

    Only used when none is set in the environment or the id file.

    This previously used the FQDN as the default domain, but that can
    be very slow on machines where DNS is broken.  So now we simply
    use the hostname.
    """
    import socket

    # XXX: Any good way to get real user name on win32?

    try:
        import pwd
        uid = os.getuid()
        w = pwd.getpwuid(uid)
        gecos = w.pw_gecos.decode(bzrlib.user_encoding)
        username = w.pw_name.decode(bzrlib.user_encoding)
        comma = gecos.find(',')
        if comma == -1:
            realname = gecos
        else:
            realname = gecos[:comma]
        if not realname:
            realname = username

    except ImportError:
        import getpass
        realname = username = getpass.getuser().decode(bzrlib.user_encoding)

    return realname, (username + '@' + socket.gethostname())


def _get_user_id():
    v = os.environ.get('BZREMAIL')
    if v:
        return v.decode(bzrlib.user_encoding)
    
    try:
        return (open(os.path.expanduser("~/.bzr.email"))
                .read()
                .decode(bzrlib.user_encoding)
                .rstrip("\r\n"))
    except IOError, e:
        if e.errno != errno.ENOENT:
            raise e

    v = os.environ.get('EMAIL')
    if v:
        return v.decode(bzrlib.user_encoding)
    else:    
        return None


def username():
    """Return email-style username.

    Something similar to 'Martin Pool <mbp@sourcefrog.net>'

    TODO: Check it's reasonably well-formed.

    TODO: Allow taking it from a dotfile to help people on windows
           who can't easily set variables.
    """
    v = _get_user_id()
    if v:
        return v
    
    name, email = _auto_user_id()
    if name:
        return '%s <%s>' % (name, email)
    else:
        return email


_EMAIL_RE = re.compile(r'[\w+.-]+@[\w+.-]+')
def user_email():
    """Return just the email component of a username."""
    e = _get_user_id()
    if e:
        m = _EMAIL_RE.search(e)
        if not m:
            bailout("%r doesn't seem to contain a reasonable email address" % e)
        return m.group(0)

    return _auto_user_id()[1]
    


def compare_files(a, b):
    """Returns true if equal in contents"""
    # TODO: don't read the whole thing in one go.
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

    
def format_date(t, offset=0, timezone='original'):
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
        bailout("unsupported timezone format %r",
                ['options are "utc", "original", "local"'])

    return (time.strftime("%a %Y-%m-%d %H:%M:%S", tt)
            + ' %+03d%02d' % (offset / 3600, (offset / 60) % 60))


def compact_date(when):
    return time.strftime('%Y%m%d%H%M%S', time.gmtime(when))
    


def filesize(f):
    """Return size of given open file."""
    return os.fstat(f.fileno())[ST_SIZE]


if hasattr(os, 'urandom'): # python 2.4 and later
    rand_bytes = os.urandom
else:
    # FIXME: No good on non-Linux
    _rand_file = file('/dev/urandom', 'rb')
    rand_bytes = _rand_file.read


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
    BzrError: ("sorry, '..' not allowed in path", [])
    """
    assert isinstance(p, types.StringTypes)
    ps = [f for f in p.split('/') if (f != '.' and f != '')]
    for f in ps:
        if f == '..':
            bailout("sorry, %r not allowed in path" % f)
    return ps

def joinpath(p):
    assert isinstance(p, list)
    for f in p:
        if (f == '..') or (f == None) or (f == ''):
            bailout("sorry, %r not allowed in path" % f)
    return '/'.join(p)


def appendpath(p1, p2):
    if p1 == '':
        return p2
    else:
        return p1 + '/' + p2
    

def extern_command(cmd, ignore_errors = False):
    mutter('external command: %s' % `cmd`)
    if os.system(cmd):
        if not ignore_errors:
            bailout('command failed')

