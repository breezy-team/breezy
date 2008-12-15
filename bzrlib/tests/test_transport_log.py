# Copyright (C) 2004, 2005, 2006, 2007 Canonical Ltd
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


"""Tests for log+ transport decorator."""


from bzrlib.tests import TestCaseWithMemoryTransport
from bzrlib.trace import mutter
from bzrlib.transport import get_transport


class TestTransportLog(TestCaseWithMemoryTransport):

    def test_log_transport(self):
        base_transport = self.get_transport('')
        logging_transport = get_transport('log+' + base_transport.base)

        # operations such as mkdir are logged
        mutter('where are you?')
        logging_transport.mkdir('subdir')
        self.assertContainsRe(self._get_log(True),
            r'mkdir memory\+\d+://.*subdir')
        self.assertContainsRe(self._get_log(True),
            '  --> None')
        # they have the expected effect
        self.assertTrue(logging_transport.has('subdir'))
        # and they operate on the underlying transport 
        self.assertTrue(base_transport.has('subdir'))


