# Copyright (C) 2005 Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
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

"""This module provides an IdentityMap."""

from . import errors


class IdentityMap:
    """An in memory map from object id to instance.

    An IdentityMap maps from keys to single instances of objects in memory.
    We have explicit calls on the map for the root of each inheritance tree
    that is store in the map. Look for find_CLASS and add_CLASS methods.
    """

    def add_weave(self, id, weave):
        """Add weave to the map with a given id."""
        if self._weave_key(id) in self._map:
            raise errors.BzrError(f"weave {id} already in the identity map")
        self._map[self._weave_key(id)] = weave
        self._reverse_map[weave] = self._weave_key(id)

    def find_weave(self, id):
        """Return the weave for 'id', or None if it is not present."""
        return self._map.get(self._weave_key(id), None)

    def __init__(self) -> None:
        """Initialize an empty IdentityMap.

        Creates internal dictionaries for mapping objects by their keys
        and reverse mapping from objects to their keys.
        """
        super().__init__()
        self._map: dict[object, object] = {}
        self._reverse_map: dict[object, object] = {}

    def remove_object(self, an_object: object):
        """Remove object from map."""
        if isinstance(an_object, list):
            raise KeyError(f"{an_object!r} not in identity map")
        else:
            self._map.pop(self._reverse_map[an_object])
            self._reverse_map.pop(an_object)

    def _weave_key(self, id):
        """Return the key for a weaves id."""
        return "weave-" + id


class NullIdentityMap:
    """A pretend in memory map from object id to instance.

    A NullIdentityMap is an Identity map that does not store anything in it.
    """

    def add_weave(self, id, weave):
        """See IdentityMap.add_weave."""

    def find_weave(self, id):
        """See IdentityMap.find_weave."""
        return None
