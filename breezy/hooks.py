# Copyright (C) 2007-2011 Canonical Ltd
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

"""Support for plugin hooking logic.

This module provides the infrastructure for hooks that allow plugins to
extend or modify the behavior of breezy operations. Hooks are registered
at specific points in the codebase and can be used to customize behavior
without modifying core code.
"""

__docformat__ = "google"

from . import errors

# The subclass exists to expose the hook's doc as the instance __doc__, which
# is a read-only type slot on the native class.
from ._cmd_rs.hooks import HookPoint as _RustHookPoint
from .pyutils import get_named_object


class HookPoint(_RustHookPoint):
    """A single hook that clients can register to be called back when it fires."""

    def __init__(self, name, doc, introduced, deprecated=None, lazy_key=None):
        """Create a HookPoint; see breezy._cmd_rs.hooks.HookPoint."""
        self.__doc__ = doc


class UnknownHook(errors.BzrError):
    """Error raised when an unknown hook is referenced."""

    _fmt = "The %(type)s hook '%(hook)s' is unknown in this version of breezy."

    def __init__(self, hook_type, hook_name):
        """Initialize UnknownHook.

        Args:
            hook_type: The type of hook.
            hook_name: The name of the unknown hook.
        """
        errors.BzrError.__init__(self)
        self.type = hook_type
        self.hook = hook_name


from ._cmd_rs.hooks import KnownHooksRegistry
from ._cmd_rs.hooks import register_known_hooks as _register_known_hooks

known_hooks = KnownHooksRegistry()
_register_known_hooks(known_hooks)


def known_hooks_key_to_object(key):
    """Convert a known_hooks key to a object.

    :param key: A tuple (module_name, member_name) as found in the keys of
        the known_hooks registry.
    :return: The object this specifies.
    """
    return get_named_object(*key)


# The values in a Hooks mapping are either plain lists (old-style) or
# HookPoints (new-style).
from ._cmd_rs.hooks import Hooks  # noqa: F401

_help_prefix = """
Hooks
=====

Introduction
------------

A hook of type *xxx* of class *yyy* needs to be registered using::

  yyy.hooks.install_named_hook("xxx", ...)

See :doc:`Using hooks<../user-guide/hooks>` in the User Guide for examples.

The class that contains each hook is given before the hooks it supplies. For
instance, BranchHooks as the class is the hooks class for
`breezy.branch.Branch.hooks`.

Each description also indicates whether the hook runs on the client (the
machine where bzr was invoked) or the server (the machine addressed by
the branch URL).  These may be, but are not necessarily, the same machine.

Plugins (including hooks) are run on the server if all of these is true:

  * The connection is via a smart server (accessed with a URL starting with
    "bzr://", "bzr+ssh://" or "bzr+http://", or accessed via a "http://"
    URL when a smart server is available via HTTP).

  * The hook is either server specific or part of general infrastructure rather
    than client specific code (such as commit).

"""


def hooks_help_text(topic):
    """Generate help text for hooks.

    Args:
        topic: The help topic (unused but required by help system).

    Returns:
        String containing formatted help text for all known hooks.
    """
    segments = [_help_prefix]
    for hook_key in sorted(known_hooks.keys()):
        hooks = known_hooks_key_to_object(hook_key)
        segments.append(hooks.docs())
    return "\n".join(segments)


# Support for installing hooks before the hooks object defining the hook point
# is imported.
from ._cmd_rs.hooks import (
    install_lazy_named_hook,  # noqa: F401
    lazy_hook_keys,  # noqa: F401
    swap_lazy_hooks,  # noqa: F401
)
