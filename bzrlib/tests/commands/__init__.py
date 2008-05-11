# Copyright (C) 2007 Canonical Ltd
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


"""Commands behaviour tests for bzr.

Test the internal behaviour of the commands (the blackbox tests are intended to
test the usage of the commands).
"""

# FIXME: If the separation described above from the blackbox tests is not worth
# it, all the tests defined below should be moved to blackbox instead. 

def load_tests(basic_tests, module, loader):
    suite = loader.suiteClass()
    # add the tests for this module
    suite.addTests(basic_tests)

    testmod_names = [
        'bzrlib.tests.commands.test_branch',
        'bzrlib.tests.commands.test_cat',
        'bzrlib.tests.commands.test_checkout',
        'bzrlib.tests.commands.test_commit',
        'bzrlib.tests.commands.test_init',
        'bzrlib.tests.commands.test_init_repository',
        'bzrlib.tests.commands.test_merge',
        'bzrlib.tests.commands.test_missing',
        'bzrlib.tests.commands.test_pull',
        'bzrlib.tests.commands.test_push',
        'bzrlib.tests.commands.test_update',
        ]
    # add the tests for the sub modules
    suite.addTests(loader.loadTestsFromModuleNames(testmod_names))

    return suite
