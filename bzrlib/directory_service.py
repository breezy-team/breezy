# Copyright (C) 2008 Canonical Ltd
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

"""Directory service registration and usage.

Directory services are utilities that provide a mapping from URL-like strings
to true URLs.  Examples include lp:urls and per-user location aliases.
"""

from bzrlib import errors, registry
from bzrlib.branch import Branch

class DirectoryServiceRegistry(registry.Registry):
    """This object maintains and uses a list of directory services.

    Directory services may be registered via the standard Registry methods.
    They will be invoked if their key is a prefix of the supplied URL.

    Each item registered should be a factory of objects that provide a look_up
    method, as invoked by dereference.  Specifically, look_up should accept a
    name and URL, and return a URL.
    """

    def dereference(self, url):
        """Dereference a supplied URL if possible.

        URLs that match a registered directory service prefix are looked up in
        it.  Non-matching urls are returned verbatim.

        This is applied only once; the resulting URL must not be one that
        requires further dereferencing.

        :param url: The URL to dereference
        :return: The dereferenced URL if applicable, the input URL otherwise.
        """
        match = self.get_prefix(url)
        if match is None:
            return url
        service, name = match
        return service().look_up(name, url)

directories = DirectoryServiceRegistry()


class AliasDirectory(object):
    """Directory lookup for locations associated with a branch.

    :parent, :submit, :public, :push, :this, and :bound are currently
    supported.  On error, a subclass of DirectoryLookupFailure will be raised.
    """

    def look_up(self, name, url):
        branch = Branch.open_containing('.')[0]
        lookups = {
            'parent': branch.get_parent,
            'submit': branch.get_submit_branch,
            'public': branch.get_public_branch,
            'bound': branch.get_bound_location,
            'push': branch.get_push_location,
            'this': lambda: branch.base
        }
        try:
            method = lookups[url[1:]]
        except KeyError:
            raise errors.InvalidLocationAlias(url)
        else:
            result = method()
        if result is None:
            raise errors.UnsetLocationAlias(url)
        return result

directories.register(':', AliasDirectory,
                     'Easy access to remembered branch locations')
