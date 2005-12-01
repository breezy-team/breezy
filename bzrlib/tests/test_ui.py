# Copyright (C) 2005 by Canonical Ltd
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

"""Tests for the bzrlib ui
"""

import os
import sys

from bzrlib.tests import TestCase
from bzrlib.ui import SilentUIFactory
from bzrlib.ui.text import TextUIFactory

class UITests(TestCase):

    def test_silent_factory(self):

        ui = SilentUIFactory()
        pb = ui.progress_bar()
        # TODO: Test that there is no output from SilentUIFactory

        self.assertEquals(ui.get_password(), None)
        self.assertEquals(ui.get_password(u'Hello There \u1234 %(user)s',
                                          user=u'some\u1234')
                         , None)

    def test_text_factory(self):
        ui = TextUIFactory()
        pb = ui.progress_bar()
        # TODO: Test the output from TextUIFactory, perhaps by overriding sys.stdout

        # Unfortunately we can't actually test the ui.get_password() because 
        # that would actually prompt the user for a password during the test suite
        # This has been tested manually with both LANG=en_US.utf-8 and LANG=C
        # print
        # self.assertEquals(ui.get_password(u"%(user)s please type 'bogus'",
        #                                   user=u'some\u1234')
        #                  , 'bogus')

