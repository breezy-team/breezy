# Copyright (C) 2009, 2010, 2016 Canonical Ltd
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

"""Tests for _rio_*."""

from ... import tests
from .. import rio


def load_tests(loader, standard_tests, pattern):
    suite, _ = tests.permute_tests_for_extension(standard_tests, loader,
                                                 'breezy.bzr._rio_py', 'breezy.bzr._rio_pyx')
    return suite


class TestValidTag(tests.TestCase):

    module = None  # Filled in by test parameterization

    def test_ok(self):
        self.assertTrue(self.module._valid_tag("foo"))

    def test_no_spaces(self):
        self.assertFalse(self.module._valid_tag("foo bla"))

    def test_numeric(self):
        self.assertTrue(self.module._valid_tag("3foo423"))

    def test_no_colon(self):
        self.assertFalse(self.module._valid_tag("foo:bla"))

    def test_type_error(self):
        self.assertRaises(TypeError, self.module._valid_tag, 423)

    def test_empty(self):
        self.assertFalse(self.module._valid_tag(""))

    def test_unicode(self):
        # When str is a unicode type, it is valid for a tag
        self.assertTrue(self.module._valid_tag(u"foo"))

    def test_non_ascii_char(self):
        self.assertFalse(self.module._valid_tag("\xb5"))


class TestReadUTF8Stanza(tests.TestCase):

    module = None  # Filled in by test parameterization

    def assertReadStanza(self, result, line_iter):
        s = self.module._read_stanza_utf8(line_iter)
        self.assertEqual(result, s)
        if s is not None:
            for tag, value in s.iter_pairs():
                self.assertIsInstance(tag, str)
                self.assertIsInstance(value, str)

    def assertReadStanzaRaises(self, exception, line_iter):
        self.assertRaises(exception, self.module._read_stanza_utf8, line_iter)

    def test_no_string(self):
        self.assertReadStanzaRaises(TypeError, [21323])

    def test_empty(self):
        self.assertReadStanza(None, [])

    def test_none(self):
        self.assertReadStanza(None, [b""])

    def test_simple(self):
        self.assertReadStanza(rio.Stanza(foo="bar"), [b"foo: bar\n", b""])

    def test_multi_line(self):
        self.assertReadStanza(
            rio.Stanza(foo="bar\nbla"), [b"foo: bar\n", b"\tbla\n"])

    def test_repeated(self):
        s = rio.Stanza()
        s.add("foo", "bar")
        s.add("foo", "foo")
        self.assertReadStanza(s, [b"foo: bar\n", b"foo: foo\n"])

    def test_invalid_early_colon(self):
        self.assertReadStanzaRaises(ValueError, [b"f:oo: bar\n"])

    def test_invalid_tag(self):
        self.assertReadStanzaRaises(ValueError, [b"f%oo: bar\n"])

    def test_continuation_too_early(self):
        self.assertReadStanzaRaises(ValueError, [b"\tbar\n"])

    def test_large(self):
        value = b"bla" * 9000
        self.assertReadStanza(rio.Stanza(foo=value.decode()),
                              [b"foo: %s\n" % value])

    def test_non_ascii_char(self):
        self.assertReadStanza(rio.Stanza(foo=u"n\xe5me"),
                              [u"foo: n\xe5me\n".encode("utf-8")])
