# Copyright (C) 2005-2012, 2016 Canonical Ltd
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

"""Configuration integration points for dromedary.

Embedders should replace these functions to provide config/auth.
The defaults provide basic functionality using the standard library.
"""

import getpass


def get_ssh_vendor_name():
    """Return the configured SSH vendor name, or None for auto-detect."""
    return None


def get_auth_user(scheme, host, port=None, default=None, ask=False, prompt=None):
    """Get username for authentication.

    Default: returns default, or falls back to the system username.
    """
    if default is not None:
        return default
    return getpass.getuser()


def get_auth_password(scheme, host, user, port=None):
    """Get password for authentication.

    Default: prompts via getpass.
    """
    return getpass.getpass(f"Password for {user}@{host}: ")
