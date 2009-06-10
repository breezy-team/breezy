# Copyright (C) 2005, 2006, 2009 Canonical Ltd
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


"""Set of flags that enable different debug behaviour.

These are set with eg ``-Dlock`` on the bzr command line or in
~/.bazaar/bazaar.conf debug_flags.

See `bzr help debug-flags` or `bzrlib/help_topics/en/debug-flags.txt`
for a list of the available options.
"""


debug_flags = set()


def set_debug_flags_from_config():
    """Turn on debug flags based on the global configuration"""

    from bzrlib.config import GlobalConfig

    c = GlobalConfig()
    value = c.get_user_option("debug_flags")
    if value is not None:
        # configobject gives us either a string if there's just one or a list
        # if there's multiple
        if isinstance(value, basestring):
            value = [value]
        for w in value:
            w = w.strip()
            debug_flags.add(w)
