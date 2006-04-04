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
from StringIO import StringIO
import sys


import bzrlib.errors as errors
from bzrlib.progress import TTYProgressBar, ProgressBarStack
from bzrlib.tests import TestCase
import bzrlib.ui
from bzrlib.ui import SilentUIFactory
from bzrlib.ui.text import TextUIFactory

class UITests(TestCase):

    def test_silent_factory(self):

        ui = SilentUIFactory()
        pb = ui.nested_progress_bar()
        try:
            # TODO: Test that there is no output from SilentUIFactory
    
            self.assertEquals(ui.get_password(), None)
            self.assertEquals(ui.get_password(u'Hello There \u1234 %(user)s',
                                              user=u'some\u1234')
                             , None)
        finally:
            pb.finished()

    def test_text_factory(self):
        ui = TextUIFactory()
        pb = ui.nested_progress_bar()
        pb.finished()
        # TODO: Test the output from TextUIFactory, perhaps by overriding sys.stdout

        # Unfortunately we can't actually test the ui.get_password() because 
        # that would actually prompt the user for a password during the test suite
        # This has been tested manually with both LANG=en_US.utf-8 and LANG=C
        # print
        # self.assertEquals(ui.get_password(u"%(user)s please type 'bogus'",
        #                                   user=u'some\u1234')
        #                  , 'bogus')


    def test_progress_note(self):
        stderr = StringIO()
        stdout = StringIO()
        old_factory = bzrlib.ui.ui_factory
        bzrlib.ui.ui_factory = TextUIFactory()
        pb = None
        try:
            pb = bzrlib.ui.ui_factory.nested_progress_bar()
            pb.to_messages_file = stdout
            bzrlib.ui.ui_factory._progress_bar_stack.bottom().to_file = stderr
            result = pb.note('t')
            self.assertEqual(None, result)
            self.assertEqual("t\n", stdout.getvalue())
            # the exact contents will depend on the terminal width and we don't
            # care about that right now - but you're probably running it on at
            # least a 10-character wide terminal :)
            self.assertContainsRe(stderr.getvalue(), r'^\r {10,}\r$')
        finally:
            if pb is not None:
                pb.finished()
            bzrlib.ui.ui_factory = old_factory

    def test_progress_nested(self):
        # test factory based nested and popping.
        ui = TextUIFactory()
        pb1 = ui.nested_progress_bar()
        pb2 = ui.nested_progress_bar()
        self.assertRaises(errors.MissingProgressBarFinish, pb1.finished)
        pb2.finished()
        pb1.finished()

    def test_progress_stack(self):
        # test the progress bar stack which the default text factory 
        # uses.
        stderr = StringIO()
        stdout = StringIO()
        # make a stack, which accepts parameters like a pb.
        stack = ProgressBarStack(to_file=stderr, to_messages_file=stdout)
        # but is not one
        self.assertFalse(getattr(stack, 'note', False))
        pb1 = stack.get_nested()
        pb2 = stack.get_nested()
        self.assertRaises(errors.MissingProgressBarFinish, pb1.finished)
        pb2.finished()
        pb1.finished()
        # the text ui factory never actually removes the stack once its setup.
        # we need to be able to nest again correctly from here.
        pb1 = stack.get_nested()
        pb2 = stack.get_nested()
        self.assertRaises(errors.MissingProgressBarFinish, pb1.finished)
        pb2.finished()
        pb1.finished()
