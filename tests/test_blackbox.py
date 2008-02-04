# Copyright (C) 2006-2007 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
"""Blackbox tests."""

from bzrlib.repository import Repository
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.trace import mutter

from mapping import BzrSvnMappingv3FileProps
from scheme import NoBranchingScheme
from tests import TestCaseWithSubversionRepository

import os

class TestBranch(ExternalBase, TestCaseWithSubversionRepository):
    def test_branch_empty(self):
        repos_url = self.make_client('d', 'de')
        self.run_bzr("branch %s dc" % repos_url)
        
    def test_log_empty(self):
        repos_url = self.make_client('d', 'de')
        self.run_bzr('log %s' % repos_url)

    def test_dumpfile(self):
        filename = os.path.join(self.test_dir, "dumpfile")
        uuid = "606c7b1f-987c-4826-b37d-eb456ceb87e1"
        open(filename, 'w').write("""SVN-fs-dump-format-version: 2

UUID: 606c7b1f-987c-4826-b37d-eb456ceb87e1

Revision-number: 0
Prop-content-length: 56
Content-length: 56

K 8
svn:date
V 27
2006-12-26T00:04:55.850520Z
PROPS-END

Revision-number: 1
Prop-content-length: 103
Content-length: 103

K 7
svn:log
V 3
add
K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-26T00:05:15.504335Z
PROPS-END

Node-path: x
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 2
Prop-content-length: 102
Content-length: 102

K 7
svn:log
V 2
rm
K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-26T00:05:30.775369Z
PROPS-END

Node-path: x
Node-action: delete


Revision-number: 3
Prop-content-length: 105
Content-length: 105

K 7
svn:log
V 5
readd
K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-26T00:05:43.584249Z
PROPS-END

Node-path: y
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 1
Node-copyfrom-path: x
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 4
Prop-content-length: 108
Content-length: 108

K 7
svn:log
V 8
Replace

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:30:06.383777Z
PROPS-END

Node-path: y
Node-action: delete


Revision-number: 5
Prop-content-length: 108
Content-length: 108

K 7
svn:log
V 8
Replace

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:30:06.383777Z
PROPS-END


Node-path: y
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 1
Node-copyfrom-path: x


""")
        self.check_output("", 'svn-import --scheme=none %s dc' % filename)
        newrepos = Repository.open("dc")
        mapping = BzrSvnMappingv3FileProps(NoBranchingScheme())
        self.assertTrue(newrepos.has_revision(
            mapping.generate_revision_id(uuid, 5, "")))
        self.assertTrue(newrepos.has_revision(
            mapping.generate_revision_id(uuid, 1, "")))
        inv1 = newrepos.get_inventory(
                mapping.generate_revision_id(uuid, 1, ""))
        inv2 = newrepos.get_inventory(
                mapping.generate_revision_id(uuid, 5, ""))
        self.assertNotEqual(inv1.path2id("y"), inv2.path2id("y"))


    def test_list(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/foo': "test", 'dc/bla': "ha"})
        self.client_add("dc/foo")
        self.client_add("dc/bla")
        self.client_commit("dc", "Msg")
        self.check_output("a/bla\na/foo\n", "ls a")

    def test_info_remote(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/foo': "test", 'dc/bla': "ha"})
        self.client_add("dc/foo")
        self.client_add("dc/bla")
        self.client_commit("dc", "Msg")
        self.check_output(
                "Repository branch (format: subversion)\nLocation:\n  shared repository: a\n  repository branch: a\n\nRelated branches:\n  parent branch: a\n", 'info a')

    def test_lightweight_checkout_lightweight_checkout(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/foo': "test", 'dc/bla': "ha"})
        self.client_add("dc/foo")
        self.client_add("dc/bla")
        self.client_commit("dc", "Msg")
        self.run_bzr("checkout --lightweight dc de")

