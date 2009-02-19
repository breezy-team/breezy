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

commands = {
        "test_builddeb": [],
        "builddeb": ["bd"],
        "merge_upstream": ["mu"],
        "import_dsc": [],
        "bd_do": [],
        "mark_uploaded": []
        }

for command, aliases in commands.iteritems():
    plugin_cmds.register_lazy('cmd_' + command, aliases, 
        "bzrlib.plugins.builddeb.cmds")

builddeb_dir = '.bzr-builddeb'
default_conf = os.path.join(builddeb_dir, 'default.conf')
global_conf = os.path.expanduser('~/.bazaar/builddeb.conf')
local_conf = os.path.join(builddeb_dir, 'local.conf')

default_build_dir = '../build-area'
default_orig_dir = '..'
default_result_dir = '..'


directories.register_lazy("deb:", 'bzrlib.plugins.builddeb.directory', 
        'VcsDirectory', 
        "Directory that uses Debian Vcs-* control fields to look up branches")

try:
    from bzrlib.revisionspec import revspec_registry
    revspec_registry.register_lazy("package:", "bzrlib.plugins.builddeb.revspec", "RevisionSpec_package")
except ImportError:
    from bzrlib.revisionspec import SPEC_TYPES
    from bzrlib.plugins.builddeb.revspec import RevisionSpec_package
    SPEC_TYPES.append(RevisionSpec_package)


def test_suite():
    from unittest import TestSuite
    from bzrlib.plugins.builddeb import tests
    result = TestSuite()
    result.addTest(tests.test_suite())
    return result


if __name__ == '__main__':
    print ("This is a Bazaar plugin. Copy this directory to ~/.bazaar/plugins "
            "to use it.\n")
    import unittest
    runner = unittest.TextTestRunner()
    runner.run(test_suite())
