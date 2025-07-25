# Copyright (C) 2010 Canonical Ltd
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

__doc__ = """Merge hook for GNU-format ChangeLog files

To enable this plugin, add a section to your locations.conf
like::

    [/home/user/proj]
    changelog_merge_files = ChangeLog

Or add an entry to your branch.conf like::

    changelog_merge_files = ChangeLog

The changelog_merge_files config option takes a list of file names (not paths),
separated by commas.  (This is unlike the news_merge plugin, which matches
paths.)  e.g. the above config examples would match both
``src/foolib/ChangeLog`` and ``docs/ChangeLog``.

The algorithm used to merge the changes can be summarised as:

 * new entries added to the top of OTHER are emitted first
 * all other additions, deletions and edits from THIS and OTHER are preserved
 * edits (e.g. to fix typos) at the top of OTHER are hard to distinguish from
   adding and deleting independent entries; the algorithm tries to guess which
   based on how similar the old and new entries are.

Caveats
-------

Most changes can be merged, but conflicts are possible if the plugin finds
edits at the top of OTHER to entries that have been deleted (or also edited) by
THIS.  In that case the plugin gives up and bzr's default merge logic will be
used.

No effort is made to deduplicate entries added by both sides.

The results depend on the choice of the 'base' version, so it might give
strange results if there is a criss-cross merge.
"""

# Since we are a built-in plugin we share the breezy version
from ... import version_info  # noqa: F401
from ...hooks import install_lazy_named_hook

# Put most of the code in a separate module that we lazy-import to keep the
# overhead of this plugin as minimal as possible.


def changelog_merge_hook(merger):
    """Merger.merge_file_content hook for GNU-format ChangeLog files."""
    from ...plugins.changelog_merge.changelog_merge import ChangeLogMerger

    return ChangeLogMerger(merger)


install_lazy_named_hook(
    "breezy.merge",
    "Merger.hooks",
    "merge_file_content",
    changelog_merge_hook,
    "GNU ChangeLog file merge",
)


def load_tests(loader, basic_tests, pattern):
    testmod_names = [
        "tests",
    ]
    for tmn in testmod_names:
        basic_tests.addTest(loader.loadTestsFromName(f"{__name__}.{tmn}"))
    return basic_tests
