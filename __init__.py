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

To enable this plugin, add a section to your location.conf
like::

    [/home/user/proj]
    changelog_merge_files = ChangeLog

Or add an entry to your branch.conf like::

    changelog_merge_files = ChangeLog

The changelog_merge_files config option takes a list of file names (not paths),
separated by commas.  (This is unlike the news_merge plugin, which matches
paths.)  e.g. the above config examples would match both
``src/foolib/ChangeLog`` and ``docs/ChangeLog``.

The algorithm this implements is very simple: it emits all the entries in OTHER
that are new compared to the common base version, followed by all the entries
in THIS.  The effect of this is to float new entries from the file being merged
in to the top of the ChangeLog.

    e.g. Given a changelog in THIS containing::

      NEW-1
      OLD-2
      OLD-1

    and a changelog in OTHER containing::

      NEW-2
      OLD-1

    it will merge as::

      NEW-2
      NEW-1
      OLD-2
      OLD-1

This has some limitations:

 * it makes no effort to detect deletions or modifications to existing entries,
   and so never conflicts.
 * it makes no effort to deduplicate entries added by both sides.
 * the results depend on the choice of the 'base' version, so it might give
   strange results if there is a criss-cross merge.
"""

version_info = (0, 0, 1, 'beta', 1)

# Put most of the code in a separate module that we lazy-import to keep the
# overhead of this plugin as minimal as possible.
from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib.plugins.changelog_merge import changelog_merge as _mod_changelog_merge
""")


def changelog_merge_hook(merger):
    """Merger.merge_file_content hook for GNU-format ChangeLog files."""
    return _mod_changelog_merge.ChangeLogMerger(merger)


def install_hook():
    from bzrlib.merge import Merger
    Merger.hooks.install_named_hook(
        'merge_file_content', changelog_merge_hook, 'GNU ChangeLog file merge')
install_hook()


def load_tests(basic_tests, module, loader):
    testmod_names = [
        'tests',
        ]
    basic_tests.addTest(loader.loadTestsFromModuleNames(
            ["%s.%s" % (__name__, tmn) for tmn in testmod_names]))
    return basic_tests

