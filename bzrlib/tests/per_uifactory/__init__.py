# Copyright (C) 2009 Canonical Ltd
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

"""Tests run per UIFactory."""

# Testing UIFactories is a bit interesting because we require they all support a
# common interface, but the way they implement it can vary very widely.  Between
# text, batch-mode, graphical and other potential UIFactories, the requirements
# to set up a factory, to make it respond to requests, and to simulate user
# input can vary a lot.
#
# We want tests that therefore allow for the evaluation of the result to vary
# per implementation, but we want to check that the supported facilities are
# the same across all UIFactorys, unless they're specifically skipped.
#
# Our normal approach is to use test scenarios but that seems to just end up
# creating test-like objects inside the scenario.  Therefore we fall back to
# the older method of putting the common tests in a mixin.
#
# Plugins that add new UIFactorys can create their own subclasses.


from cStringIO import StringIO
import unittest


from bzrlib import (
    tests,
    ui,
    )


class UIFactoryTestMixin(object):
    """Common tests for UIFactories.

    These are supposed to be expressed with no assumptions about how the
    UIFactory implements the method, only that it does implement them (or
    fails cleanly), and that the concrete subclass will make arrangements to
    build a factory and to examine its behaviour.

    Note that this is *not* a TestCase, because it can't be directly run, but
    the concrete subclasses should be.
    """

    def test_note(self):
        self.factory.note("a note to the user")
        self._expect_note("a note to the user")


class TestTextUIFactory(tests.TestCase, UIFactoryTestMixin):

    def setUp(self):
        super(TestTextUIFactory, self).setUp()
        self.stdin = StringIO()
        self.stdout = StringIO()
        self.stderr = StringIO()
        self.factory = ui.text.TextUIFactory(self.stdin, self.stdout,
            self.stderr)

    def _expect_note(self, note_text):
        self.assertEquals("%s\n" % note_text,
            self.stdout.getvalue())


class TestSilentUIFactory(tests.TestCase, UIFactoryTestMixin):
    # discards output, therefore tests for output expect nothing

    def setUp(self):
        super(TestSilentUIFactory, self).setUp()
        self.factory = ui.SilentUIFactory()

    def _expect_note(self, note_text):
        # it's just discarded
        pass


class TestCannedInputUIFactory(tests.TestCase, UIFactoryTestMixin):
    # discards output, reads input from variables

    def setUp(self):
        super(TestCannedInputUIFactory, self).setUp()
        self.factory = ui.CannedInputUIFactory([])

    def _expect_note(self, note_text):
        pass
