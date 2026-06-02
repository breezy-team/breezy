# Copyright (C) 2011, 2016 Canonical Ltd
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

"""Tests for breezy.i18n."""

import io

from .. import errors, i18n, tests, workingtree


class TestZzzTranslation(tests.TestCase):
    def _check_exact(self, expected, source):
        self.assertEqual(expected, source)
        self.assertEqual(type(expected), type(source))

    def test_translation(self):
        self.addCleanup(i18n.install)
        i18n.install_zzz()

        t = i18n.zzz("msg")
        self._check_exact("zz\xe5{{msg}}", t)

        t = i18n.gettext("msg")
        self._check_exact("zz\xe5{{msg}}", t)

        t = i18n.ngettext("msg1", "msg2", 0)
        self._check_exact("zz\xe5{{msg2}}", t)
        t = i18n.ngettext("msg1", "msg2", 2)
        self._check_exact("zz\xe5{{msg2}}", t)

        t = i18n.ngettext("msg1", "msg2", 1)
        self._check_exact("zz\xe5{{msg1}}", t)


class TestGetText(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(i18n.install)
        i18n.install_zzz()

    def test_oneline(self):
        self.assertEqual("zz\xe5{{spam ham eggs}}", i18n.gettext("spam ham eggs"))

    def test_multiline(self):
        self.assertEqual(
            "zz\xe5{{spam\nham\n\neggs\n}}", i18n.gettext("spam\nham\n\neggs\n")
        )


class TestGetTextPerParagraph(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(i18n.install)
        i18n.install_zzz()

    def test_oneline(self):
        self.assertEqual(
            "zz\xe5{{spam ham eggs}}", i18n.gettext_per_paragraph("spam ham eggs")
        )

    def test_multiline(self):
        self.assertEqual(
            "zz\xe5{{spam\nham}}\n\nzz\xe5{{eggs\n}}",
            i18n.gettext_per_paragraph("spam\nham\n\neggs\n"),
        )


class TestTranslate(tests.TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self.addCleanup(i18n.install)
        i18n.install_zzz()

    def test_error_message_translation(self):
        """Do errors get translated?"""
        err = None
        self.make_branch_and_tree(".")
        try:
            workingtree.WorkingTree.open("./foo")
        except errors.NotBranchError as e:
            err = str(e)
        self.assertContainsRe(err, "zz\xe5{{Not a branch: .*}}")

    def test_topic_help_translation(self):
        """Does topic help get translated?"""
        from .. import help

        out = io.StringIO()
        help.help("authentication", out)
        self.assertContainsRe(out.getvalue(), "zz\xe5{{Authentication Settings")


class LoadPluginTranslations(tests.TestCase):
    def test_does_not_exist(self):
        translation = i18n.load_plugin_translations("doesnotexist")
        self.assertEqual("foo", translation.gettext("foo"))
