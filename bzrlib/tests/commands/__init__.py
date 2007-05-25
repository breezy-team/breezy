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

These test the behaviour of the commands.
The API is tested in the tests/blackbox files.
"""

from bzrlib.tests import (
                          TestLoader,
                          )


def test_suite():
    testmod_names = [
        'bzrlib.tests.commands.test_branch',
        'bzrlib.tests.commands.test_cat',
        'bzrlib.tests.commands.test_checkout',
        'bzrlib.tests.commands.test_init',
        'bzrlib.tests.commands.test_init_repository',
        'bzrlib.tests.commands.test_merge',
        'bzrlib.tests.commands.test_missing',
        'bzrlib.tests.commands.test_pull',
        'bzrlib.tests.commands.test_push',
        ]
    loader = TestLoader()
    suite = loader.loadTestsFromModuleNames(testmod_names)

    return suite
