# Copyright (C) 2007-2010 Canonical Ltd
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


"""Commands behaviour tests for bzr.

Test the internal behaviour of the commands (the blackbox tests are intended to
test the usage of the commands).
"""

# FIXME: If the separation described above from the blackbox tests is not worth
# it, all the tests defined below should be moved to blackbox instead.


def load_tests(loader, basic_tests, pattern):
    suite = loader.suiteClass()
    # add the tests for this module
    suite.addTests(basic_tests)

    testmod_names = [
        'breezy.tests.commands.test_branch',
        'breezy.tests.commands.test_cat',
        'breezy.tests.commands.test_checkout',
        'breezy.tests.commands.test_commit',
        'breezy.tests.commands.test_init',
        'breezy.tests.commands.test_init_repository',
        'breezy.tests.commands.test_merge',
        'breezy.tests.commands.test_missing',
        'breezy.tests.commands.test_pull',
        'breezy.tests.commands.test_push',
        'breezy.tests.commands.test_update',
        'breezy.tests.commands.test_revert',
        ]
    # add the tests for the sub modules
    suite.addTests(loader.loadTestsFromModuleNames(testmod_names))

    return suite
