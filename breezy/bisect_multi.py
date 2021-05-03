# Copyright (C) 2007 Canonical Ltd
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

"""Bisection lookup multiple keys."""

__all__ = [
    'bisect_multi_bytes',
    ]


def bisect_multi_bytes(content_lookup, size, keys):
    """Perform bisection lookups for keys using byte based addressing.

    The keys are looked up via the content_lookup routine. The content_lookup
    routine gives bisect_multi_bytes information about where to keep looking up
    to find the data for the key, and bisect_multi_bytes feeds this back into
    the lookup function until the search is complete. The search is complete
    when the list of keys which have returned something other than -1 or +1 is
    empty. Keys which are not found are not returned to the caller.

    :param content_lookup: A callable that takes a list of (offset, key) pairs
        and returns a list of result tuples ((offset, key), result). Each
        result can be one of:
          -1: The key comes earlier in the content.
          False: The key is not present in the content.
          +1: The key comes later in the content.
          Any other value: A final result to return to the caller.
    :param size: The length of the content.
    :param keys: The keys to bisect for.
    :return: An iterator of the results.
    """
    # possibly make this a generator, but a list meets the contract for now.
    result = []
    delta = size // 2
    search_keys = [(delta, key) for key in keys]
    while search_keys:
        search_results = content_lookup(search_keys)
        if delta > 1:
            delta = delta // 2
        search_keys = []
        for (location, key), status in search_results:
            if status == -1:
                search_keys.append((location - delta, key))
            elif status == 1:
                search_keys.append((location + delta, key))
            elif status is False:
                # not present, stop searching
                continue
            else:
                result.append((key, status))
    return result
