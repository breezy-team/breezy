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

from catalogus.registry import _LazyObjectGetter, _ObjectGetter
from catalogus.pyutils import calc_parent_name, get_named_object

from . import errors, registry
from .lazy_import import lazy_import

lazy_import(
    globals(),
    """
from breezy import (
    _format_version_tuple,
    )
from breezy.i18n import gettext
""",
)


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


class KnownHooksRegistry(registry.Registry[str, "Hooks", None]):
    """Registry for all known hook points in breezy.

    This registry maps hook points to their location and provides utilities
    for managing the collection of known hooks.
    """

    # known_hooks registry contains
    # tuple of (module, member name) which is the hook point
    # module where the specific hooks are defined
    # callable to get the empty specific Hooks for that attribute

    def register_lazy_hook(
        self, hook_module_name, hook_member_name, hook_factory_member_name
    ):
        """Register a hook lazily to avoid circular imports.

        Args:
            hook_module_name: Module containing the hook point.
            hook_member_name: Member name of the hook point.
            hook_factory_member_name: Factory function to create the hook.
        """
        self.register_lazy(
            (hook_module_name, hook_member_name),
            hook_module_name,
            hook_factory_member_name,
        )

    def iter_parent_objects(self):
        """Yield (hook_key, (parent_object, attr)) tuples for every registered
        hook, where 'parent_object' is the object that holds the hook
        instance.

        This is useful for resetting/restoring all the hooks to a known state,
        as is done in breezy.tests.TestCase._clear_hooks.
        """
        for key in self.keys():
            yield key, self.key_to_parent_and_attribute(key)

    def key_to_parent_and_attribute(self, key):
        """Convert a known_hooks key to a (parent_obj, attr) pair.

        :param key: A tuple (module_name, member_name) as found in the keys of
            the known_hooks registry.
        :return: The parent_object of the hook and the name of the attribute on
            that parent object where the hook is kept.
        """
        parent_mod, parent_member, attr = calc_parent_name(*key)
        return get_named_object(parent_mod, parent_member), attr


_builtin_known_hooks = (
    ("breezy.branch", "Branch.hooks", "BranchHooks"),
    ("breezy.controldir", "ControlDir.hooks", "ControlDirHooks"),
    ("breezy.commands", "Command.hooks", "CommandHooks"),
    ("breezy.config", "ConfigHooks", "_ConfigHooks"),
    ("breezy.info", "hooks", "InfoHooks"),
    ("breezy.lock", "Lock.hooks", "LockHooks"),
    ("breezy.merge", "Merger.hooks", "MergeHooks"),
    ("breezy.msgeditor", "hooks", "MessageEditorHooks"),
    ("breezy.mutabletree", "MutableTree.hooks", "MutableTreeHooks"),
    ("breezy.bzr.smart.client", "_SmartClient.hooks", "SmartClientHooks"),
    ("breezy.bzr.smart.server", "SmartTCPServer.hooks", "SmartServerHooks"),
    ("breezy.status", "hooks", "StatusHooks"),
    ("breezy.transport", "Transport.hooks", "TransportHooks"),
    (
        "breezy.version_info_formats.format_rio",
        "RioVersionInfoBuilder.hooks",
        "RioVersionInfoBuilderHooks",
    ),
    ("breezy.merge_directive", "BaseMergeDirective.hooks", "MergeDirectiveHooks"),
)

known_hooks = KnownHooksRegistry()
for _hook_module, _hook_attribute, _hook_class in _builtin_known_hooks:
    known_hooks.register_lazy_hook(_hook_module, _hook_attribute, _hook_class)
del _builtin_known_hooks, _hook_module, _hook_attribute, _hook_class


def known_hooks_key_to_object(key):
    """Convert a known_hooks key to a object.

    :param key: A tuple (module_name, member_name) as found in the keys of
        the known_hooks registry.
    :return: The object this specifies.
    """
    return get_named_object(*key)


class Hooks(dict):
    """A dictionary mapping hook name to a list of callables.

    e.g. ['FOO'] Is the list of items to be called when the
    FOO hook is triggered.
    """

    def __init__(self, module=None, member_name=None):
        """Create a new hooks dictionary.

        :param module: The module from which this hooks dictionary should be loaded
            (used for lazy hooks)
        :param member_name: Name under which this hooks dictionary should be loaded.
            (used for lazy hooks)
        """
        dict.__init__(self)
        self._callable_names = {}
        self._lazy_callable_names = {}
        self._module = module
        self._member_name = member_name

    def add_hook(self, name, doc, introduced, deprecated=None):
        """Add a hook point to this dictionary.

        :param name: The name of the hook, for clients to use when registering.
        :param doc: The docs for the hook.
        :param introduced: When the hook was introduced (e.g. (0, 15)).
        :param deprecated: When the hook was deprecated, None for
            not-deprecated.
        """
        if name in self:
            raise errors.DuplicateKey(name)
        if self._module:
            callbacks = _lazy_hooks.setdefault(
                (self._module, self._member_name, name), []
            )
        else:
            callbacks = None
        hookpoint = HookPoint(
            name=name,
            doc=doc,
            introduced=introduced,
            deprecated=deprecated,
            callbacks=callbacks,
        )
        self[name] = hookpoint

    def docs(self):
        """Generate the documentation for this Hooks instance.

        This introspects all the individual hooks and returns their docs as well.
        """
        hook_names = sorted(self.keys())
        hook_docs = []
        name = self.__class__.__name__
        hook_docs.append(name)
        hook_docs.append("-" * len(name))
        hook_docs.append("")
        for hook_name in hook_names:
            hook = self[hook_name]
            hook_docs.append(hook.docs())
        return "\n".join(hook_docs)

    def get_hook_name(self, a_callable):
        """Get the name for a_callable for UI display.

        If no name has been registered, the string 'No hook name' is returned.
        We use a fixed string rather than repr or the callables module because
        the code names are rarely meaningful for end users and this is not
        intended for debugging.
        """
        name = self._callable_names.get(a_callable, None)
        if name is None and a_callable is not None:
            name = self._lazy_callable_names.get(
                (a_callable.__module__, a_callable.__name__), None
            )
        if name is None:
            return "No hook name"
        return name

    def install_named_hook_lazy(
        self, hook_name, callable_module, callable_member, name
    ):
        """Install a_callable in to the hook hook_name lazily, and label it.

        :param hook_name: A hook name. See the __init__ method for the complete
            list of hooks.
        :param callable_module: Name of the module in which the callable is
            present.
        :param callable_member: Member name of the callable.
        :param name: A name to associate the callable with, to show users what
            is running.
        """
        try:
            hook = self[hook_name]
        except KeyError as err:
            raise UnknownHook(self.__class__.__name__, hook_name) from err
        try:
            hook_lazy = hook.hook_lazy
        except AttributeError as err:
            raise errors.UnsupportedOperation(
                self.install_named_hook_lazy, self
            ) from err
        else:
            hook_lazy(callable_module, callable_member, name)
        if name is not None:
            self.name_hook_lazy(callable_module, callable_member, name)

    def install_named_hook(self, hook_name, a_callable, name):
        """Install a_callable in to the hook hook_name, and label it name.

        :param hook_name: A hook name. See the __init__ method for the complete
            list of hooks.
        :param a_callable: The callable to be invoked when the hook triggers.
            The exact signature will depend on the hook - see the __init__
            method for details on each hook.
        :param name: A name to associate a_callable with, to show users what is
            running.
        """
        try:
            hook = self[hook_name]
        except KeyError as err:
            raise UnknownHook(self.__class__.__name__, hook_name) from err
        try:
            # list hooks, old-style, not yet deprecated but less useful.
            hook.append(a_callable)
        except AttributeError:
            hook.hook(a_callable, name)
        if name is not None:
            self.name_hook(a_callable, name)

    def uninstall_named_hook(self, hook_name, label):
        """Uninstall named hooks.

        :param hook_name: Hook point name
        :param label: Label of the callable to uninstall
        """
        try:
            hook = self[hook_name]
        except KeyError as err:
            raise UnknownHook(self.__class__.__name__, hook_name) from err
        try:
            uninstall = hook.uninstall
        except AttributeError as err:
            raise errors.UnsupportedOperation(self.uninstall_named_hook, self) from err
        else:
            uninstall(label)

    def name_hook(self, a_callable, name):
        """Associate name with a_callable to show users what is running."""
        self._callable_names[a_callable] = name

    def name_hook_lazy(self, callable_module, callable_member, callable_name):
        """Associate a name with a lazily-loaded callable.

        Args:
            callable_module: Module containing the callable.
            callable_member: Member name of the callable.
            callable_name: Display name for the callable.
        """
        self._lazy_callable_names[(callable_module, callable_member)] = callable_name


class HookPoint:
    """A single hook that clients can register to be called back when it fires.

    Attributes:
      name: The name of the hook.
      doc: The docs for using the hook.
      introduced: A version tuple specifying what version the hook was
                      introduced in. None indicates an unknown version.
      deprecated: A version tuple specifying what version the hook was
                      deprecated or superseded in. None indicates that the hook
                      is not superseded or deprecated. If the hook is
                      superseded then the doc should describe the recommended
                      replacement hook to register for.
    """

    def __init__(self, name, doc, introduced, deprecated=None, callbacks=None):
        """Create a HookPoint.

        :param name: The name of the hook, for clients to use when registering.
        :param doc: The docs for the hook.
        :param introduced: When the hook was introduced (e.g. (0, 15)).
        :param deprecated: When the hook was deprecated, None for
            not-deprecated.
        """
        self.name = name
        self.__doc__ = doc
        self.introduced = introduced
        self.deprecated = deprecated
        if callbacks is None:
            self._callbacks = []
        else:
            self._callbacks = callbacks

    def docs(self):
        r"""Generate the documentation for this HookPoint.

        :return: A string terminated in \n.
        """
        import textwrap

        strings = []
        strings.append(self.name)
        strings.append("~" * len(self.name))
        strings.append("")
        if self.introduced:
            introduced_string = _format_version_tuple(self.introduced)
        else:
            introduced_string = "unknown"
        strings.append(gettext("Introduced in: %s") % introduced_string)
        if self.deprecated:
            deprecated_string = _format_version_tuple(self.deprecated)
            strings.append(gettext("Deprecated in: %s") % deprecated_string)
        strings.append("")
        strings.extend(textwrap.wrap(self.__doc__, break_long_words=False))
        strings.append("")
        return "\n".join(strings)

    def __eq__(self, other):
        """Return True if this HookPoint equals another."""
        return isinstance(other, type(self)) and other.__dict__ == self.__dict__

    def hook_lazy(self, callback_module, callback_member, callback_label):
        """Lazily register a callback to be called when this HookPoint fires.

        :param callback_module: Module of the callable to use when this
            HookPoint fires.
        :param callback_member: Member name of the callback.
        :param callback_label: A label to show in the UI while this callback is
            processing.
        """
        obj_getter = _LazyObjectGetter(callback_module, callback_member)
        self._callbacks.append((obj_getter, callback_label))

    def hook(self, callback, callback_label):
        """Register a callback to be called when this HookPoint fires.

        :param callback: The callable to use when this HookPoint fires.
        :param callback_label: A label to show in the UI while this callback is
            processing.
        """
        obj_getter = _ObjectGetter(callback)
        self._callbacks.append((obj_getter, callback_label))

    def uninstall(self, label):
        """Uninstall the callback with the specified label.

        :param label: Label of the entry to uninstall
        """
        entries_to_remove = []
        for entry in self._callbacks:
            (entry_callback, entry_label) = entry
            if entry_label == label:
                entries_to_remove.append(entry)
        if entries_to_remove == []:
            raise KeyError(f"No entry with label {label!r}")
        for entry in entries_to_remove:
            self._callbacks.remove(entry)

    def __iter__(self):
        """Iterate over registered callbacks."""
        return (callback.get_obj() for callback, name in self._callbacks)

    def __len__(self):
        """Return the number of registered callbacks."""
        return len(self._callbacks)

    def __repr__(self):
        """Return string representation of this HookPoint."""
        strings = []
        strings.append(f"<{type(self).__name__}(")
        strings.append(self.name)
        strings.append("), callbacks=[")
        callbacks = self._callbacks
        for callback, callback_name in callbacks:
            strings.append(repr(callback.get_obj()))
            strings.append("(")
            strings.append(callback_name)
            strings.append("),")
        if len(callbacks) == 1:
            strings[-1] = ")"
        strings.append("]>")
        return "".join(strings)


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


# Lazily registered hooks. Maps (module, name, hook_name) tuples
# to lists of tuples with objectgetters and names
_lazy_hooks: dict[tuple[str, str, str], list[tuple[_ObjectGetter, str]]] = {}


def install_lazy_named_hook(
    hookpoints_module, hookpoints_name, hook_name, a_callable, name
):
    """Install a callable in to a hook lazily, and label it name.

    :param hookpoints_module: Module name of the hook points.
    :param hookpoints_name: Name of the hook points.
    :param hook_name: A hook name.
    :param callable: a callable to call for the hook.
    :param name: A name to associate a_callable with, to show users what is
        running.
    """
    key = (hookpoints_module, hookpoints_name, hook_name)
    obj_getter = _ObjectGetter(a_callable)
    _lazy_hooks.setdefault(key, []).append((obj_getter, name))
