# Copyright (C) 2008, 2009, 2011 Canonical Ltd
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

"""Directory service registration and usage.

Directory services are utilities that provide a mapping from URL-like strings
to true URLs.  Examples include lp:urls and per-user location aliases.
"""

from collections.abc import Callable

from . import branch as _mod_branch
from . import errors, registry
from .lazy_import import lazy_import

lazy_import(
    globals(),
    """
from breezy import (
    controldir as _mod_controldir,
    urlutils,
    )
""",
)


class DirectoryLookupFailure(errors.BzrError):
    """Base type for lookup errors."""


class InvalidLocationAlias(DirectoryLookupFailure):
    _fmt = '"%(alias_name)s" is not a valid location alias.'

    def __init__(self, alias_name):
        DirectoryLookupFailure.__init__(self, alias_name=alias_name)


class UnsetLocationAlias(DirectoryLookupFailure):
    _fmt = "No %(alias_name)s location assigned."

    def __init__(self, alias_name):
        DirectoryLookupFailure.__init__(self, alias_name=alias_name[1:])


class DirectoryServiceRegistry(registry.Registry):
    """This object maintains and uses a list of directory services.

    Directory services may be registered via the standard Registry methods.
    They will be invoked if their key is a prefix of the supplied URL.

    Each item registered should be a factory of objects that provide a look_up
    method, as invoked by dereference.  Specifically, look_up should accept a
    name and URL, and return a URL.
    """

    def dereference(self, url, purpose=None):
        """Dereference a supplied URL if possible.

        URLs that match a registered directory service prefix are looked up in
        it.  Non-matching urls are returned verbatim.

        This is applied only once; the resulting URL must not be one that
        requires further dereferencing.

        :param url: The URL to dereference
        :param purpose: Purpose of the URL ('read', 'write' or None - if not declared)
        :return: The dereferenced URL if applicable, the input URL otherwise.
        """
        match = self.get_prefix(url)
        if match is None:
            return url
        service, name = match
        directory = service()
        try:
            return directory.look_up(name, url, purpose=purpose)
        except TypeError:
            # Compatibility for plugins written for Breezy < 3.0.0
            return directory.look_up(name, url)


directories = DirectoryServiceRegistry()


class Directory:
    """Abstract directory lookup class."""

    def look_up(self, name, url, purpose=None):
        """Look up an entry in a directory.

        :param name: Directory name
        :param url: The URL to dereference
        :param purpose: Purpose of the URL ('read', 'write' or None - if not declared)
        :return: The dereferenced URL if applicable, the input URL otherwise.
        """
        raise NotImplementedError(self.look_up)


class AliasDirectory(Directory):
    """Directory lookup for locations associated with a branch.

    :parent, :submit, :public, :push, :this, and :bound are currently
    supported.  On error, a subclass of DirectoryLookupFailure will be raised.
    """

    branch_aliases = registry.Registry[
        str, Callable[[_mod_branch.Branch], str | None]
    ]()
    branch_aliases.register(
        "parent", lambda b: b.get_parent(), help="The parent of this branch."
    )
    branch_aliases.register(
        "submit",
        lambda b: b.get_submit_branch(),
        help="The submit branch for this branch.",
    )
    branch_aliases.register(
        "public",
        lambda b: b.get_public_branch(),
        help="The public location of this branch.",
    )
    branch_aliases.register(
        "bound",
        lambda b: b.get_bound_location(),
        help="The branch this branch is bound to, for bound branches.",
    )
    branch_aliases.register(
        "push",
        lambda b: b.get_push_location(),
        help="The saved location used for `brz push` with no arguments.",
    )
    branch_aliases.register("this", lambda b: b.base, help="This branch.")

    def look_up(self, name, url, purpose=None):
        branch = _mod_branch.Branch.open_containing(".")[0]
        parts = url.split("/", 1)
        if len(parts) == 2:
            name, extra = parts
        else:
            (name,) = parts
            extra = None
        try:
            method = self.branch_aliases.get(name[1:])
        except KeyError:
            raise InvalidLocationAlias(url)
        else:
            result = method(branch)
        if result is None:
            raise UnsetLocationAlias(url)
        if extra is not None:
            result = urlutils.join(result, extra)
        return result

    @classmethod
    def help_text(cls, topic):
        alias_lines = []
        for key in cls.branch_aliases.keys():
            help = cls.branch_aliases.get_help(key)
            alias_lines.append(f"  :{key:<10}{help}\n")
        return """\
Location aliases
================

Bazaar defines several aliases for locations associated with a branch.  These
can be used with most commands that expect a location, such as `brz push`.

The aliases are::

{}
For example, to push to the parent location::

    brz push :parent
""".format("".join(alias_lines))


directories.register(":", AliasDirectory, "Easy access to remembered branch locations")


class ColocatedDirectory(Directory):
    """Directory lookup for colocated branches.

    co:somename will resolve to the colocated branch with "somename" in
    the current directory.
    """

    def look_up(self, name, url, purpose=None):
        dir = _mod_controldir.ControlDir.open_containing(".")[0]
        return urlutils.join_segment_parameters(
            dir.user_url, {"branch": urlutils.escape(name)}
        )


directories.register("co:", ColocatedDirectory, "Easy access to colocated branches")
