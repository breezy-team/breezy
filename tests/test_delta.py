# Copyright (C) 2005-2007 Jelmer Vernooij <jelmer@samba.org>
 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from bzrlib.tests import TestCase

from bzrlib.plugins.svn.delta import send_stream

from cStringIO import StringIO

class DeltaTests(TestCase):

    def setUp(self):
        super(DeltaTests, self).setUp()
        self.windows = []

    def storing_window_handler(self, window):
        self.windows.append(window)

    def test_send_stream(self):
        stream = StringIO("foo")
        send_stream(stream, self.storing_window_handler)
        self.assertEquals([(0, 0, 3, 0, [(2, 0, 3)], 'foo'), None], 
                          self.windows)
