# Copyright (C) 2007 Jelmer Vernooij <jelmer@samba.org>

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

"""Subversion fetch tests."""

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.repository import Repository
from bzrlib.trace import mutter

from convert import load_dumpfile
from fileids import generate_svn_file_id, generate_file_id
import format
from scheme import TrunkBranchingScheme, NoBranchingScheme
from tests import TestCaseWithSubversionRepository
from transport import SvnRaTransport

import os

class TestFetchWorks(TestCaseWithSubversionRepository):
    def test_fetch_fileid_renames(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/test': "data"})
        self.client_add("dc/test")
        self.client_set_prop("dc", "bzr:file-ids", "test\tbla\n")
        self.client_set_prop("dc", "bzr:revision-info", "")
        self.client_commit("dc", "Msg")

        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f", format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.assertEqual("bla", newrepos.get_inventory(
            oldrepos.generate_revision_id(1, "", "none")).path2id("test"))

    def test_fetch_trunk1(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/proj1/trunk/file': "data"})
        self.client_add("dc/proj1")
        self.client_commit("dc", "My Message")
        oldrepos = Repository.open(repos_url)
        oldrepos.set_branching_scheme(TrunkBranchingScheme(1))
        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)

    def test_fetch_complex_ids_dirs(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/dir/adir': None})
        self.client_add("dc/dir")
        self.client_set_prop("dc", "bzr:revision-info", "")
        self.client_set_prop("dc", "bzr:file-ids", "dir\tbloe\ndir/adir\tbla\n")
        self.client_commit("dc", "My Message")
        self.client_update("dc")
        self.client_copy("dc/dir/adir", "dc/bdir")
        self.client_delete("dc/dir/adir")
        self.client_set_prop("dc", "bzr:revision-info", "properties: \n")
        self.client_set_prop("dc", "bzr:file-ids", "bdir\tbla\n")
        self.client_commit("dc", "My Message")
        self.client_update("dc")
        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        tree = newrepos.revision_tree(oldrepos.generate_revision_id(2, "", "none"))
        self.assertEquals("bloe", tree.path2id("dir"))
        self.assertIs(None, tree.path2id("dir/adir"))
        self.assertEquals("bla", tree.path2id("bdir"))

    def test_fetch_complex_ids_files(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/dir/adir': 'contents'})
        self.client_add("dc/dir")
        self.client_set_prop("dc", "bzr:revision-info", "")
        self.client_set_prop("dc", "bzr:file-ids", "dir\tbloe\ndir/adir\tbla\n")
        self.client_commit("dc", "My Message")
        self.client_update("dc")
        self.client_copy("dc/dir/adir", "dc/bdir")
        self.client_delete("dc/dir/adir")
        self.client_set_prop("dc", "bzr:revision-info", "properties: \n")
        self.client_set_prop("dc", "bzr:file-ids", "bdir\tbla\n")
        self.client_commit("dc", "My Message")
        self.client_update("dc")
        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        tree = newrepos.revision_tree(oldrepos.generate_revision_id(2, "", "none"))
        self.assertEquals("bloe", tree.path2id("dir"))
        self.assertIs(None, tree.path2id("dir/adir"))
        mutter('entries: %r' % tree.inventory.entries())
        self.assertEquals("bla", tree.path2id("bdir"))

    def test_fetch_special_char(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({u'dc/trunk/f\x2cle': "data"})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")
        oldrepos = Repository.open(repos_url)
        oldrepos.set_branching_scheme(TrunkBranchingScheme(1))
        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)

    def test_fetch_delete(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.client_delete("dc/foo/bla")
        self.client_commit("dc", "Second Message")
        newrepos = Repository.open("f")
        oldrepos.copy_content_into(newrepos)
        self.assertTrue(oldrepos.has_revision(oldrepos.generate_revision_id(2, "", "none")))

    def test_fetch_delete_recursive(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.client_delete("dc/foo")
        self.client_commit("dc", "Second Message")
        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f", format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        tree = newrepos.revision_tree(oldrepos.generate_revision_id(1, "", "none"))
        self.assertEquals(3, len(tree.inventory))
        tree = newrepos.revision_tree(oldrepos.generate_revision_id(2, "", "none"))
        self.assertEquals(1, len(tree.inventory))

    def test_fetch_local(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/foo/blo': "data2", "dc/bar/foo": "data3", 'dc/foo/bla': "data"})
        self.client_add("dc/foo/blo")
        self.client_add("dc/bar")
        self.client_commit("dc", "Second Message")
        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, "", "none")))
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(2, "", "none")))
        tree = newrepos.revision_tree(
                oldrepos.generate_revision_id(2, "", "none"))
        self.assertTrue(tree.has_filename("foo/bla"))
        self.assertTrue(tree.has_filename("foo"))
        self.assertEqual("data", tree.get_file_by_path("foo/bla").read())

    def test_fetch_replace(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/bla': "data"})
        self.client_add("dc/bla")
        self.client_commit("dc", "My Message")
        self.client_delete("dc/bla")
        self.build_tree({'dc/bla': "data2"})
        self.client_add("dc/bla")
        self.client_commit("dc", "Second Message")
        oldrepos = Repository.open("svn+"+repos_url)
        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, "", "none")))
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(2, "", "none")))
        inv1 = newrepos.get_inventory(
                oldrepos.generate_revision_id(1, "", "none"))
        inv2 = newrepos.get_inventory(
                oldrepos.generate_revision_id(2, "", "none"))
        self.assertNotEqual(inv1.path2id("bla"), inv2.path2id("bla"))

    def test_fetch_copy_subdir(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/trunk/mydir/a': "data"})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/branches/tmp': None})
        self.client_add("dc/branches")
        self.client_commit("dc", "Second Message")
        self.client_copy("dc/trunk/mydir", "dc/branches/tmp/abranch")
        self.client_commit("dc", "Third Message")
        oldrepos = Repository.open("svn+"+repos_url)
        oldrepos.set_branching_scheme(TrunkBranchingScheme())
        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)

    def test_fetch_replace_nordic(self):
        filename = os.path.join(self.test_dir, "dumpfile")
        open(filename, 'w').write("""SVN-fs-dump-format-version: 2

UUID: 606c7b1f-987c-4826-b37d-eb556ceb87e1

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

Node-path: x\xc3\xa1
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END

Node-path: u\xc3\xa1
Node-path: bla
Node-kind: file
Node-action: add
Prop-content-length: 10
Text-content-length: 5
Text-content-md5: 49803c8f7913948eb3e30bae749ae6bd
Content-length: 15

PROPS-END
bloe


Revision-number: 2
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

Node-path: x\xc3\xa1
Node-action: delete

""")
        os.mkdir("old")

        load_dumpfile("dumpfile", "old")
        oldrepos = Repository.open("old")
        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, "", "none")))
        inv1 = newrepos.get_inventory(
                oldrepos.generate_revision_id(1, "", "none"))
        self.assertTrue(inv1.has_filename(u"x\xe1"))

    def test_fetch_replace_with_subreplace(self):
        filename = os.path.join(self.test_dir, "dumpfile")
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

Node-path: x/t
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END

Node-path: u
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END

Revision-number: 2
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

Node-path: x
Node-action: delete

Node-path: x
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 3
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

Node-path: x
Node-action: delete

Node-path: y
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 1
Node-copyfrom-path: x

Node-path: y/t
Node-action: delete

Node-path: y/t
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 1
Node-copyfrom-path: u


""")
        os.mkdir("old")

        load_dumpfile("dumpfile", "old")
        oldrepos = Repository.open("old")
        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, "", "none")))
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(3, "", "none")))
        inv1 = newrepos.get_inventory(
                oldrepos.generate_revision_id(1, "", "none"))
        inv2 = newrepos.get_inventory(
                oldrepos.generate_revision_id(3, "", "none"))

    def test_fetch_replace_self(self):
        filename = os.path.join(self.test_dir, "dumpfile")
        open(filename, 'w').write("""SVN-fs-dump-format-version: 2

UUID: 6dcc86fc-ac21-4df7-a3a3-87616123c853

Revision-number: 0
Prop-content-length: 56
Content-length: 56

K 8
svn:date
V 27
2006-12-25T04:27:54.633666Z
PROPS-END

Revision-number: 1
Prop-content-length: 108
Content-length: 108

K 7
svn:log
V 8
Add dir

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:28:17.503039Z
PROPS-END

Node-path: bla
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 2
Prop-content-length: 117
Content-length: 117

K 7
svn:log
V 16
Add another dir

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:28:30.160663Z
PROPS-END

Node-path: blie
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 3
Prop-content-length: 105
Content-length: 105

K 7
svn:log
V 5
Copy

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:28:44.996894Z
PROPS-END

Node-path: bloe
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 1
Node-copyfrom-path: bla


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

Node-path: bla
Node-action: delete


Node-path: bla
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 2
Node-copyfrom-path: bla


""")
        os.mkdir("old")

        load_dumpfile("dumpfile", "old")
        oldrepos = Repository.open("old")
        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, "", "none")))
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(3, "", "none")))
        inv1 = newrepos.get_inventory(
                oldrepos.generate_revision_id(1, "", "none"))
        inv2 = newrepos.get_inventory(
                oldrepos.generate_revision_id(3, "", "none"))
        self.assertEqual(inv1.path2id("bla"), inv2.path2id("bla"))

    def test_fetch_replace_backup(self):
        filename = os.path.join(self.test_dir, "dumpfile")
        open(filename, 'w').write("""SVN-fs-dump-format-version: 2

UUID: 6dcc86fc-ac21-4df7-a3a3-87616123c853

Revision-number: 0
Prop-content-length: 56
Content-length: 56

K 8
svn:date
V 27
2006-12-25T04:27:54.633666Z
PROPS-END

Revision-number: 1
Prop-content-length: 108
Content-length: 108

K 7
svn:log
V 8
Add dir

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:28:17.503039Z
PROPS-END

Node-path: bla
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 2
Prop-content-length: 117
Content-length: 117

K 7
svn:log
V 16
Add another dir

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:28:30.160663Z
PROPS-END

Node-path: blie
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 3
Prop-content-length: 105
Content-length: 105

K 7
svn:log
V 5
Copy

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:28:44.996894Z
PROPS-END

Node-path: bloe
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 1
Node-copyfrom-path: bla


Revision-number: 4
Prop-content-length: 112
Content-length: 112

K 7
svn:log
V 11
Change bla

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T23:51:09.678679Z
PROPS-END

Node-path: bla
Node-kind: dir
Node-action: change
Prop-content-length: 28
Content-length: 28

K 3
foo
V 5
bloe

PROPS-END


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

Node-path: bla
Node-action: delete


Node-path: bla
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 1
Node-copyfrom-path: bla


""")
        os.mkdir("old")

        load_dumpfile("dumpfile", "old")
        oldrepos = Repository.open("old")
        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, "", "none")))
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(3, "", "none")))
        inv1 = newrepos.get_inventory(
                oldrepos.generate_revision_id(1, "", "none"))
        inv2 = newrepos.get_inventory(
                oldrepos.generate_revision_id(3, "", "none"))
        self.assertEqual(inv1.path2id("bla"), inv2.path2id("bla"))

    def test_fetch_replace_unrelated(self):
        filename = os.path.join(self.test_dir, "dumpfile")
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

Node-path: x
Node-kind: dir
Node-action: add
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

Node-path: x
Node-action: delete


Node-path: x
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 1
Node-copyfrom-path: x

                
""")
        os.mkdir("old")

        load_dumpfile("dumpfile", "old")
        oldrepos = Repository.open("old")
        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, "", "none")))
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(4, "", "none")))
        inv1 = newrepos.get_inventory(
                oldrepos.generate_revision_id(1, "", "none"))
        inv2 = newrepos.get_inventory(
                oldrepos.generate_revision_id(4, "", "none"))
        self.assertNotEqual(inv1.path2id("x"), inv2.path2id("x"))

    def test_fetch_replace_related(self):
        filename = os.path.join(self.test_dir, "dumpfile")
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
        os.mkdir("old")

        load_dumpfile("dumpfile", "old")
        oldrepos = Repository.open("old")
        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, "", "none")))
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(5, "", "none")))
        inv1 = newrepos.get_inventory(
                oldrepos.generate_revision_id(1, "", "none"))
        inv2 = newrepos.get_inventory(
                oldrepos.generate_revision_id(5, "", "none"))
        self.assertNotEqual(inv1.path2id("y"), inv2.path2id("y"))

    def test_fetch_dir_upgrade(self):
        repos_url = self.make_client('d', 'dc')

        self.build_tree({'dc/trunk/lib/file': 'data'})
        self.client_add("dc/trunk")
        self.client_commit("dc", "trunk data")

        self.build_tree({'dc/branches': None})
        self.client_add("dc/branches")
        self.client_copy("dc/trunk/lib", "dc/branches/mybranch")
        self.client_commit("dc", "split out lib")

        oldrepos = Repository.open(repos_url)
        oldrepos.set_branching_scheme(TrunkBranchingScheme())
        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)

        branch = Branch.open("%s/branches/mybranch" % repos_url)
        self.assertEqual([oldrepos.generate_revision_id(2, "branches/mybranch", "trunk0")], 
                         branch.revision_history())

    def test_fetch_file_from_non_branch(self):
        repos_url = self.make_client('d', 'dc')

        self.build_tree({'dc/old-trunk/lib/file': 'data'})
        self.client_add("dc/old-trunk")
        self.client_commit("dc", "trunk data")

        self.build_tree({'dc/trunk/lib': None})
        self.client_add("dc/trunk")
        self.client_copy("dc/old-trunk/lib/file", "dc/trunk/lib/file")
        self.client_commit("dc", "revive old trunk")

        oldrepos = Repository.open(repos_url)
        oldrepos.set_branching_scheme(TrunkBranchingScheme())
        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)

        branch = Branch.open("%s/trunk" % repos_url)
        self.assertEqual([oldrepos.generate_revision_id(2, "trunk", "trunk0")], 
                         branch.revision_history())

    def test_fetch_dir_from_non_branch(self):
        repos_url = self.make_client('d', 'dc')

        self.build_tree({'dc/old-trunk/lib/file': 'data'})
        self.client_add("dc/old-trunk")
        self.client_commit("dc", "trunk data")

        self.build_tree({'dc/trunk': None})
        self.client_add("dc/trunk")
        self.client_copy("dc/old-trunk/lib", "dc/trunk")
        self.client_commit("dc", "revive old trunk")

        oldrepos = Repository.open(repos_url)
        oldrepos.set_branching_scheme(TrunkBranchingScheme())
        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)

        branch = Branch.open("%s/trunk" % repos_url)
        self.assertEqual([oldrepos.generate_revision_id(2, "trunk", "trunk0")],
                         branch.revision_history())

    def test_fetch_from_non_branch(self):
        repos_url = self.make_client('d', 'dc')

        self.build_tree({'dc/old-trunk/lib/file': 'data'})
        self.client_add("dc/old-trunk")
        self.client_commit("dc", "trunk data")

        self.client_copy("dc/old-trunk", "dc/trunk")
        self.client_commit("dc", "revive old trunk")

        oldrepos = Repository.open(repos_url)
        oldrepos.set_branching_scheme(TrunkBranchingScheme())
        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)

        branch = Branch.open("%s/trunk" % repos_url)
        self.assertEqual([oldrepos.generate_revision_id(2, "trunk", "trunk0")],
                         branch.revision_history())



    def test_fetch_branch_downgrade(self):
        repos_url = self.make_client('d', 'dc')

        self.build_tree({'dc/trunk/file': 'data'})
        self.client_add("dc/trunk")
        self.client_commit("dc", "trunk data")

        self.build_tree({'dc/branches/mybranch': None})
        self.client_add("dc/branches")
        self.client_copy("dc/trunk", "dc/branches/mybranch/lib")
        self.client_commit("dc", "split out lib")

        oldrepos = Repository.open(repos_url)
        oldrepos.set_branching_scheme(TrunkBranchingScheme())
        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)

    def test_fetch_all(self):
        repos_url = self.make_client('d', 'dc')

        self.build_tree({'dc/trunk': None, 
                         'dc/trunk/hosts': 'hej1'})
        self.client_add("dc/trunk")
        self.client_commit("dc", "created trunk and added hosts") #1

        self.build_tree({'dc/trunk/hosts': 'hej2'})
        self.client_commit("dc", "rev 2") #2

        self.build_tree({'dc/trunk/hosts': 'hej3'})
        self.client_commit("dc", "rev 3") #3

        self.build_tree({'dc/branches/foobranch/file': 'foohosts'})
        self.client_add("dc/branches")
        self.client_commit("dc", "foohosts") #4

        oldrepos = Repository.open(repos_url)
        oldrepos.set_branching_scheme(TrunkBranchingScheme())
        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)

        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, "trunk", "trunk0")))
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(2, "trunk", "trunk0")))
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(3, "trunk", "trunk0")))
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(4, "branches/foobranch", "trunk0")))
        self.assertFalse(newrepos.has_revision(
            oldrepos.generate_revision_id(4, "trunk", "trunk0")))
        self.assertFalse(newrepos.has_revision(
            oldrepos.generate_revision_id(2, "", "trunk0")))

    def test_fetch_copy_root_id_kept(self):
        repos_url = self.make_client('d', 'dc')

        self.build_tree({'dc/trunk': None, 
                         'dc/trunk/hosts': 'hej1'})
        self.client_add("dc/trunk")
        self.client_commit("dc", "created trunk and added hosts") #1

        self.build_tree({'dc/branches': None})
        self.client_add("dc/branches")
        self.client_commit("dc", "added branches") #2

        self.client_copy("dc/trunk", "dc/branches/foobranch")
        self.client_commit("dc", "added branch foobranch") #3

        repos = format.SvnRemoteAccess(SvnRaTransport("svn+"+repos_url), format.SvnFormat()).find_repository()

        tree = repos.revision_tree(
             repos.generate_revision_id(3, "branches/foobranch", "trunk0"))

        self.assertEqual(generate_svn_file_id(repos.uuid, 1, "trunk", ""), tree.inventory.root.file_id)

    def test_fetch_odd(self):
        repos_url = self.make_client('d', 'dc')

        self.build_tree({'dc/trunk': None, 
                         'dc/trunk/hosts': 'hej1'})
        self.client_add("dc/trunk")
        self.client_commit("dc", "created trunk and added hosts") #1
        self.client_update("dc")

        self.build_tree({'dc/trunk/hosts': 'hej2'})
        self.client_commit("dc", "rev 2") #2
        self.client_update("dc")

        self.build_tree({'dc/trunk/hosts': 'hej3'})
        self.client_commit("dc", "rev 3") #3
        self.client_update("dc")

        self.build_tree({'dc/branches': None})
        self.client_add("dc/branches")
        self.client_commit("dc", "added branches") #4
        self.client_update("dc")

        self.client_copy("dc/trunk", "dc/branches/foobranch")
        self.client_commit("dc", "added branch foobranch") #5
        self.client_update("dc")

        self.build_tree({'dc/branches/foobranch/hosts': 'foohosts'})
        self.client_commit("dc", "foohosts") #6

        repos = format.SvnRemoteAccess(SvnRaTransport("svn+"+repos_url), format.SvnFormat()).find_repository()

        tree = repos.revision_tree(
             repos.generate_revision_id(6, "branches/foobranch", "trunk0"))

    def test_fetch_consistent(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/bla': "data"})
        self.client_add("dc/bla")
        self.client_set_prop("dc/bla", "svn:executable", "*")
        self.client_commit("dc", "My Message")
        oldrepos = Repository.open("svn+"+repos_url)
        dir1 = BzrDir.create("f",format.get_rich_root_format())
        dir2 = BzrDir.create("g",format.get_rich_root_format())
        newrepos1 = dir1.create_repository()
        newrepos2 = dir2.create_repository()
        oldrepos.copy_content_into(newrepos1)
        oldrepos.copy_content_into(newrepos2)
        inv1 = newrepos1.get_inventory(
                oldrepos.generate_revision_id(1, "", "none"))
        inv2 = newrepos2.get_inventory(
                oldrepos.generate_revision_id(1, "", "none"))
        self.assertEqual(inv1, inv2)

    def test_fetch_executable(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/bla': "data", 'dc/blie': "data2"})
        self.client_add("dc/bla")
        self.client_add("dc/blie")
        self.client_set_prop("dc/bla", "svn:executable", "*")
        self.client_set_prop("dc/blie", "svn:executable", "")
        self.client_commit("dc", "My Message")
        oldrepos = Repository.open("svn+"+repos_url)
        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, "", "none")))
        inv1 = newrepos.get_inventory(
                oldrepos.generate_revision_id(1, "", "none"))
        self.assertTrue(inv1[inv1.path2id("bla")].executable)
        self.assertTrue(inv1[inv1.path2id("blie")].executable)

    def test_fetch_symlink(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/bla': "data"})
        os.symlink('bla', 'dc/mylink')
        self.client_add("dc/bla")
        self.client_add("dc/mylink")
        self.client_commit("dc", "My Message")
        oldrepos = Repository.open("svn+"+repos_url)
        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, "", "none")))
        inv1 = newrepos.get_inventory(
                oldrepos.generate_revision_id(1, "", "none"))
        self.assertEqual('symlink', inv1[inv1.path2id("mylink")].kind)
        self.assertEqual('bla', inv1[inv1.path2id("mylink")].symlink_target)


    def test_fetch_executable_separate(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/bla': "data"})
        self.client_add("dc/bla")
        self.client_commit("dc", "My Message")
        self.client_set_prop("dc/bla", "svn:executable", "*")
        self.client_commit("dc", "Make executable")
        oldrepos = Repository.open("svn+"+repos_url)
        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, "", "none")))
        inv1 = newrepos.get_inventory(
                oldrepos.generate_revision_id(1, "", "none"))
        self.assertFalse(inv1[inv1.path2id("bla")].executable)
        inv2 = newrepos.get_inventory(
                oldrepos.generate_revision_id(2, "", "none"))
        self.assertTrue(inv2[inv2.path2id("bla")].executable)
        self.assertEqual(oldrepos.generate_revision_id(2, "", "none"), 
                         inv2[inv2.path2id("bla")].revision)

    def test_fetch_ghosts(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/bla': "data"})
        self.client_add("dc/bla")
        self.client_set_prop("dc", "bzr:ancestry:v3-none", "aghost\n")
        self.client_commit("dc", "My Message")
        oldrepos = Repository.open("svn+"+repos_url)
        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)

        rev = newrepos.get_revision(oldrepos.generate_revision_id(1, "", "none"))
        self.assertTrue("aghost" in rev.parent_ids)

    def test_fetch_svk_merge(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/trunk/bla': "data", "dc/branches": None})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")

        self.client_add("dc/branches")
        self.client_copy("dc/trunk", "dc/branches/foo")
        self.build_tree({'dc/branches/foo/bla': "more data"})
        self.client_commit("dc", "Branch")

        oldrepos = Repository.open("svn+"+repos_url)
        self.client_set_prop("dc/trunk", "svk:merge", 
                             "%s:/branches/foo:2\n" % oldrepos.uuid)
        self.client_commit("dc", "Merge")

        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)

        rev = newrepos.get_revision(oldrepos.generate_revision_id(3, "trunk", "trunk0"))
        mutter('parent ids: %r' % rev.parent_ids)
        self.assertTrue(oldrepos.generate_revision_id(2, "branches/foo", "trunk0") in rev.parent_ids)

    def test_fetch_invalid_ghosts(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/bla': "data"})
        self.client_add("dc/bla")
        self.client_set_prop("dc", "bzr:ancestry:v3-none", "a ghost\n")
        self.client_commit("dc", "My Message")
        oldrepos = Repository.open("svn+"+repos_url)
        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)

        rev = newrepos.get_revision(oldrepos.generate_revision_id(1, "", "none"))
        self.assertEqual([oldrepos.generate_revision_id(0, "", "none")], rev.parent_ids)

    def test_fetch_property_change_only(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/trunk/bla': "data"})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message") #1
        self.client_set_prop("dc", "some:property", "some data\n")
        self.client_update("dc")
        self.client_commit("dc", "My 3") #2
        self.client_set_prop("dc", "some2:property", "some data\n")
        self.client_commit("dc", "My 2") #3
        self.client_set_prop("dc", "some:property", "some data4\n")
        self.client_commit("dc", "My 4") #4
        oldrepos = Repository.open("svn+"+repos_url)
        dir = BzrDir.create("f", format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.assertEquals([
            oldrepos.generate_revision_id(0, "", "none"),
            oldrepos.generate_revision_id(1, "", "none"),
            oldrepos.generate_revision_id(2, "", "none"),
            oldrepos.generate_revision_id(3, "", "none"),
            oldrepos.generate_revision_id(4, "", "none"),
            ], newrepos.all_revision_ids())

    def test_fetch_property_change_only_trunk(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/trunk/bla': "data"})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")
        self.client_set_prop("dc/trunk", "some:property", "some data\n")
        self.client_commit("dc", "My 3")
        self.client_set_prop("dc/trunk", "some2:property", "some data\n")
        self.client_commit("dc", "My 2")
        self.client_set_prop("dc/trunk", "some:property", "some data3\n")
        self.client_commit("dc", "My 4")
        oldrepos = Repository.open("svn+"+repos_url)
        oldrepos.set_branching_scheme(TrunkBranchingScheme())
        dir = BzrDir.create("f", format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.assertEquals([
            oldrepos.generate_revision_id(1, "trunk", "trunk0"),
            oldrepos.generate_revision_id(2, "trunk", "trunk0"),
            oldrepos.generate_revision_id(3, "trunk", "trunk0"),
            oldrepos.generate_revision_id(4, "trunk", "trunk0"),
            ], newrepos.all_revision_ids())

    def test_fetch_crosscopy(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/trunk/adir/afile': "data", 
                         'dc/trunk/adir/stationary': None,
                         'dc/branches/abranch': None})
        self.client_add("dc/trunk")
        self.client_add("dc/branches")
        self.client_commit("dc", "Initial commit")

        # copyrev
        self.client_copy("dc/trunk/adir", "dc/branches/abranch/bdir")
        self.client_commit("dc", "Cross copy commit")

        # prevrev
        self.build_tree({"dc/branches/abranch/bdir/afile": "otherdata"})
        self.client_commit("dc", "Change data")

        # lastrev
        self.build_tree({"dc/branches/abranch/bdir/bfile": "camel",
                      "dc/branches/abranch/bdir/stationary/traveller": "data"})
        self.client_add("dc/branches/abranch/bdir/bfile")
        self.client_add("dc/branches/abranch/bdir/stationary/traveller")
        self.client_commit("dc", "Change dir")

        oldrepos = Repository.open("svn+"+repos_url)
        oldrepos.set_branching_scheme(TrunkBranchingScheme())
        dir = BzrDir.create("f",format.get_rich_root_format())
        newrepos = dir.create_repository()
        copyrev = oldrepos.generate_revision_id(2, "branches/abranch", "trunk0")
        prevrev = oldrepos.generate_revision_id(3, "branches/abranch", "trunk0")
        lastrev = oldrepos.generate_revision_id(4, "branches/abranch", "trunk0")
        oldrepos.copy_content_into(newrepos, lastrev)

        inventory = newrepos.get_inventory(lastrev)
        self.assertEqual(prevrev, 
                         inventory[inventory.path2id("bdir/afile")].revision)

        inventory = newrepos.get_inventory(prevrev)
        self.assertEqual(copyrev, 
                         inventory[inventory.path2id("bdir/stationary")].revision)


