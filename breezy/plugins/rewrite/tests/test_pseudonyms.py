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

from ....revision import Revision
from ....tests import TestCase

from ..pseudonyms import extract_foreign_revids


class ExtractForeignRevidTests(TestCase):

    def test_no_foreign_revid(self):
        x = Revision(b"myrevid")
        self.assertEquals(set(), extract_foreign_revids(x))

    def test_cscvs(self):
        x = Revision(b"myrevid")
        x.properties = {
            "cscvs-svn-repository-uuid": "someuuid",
            "cscvs-svn-revision-number": "4",
            "cscvs-svn-branch-path": "/trunk"}
        self.assertEquals(
            set([("svn", "someuuid:4:trunk")]),
            extract_foreign_revids(x))
