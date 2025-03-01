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


class ZzzTranslations:
    """Special Zzz translation for debugging i18n stuff.

    This class can be used to confirm that the message is properly translated
    during black box tests.
    """

    _null_translation = i18n._gettext.NullTranslations()

    def zzz(self, s):
        return "zz\xe5{{{{{}}}}}".format(s)

    def gettext(self, s):
        return self.zzz(self._null_translation.gettext(s))

    def ngettext(self, s, p, n):
        return self.zzz(self._null_translation.ngettext(s, p, n))

    def ugettext(self, s):
        return self.zzz(self._null_translation.ugettext(s))

    def ungettext(self, s, p, n):
        return self.zzz(self._null_translation.ungettext(s, p, n))


class TestZzzTranslation(tests.TestCase):
    def _check_exact(self, expected, source):
        self.assertEqual(expected, source)
        self.assertEqual(type(expected), type(source))

    def test_translation(self):
        trans = ZzzTranslations()

        t = trans.zzz("msg")
        self._check_exact("zz\xe5{{msg}}", t)

        t = trans.gettext("msg")
        self._check_exact("zz\xe5{{msg}}", t)

        t = trans.ngettext("msg1", "msg2", 0)
        self._check_exact("zz\xe5{{msg2}}", t)
        t = trans.ngettext("msg1", "msg2", 2)
        self._check_exact("zz\xe5{{msg2}}", t)

        t = trans.ngettext("msg1", "msg2", 1)
        self._check_exact("zz\xe5{{msg1}}", t)


class TestGetText(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.overrideAttr(i18n, "_translations", ZzzTranslations())

    def test_oneline(self):
        self.assertEqual("zz\xe5{{spam ham eggs}}", i18n.gettext("spam ham eggs"))

    def test_multiline(self):
        self.assertEqual(
            "zz\xe5{{spam\nham\n\neggs\n}}", i18n.gettext("spam\nham\n\neggs\n")
        )


class TestGetTextPerParagraph(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.overrideAttr(i18n, "_translations", ZzzTranslations())

    def test_oneline(self):
        self.assertEqual(
            "zz\xe5{{spam ham eggs}}", i18n.gettext_per_paragraph("spam ham eggs")
        )

    def test_multiline(self):
        self.assertEqual(
            "zz\xe5{{spam\nham}}\n\nzz\xe5{{eggs\n}}",
            i18n.gettext_per_paragraph("spam\nham\n\neggs\n"),
        )


class TestInstall(tests.TestCase):
    def setUp(self):
        super().setUp()
        # Restore a proper env to test translation installation
        self.overrideAttr(i18n, "_translations", None)

    def test_custom_languages(self):
        i18n.install("nl:fy")
        # Whether we found a valid tranlsation or not doesn't matter, we got
        # one and _translations is not None anymore.
        self.assertIsInstance(i18n._translations, i18n._gettext.NullTranslations)

    def test_no_env_variables(self):
        self.overrideEnv("LANGUAGE", None)
        self.overrideEnv("LC_ALL", None)
        self.overrideEnv("LC_MESSAGES", None)
        self.overrideEnv("LANG", None)
        i18n.install()
        # Whether we found a valid tranlsation or not doesn't matter, we got
        # one and _translations is not None anymore.
        self.assertIsInstance(i18n._translations, i18n._gettext.NullTranslations)

    def test_disable_i18n(self):
        i18n.disable_i18n()
        i18n.install()
        # It's disabled, you can't install anything and we fallback to null
        self.assertIsInstance(i18n._translations, i18n._gettext.NullTranslations)


class TestTranslate(tests.TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self.overrideAttr(i18n, "_translations", ZzzTranslations())

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
