# Copyright (C) 2005 Robey Pointer <robey@lag.net>
# Copyright (C) 2005, 2006 Canonical Ltd
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

"""Foundation SSH support for SFTP and smart server."""

import os
import socket
import sys
import weakref

from bzrlib.config import config_dir, ensure_config_dir_exists
from bzrlib.errors import (ConnectionError,
                           ParamikoNotPresent,
                           TransportError,
                           )

from bzrlib.osutils import pathjoin, fancy_rename, getcwd
from bzrlib.trace import mutter, warning

try:
    import paramiko
except ImportError, e:
    raise ParamikoNotPresent(e)
else:
    from paramiko.sftp_client import SFTPClient


SYSTEM_HOSTKEYS = {}
BZR_HOSTKEYS = {}


# This is a weakref dictionary, so that we can reuse connections
# that are still active. Long term, it might be nice to have some
# sort of expiration policy, such as disconnect if inactive for
# X seconds. But that requires a lot more fanciness.
_connected_hosts = weakref.WeakValueDictionary()

# Paramiko 1.5 tries to open a socket.AF_UNIX in order to connect
# to ssh-agent. That attribute doesn't exist on win32 (it does in cygwin)
# so we get an AttributeError exception. So we will not try to
# connect to an agent if we are on win32 and using Paramiko older than 1.6
_use_ssh_agent = (sys.platform != 'win32' or _paramiko_version >= (1, 6, 0))


class LoopbackSFTP(object):
    """Simple wrapper for a socket that pretends to be a paramiko Channel."""

    def __init__(self, sock):
        self.__socket = sock
 
    def send(self, data):
        return self.__socket.send(data)

    def recv(self, n):
        return self.__socket.recv(n)

    def recv_ready(self):
        return True

    def close(self):
        self.__socket.close()


class SSHVendor(object):
    def connect_sftp(self, username, password, host, port):
        raise NotImplementedError(self.connect_sftp)

    def connect_ssh(self, username, password, host, port, command):
        raise NotImplementedError(self.connect_ssh)
        

class LoopbackVendor(SSHVendor):
    
    def connect_sftp(self, username, password, host, port):
        sock = socket.socket()
        try:
            sock.connect((host, port))
        except socket.error, e:
            raise ConnectionError('Unable to connect to SSH host %s:%s: %s'
                                  % (host, port, e))
        return SFTPClient(LoopbackSFTP(sock))


class ParamikoVendor(SSHVendor):

    def connect_sftp(self, username, password, host, port):
        global SYSTEM_HOSTKEYS, BZR_HOSTKEYS
        
        load_host_keys()

        try:
            t = paramiko.Transport((host, port or 22))
            t.set_log_channel('bzr.paramiko')
            t.start_client()
        except (paramiko.SSHException, socket.error), e:
            raise ConnectionError('Unable to reach SSH host %s:%s: %s' 
                                  % (host, port, e))
            
        server_key = t.get_remote_server_key()
        server_key_hex = paramiko.util.hexify(server_key.get_fingerprint())
        keytype = server_key.get_name()
        if SYSTEM_HOSTKEYS.has_key(host) and SYSTEM_HOSTKEYS[host].has_key(keytype):
            our_server_key = SYSTEM_HOSTKEYS[host][keytype]
            our_server_key_hex = paramiko.util.hexify(our_server_key.get_fingerprint())
        elif BZR_HOSTKEYS.has_key(host) and BZR_HOSTKEYS[host].has_key(keytype):
            our_server_key = BZR_HOSTKEYS[host][keytype]
            our_server_key_hex = paramiko.util.hexify(our_server_key.get_fingerprint())
        else:
            warning('Adding %s host key for %s: %s' % (keytype, host, server_key_hex))
            if not BZR_HOSTKEYS.has_key(host):
                BZR_HOSTKEYS[host] = {}
            BZR_HOSTKEYS[host][keytype] = server_key
            our_server_key = server_key
            our_server_key_hex = paramiko.util.hexify(our_server_key.get_fingerprint())
            save_host_keys()
        if server_key != our_server_key:
            filename1 = os.path.expanduser('~/.ssh/known_hosts')
            filename2 = pathjoin(config_dir(), 'ssh_host_keys')
            raise TransportError('Host keys for %s do not match!  %s != %s' % \
                (host, our_server_key_hex, server_key_hex),
                ['Try editing %s or %s' % (filename1, filename2)])

        _paramiko_auth(username, password, host, t)
        
        try:
            sftp = t.open_sftp_client()
        except paramiko.SSHException, e:
            raise ConnectionError('Unable to start sftp client %s:%d' %
                                  (host, port), e)
        return sftp


class SubprocessVendor(SSHVendor):
    pass


class OpenSSHSubprocessVendor(SubprocessVendor):
    pass


class SSHCorpSubprocessVendor(SubprocessVendor):
    pass
    

def _paramiko_auth(username, password, host, paramiko_transport):
    # paramiko requires a username, but it might be none if nothing was supplied
    # use the local username, just in case.
    # We don't override username, because if we aren't using paramiko,
    # the username might be specified in ~/.ssh/config and we don't want to
    # force it to something else
    # Also, it would mess up the self.relpath() functionality
    username = username or getpass.getuser()

    if _use_ssh_agent:
        agent = paramiko.Agent()
        for key in agent.get_keys():
            mutter('Trying SSH agent key %s' % paramiko.util.hexify(key.get_fingerprint()))
            try:
                paramiko_transport.auth_publickey(username, key)
                return
            except paramiko.SSHException, e:
                pass
    
    # okay, try finding id_rsa or id_dss?  (posix only)
    if _try_pkey_auth(paramiko_transport, paramiko.RSAKey, username, 'id_rsa'):
        return
    if _try_pkey_auth(paramiko_transport, paramiko.DSSKey, username, 'id_dsa'):
        return

    if password:
        try:
            paramiko_transport.auth_password(username, password)
            return
        except paramiko.SSHException, e:
            pass

    # give up and ask for a password
    password = bzrlib.ui.ui_factory.get_password(
            prompt='SSH %(user)s@%(host)s password',
            user=username, host=host)
    try:
        paramiko_transport.auth_password(username, password)
    except paramiko.SSHException, e:
        raise ConnectionError('Unable to authenticate to SSH host as %s@%s' %
                              (username, host), e)


def _try_pkey_auth(paramiko_transport, pkey_class, username, filename):
    filename = os.path.expanduser('~/.ssh/' + filename)
    try:
        key = pkey_class.from_private_key_file(filename)
        paramiko_transport.auth_publickey(username, key)
        return True
    except paramiko.PasswordRequiredException:
        password = bzrlib.ui.ui_factory.get_password(
                prompt='SSH %(filename)s password',
                filename=filename)
        try:
            key = pkey_class.from_private_key_file(filename, password)
            paramiko_transport.auth_publickey(username, key)
            return True
        except paramiko.SSHException:
            mutter('SSH authentication via %s key failed.' % (os.path.basename(filename),))
    except paramiko.SSHException:
        mutter('SSH authentication via %s key failed.' % (os.path.basename(filename),))
    except IOError:
        pass
    return False


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
    bzr_hostkey_path = pathjoin(config_dir(), 'ssh_host_keys')
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
    bzr_hostkey_path = pathjoin(config_dir(), 'ssh_host_keys')
    ensure_config_dir_exists()

    try:
        f = open(bzr_hostkey_path, 'w')
        f.write('# SSH host keys collected by bzr\n')
        for hostname, keys in BZR_HOSTKEYS.iteritems():
            for keytype, key in keys.iteritems():
                f.write('%s %s %s\n' % (hostname, keytype, key.get_base64()))
        f.close()
    except IOError, e:
        mutter('failed to save bzr host keys: ' + str(e))


