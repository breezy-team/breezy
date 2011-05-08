#    test_dep3.py -- Testsuite for builddeb dep3.py
#    Copyright (C) 2011 Canonical Ltd.
#    
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

from cStringIO import StringIO

from bzrlib.tests import TestCase

from bzrlib.plugins.builddeb.dep3 import dep3_patch_header

from debian.deb822 import Deb822


class Dep3HeaderTests(TestCase):

    def dep3_header(self, description=None, bugs=None, authors=None,
            revision_id=None, last_update=None):
        f = StringIO()
        dep3_patch_header(f, description=description, bugs=bugs,
            authors=authors, revision_id=revision_id, last_update=last_update)
        f.seek(0)
        return Deb822(f)

    def test_description(self):
        ret = self.dep3_header(description="This patch fixes the foobar")
        self.assertEquals("This patch fixes the foobar", ret["Description"])

    def test_last_updated(self):
        ret = self.dep3_header(last_update=1304840034)
        self.assertEquals("2011-05-08", ret["Last-Update"])

    def test_revision_id(self):
        ret = self.dep3_header(revision_id="myrevid")
        self.assertEquals("myrevid", ret["X-Bzr-Revision-Id"])
