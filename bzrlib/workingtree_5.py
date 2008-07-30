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

"""WorkingTree5 format and implementation.
"""

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    views,
    workingtree_4,
    )
""")


class WorkingTree5(workingtree_4.WorkingTree4):
    """This is the Format 5 working tree.

    This differs from WorkingTree4 by:
     - Supporting a current view that may mask the set of files in a tree
       impacted by most user operations.

    This is new in bzr 1.7.
    """

    def _make_views(self):
        return views.PathBasedViews(self)


class WorkingTreeFormat5(workingtree_4.WorkingTreeFormat4):
    """WorkingTree format supporting views.
    """

    upgrade_recommended = False

    _tree_class = WorkingTree5

    def get_format_string(self):
        """See WorkingTreeFormat.get_format_string()."""
        return "Bazaar Working Tree Format 5 (bzr 1.7)\n"

    def get_format_description(self):
        """See WorkingTreeFormat.get_format_description()."""
        return "Working tree format 5"

    def _init_custom_control_files(self, wt):
        """Subclasses with custom control files should override this method."""
        wt._transport.put_bytes('views', '', mode=wt.bzrdir._get_file_mode())

    def supports_views(self):
        return True


class Converter4to5(object):
    """Perform an in-place upgrade of format 4 to format 5 trees."""

    def __init__(self):
        self.target_format = WorkingTreeFormat5()

    def convert(self, tree):
        # lock the control files not the tree, so that we don't get tree
        # on-unlock behaviours, and so that no-one else diddles with the 
        # tree during upgrade.
        tree._control_files.lock_write()
        try:
            self.init_custom_control_files(tree)
            self.update_format(tree)
        finally:
            tree._control_files.unlock()

    def _init_custom_control_files(self, tree):
        """Initialize custom control files."""
        tree._transport.put_bytes('views', '',
            mode=tree.bzrdir._get_file_mode())

    def update_format(self, tree):
        """Change the format marker."""
        tree._transport.put_bytes('format',
            self.target_format.get_format_string(),
            mode=tree.bzrdir._get_file_mode())
