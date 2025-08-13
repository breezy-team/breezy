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

import getpass
import logging
import os
from binascii import hexlify

import paramiko

from ... import bedding, config, errors, osutils, trace, ui
from . import SSHConnection, SSHVendor

SYSTEM_HOSTKEYS: dict[str, dict[str, str]] = {}
BRZ_HOSTKEYS: dict[str, dict[str, str]] = {}


def _paramiko_auth(username, password, host, port, paramiko_transport):
    auth = config.AuthenticationConfig()
    # paramiko requires a username, but it might be none if nothing was
    # supplied.  If so, use the local username.
    if username is None:
        username = auth.get_user("ssh", host, port=port, default=getpass.getuser())
    agent = paramiko.Agent()
    for key in agent.get_keys():
        trace.mutter(f"Trying SSH agent key {hexlify(key.get_fingerprint()).upper()}")
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
        raise ConnectionError(
            "Unable to authenticate to SSH host as"
            f"\n  {username}@{host}\nsupported auth types: {supported_auth_types}"
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
            raise ConnectionError(
                f"Unable to authenticate to SSH host as\n  {username}@{host}\n", e
            ) from e
    else:
        raise ConnectionError(
            f"Unable to authenticate to SSH host as  {username}@{host}"
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
                f"SSH authentication via {os.path.basename(filename)} key failed."
            )
    except paramiko.SSHException:
        trace.mutter(f"SSH authentication via {os.path.basename(filename)} key failed.")
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
                    f.write(f"{hostname} {keytype} {key.get_base64()}\n")
    except OSError as e:
        trace.mutter("failed to save bzr host keys: " + str(e))


class ParamikoVendor(SSHVendor):
    """Vendor that uses paramiko."""

    def _hexify(self, s):
        return hexlify(s).upper()

    def _connect(self, username, password, host, port):
        global SYSTEM_HOSTKEYS, BRZ_HOSTKEYS

        from .paramiko import (
            _paramiko_auth,
            _ssh_host_keys_config_dir,
            load_host_keys,
            save_host_keys,
        )

        load_host_keys()

        try:
            t = paramiko.Transport((host, port or 22))
            t.set_log_channel("bzr.paramiko")
            t.start_client()
        except (paramiko.SSHException, OSError) as e:
            self._raise_connection_error(host, port=port, orig_error=e)

        server_key = t.get_remote_server_key()
        server_key_hex = self._hexify(server_key.get_fingerprint())
        keytype = server_key.get_name()
        if host in SYSTEM_HOSTKEYS and keytype in SYSTEM_HOSTKEYS[host]:
            our_server_key = SYSTEM_HOSTKEYS[host][keytype]
            our_server_key_hex = self._hexify(our_server_key.get_fingerprint())
        elif host in BRZ_HOSTKEYS and keytype in BRZ_HOSTKEYS[host]:
            our_server_key = BRZ_HOSTKEYS[host][keytype]
            our_server_key_hex = self._hexify(our_server_key.get_fingerprint())
        else:
            trace.warning(f"Adding {keytype} host key for {host}: {server_key_hex}")
            add = getattr(BRZ_HOSTKEYS, "add", None)
            if add is not None:  # paramiko >= 1.X.X
                BRZ_HOSTKEYS.add(host, keytype, server_key)
            else:
                BRZ_HOSTKEYS.setdefault(host, {})[keytype] = server_key
            our_server_key = server_key
            our_server_key_hex = self._hexify(our_server_key.get_fingerprint())
            save_host_keys()
        if server_key != our_server_key:
            filename1 = os.path.expanduser("~/.ssh/known_hosts")
            filename2 = _ssh_host_keys_config_dir()
            raise errors.TransportError(
                f"Host keys for {host} do not match!  {our_server_key_hex} != {server_key_hex}",
                [f"Try editing {filename1} or {filename2}"],
            )

        _paramiko_auth(username, password, host, port, t)
        return t

    def connect_sftp(self, username, password, host, port):
        t = self._connect(username, password, host, port)
        try:
            return t.open_sftp_client()
        except paramiko.SSHException as e:
            self._raise_connection_error(
                host, port=port, orig_error=e, msg="Unable to start sftp client"
            )

    def connect_ssh(self, username, password, host, port, command):
        t = self._connect(username, password, host, port)
        try:
            channel = t.open_session()
            cmdline = " ".join(command)
            channel.exec_command(cmdline)
            return _ParamikoSSHConnection(channel)
        except paramiko.SSHException as e:
            self._raise_connection_error(
                host, port=port, orig_error=e, msg="Unable to invoke remote bzr"
            )


class _ParamikoSSHConnection(SSHConnection):
    """An SSH connection via paramiko."""

    def __init__(self, channel):
        self.channel = channel

    def get_sock_or_pipes(self):
        return ("socket", self.channel)

    def close(self):
        return self.channel.close()


paramiko_vendor = ParamikoVendor()
