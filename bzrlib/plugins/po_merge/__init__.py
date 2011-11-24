# Copyright (C) 2011 Canonical Ltd
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

__doc__ = """Merge hook for ``.po`` files.

To enable this plugin, add a section to your branch.conf or location.conf
like::

    [/home/user/code/bzr]
    po_merge.pot_file = po/xxx.pot
    po_merge.po_files = po/*.po

The ``po_merge.pot_file`` config option takes a list of file paths, separated
by commas.

The ``po_merge.po_files`` config option takes a list of file globs, separated
by commas.

The ``po_merge.command`` is the command whose output is used as the result of
the merge. It defaults to::

   msgmerge -N "{other}" "{pot_file}" -C "{this}" -o "{result}"

where:

* ``this`` is the ``.po`` file content before the merge in the current branch,
* ``other`` is the ``.po`` file content in the branch merged from,
* ``pot_file`` is the path to the ``.pot`` file corresponding to the ``.po``
  file being merged.

In the simple case where a single ``.pot`` file and a single set of ``.po``
files exist, each config option can specify a single value.

When several ``(.pot file, .po fileset)`` exist, both lists should be
synchronized. For example::

    [/home/user/code/bzr]
    po_merge.pot_file = po/adduser.pot,doc/po4a/po/adduser.pot
    po_merge.po_files = po/*.po,doc/po4a/po/*.po

``po/adduser.pot`` will be used for ``po/*.po`` and ``doc/po4a/po/adduser.pot``
will be used for ``doc/po4a/po/*.po``.
"""

# Since we are a built-in plugin we share the bzrlib version
from bzrlib import version_info
from bzrlib.hooks import install_lazy_named_hook


def po_merge_hook(merger):
    """Merger.merge_file_content hook for bzr-format NEWS files."""
    from bzrlib.plugins.po_merge.po_merge import PoMerger
    return PoMerger(merger)


install_lazy_named_hook("bzrlib.merge", "Merger.hooks", "merge_file_content",
    po_merge_hook, ".po file merge")


def load_tests(basic_tests, module, loader):
    testmod_names = [
        'tests',
        ]
    basic_tests.addTest(loader.loadTestsFromModuleNames(
            ["%s.%s" % (__name__, tmn) for tmn in testmod_names]))
    return basic_tests

