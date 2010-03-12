# Copyright (C) 2010 by Jelmer Vernooij <jelmer@samba.org>
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

"""Tests for pseudonym handling."""

from bzrlib.revision import Revision
from bzrlib.tests import TestCase

from bzrlib.plugins.rewrite.pseudonyms import extract_foreign_revids


class ExtractForeignRevidTests(TestCase):

    def test_no_foreign_revid(self):
        x = Revision("myrevid")
        self.assertEquals(set(), extract_foreign_revids(x))

