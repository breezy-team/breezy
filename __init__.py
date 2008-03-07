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

"""Upload a working treem incrementally"""

from bzrlib import commands

class cmd_upload(commands.Command):
    def run(self):
        pass

commands.register_command(cmd_upload)

def test_suite():
    from bzrlib.tests import TestUtil

    suite = TestUtil.TestSuite()
    loader = TestUtil.TestLoader()
    testmod_names = [
        'test_upload',
        ]

    suite.addTest(loader.loadTestsFromModuleNames(
            ["%s.%s" % (__name__, tmn) for tmn in testmod_names]))
    return suite
