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

"""Merge hook for bzr's NEWS file.

To enable this plugin, add a section to your branch.conf or location.conf
like::

    [/home/user/code/bzr]
    news_merge_files = NEWS
    news_merge_files:policy = recurse

The news_merge_files config option takes a list of file paths, separated by
commas.

Limitations:

* if there's a conflict in more than just bullet points, this doesn't yet know
  how to resolve that, so bzr will fallback to the default line-based merge.
"""

# Since we are a built-in plugin we share the bzrlib version
from bzrlib import version_info

# Put most of the code in a separate module that we lazy-import to keep the
# overhead of this plugin as minimal as possible.
from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib.plugins.news_merge.news_merge import news_merger
""")

from bzrlib.merge import Merger


def news_merge_hook(params):
    """Merger.merge_file_content hook function for bzr-format NEWS files."""
    # First, check whether this custom merge logic should be used.  We expect
    # most files should not be merged by this file.
    if params.winner == 'other':
        # OTHER is a straight winner, rely on default merge.
        return 'not_applicable', None
    elif not params.is_file_merge():
        # THIS and OTHER aren't both files.
        return 'not_applicable', None
    elif not filename_matches_config(params):
        # The filename isn't listed in the 'news_merge_files' config option.
        return 'not_applicable', None
    return news_merger(params)


def filename_matches_config(params):
    affected_files = getattr(params, '_news_merge_affected_files', None)
    if affected_files is None:
        config = params.merger.this_tree.branch.get_config()
        # Until bzr provides a better policy for caching the config, we just
        # add the part we're interested in to the params to avoid reading the
        # config files repeatedly (bazaar.conf, location.conf, branch.conf).
        affected_files = config.get_user_option_as_list('news_merge_files')
        if affected_files is None:
            # If nothing was specified in the config, we have nothing to do,
            # but we use None in the params to start the caching.
            affected_files = []
        params._news_merge_affected_files = affected_files
    if affected_files:
        filename = params.merger.this_tree.id2path(params.file_id)
        if filename in affected_files:
            return True
    return False

def install_hook():
    Merger.hooks.install_named_hook(
        'merge_file_content', news_merge_hook, 'NEWS file merge')
install_hook()


def load_tests(basic_tests, module, loader):
    testmod_names = [
        'tests',
        ]
    basic_tests.addTest(loader.loadTestsFromModuleNames(
            ["%s.%s" % (__name__, tmn) for tmn in testmod_names]))
    return basic_tests

