#    __init__.py -- The plugin for bzr
#    Copyright (C) 2005 Jamie Wilkinson <jaq@debian.org> 
#                  2006, 2007 James Westby <jw+debian@jameswestby.net>
#                  2007 Reinhard Tartler <siretart@tauware.de>
#                  2008 Canonical Ltd.
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

"""bzr-builddeb - manage packages in a Bazaar branch."""

import os

from bzrlib.commands import plugin_cmds
from bzrlib.directory_service import directories

from bzrlib.plugins.builddeb.config import DebBuildConfig
from bzrlib.plugins.builddeb import revspec
from bzrlib.plugins.builddeb.version import version_info

commands = {
        "test_builddeb": [],
        "builddeb": ["bd"],
        "merge_upstream": ["mu"],
        "import_dsc": [],
        "bd_do": [],
        "mark_uploaded": []
        }

plugin_cmds.register_lazy('cmd_' + command, aliases, 
    "bzrlib.plugins.builddeb.commands")

builddeb_dir = '.bzr-builddeb'
default_conf = os.path.join(builddeb_dir, 'default.conf')
global_conf = os.path.expanduser('~/.bazaar/builddeb.conf')
local_conf = os.path.join(builddeb_dir, 'local.conf')

default_build_dir = '../build-area'
default_orig_dir = '..'
default_result_dir = '..'


def debuild_config(tree, working_tree, no_user_config):
    """Obtain the Debuild configuration object.

    :param tree: A Tree object, can be a WorkingTree or RevisionTree.
    :param working_tree: Whether the tree is a working tree.
    :param no_user_config: Whether to skip the user configuration
    """
    config_files = []
    user_config = None
    if (working_tree and 
        tree.has_filename(local_conf) and tree.path2id(local_conf) is None):
        config_files.append((tree.get_file_byname(local_conf), True))
    if not no_user_config:
        config_files.append((global_conf, True))
        user_config = global_conf
    if tree.path2id(default_conf):
        config_files.append((tree.get_file(tree.path2id(default_conf)), False))
    config = DebBuildConfig(config_files)
    config.set_user_config(user_config)
    return config


directories.register_lazy("deb:", 'bzrlib.plugins.builddeb.directory', 
        'VcsDirectory', 
        "Directory that uses Debian Vcs-* control fields to look up branches")

if __name__ == '__main__':
    print ("This is a Bazaar plugin. Copy this directory to ~/.bazaar/plugins "
            "to use it.\n")
    import unittest
    runner = unittest.TextTestRunner()
    runner.run(test_suite())
else:
    import sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
