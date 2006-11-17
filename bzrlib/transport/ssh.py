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

import errno
import getpass
import os
import socket
import subprocess
import sys

from bzrlib.config import config_dir, ensure_config_dir_exists
from bzrlib.errors import (ConnectionError,
                           ParamikoNotPresent,
                           SocketConnectionError,
                           TransportError,
                           UnknownSSH,
                           )

from bzrlib.osutils import pathjoin
from bzrlib.trace import mutter, warning
import bzrlib.ui

try:
    import paramiko
except ImportError, e:
    # If we have an ssh subprocess, we don't strictly need paramiko for all ssh
    # access
    paramiko = None
else:
    from paramiko.sftp_client import SFTPClient


SYSTEM_HOSTKEYS = {}
BZR_HOSTKEYS = {}


_paramiko_version = getattr(paramiko, '__version_info__', (0, 0, 0))

# Paramiko 1.5 tries to open a socket.AF_UNIX in order to connect
# to ssh-agent. That attribute doesn't exist on win32 (it does in cygwin)
# so we get an AttributeError exception. So we will not try to
# connect to an agent if we are on win32 and using Paramiko older than 1.6
_use_ssh_agent = (sys.platform != 'win32' or _paramiko_version >= (1, 6, 0))

_ssh_vendors = {}

def register_ssh_vendor(name, vendor):
    """Register SSH vendor."""
    _ssh_vendors[name] = vendor

    
_ssh_vendor = None
def _get_ssh_vendor():
    """Find out what version of SSH is on the system."""
    global _ssh_vendor
    if _ssh_vendor is not None:
        return _ssh_vendor

    if 'BZR_SSH' in os.environ:
        vendor_name = os.environ['BZR_SSH']
        try:
            _ssh_vendor = _ssh_vendors[vendor_name]
        except KeyError:
            raise UnknownSSH(vendor_name)
        return _ssh_vendor

    try:
        p = subprocess.Popen(['ssh', '-V'],
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             **os_specific_subprocess_params())
        returncode = p.returncode
        stdout, stderr = p.communicate()
    except OSError:
        returncode = -1
        stdout = stderr = ''
    if 'OpenSSH' in stderr:
        mutter('ssh implementation is OpenSSH')
        _ssh_vendor = OpenSSHSubprocessVendor()
    elif 'SSH Secure Shell' in stderr:
        mutter('ssh implementation is SSH Corp.')
        _ssh_vendor = SSHCorpSubprocessVendor()

    if _ssh_vendor is not None:
        return _ssh_vendor

    # XXX: 20051123 jamesh
    # A check for putty's plink or lsh would go here.

    mutter('falling back to paramiko implementation')
    _ssh_vendor = ParamikoVendor()
    return _ssh_vendor


def _ignore_sigint():
    # TODO: This should possibly ignore SIGHUP as well, but bzr currently
    # doesn't handle it itself.
    # <https://launchpad.net/products/bzr/+bug/41433/+index>
    import signal
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    


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
    """Abstract base class for SSH vendor implementations."""
    
    def connect_sftp(self, username, password, host, port):
        """Make an SSH connection, and return an SFTPClient.
        
        :param username: an ascii string
        :param password: an ascii string
        :param host: a host name as an ascii string
        :param port: a port number
        :type port: int

        :raises: ConnectionError if it cannot connect.

        :rtype: paramiko.sftp_client.SFTPClient
        """
        raise NotImplementedError(self.connect_sftp)

    def connect_ssh(self, username, password, host, port, command):
        """Make an SSH connection.
        
        :returns: something with a `close` method, and a `get_filelike_channels`
            method that returns a pair of (read, write) filelike objects.
        """
        raise NotImplementedError(self.connect_ssh)
        
    def _raise_connection_error(self, host, port=None, orig_error=None,
                                msg='Unable to connect to SSH host'):
        """Raise a SocketConnectionError with properly formatted host.

        This just unifies all the locations that try to raise ConnectionError,
        so that they format things properly.
        """
        raise SocketConnectionError(host=host, port=port, msg=msg,
                                    orig_error=orig_error)


class LoopbackVendor(SSHVendor):
    """SSH "vendor" that connects over a plain TCP socket, not SSH."""
    
    def connect_sftp(self, username, password, host, port):
        sock = socket.socket()
        try:
            sock.connect((host, port))
        except socket.error, e:
            self._raise_connection_error(host, port=port, orig_error=e)
        return SFTPClient(LoopbackSFTP(sock))

register_ssh_vendor('loopback', LoopbackVendor())


class _ParamikoSSHConnection(object):
    def __init__(self, channel):
        self.channel = channel

    def get_filelike_channels(self):
        return self.channel.makefile('rb'), self.channel.makefile('wb')

    def close(self):
        return self.channel.close()


class ParamikoVendor(SSHVendor):
    """Vendor that uses paramiko."""

    def _connect(self, username, password, host, port):
        global SYSTEM_HOSTKEYS, BZR_HOSTKEYS
        
        load_host_keys()

        try:
            t = paramiko.Transport((host, port or 22))
            t.set_log_channel('bzr.paramiko')
            t.start_client()
        except (paramiko.SSHException, socket.error), e:
            self._raise_connection_error(host, port=port, orig_error=e)
            
        server_key = t.get_remote_server_key()
        server_key_hex = paramiko.util.hexify(server_key.get_fingerprint())
        keytype = server_key.get_name()
        if host in SYSTEM_HOSTKEYS and keytype in SYSTEM_HOSTKEYS[host]:
            our_server_key = SYSTEM_HOSTKEYS[host][keytype]
            our_server_key_hex = paramiko.util.hexify(our_server_key.get_fingerprint())
        elif host in BZR_HOSTKEYS and keytype in BZR_HOSTKEYS[host]:
            our_server_key = BZR_HOSTKEYS[host][keytype]
            our_server_key_hex = paramiko.util.hexify(our_server_key.get_fingerprint())
        else:
            warning('Adding %s host key for %s: %s' % (keytype, host, server_key_hex))
            add = getattr(BZR_HOSTKEYS, 'add', None)
            if add is not None: # paramiko >= 1.X.X
                BZR_HOSTKEYS.add(host, keytype, server_key)
            else:
                BZR_HOSTKEYS.set_default(host, {})[keytype] = server_key
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
        return t
        
    def connect_sftp(self, username, password, host, port):
        t = self._connect(username, password, host, port)
        try:
            return t.open_sftp_client()
        except paramiko.SSHException, e:
            self._raise_connection_error(host, port=port, orig_error=e,
                                         msg='Unable to start sftp client')

    def connect_ssh(self, username, password, host, port, command):
        t = self._connect(username, password, host, port)
        try:
            channel = t.open_session()
            cmdline = ' '.join(command)
            channel.exec_command(cmdline)
            return _ParamikoSSHConnection(channel)
        except paramiko.SSHException, e:
            self._raise_connection_error(host, port=port, orig_error=e,
                                         msg='Unable to invoke remote bzr')

if paramiko is not None:
    register_ssh_vendor('paramiko', ParamikoVendor())


class SubprocessVendor(SSHVendor):
    """Abstract base class for vendors that use pipes to a subprocess."""
    
    def _connect(self, argv):
        proc = subprocess.Popen(argv,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                **os_specific_subprocess_params())
        return SSHSubprocess(proc)

    def connect_sftp(self, username, password, host, port):
        try:
            argv = self._get_vendor_specific_argv(username, host, port,
                                                  subsystem='sftp')
            sock = self._connect(argv)
            return SFTPClient(sock)
        except (EOFError, paramiko.SSHException), e:
            self._raise_connection_error(host, port=port, orig_error=e)
        except (OSError, IOError), e:
            # If the machine is fast enough, ssh can actually exit
            # before we try and send it the sftp request, which
            # raises a Broken Pipe
            if e.errno not in (errno.EPIPE,):
                raise
            self._raise_connection_error(host, port=port, orig_error=e)

    def connect_ssh(self, username, password, host, port, command):
        try:
            argv = self._get_vendor_specific_argv(username, host, port,
                                                  command=command)
            return self._connect(argv)
        except (EOFError), e:
            self._raise_connection_error(host, port=port, orig_error=e)
        except (OSError, IOError), e:
            # If the machine is fast enough, ssh can actually exit
            # before we try and send it the sftp request, which
            # raises a Broken Pipe
            if e.errno not in (errno.EPIPE,):
                raise
            self._raise_connection_error(host, port=port, orig_error=e)

    def _get_vendor_specific_argv(self, username, host, port, subsystem=None,
                                  command=None):
        """Returns the argument list to run the subprocess with.
        
        Exactly one of 'subsystem' and 'command' must be specified.
        """
        raise NotImplementedError(self._get_vendor_specific_argv)

register_ssh_vendor('none', ParamikoVendor())


class OpenSSHSubprocessVendor(SubprocessVendor):
    """SSH vendor that uses the 'ssh' executable from OpenSSH."""
    
    def _get_vendor_specific_argv(self, username, host, port, subsystem=None,
                                  command=None):
        assert subsystem is not None or command is not None, (
            'Must specify a command or subsystem')
        if subsystem is not None:
            assert command is None, (
                'subsystem and command are mutually exclusive')
        args = ['ssh',
                '-oForwardX11=no', '-oForwardAgent=no',
                '-oClearAllForwardings=yes', '-oProtocol=2',
                '-oNoHostAuthenticationForLocalhost=yes']
        if port is not None:
            args.extend(['-p', str(port)])
        if username is not None:
            args.extend(['-l', username])
        if subsystem is not None:
            args.extend(['-s', host, subsystem])
        else:
            args.extend([host] + command)
        return args

register_ssh_vendor('openssh', OpenSSHSubprocessVendor())


class SSHCorpSubprocessVendor(SubprocessVendor):
    """SSH vendor that uses the 'ssh' executable from SSH Corporation."""

    def _get_vendor_specific_argv(self, username, host, port, subsystem=None,
                                  command=None):
        assert subsystem is not None or command is not None, (
            'Must specify a command or subsystem')
        if subsystem is not None:
            assert command is None, (
                'subsystem and command are mutually exclusive')
        args = ['ssh', '-x']
        if port is not None:
            args.extend(['-p', str(port)])
        if username is not None:
            args.extend(['-l', username])
        if subsystem is not None:
            args.extend(['-s', subsystem, host])
        else:
            args.extend([host] + command)
        return args
    
register_ssh_vendor('ssh', SSHCorpSubprocessVendor())


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


def os_specific_subprocess_params():
    """Get O/S specific subprocess parameters."""
    if sys.platform == 'win32':
        # setting the process group and closing fds is not supported on 
        # win32
        return {}
    else:
        # We close fds other than the pipes as the child process does not need 
        # them to be open.
        #
        # We also set the child process to ignore SIGINT.  Normally the signal
        # would be sent to every process in the foreground process group, but
        # this causes it to be seen only by bzr and not by ssh.  Python will
        # generate a KeyboardInterrupt in bzr, and we will then have a chance
        # to release locks or do other cleanup over ssh before the connection
        # goes away.  
        # <https://launchpad.net/products/bzr/+bug/5987>
        #
        # Running it in a separate process group is not good because then it
        # can't get non-echoed input of a password or passphrase.
        # <https://launchpad.net/products/bzr/+bug/40508>
        return {'preexec_fn': _ignore_sigint,
                'close_fds': True,
                }


class SSHSubprocess(object):
    """A socket-like object that talks to an ssh subprocess via pipes."""

    def __init__(self, proc):
        self.proc = proc

    def send(self, data):
        return os.write(self.proc.stdin.fileno(), data)

    def recv_ready(self):
        # TODO: jam 20051215 this function is necessary to support the
        # pipelined() function. In reality, it probably should use
        # poll() or select() to actually return if there is data
        # available, otherwise we probably don't get any benefit
        return True

    def recv(self, count):
        return os.read(self.proc.stdout.fileno(), count)

    def close(self):
        self.proc.stdin.close()
        self.proc.stdout.close()
        self.proc.wait()

    def get_filelike_channels(self):
        return (self.proc.stdout, self.proc.stdin)

