# Copyright (C) 2011 Canonical Ltd
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

"""Tests for bzrlib.i18n"""

from bzrlib import i18n, tests


class TestZzzTranslation(tests.TestCase):

    def _check_exact(self, expected, source):
        self.assertEqual(expected, source)
        self.assertEqual(type(expected), type(source))

    def test_translation(self):
        trans = i18n._ZzzTranslations()

        t = trans.zzz('msg')
        self._check_exact(u'zz{{msg}}', t)

        t = trans.ugettext('msg')
        self._check_exact(u'zz{{msg}}', t)

        t = trans.ungettext('msg1', 'msg2', 0)
        self._check_exact(u'zz{{msg2}}', t)
        t = trans.ungettext('msg1', 'msg2', 2)
        self._check_exact(u'zz{{msg2}}', t)

        t = trans.ungettext('msg1', 'msg2', 1)
        self._check_exact(u'zz{{msg1}}', t)


class TestGetText(tests.TestCase):

    def setUp(self):
        super(TestGetText, self).setUp()
        self.overrideAttr(i18n, '_translation', i18n._ZzzTranslations())

    def test_oneline(self):
        self.assertEqual(u"zz{{spam ham eggs}}",
                         i18n.gettext("spam ham eggs"))

    def test_multiline(self):
        self.assertEqual(u"zz{{spam\nham}}\n\nzz{{eggs\n}}",
                         i18n.gettext("spam\nham\n\neggs\n"))
