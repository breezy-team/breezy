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

__doc__ = """Merge hook for bzr's NEWS file.

To enable this plugin, add a section to your branch.conf or location.conf
like::

    [/home/user/code/bzr]
    news_merge_files = NEWS

The news_merge_files config option takes a list of file paths, separated by
commas.

Limitations:

* if there's a conflict in more than just bullet points, this doesn't yet know
  how to resolve that, so bzr will fallback to the default line-based merge.
"""

# Since we are a built-in plugin we share the breezy version
from ... import version_info  # noqa: F401
from ...hooks import install_lazy_named_hook


def news_merge_hook(merger):
    """Merger.merge_file_content hook for bzr-format NEWS files."""
    from .news_merge import NewsMerger
    return NewsMerger(merger)


install_lazy_named_hook("breezy.merge", "Merger.hooks", "merge_file_content",
                        news_merge_hook, "NEWS file merge")


def test_suite():
    from . import tests
    return tests.test_suite()
