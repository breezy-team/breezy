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
    po_merge.pot_dirs = po,doc/po4a/po

The ``po_merge.pot_dirs`` config option takes a list of directories that can
contain ``.po`` files, separated by commas (if several directories are
needed). Each directory should contain a single ``.pot`` file.

The ``po_merge.command`` is the command whose output is used as the result of
the merge. It defaults to::

   msgmerge -N "{other}" "{pot_file}" -C "{this}" -o "{result}"

where:

* ``this`` is the ``.po`` file content before the merge in the current branch,
* ``other`` is the ``.po`` file content in the branch merged from,
* ``pot_file`` is the path to the ``.pot`` file corresponding to the ``.po``
  file being merged.

If conflicts occur in a ``.pot`` file during a given merge, the ``.po`` files
will use the ``.pot`` file present in tree before the merge. If this doesn't
suit your needs, you should can disable the plugin during the merge with::

  bzr merge <usual merge args> -Opo_merge.po_dirs=

This will allow you to resolve the conflicts in the ``.pot`` file and then
merge the ``.po`` files again with::

  bzr remerge po/*.po doc/po4a/po/*.po

"""

from ... import (
    config,  # Since we are a built-in plugin we share the breezy version
    version_info,  # noqa: F401
)
from ...hooks import install_lazy_named_hook


def register_lazy_option(key, member):
    config.option_registry.register_lazy(
        key, "breezy.plugins.po_merge.po_merge", member
    )


register_lazy_option("po_merge.command", "command_option")
register_lazy_option("po_merge.po_dirs", "po_dirs_option")
register_lazy_option("po_merge.po_glob", "po_glob_option")
register_lazy_option("po_merge.pot_glob", "pot_glob_option")


def po_merge_hook(merger):
    """Merger.merge_file_content hook for po files."""
    from .po_merge import PoMerger

    return PoMerger(merger)


install_lazy_named_hook(
    "breezy.merge",
    "Merger.hooks",
    "merge_file_content",
    po_merge_hook,
    ".po file merge",
)


def load_tests(loader, basic_tests, pattern):
    testmod_names = [
        "tests",
    ]
    basic_tests.addTest(
        loader.loadTestsFromModuleNames(
            ["{}.{}".format(__name__, tmn) for tmn in testmod_names]
        )
    )
    return basic_tests
