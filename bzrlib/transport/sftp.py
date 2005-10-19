# Copyright (C) 2005 Robey Pointer <robey@lag.net>, Canonical Ltd

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

"""
Implementation of Transport over SFTP, using paramiko.
"""

import getpass
import os
import re
import stat
import sys
import urllib

from bzrlib.errors import TransportNotPossible, NoSuchFile, NonRelativePath, TransportError
from bzrlib.config import config_dir
from bzrlib.trace import mutter, warning, error
from bzrlib.transport import Transport, register_transport

try:
    import paramiko
except ImportError:
    error('The SFTP plugin requires paramiko.')
    raise


SYSTEM_HOSTKEYS = {}
BZR_HOSTKEYS = {}

def load_host_keys():
    """
    Load system host keys (probably doesn't work on windows) and any
    "discovered" keys from previous sessions.
    """
    global SYSTEM_HOSTKEYS, BZR_HOSTKEYS
    try:
        SYSTEM_HOSTKEYS = paramiko.util.load_host_keys(os.path.expanduser('~/.ssh/known_hosts'))
    except Exception, e:
        mutter('failed to load system host keys: ' + str(e))
    bzr_hostkey_path = os.path.join(config_dir(), 'ssh_host_keys')
    try:
        BZR_HOSTKEYS = paramiko.util.load_host_keys(bzr_hostkey_path)
    except Exception, e:
        mutter('failed to load bzr host keys: ' + str(e))
        save_host_keys()

def save_host_keys():
    """
    Save "discovered" host keys in $(config)/ssh_host_keys/.
    """
    global SYSTEM_HOSTKEYS, BZR_HOSTKEYS
    bzr_hostkey_path = os.path.join(config_dir(), 'ssh_host_keys')
    if not os.path.isdir(config_dir()):
        os.mkdir(config_dir())
    try:
        f = open(bzr_hostkey_path, 'w')
        f.write('# SSH host keys collected by bzr\n')
        for hostname, keys in BZR_HOSTKEYS.iteritems():
            for keytype, key in keys.iteritems():
                f.write('%s %s %s\n' % (hostname, keytype, key.get_base64()))
        f.close()
    except IOError, e:
        mutter('failed to save bzr host keys: ' + str(e))



class SFTPTransportError (TransportError):
    pass


class SFTPTransport (Transport):
    """
    Transport implementation for SFTP access.
    """

    _url_matcher = re.compile(r'^sftp://([^@]*@)?(.*?)(:\d+)?(/.*)?$')
    
    def __init__(self, base, clone_from=None):
        assert base.startswith('sftp://')
        super(SFTPTransport, self).__init__(base)
        self._parse_url(base)
        if clone_from is None:
            self._sftp_connect()
        else:
            # use the same ssh connection, etc
            self._sftp = clone_from._sftp
        # super saves 'self.base'
    
    def should_cache(self):
        """
        Return True if the data pulled across should be cached locally.
        """
        return True

    def clone(self, offset=None):
        """
        Return a new SFTPTransport with root at self.base + offset.
        We share the same SFTP session between such transports, because it's
        fairly expensive to set them up.
        """
        if offset is None:
            return SFTPTransport(self.base, self)
        else:
            return SFTPTransport(self.abspath(offset), self)

    def abspath(self, relpath):
        """
        Return the full url to the given relative path.
        
        @param relpath: the relative path or path components
        @type relpath: str or list
        """
        return self._unparse_url(self._abspath(relpath))
    
    def _abspath(self, relpath):
        """Return the absolute path segment without the SFTP URL."""
        # FIXME: share the common code across transports
        assert isinstance(relpath, basestring)
        relpath = [urllib.unquote(relpath)]
        basepath = self._path.split('/')
        if len(basepath) > 0 and basepath[-1] == '':
            basepath = basepath[:-1]

        for p in relpath:
            if p == '..':
                if len(basepath) == 0:
                    # In most filesystems, a request for the parent
                    # of root, just returns root.
                    continue
                basepath.pop()
            elif p == '.':
                continue # No-op
            else:
                basepath.append(p)

        path = '/'.join(basepath)
        if path[0] != '/':
            path = '/' + path
        return path

    def relpath(self, abspath):
        # FIXME: this is identical to HttpTransport -- share it
        if not abspath.startswith(self.base):
            raise NonRelativePath('path %r is not under base URL %r'
                           % (abspath, self.base))
        pl = len(self.base)
        return abspath[pl:].lstrip('/')

    def has(self, relpath):
        """
        Does the target location exist?
        """
        try:
            self._sftp.stat(self._abspath(relpath))
            return True
        except IOError:
            return False

    def get(self, relpath, decode=False):
        """
        Get the file at the given relative path.

        :param relpath: The relative path to the file
        """
        try:
            path = self._abspath(relpath)
            return self._sftp.file(path)
        except (IOError, paramiko.SSHException), x:
            raise NoSuchFile('Error retrieving %s: %s' % (path, str(x)), x)

    def get_partial(self, relpath, start, length=None):
        """
        Get just part of a file.

        :param relpath: Path to the file, relative to base
        :param start: The starting position to read from
        :param length: The length to read. A length of None indicates
                       read to the end of the file.
        :return: A file-like object containing at least the specified bytes.
                 Some implementations may return objects which can be read
                 past this length, but this is not guaranteed.
        """
        f = self.get(relpath)
        f.seek(start)
        return f

    def put(self, relpath, f):
        """
        Copy the file-like or string object into the location.

        :param relpath: Location to put the contents, relative to base.
        :param f:       File-like or string object.
        """
        # FIXME: should do something atomic or locking here, this is unsafe
        try:
            path = self._abspath(relpath)
            fout = self._sftp.file(path, 'wb')
        except (IOError, paramiko.SSHException), x:
            raise SFTPTransportError('Unable to write file %r' % (path,), x)
        try:
            self._pump(f, fout)
        finally:
            fout.close()

    def iter_files_recursive(self):
        """Walk the relative paths of all files in this transport."""
        queue = list(self.list_dir('.'))
        while queue:
            relpath = queue.pop(0)
            st = self.stat(relpath)
            if stat.S_ISDIR(st.st_mode):
                for i, basename in enumerate(self.list_dir(relpath)):
                    queue.insert(i, relpath+'/'+basename)
            else:
                yield relpath

    def mkdir(self, relpath):
        """Create a directory at the given path."""
        try:
            path = self._abspath(relpath)
            self._sftp.mkdir(path)
        except (IOError, paramiko.SSHException), x:
            raise SFTPTransportError('Unable to mkdir %r' % (path,), x)

    def append(self, relpath, f):
        """
        Append the text in the file-like object into the final
        location.
        """
        try:
            path = self._abspath(relpath)
            fout = self._sftp.file(path, 'ab')
            self._pump(f, fout)
        except (IOError, paramiko.SSHException), x:
            raise SFTPTransportError('Unable to append file %r' % (path,), x)

    def copy(self, rel_from, rel_to):
        """Copy the item at rel_from to the location at rel_to"""
        path_from = self._abspath(rel_from)
        path_to = self._abspath(rel_to)
        try:
            fin = self._sftp.file(path_from, 'rb')
            try:
                fout = self._sftp.file(path_to, 'wb')
                try:
                    fout.set_pipelined(True)
                    self._pump(fin, fout)
                finally:
                    fout.close()
            finally:
                fin.close()
        except (IOError, paramiko.SSHException), x:
            raise SFTPTransportError('Unable to copy %r to %r' % (path_from, path_to), x)

    def move(self, rel_from, rel_to):
        """Move the item at rel_from to the location at rel_to"""
        path_from = self._abspath(rel_from)
        path_to = self._abspath(rel_to)
        try:
            self._sftp.rename(path_from, path_to)
        except (IOError, paramiko.SSHException), x:
            raise SFTPTransportError('Unable to move %r to %r' % (path_from, path_to), x)

    def delete(self, relpath):
        """Delete the item at relpath"""
        path = self._abspath(relpath)
        try:
            self._sftp.remove(path)
        except (IOError, paramiko.SSHException), x:
            raise SFTPTransportError('Unable to delete %r' % (path,), x)
            
    def listable(self):
        """Return True if this store supports listing."""
        return True

    def list_dir(self, relpath):
        """
        Return a list of all files at the given location.
        """
        # does anything actually use this?
        path = self._abspath(relpath)
        try:
            return self._sftp.listdir(path)
        except (IOError, paramiko.SSHException), x:
            raise SFTPTransportError('Unable to list folder %r' % (path,), x)

    def stat(self, relpath):
        """Return the stat information for a file."""
        path = self._abspath(relpath)
        try:
            return self._sftp.stat(path)
        except (IOError, paramiko.SSHException), x:
            raise SFTPTransportError('Unable to stat %r' % (path,), x)

    def lock_read(self, relpath):
        """
        Lock the given file for shared (read) access.
        :return: A lock object, which should be passed to Transport.unlock()
        """
        # FIXME: there should be something clever i can do here...
        class BogusLock(object):
            def __init__(self, path):
                self.path = path
            def unlock(self):
                pass
        return BogusLock(relpath)

    def lock_write(self, relpath):
        """
        Lock the given file for exclusive (write) access.
        WARNING: many transports do not support this, so trying avoid using it

        :return: A lock object, which should be passed to Transport.unlock()
        """
        # FIXME: there should be something clever i can do here...
        class BogusLock(object):
            def __init__(self, path):
                self.path = path
            def unlock(self):
                pass
        return BogusLock(relpath)


    def _unparse_url(self, path=None):
        if path is None:
            path = self._path
        if self._port == 22:
            return 'sftp://%s@%s%s' % (self._username, self._host, path)
        return 'sftp://%s@%s:%d%s' % (self._username, self._host, self._port, path)

    def _parse_url(self, url):
        assert url[:7] == 'sftp://'
        m = self._url_matcher.match(url)
        if m is None:
            raise SFTPTransportError('Unable to parse SFTP URL %r' % (url,))
        self._username, self._host, self._port, self._path = m.groups()
        if self._username is None:
            self._username = getpass.getuser()
        else:
            self._username = self._username[:-1]
        if self._port is None:
            self._port = 22
        else:
            self._port = int(self._port[1:])
        if (self._path is None) or (self._path == ''):
            self._path = '/'

    def _sftp_connect(self):
        global SYSTEM_HOSTKEYS, BZR_HOSTKEYS
        
        load_host_keys()
        
        try:
            t = paramiko.Transport((self._host, self._port))
            t.start_client()
        except paramiko.SSHException:
            raise SFTPTransportError('Unable to reach SSH host %s:%d' % (self._host, self._port))
            
        server_key = t.get_remote_server_key()
        server_key_hex = paramiko.util.hexify(server_key.get_fingerprint())
        keytype = server_key.get_name()
        if SYSTEM_HOSTKEYS.has_key(self._host) and SYSTEM_HOSTKEYS[self._host].has_key(keytype):
            our_server_key = SYSTEM_HOSTKEYS[self._host][keytype]
            our_server_key_hex = paramiko.util.hexify(our_server_key.get_fingerprint())
        elif BZR_HOSTKEYS.has_key(self._host) and BZR_HOSTKEYS[self._host].has_key(keytype):
            our_server_key = BZR_HOSTKEYS[self._host][keytype]
            our_server_key_hex = paramiko.util.hexify(our_server_key.get_fingerprint())
        else:
            warning('Adding %s host key for %s: %s' % (keytype, self._host, server_key_hex))
            if not BZR_HOSTKEYS.has_key(self._host):
                BZR_HOSTKEYS[self._host] = {}
            BZR_HOSTKEYS[self._host][keytype] = server_key
            our_server_key = server_key
            our_server_key_hex = paramiko.util.hexify(our_server_key.get_fingerprint())
            save_host_keys()
        if server_key != our_server_key:
            filename1 = os.path.expanduser('~/.ssh/known_hosts')
            filename2 = os.path.join(config_dir(), 'ssh_host_keys')
            raise SFTPTransportError('Host keys for %s do not match!  %s != %s' % \
                (self._host, our_server_key_hex, server_key_hex),
                ['Try editing %s or %s' % (filename1, filename2)])

        self._sftp_auth(t, self._username, self._host)
        
        try:
            self._sftp = t.open_sftp_client()
        except paramiko.SSHException:
            raise BzrError('Unable to find path %s on SFTP server %s' % \
                (self._path, self._host))

    def _sftp_auth(self, transport, username, host):
        agent = paramiko.Agent()
        for key in agent.get_keys():
            mutter('Trying SSH agent key %s' % paramiko.util.hexify(key.get_fingerprint()))
            try:
                transport.auth_publickey(self._username, key)
                return
            except paramiko.SSHException, e:
                pass
        
        # okay, try finding id_rsa or id_dss?  (posix only)
        if self._try_pkey_auth(transport, paramiko.RSAKey, 'id_rsa'):
            return
        if self._try_pkey_auth(transport, paramiko.DSSKey, 'id_dsa'):
            return

        # give up and ask for a password
        password = getpass.getpass('SSH %s@%s password: ' % (self._username, self._host))
        try:
            transport.auth_password(self._username, password)
        except paramiko.SSHException:
            raise SFTPTransportError('Unable to authenticate to SSH host as %s@%s' % \
                (self._username, self._host))

    def _try_pkey_auth(self, transport, pkey_class, filename):
        filename = os.path.expanduser('~/.ssh/' + filename)
        try:
            key = pkey_class.from_private_key_file(filename)
            transport.auth_publickey(self._username, key)
            return True
        except paramiko.PasswordRequiredException:
            password = getpass.getpass('SSH %s password: ' % (os.path.basename(filename),))
            try:
                key = pkey_class.from_private_key_file(filename, password)
                transport.auth_publickey(self._username, key)
                return True
            except paramiko.SSHException:
                mutter('SSH authentication via %s key failed.' % (os.path.basename(filename),))
        except paramiko.SSHException:
            mutter('SSH authentication via %s key failed.' % (os.path.basename(filename),))
        except IOError:
            pass
        return False


register_transport('sftp://', SFTPTransport)

