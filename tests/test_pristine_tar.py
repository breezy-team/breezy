# Copyright (C) 2012 Jelmer Vernooij <jelmer@samba.org>
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

"""Tests for pristine tar extraction code."""

from base64 import standard_b64encode

from bzrlib.plugins.git.pristine_tar import revision_pristine_tar_data

from bzrlib.revision import Revision
from bzrlib.tests import TestCase

class RevisionPristineTarDataTests(TestCase):

    def test_pristine_tar_delta_unknown(self):
        rev = Revision("myrevid")
        self.assertRaises(KeyError,
            revision_pristine_tar_data, rev)

    def test_pristine_tar_delta_gz(self):
        rev = Revision("myrevid")
        rev.properties["deb-pristine-delta"] = standard_b64encode("bla")
        self.assertEquals("bla", revision_pristine_tar_data(rev))
