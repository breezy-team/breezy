# Copyright (C) 2007, 2009, 2011 Canonical Ltd
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

"""Tests for generating docs (man pages).

This test checks that generation will be successful
and produce non-empty output.
"""

from io import StringIO

import breezy.commands

from . import TestCase


class Options:
    """Simply container."""

    pass


class TestGenerateDocs(TestCase):
    def setUp(self):
        super().setUp()
        self.sio = StringIO()
        self.options = Options()
        self.options.brz_name = "brz"
        breezy.commands.install_bzr_command_hooks()

    def test_man_page(self):
        from breezy.doc_generate import autodoc_man

        autodoc_man.infogen(self.options, self.sio)
        self.assertNotEqual("", self.sio.getvalue())

    def test_rstx_man(self):
        from breezy.doc_generate import autodoc_rstx

        autodoc_rstx.infogen(self.options, self.sio)
        self.assertNotEqual("", self.sio.getvalue())
