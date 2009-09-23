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

"""Tests run per UIFactory.

Testing UIFactories is a bit interesting because we require they all support a
common interface, but the way they implement it can vary very widely.  Between
text, batch-mode, graphical and other potential UIFactories, the requirements
to set up a factory, to make it respond to requests, and to simulate user
input can vary a lot.
"""

# This may seem like a complicated way to test it compared to just having
# tests for each implementation, but it's supposed to help make sure that all
# new methods added to the UIFactory interface are tested by default, rather
# than forgotten.  At least there should be an explicit decision (eg with
# TestSkipped) that it's not possible to test them automatically.
#
# For each UIFactory we have a UIFactoryFitting


from cStringIO import StringIO
import unittest


from bzrlib import (
    tests,
    ui,
    )


class TestUIFactory(tests.TestCase):

    def setUp(self):
        tests.TestCase.setUp(self)
        self.fitting = self.fitting_class()

    def test_construction(self):
        factory = self.fitting.make_factory()

    def test_note(self):
        self.fitting.check_note("a note to the user")


class BaseUIFactoryFitting(object):

    pass


class TextUIFactoryFitting(BaseUIFactoryFitting):

    def make_factory(self):
        self.stdin = StringIO()
        self.stdout = StringIO()
        self.stderr = StringIO()
        self.factory = ui.text.TextUIFactory(self.stdin, self.stdout,
            self.stderr)
        return self.factory

    def check_note(self, note_text):
        factory = self.make_factory()
        factory.note(note_text)
        # XXX: This should be assertEquals but this isn't a TestCase
        # self.assertEquals("%s\n" % note_text,
        #    self.stdout.getvalue())


# NB: There's no registry of UIFactories at the moment so we just define the
# scenarios here.  Plugins that provide custom UIFactories might like to add
# their factories and suitable fittings.
scenarios = [
    ('text', dict(fitting_class=TextUIFactoryFitting))
    ]


def load_tests(base_test_suite, module, loader):
    to_test_suite = unittest.TestSuite()
    tests.multiply_tests(base_test_suite, scenarios, to_test_suite)
    return to_test_suite
