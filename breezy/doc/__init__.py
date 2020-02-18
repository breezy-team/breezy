# Copyright (C) 2005 Canonical Ltd
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

"""Documentation for breezy.

See breezy.doc.api for api documentation and in the future breezy.doc.man
for man page generation.
"""


def load_tests(loader, basic_tests, pattern):
    suite = loader.suiteClass()
    # add the tests for this module (obviously none so far)
    suite.addTests(basic_tests)

    testmod_names = [
        'breezy.doc.api',
        ]

    # add the tests for the sub modules
    suite.addTests(loader.loadTestsFromModuleNames(testmod_names))

    return suite
