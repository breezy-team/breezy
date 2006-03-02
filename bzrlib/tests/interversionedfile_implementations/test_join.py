# Copyright (C) 2006 by Canonical Ltd
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

"""Tests for join between versioned files."""


from bzrlib.tests import TestCaseWithTransport
from bzrlib.transport import get_transport


class TestJoin(TestCaseWithTransport):
    #Tests have self.versionedfile_factory and self.versionedfile_factory_to
    #available to create source and target versioned files respectively.

    def get_source(self, name='source'):
        """Get a versioned file we will be joining from."""
        return self.versionedfile_factory(name,
                                          get_transport(self.get_url()))

    def get_target(self, name='source'):
        """"Get an empty versioned file to join into."""
        return self.versionedfile_factory_to(name,
                                             get_transport(self.get_url()))

    def test_join(self):
        f1 = self.get_source()
        f1.add_lines('r0', [], ['a\n', 'b\n'])
        f1.add_lines('r1', ['r0'], ['c\n', 'b\n'])
        f2 = self.get_target()
        f2.join(f1, None)
        def verify_file(f):
            self.assertTrue(f.has_version('r0'))
            self.assertTrue(f.has_version('r1'))
        verify_file(f2)
        verify_file(self.get_target())

        self.assertRaises(RevisionNotPresent,
            f2.join, f1, version_ids=['r3'])

        #f3 = self.get_file('1')
        #f3.add_lines('r0', ['a\n', 'b\n'], [])
        #f3.add_lines('r1', ['c\n', 'b\n'], ['r0'])
        #f4 = self.get_file('2')
        #f4.join(f3, ['r0'])
        #self.assertTrue(f4.has_version('r0'))
        #self.assertFalse(f4.has_version('r1'))

