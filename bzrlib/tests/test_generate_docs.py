# Copyright (C) 2007 Canonical Ltd
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

"""Tests for generating docs (man pages).

This test checks that generation will be successful
and produce non-empty output.
"""

from cStringIO import StringIO

from bzrlib.tests import TestCase


class Options:
    """Simply container"""
    pass


class TestGenerateDocs(TestCase):

    def setUp(self):
        self.sio = StringIO()
        self.options = Options()
        self.options.bzr_name = 'bzr'

    def test_man_page(self):
        from tools.doc_generate import autodoc_man

        autodoc_man.infogen(self.options, self.sio)
        self.assertNotEqual('', self.sio.getvalue())

    def test_rstx_man(self):
        from tools.doc_generate import autodoc_rstx

        autodoc_rstx.infogen(self.options, self.sio)
        self.assertNotEqual('', self.sio.getvalue())
