# Copyright (C) 2007, 2008 Canonical Ltd
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


"""Support for plugin hooking logic."""
from bzrlib.lazy_import import lazy_import
from bzrlib.symbol_versioning import deprecated_method, one_five
lazy_import(globals(), """
import textwrap

from bzrlib import (
        _format_version_tuple,
        errors,
        )
""")


class Hooks(dict):
    """A dictionary mapping hook name to a list of callables.

    e.g. ['FOO'] Is the list of items to be called when the
    FOO hook is triggered.
    """

    def __init__(self):
        dict.__init__(self)
        self._callable_names = {}

    def create_hook(self, hook):
        """Create a hook which can have callbacks registered for it.

        :param hook: The hook to create. An object meeting the protocol of
            bzrlib.hooks.HookPoint. It's name is used as the key for future
            lookups.
        """
        if hook.name in self:
            raise errors.DuplicateKey(hook.name)
        self[hook.name] = hook

    def docs(self):
        """Generate the documentation for this Hooks instance.

        This introspects all the individual hooks and returns their docs as well.
        """
        hook_names = sorted(self.keys())
        hook_docs = []
        name = self.__class__.__name__
        hook_docs.append(name)
        hook_docs.append("="*len(name))
        hook_docs.append("")
        for hook_name in hook_names:
            hook = self[hook_name]
            try:
                hook_docs.append(hook.docs())
            except AttributeError:
                # legacy hook
                strings = []
                strings.append(hook_name)
                strings.append("-" * len(hook_name))
                strings.append("")
                strings.append("An old-style hook. For documentation see the __init__ "
                    "method of '%s'\n" % (name,))
                hook_docs.extend(strings)
        return "\n".join(hook_docs)

    def get_hook_name(self, a_callable):
        """Get the name for a_callable for UI display.

        If no name has been registered, the string 'No hook name' is returned.
        We use a fixed string rather than repr or the callables module because
        the code names are rarely meaningful for end users and this is not
        intended for debugging.
        """
        return self._callable_names.get(a_callable, "No hook name")

    @deprecated_method(one_five)
    def install_hook(self, hook_name, a_callable):
        """Install a_callable in to the hook hook_name.

        :param hook_name: A hook name. See the __init__ method of BranchHooks
            for the complete list of hooks.
        :param a_callable: The callable to be invoked when the hook triggers.
            The exact signature will depend on the hook - see the __init__
            method of BranchHooks for details on each hook.
        """
        self.install_named_hook(hook_name, a_callable, None)

    def install_named_hook(self, hook_name, a_callable, name):
        """Install a_callable in to the hook hook_name, and label it name.

        :param hook_name: A hook name. See the __init__ method of BranchHooks
            for the complete list of hooks.
        :param a_callable: The callable to be invoked when the hook triggers.
            The exact signature will depend on the hook - see the __init__
            method of BranchHooks for details on each hook.
        :param name: A name to associate a_callable with, to show users what is
            running.
        """
        try:
            hook = self[hook_name]
        except KeyError:
            raise errors.UnknownHook(self.__class__.__name__, hook_name)
        try:
            # list hooks, old-style, not yet deprecated but less useful.
            hook.append(a_callable)
        except AttributeError:
            hook.hook(a_callable, name)
        if name is not None:
            self.name_hook(a_callable, name)

    def name_hook(self, a_callable, name):
        """Associate name with a_callable to show users what is running."""
        self._callable_names[a_callable] = name


class HookPoint(object):
    """A single hook that clients can register to be called back when it fires.

    :ivar name: The name of the hook.
    :ivar introduced: A version tuple specifying what version the hook was
        introduced in. None indicates an unknown version.
    :ivar deprecated: A version tuple specifying what version the hook was
        deprecated or superceded in. None indicates that the hook is not
        superceded or deprecated. If the hook is superceded then the doc
        should describe the recommended replacement hook to register for.
    :ivar doc: The docs for using the hook.
    """

    def __init__(self, name, doc, introduced, deprecated):
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
        self._callbacks = []
        self._callback_names = {}

    def docs(self):
        """Generate the documentation for this HookPoint.

        :return: A string terminated in \n.
        """
        strings = []
        strings.append(self.name)
        strings.append('-'*len(self.name))
        strings.append('')
        if self.introduced:
            introduced_string = _format_version_tuple(self.introduced)
        else:
            introduced_string = 'unknown'
        strings.append('Introduced in: %s' % introduced_string)
        if self.deprecated:
            deprecated_string = _format_version_tuple(self.deprecated)
        else:
            deprecated_string = 'Not deprecated'
        strings.append('Deprecated in: %s' % deprecated_string)
        strings.append('')
        strings.extend(textwrap.wrap(self.__doc__))
        strings.append('')
        return '\n'.join(strings)

    def hook(self, callback, callback_label):
        """Register a callback to be called when this HookPoint fires.

        :param callback: The callable to use when this HookPoint fires.
        :param callback_label: A label to show in the UI while this callback is
            processing.
        """
        self._callbacks.append(callback)
        self._callback_names[callback] = callback_label

    def __iter__(self):
        return iter(self._callbacks)

    def __repr__(self):
        strings = []
        strings.append("<%s(" % type(self).__name__)
        strings.append(self.name)
        strings.append("), callbacks=[")
        for callback in self._callbacks:
            strings.append(repr(callback))
            strings.append("(")
            strings.append(self._callback_names[callback])
            strings.append("),")
        if len(self._callbacks) == 1:
            strings[-1] = ")"
        strings.append("]>")
        return ''.join(strings)
