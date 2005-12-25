# Copyright (C) 2005 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from bzrlib.tests import TestCaseInTempDir
from bzrlib.transport import get_transport
from bzrlib.lockable_files import LockableFiles
from bzrlib.errors import NoSuchFile, ReadOnlyError
from StringIO import StringIO

class TestLockableFiles(TestCaseInTempDir):
    def setUp(self):
        super(self.__class__, self).setUp()
        transport = get_transport('.')
        transport.mkdir('.bzr')
        self.lockable = LockableFiles(transport, 'my-lock')

    def test_locks(self):
        self.assertRaises(ReadOnlyError, self.lockable.put, 'foo', 
                          StringIO('bar\u1234'))
