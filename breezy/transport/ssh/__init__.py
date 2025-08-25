# Copyright (C) 2006-2011 Robey Pointer <robey@lag.net>
# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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

"""Foundation SSH support for SFTP and smart server."""

import errno
import os
import socket
import subprocess
import sys

from ... import config, errors, osutils, registry, trace
from ..._transport_rs import sftp as _sftp_rs

SFTPClient = _sftp_rs.SFTPClient

try:
    import paramiko
except ModuleNotFoundError:
    # If we have an ssh subprocess, we don't strictly need paramiko for all ssh
    # access
    paramiko = None  # type: ignore


class StrangeHostname(errors.BzrError):
    """Error raised when an SSH hostname looks suspicious.

    This error is raised when the hostname starts with a dash, which could
    potentially be interpreted as a command-line option by the SSH client.

    Attributes:
        hostname: The suspicious hostname that was rejected.
    """

    _fmt = "Refusing to connect to strange SSH hostname %(hostname)s"


class SSHVendorManager(registry.Registry[str, "SSHVendor", None]):
    """Manager for manage SSH vendors."""

    def __init__(self):
        """Initialize the SSH vendor manager.

        Sets up the registry and initializes the vendor cache.
        """
        super().__init__()
        self._cached_ssh_vendor = None

    def clear_cache(self):
        """Clear previously cached lookup result."""
        self._cached_ssh_vendor = None

    def _get_vendor_by_config(self):
        """Get SSH vendor based on configuration.

        Looks up the SSH vendor from the global configuration. If a vendor
        name is specified but not registered, attempts to use it as an
        executable path.

        Returns:
            SSHVendor: The configured SSH vendor, or None if not configured.

        Raises:
            UnknownSSH: If the configured vendor name is not found and cannot
                be used as an executable path.
        """
        vendor_name = config.GlobalStack().get("ssh")
        if vendor_name is not None:
            try:
                vendor = self.get(vendor_name)
            except KeyError as err:
                vendor = self._get_vendor_from_path(vendor_name)
                if vendor is None:
                    raise errors.UnknownSSH(vendor_name) from err
                vendor.executable_path = vendor_name
            return vendor
        return None

    def _get_ssh_version_string(self, args):
        """Return SSH version string from the subprocess.

        Runs the given command and captures its output to determine
        the SSH implementation version.

        Args:
            args: Command line arguments to execute (typically ['ssh', '-V']).

        Returns:
            str: Combined stdout and stderr output decoded using terminal encoding.
                Returns empty string if the command fails.
        """
        try:
            p = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                **os_specific_subprocess_params(),
            )
            stdout, stderr = p.communicate()
        except OSError:
            stdout = stderr = b""
        return (stdout + stderr).decode(osutils.get_terminal_encoding())

    def _get_vendor_by_version_string(self, version, progname):
        """Return the vendor or None based on output from the subprocess.

        Examines the version string to determine which SSH implementation
        is being used (OpenSSH, SSH Corp, GNU lsh, or PuTTY plink).

        Args:
            version: The output of 'ssh -V' like command.
            progname: The program name that was executed.

        Returns:
            SSHVendor: The appropriate vendor instance, or None if not recognized.
        """
        vendor = None
        if "OpenSSH" in version:
            trace.mutter("ssh implementation is OpenSSH")
            vendor = OpenSSHSubprocessVendor()
        elif "SSH Secure Shell" in version:
            trace.mutter("ssh implementation is SSH Corp.")
            vendor = SSHCorpSubprocessVendor()
        elif "lsh" in version:
            trace.mutter("ssh implementation is GNU lsh.")
            vendor = LSHSubprocessVendor()
        # As plink user prompts are not handled currently, don't auto-detect
        # it by inspection below, but keep this vendor detection for if a path
        # is given in BRZ_SSH. See https://bugs.launchpad.net/bugs/414743
        elif "plink" in version and progname == "plink":
            # Checking if "plink" was the executed argument as Windows
            # sometimes reports 'ssh -V' incorrectly with 'plink' in its
            # version.  See https://bugs.launchpad.net/bzr/+bug/107155
            trace.mutter("ssh implementation is Putty's plink.")
            vendor = PLinkSubprocessVendor()
        return vendor

    def _get_vendor_by_inspection(self):
        """Return the vendor or None by checking for known SSH implementations.

        Runs 'ssh -V' to determine the SSH implementation in use.

        Returns:
            SSHVendor: The detected vendor, or None if not recognized.
        """
        version = self._get_ssh_version_string(["ssh", "-V"])
        return self._get_vendor_by_version_string(version, "ssh")

    def _get_vendor_from_path(self, path):
        """Return the vendor or None using the program at the given path.

        Runs the specified executable with '-V' to determine its type.

        Args:
            path: Path to the SSH executable.

        Returns:
            SSHVendor: The detected vendor, or None if not recognized.
        """
        version = self._get_ssh_version_string([path, "-V"])
        return self._get_vendor_by_version_string(
            version, os.path.splitext(os.path.basename(path))[0]
        )

    def get_vendor(self):
        """Find out what version of SSH is on the system.

        :raises SSHVendorNotFound: if no any SSH vendor is found
        :raises UnknownSSH: if the BRZ_SSH environment variable contains
                            unknown vendor name
        """
        if self._cached_ssh_vendor is None:
            vendor = self._get_vendor_by_config()
            if vendor is None:
                vendor = self._get_vendor_by_inspection()
                if vendor is None:
                    trace.mutter("falling back to default implementation")
                    if self.default_key is None:
                        raise errors.SSHVendorNotFound()
                    vendor = self.get()
            self._cached_ssh_vendor = vendor
        return self._cached_ssh_vendor


_ssh_vendor_manager = SSHVendorManager()
_get_ssh_vendor = _ssh_vendor_manager.get_vendor
register_ssh_vendor = _ssh_vendor_manager.register
register_lazy_ssh_vendor = _ssh_vendor_manager.register_lazy


def _ignore_signals():
    """Configure signal handling for SSH subprocesses.

    Sets up signal handlers to ignore SIGINT and conditionally SIGQUIT.
    This prevents the SSH subprocess from being interrupted by keyboard
    interrupts intended for the parent process.

    The function ignores:
    - SIGINT: Always ignored to prevent Ctrl+C from affecting SSH
    - SIGQUIT: Ignored if not already set to default (to respect breakin)
    """
    # TODO: This should possibly ignore SIGHUP as well, but bzr currently
    # doesn't handle it itself.
    # <https://launchpad.net/products/bzr/+bug/41433/+index>
    import signal

    signal.signal(signal.SIGINT, signal.SIG_IGN)
    # GZ 2010-02-19: Perhaps make this check if breakin is installed instead
    if signal.getsignal(signal.SIGQUIT) != signal.SIG_DFL:
        signal.signal(signal.SIGQUIT, signal.SIG_IGN)


class SocketAsChannelAdapter:
    """Simple wrapper for a socket that pretends to be a paramiko Channel."""

    def __init__(self, sock):
        """Initialize the adapter with a socket.

        Args:
            sock: A socket object to wrap.
        """
        self.__socket = sock

    def get_name(self):
        """Get the name of this channel adapter.

        Returns:
            str: A descriptive name for this adapter.
        """
        return "bzr SocketAsChannelAdapter"

    def send(self, data):
        """Send data through the socket.

        Args:
            data: Bytes to send.

        Returns:
            int: Number of bytes sent.
        """
        return self.__socket.send(data)

    def recv(self, n):
        """Receive data from the socket.

        Args:
            n: Maximum number of bytes to receive.

        Returns:
            bytes: Data received from the socket, or empty string if the
                connection is closed.

        Note:
            Returns empty string instead of raising an exception when the
            connection is closed, to match paramiko's expected behavior.
        """
        try:
            return self.__socket.recv(n)
        except OSError as e:
            if e.args[0] in (
                errno.EPIPE,
                errno.ECONNRESET,
                errno.ECONNABORTED,
                errno.EBADF,
            ):
                # Connection has closed.  Paramiko expects an empty string in
                # this case, not an exception.
                return ""
            raise

    def recv_ready(self):
        """Check if data is available for reading.

        Returns:
            bool: Always returns True. Should ideally use poll() or select()
                to check for actual data availability.

        Note:
            This is a simplified implementation that always returns True.
            A proper implementation would check if data is actually available.
        """
        # TODO: jam 20051215 this function is necessary to support the
        # pipelined() function. In reality, it probably should use
        # poll() or select() to actually return if there is data
        # available, otherwise we probably don't get any benefit
        return True

    def close(self):
        """Close the underlying socket."""
        self.__socket.close()


class SSHVendor:
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

        :returns: an SSHConnection.
        """
        raise NotImplementedError(self.connect_ssh)

    def _raise_connection_error(
        self, host, port=None, orig_error=None, msg="Unable to connect to SSH host"
    ):
        """Raise a SocketConnectionError with properly formatted host.

        This just unifies all the locations that try to raise ConnectionError,
        so that they format things properly.

        Args:
            host: The hostname that failed to connect.
            port: The port number (optional).
            orig_error: The original exception that caused the connection failure.
            msg: Custom error message.

        Raises:
            SocketConnectionError: Always raises this error with the provided details.
        """
        raise errors.SocketConnectionError(
            host=host, port=port, msg=msg, orig_error=orig_error
        )


class LoopbackVendor(SSHVendor):
    """SSH "vendor" that connects over a plain TCP socket, not SSH."""

    def connect_sftp(self, username, password, host, port):
        """Connect to an SFTP server using a plain TCP socket.

        This is a loopback implementation that bypasses SSH and connects
        directly via TCP. Useful for testing or local connections.

        Args:
            username: SSH username (ignored in loopback).
            password: SSH password (ignored in loopback).
            host: Hostname to connect to.
            port: Port number to connect to.

        Returns:
            SFTPClient: An SFTP client connected via TCP socket.

        Raises:
            SocketConnectionError: If connection fails.
        """
        sock = socket.socket()
        try:
            sock.connect((host, port))
        except OSError as e:
            self._raise_connection_error(host, port=port, orig_error=e)
        return SFTPClient(sock.detach())


register_ssh_vendor("loopback", LoopbackVendor())


_ssh_connection_errors: tuple[type[Exception], ...] = (
    EOFError,
    OSError,
    IOError,
    socket.error,
)
if paramiko is not None:
    register_lazy_ssh_vendor(
        "paramiko", "breezy.transport.ssh.paramiko", "paramiko_vendor"
    )
    register_lazy_ssh_vendor("none", "breezy.transport.ssh.paramiko", "paramiko_vendor")
    _ssh_vendor_manager.default_key = "paramiko"
    _ssh_connection_errors += (paramiko.SSHException,)


class SubprocessVendor(SSHVendor):
    """Abstract base class for vendors that use pipes to a subprocess."""

    # In general stderr should be inherited from the parent process so prompts
    # are visible on the terminal. This can be overriden to another file for
    # tests, but beware of using PIPE which may hang due to not being read.
    _stderr_target = None

    @staticmethod
    def _check_hostname(arg):
        """Check if hostname is safe to pass to subprocess.

        Args:
            arg: The hostname to check.

        Raises:
            StrangeHostname: If the hostname starts with a dash.
        """
        if arg.startswith("-"):
            raise StrangeHostname(hostname=arg)

    def _connect(self, argv):
        """Create and connect to an SSH subprocess.

        Attempts to use socketpair for better performance (non-blocking reads),
        falling back to pipes if socketpair is not available.

        Args:
            argv: Command line arguments for the SSH subprocess.

        Returns:
            SSHSubprocessConnection: A connection to the SSH subprocess.
        """
        # Attempt to make a socketpair to use as stdin/stdout for the SSH
        # subprocess.  We prefer sockets to pipes because they support
        # non-blocking short reads, allowing us to optimistically read 64k (or
        # whatever) chunks.
        try:
            my_sock, subproc_sock = socket.socketpair()
            osutils.set_fd_cloexec(my_sock)
        except (AttributeError, OSError):
            # This platform doesn't support socketpair(), so just use ordinary
            # pipes instead.
            stdin = stdout = subprocess.PIPE
            my_sock, subproc_sock = None, None
        else:
            stdin = stdout = subproc_sock
        proc = subprocess.Popen(
            argv,
            stdin=stdin,
            stdout=stdout,
            stderr=self._stderr_target,
            bufsize=0,
            **os_specific_subprocess_params(),
        )
        if subproc_sock is not None:
            subproc_sock.close()
        return SSHSubprocessConnection(proc, sock=my_sock)

    def connect_sftp(self, username, password, host, port):
        """Connect to an SFTP server using an SSH subprocess.

        Args:
            username: SSH username.
            password: SSH password (not used by subprocess vendors).
            host: Hostname to connect to.
            port: Port number to connect to.

        Returns:
            SFTPClient: An SFTP client connected via SSH subprocess.

        Raises:
            SocketConnectionError: If connection fails.
        """
        try:
            argv = self._get_vendor_specific_argv(
                username, host, port, subsystem="sftp"
            )
            sock = self._connect(argv)
            return SFTPClient(sock._sock.detach())
        except _ssh_connection_errors as e:
            self._raise_connection_error(host, port=port, orig_error=e)

    def connect_ssh(self, username, password, host, port, command):
        """Connect to an SSH server and run a command.

        Args:
            username: SSH username.
            password: SSH password (not used by subprocess vendors).
            host: Hostname to connect to.
            port: Port number to connect to.
            command: Command to execute on the remote host.

        Returns:
            SSHSubprocessConnection: A connection to the SSH subprocess.

        Raises:
            SocketConnectionError: If connection fails.
        """
        try:
            argv = self._get_vendor_specific_argv(username, host, port, command=command)
            return self._connect(argv)
        except _ssh_connection_errors as e:
            self._raise_connection_error(host, port=port, orig_error=e)

    def _get_vendor_specific_argv(
        self, username, host, port, subsystem=None, command=None
    ):
        """Returns the argument list to run the subprocess with.

        Exactly one of 'subsystem' and 'command' must be specified.
        """
        raise NotImplementedError(self._get_vendor_specific_argv)


class OpenSSHSubprocessVendor(SubprocessVendor):
    """SSH vendor that uses the 'ssh' executable from OpenSSH."""

    executable_path = "ssh"

    def _get_vendor_specific_argv(
        self, username, host, port, subsystem=None, command=None
    ):
        """Build OpenSSH command line arguments.

        Args:
            username: SSH username.
            host: Hostname to connect to.
            port: Port number (optional).
            subsystem: SSH subsystem to invoke (e.g., 'sftp').
            command: Command to execute (alternative to subsystem).

        Returns:
            list: Command line arguments for OpenSSH.
        """
        args = [
            self.executable_path,
            "-oForwardX11=no",
            "-oForwardAgent=no",
            "-oClearAllForwardings=yes",
            "-oNoHostAuthenticationForLocalhost=yes",
        ]
        if port is not None:
            args.extend(["-p", str(port)])
        if username is not None:
            args.extend(["-l", username])
        if subsystem is not None:
            args.extend(["-s", "--", host, subsystem])
        else:
            args.extend(["--", host] + command)
        return args


register_ssh_vendor("openssh", OpenSSHSubprocessVendor())


class SSHCorpSubprocessVendor(SubprocessVendor):
    """SSH vendor that uses the 'ssh' executable from SSH Corporation."""

    executable_path = "ssh"

    def _get_vendor_specific_argv(
        self, username, host, port, subsystem=None, command=None
    ):
        """Build SSH Corporation command line arguments.

        Args:
            username: SSH username.
            host: Hostname to connect to.
            port: Port number (optional).
            subsystem: SSH subsystem to invoke (e.g., 'sftp').
            command: Command to execute (alternative to subsystem).

        Returns:
            list: Command line arguments for SSH Corp's ssh.
        """
        self._check_hostname(host)
        args = [self.executable_path, "-x"]
        if port is not None:
            args.extend(["-p", str(port)])
        if username is not None:
            args.extend(["-l", username])
        if subsystem is not None:
            args.extend(["-s", subsystem, host])
        else:
            args.extend([host] + command)
        return args


register_ssh_vendor("sshcorp", SSHCorpSubprocessVendor())


class LSHSubprocessVendor(SubprocessVendor):
    """SSH vendor that uses the 'lsh' executable from GNU."""

    executable_path = "lsh"

    def _get_vendor_specific_argv(
        self, username, host, port, subsystem=None, command=None
    ):
        """Build GNU lsh command line arguments.

        Args:
            username: SSH username.
            host: Hostname to connect to.
            port: Port number (optional).
            subsystem: SSH subsystem to invoke (e.g., 'sftp').
            command: Command to execute (alternative to subsystem).

        Returns:
            list: Command line arguments for GNU lsh.
        """
        self._check_hostname(host)
        args = [self.executable_path]
        if port is not None:
            args.extend(["-p", str(port)])
        if username is not None:
            args.extend(["-l", username])
        if subsystem is not None:
            args.extend(["--subsystem", subsystem, host])
        else:
            args.extend([host] + command)
        return args


register_ssh_vendor("lsh", LSHSubprocessVendor())


class PLinkSubprocessVendor(SubprocessVendor):
    """SSH vendor that uses the 'plink' executable from Putty."""

    executable_path = "plink"

    def _get_vendor_specific_argv(
        self, username, host, port, subsystem=None, command=None
    ):
        """Build PuTTY plink command line arguments.

        Args:
            username: SSH username.
            host: Hostname to connect to.
            port: Port number (optional).
            subsystem: SSH subsystem to invoke (e.g., 'sftp').
            command: Command to execute (alternative to subsystem).

        Returns:
            list: Command line arguments for plink.
        """
        self._check_hostname(host)
        args = [self.executable_path, "-x", "-a", "-ssh", "-2", "-batch"]
        if port is not None:
            args.extend(["-P", str(port)])
        if username is not None:
            args.extend(["-l", username])
        if subsystem is not None:
            args.extend(["-s", host, subsystem])
        else:
            args.extend([host] + command)
        return args


register_ssh_vendor("plink", PLinkSubprocessVendor())


def _paramiko_auth(username, password, host, port, paramiko_transport):
    auth = config.AuthenticationConfig()
    # paramiko requires a username, but it might be none if nothing was
    # supplied.  If so, use the local username.
    if username is None:
        username = auth.get_user("ssh", host, port=port, default=getpass.getuser())
    agent = paramiko.Agent()
    for key in agent.get_keys():
        trace.mutter(
            "Trying SSH agent key {}".format(hexlify(key.get_fingerprint()).upper())
        )
        try:
            paramiko_transport.auth_publickey(username, key)
            return
        except paramiko.SSHException:
            pass

    # okay, try finding id_rsa or id_dss?  (posix only)
    if _try_pkey_auth(paramiko_transport, paramiko.RSAKey, username, "id_rsa"):
        return
    # DSSKey was removed in paramiko 4.0.0 as DSA keys are deprecated
    if hasattr(paramiko, "DSSKey"):
        if _try_pkey_auth(paramiko_transport, paramiko.DSSKey, username, "id_dsa"):
            return

    # If we have gotten this far, we are about to try for passwords, do an
    # auth_none check to see if it is even supported.
    supported_auth_types = []
    try:
        # Note that with paramiko <1.7.5 this logs an INFO message:
        #    Authentication type (none) not permitted.
        # So we explicitly disable the logging level for this action
        old_level = paramiko_transport.logger.level
        paramiko_transport.logger.setLevel(logging.WARNING)
        try:
            paramiko_transport.auth_none(username)
        finally:
            paramiko_transport.logger.setLevel(old_level)
    except paramiko.BadAuthenticationType as e:
        # Supported methods are in the exception
        supported_auth_types = e.allowed_types
    except paramiko.SSHException:
        # Don't know what happened, but just ignore it
        pass
    # We treat 'keyboard-interactive' and 'password' auth methods identically,
    # because Paramiko's auth_password method will automatically try
    # 'keyboard-interactive' auth (using the password as the response) if
    # 'password' auth is not available.  Apparently some Debian and Gentoo
    # OpenSSH servers require this.
    # XXX: It's possible for a server to require keyboard-interactive auth that
    # requires something other than a single password, but we currently don't
    # support that.
    if (
        "password" not in supported_auth_types
        and "keyboard-interactive" not in supported_auth_types
    ):
        raise errors.ConnectionError(
            "Unable to authenticate to SSH host as"
            "\n  {}@{}\nsupported auth types: {}".format(
                username, host, supported_auth_types
            )
        )

    if password:
        try:
            paramiko_transport.auth_password(username, password)
            return
        except paramiko.SSHException:
            pass

    # give up and ask for a password
    password = auth.get_password("ssh", host, username, port=port)
    # get_password can still return None, which means we should not prompt
    if password is not None:
        try:
            paramiko_transport.auth_password(username, password)
        except paramiko.SSHException as e:
            raise errors.ConnectionError(
                "Unable to authenticate to SSH host as\n  {}@{}\n".format(
                    username, host
                ),
                e,
            ) from e
    else:
        raise errors.ConnectionError(
            "Unable to authenticate to SSH host as  {}@{}".format(username, host)
        )


def _try_pkey_auth(paramiko_transport, pkey_class, username, filename):
    filename = os.path.expanduser("~/.ssh/" + filename)
    try:
        key = pkey_class.from_private_key_file(filename)
        paramiko_transport.auth_publickey(username, key)
        return True
    except paramiko.PasswordRequiredException:
        password = ui.ui_factory.get_password(
            prompt="SSH %(filename)s password", filename=os.fsdecode(filename)
        )
        try:
            key = pkey_class.from_private_key_file(filename, password)
            paramiko_transport.auth_publickey(username, key)
            return True
        except paramiko.SSHException:
            trace.mutter(
                "SSH authentication via {} key failed.".format(
                    os.path.basename(filename)
                )
            )
    except paramiko.SSHException:
        trace.mutter(
            "SSH authentication via {} key failed.".format(os.path.basename(filename))
        )
    except OSError:
        pass
    return False


def _ssh_host_keys_config_dir():
    return osutils.pathjoin(bedding.config_dir(), "ssh_host_keys")


def load_host_keys():
    """Load system host keys (probably doesn't work on windows) and any
    "discovered" keys from previous sessions.
    """
    global SYSTEM_HOSTKEYS, BRZ_HOSTKEYS
    try:
        SYSTEM_HOSTKEYS = paramiko.util.load_host_keys(
            os.path.expanduser("~/.ssh/known_hosts")
        )
    except OSError as e:
        trace.mutter("failed to load system host keys: " + str(e))
    brz_hostkey_path = _ssh_host_keys_config_dir()
    try:
        BRZ_HOSTKEYS = paramiko.util.load_host_keys(brz_hostkey_path)
    except OSError as e:
        trace.mutter("failed to load brz host keys: " + str(e))
        save_host_keys()


def save_host_keys():
    """Save "discovered" host keys in $(config)/ssh_host_keys/."""
    global SYSTEM_HOSTKEYS, BRZ_HOSTKEYS
    bzr_hostkey_path = _ssh_host_keys_config_dir()
    bedding.ensure_config_dir_exists()

    try:
        with open(bzr_hostkey_path, "w") as f:
            f.write("# SSH host keys collected by bzr\n")
            for hostname, keys in BRZ_HOSTKEYS.items():
                for keytype, key in keys.items():
                    f.write("{} {} {}\n".format(hostname, keytype, key.get_base64()))
    except OSError as e:
        trace.mutter("failed to save bzr host keys: " + str(e))


def os_specific_subprocess_params():
    """Get O/S specific subprocess parameters.

    Returns different parameters based on the operating system:
    - Windows: Empty dict (no special handling)
    - Unix-like: Dict with preexec_fn to ignore signals and close_fds=True

    Returns:
        dict: Subprocess parameters suitable for the current OS.
    """
    if sys.platform == "win32":
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
        return {
            "preexec_fn": _ignore_signals,
            "close_fds": True,
        }


import weakref

_subproc_weakrefs: set[weakref.ref] = set()


def _close_ssh_proc(proc, sock):
    """Carefully close stdin/stdout and reap the SSH process.

    If the pipes are already closed and/or the process has already been
    wait()ed on, that's ok, and no error is raised.  The goal is to do our best
    to clean up (whether or not a clean up was already tried).

    Args:
        proc: The subprocess.Popen instance to clean up.
        sock: Optional socket to close (may be None).

    Note:
        Silently ignores OSError exceptions during cleanup to handle
        already-closed resources gracefully.
    """
    funcs = []
    for closeable in (proc.stdin, proc.stdout, sock):
        # We expect that either proc (a subprocess.Popen) will have stdin and
        # stdout streams to close, or that we will have been passed a socket to
        # close, with the option not in use being None.
        if closeable is not None:
            funcs.append(closeable.close)
    funcs.append(proc.wait)
    for func in funcs:
        try:
            func()
        except OSError:
            # It's ok for the pipe to already be closed, or the process to
            # already be finished.
            continue


class SSHConnection:
    """Abstract base class for SSH connections."""

    def get_sock_or_pipes(self):
        """Returns a (kind, io_object) pair.

        If kind == 'socket', then io_object is a socket.

        If kind == 'pipes', then io_object is a pair of file-like objects
        (read_from, write_to).

        Returns:
            tuple: A (kind, io_object) pair where:
                - kind is either 'socket' or 'pipes'
                - io_object is either a socket or (read_file, write_file) tuple
        """
        raise NotImplementedError(self.get_sock_or_pipes)

    def close(self):
        """Close the SSH connection.

        Subclasses must implement this method to properly close their
        connection type.
        """
        raise NotImplementedError(self.close)


class SSHSubprocessConnection(SSHConnection):
    """A connection to an ssh subprocess via pipes or a socket.

    This class is also socket-like enough to be used with
    SocketAsChannelAdapter (it has 'send' and 'recv' methods).
    """

    def __init__(self, proc, sock=None):
        """Constructor.

        :param proc: a subprocess.Popen
        :param sock: if proc.stdin/out is a socket from a socketpair, then sock
            should breezy's half of that socketpair.  If not passed, proc's
            stdin/out is assumed to be ordinary pipes.
        """
        self.proc = proc
        self._sock = sock
        # Add a weakref to proc that will attempt to do the same as self.close
        # to avoid leaving processes lingering indefinitely.

        def terminate(ref):
            _subproc_weakrefs.remove(ref)
            _close_ssh_proc(proc, sock)

        _subproc_weakrefs.add(weakref.ref(self, terminate))

    def send(self, data):
        """Send data through the connection.

        Uses either socket.send() or os.write() depending on the
        connection type.

        Args:
            data: Bytes to send.

        Returns:
            int: Number of bytes sent.
        """
        if self._sock is not None:
            return self._sock.send(data)
        else:
            return os.write(self.proc.stdin.fileno(), data)

    def recv(self, count):
        """Receive data from the connection.

        Uses either socket.recv() or os.read() depending on the
        connection type.

        Args:
            count: Maximum number of bytes to receive.

        Returns:
            bytes: Data received from the connection.
        """
        if self._sock is not None:
            return self._sock.recv(count)
        else:
            return os.read(self.proc.stdout.fileno(), count)

    def close(self):
        """Close the SSH subprocess connection.

        Delegates to _close_ssh_proc to handle cleanup of the subprocess
        and any associated sockets or pipes.
        """
        _close_ssh_proc(self.proc, self._sock)

    def get_sock_or_pipes(self):
        """Get the underlying I/O objects for this connection.

        Returns:
            tuple: A (kind, io_object) pair where:
                - If using socketpair: ('socket', socket_object)
                - If using pipes: ('pipes', (stdout_pipe, stdin_pipe))
        """
        if self._sock is not None:
            return "socket", self._sock
        else:
            return "pipes", (self.proc.stdout, self.proc.stdin)
