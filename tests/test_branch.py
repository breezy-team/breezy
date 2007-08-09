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

"""Branch tests."""

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.errors import NoSuchFile, NoSuchRevision, NotBranchError
from bzrlib.repository import Repository
from bzrlib.trace import mutter

import os
from unittest import TestCase

from branch import FakeControlFiles, SvnBranchFormat
from convert import load_dumpfile
from fileids import generate_svn_file_id
from repository import MAPPING_VERSION, generate_svn_revision_id, SVN_PROP_BZR_REVISION_ID
from tests import TestCaseWithSubversionRepository

class WorkingSubversionBranch(TestCaseWithSubversionRepository):
    def test_last_rev_rev_hist(self):
        repos_url = self.make_client("a", "dc")
        branch = Branch.open(repos_url)
        branch.revision_history()
        self.assertEqual(branch.generate_revision_id(0), branch.last_revision())

    def test_get_branch_path_root(self):
        repos_url = self.make_client("a", "dc")
        branch = Branch.open(repos_url)
        self.assertEqual("", branch.get_branch_path())

    def test_get_branch_path_subdir(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({"dc/trunk": None})
        self.client_add("dc/trunk")
        self.client_commit("dc", "Add branch")
        branch = Branch.open(repos_url+"/trunk")
        self.assertEqual("trunk", branch.get_branch_path())

    def test_open_nonexistant(self):
        repos_url = self.make_client("a", "dc")
        self.assertRaises(NotBranchError, Branch.open, repos_url + "/trunk")

    def test_last_rev_rev_info(self):
        repos_url = self.make_client("a", "dc")
        branch = Branch.open(repos_url)
        self.assertEqual((1, branch.generate_revision_id(0)),
                branch.last_revision_info())
        branch.revision_history()
        self.assertEqual((1, branch.generate_revision_id(0)),
                branch.last_revision_info())

    def test_lookup_revision_id_unknown(self):
        repos_url = self.make_client("a", "dc")
        branch = Branch.open(repos_url)
        self.assertRaises(NoSuchRevision, 
                lambda: branch.lookup_revision_id("bla"))

    def test_lookup_revision_id(self):
        repos_url = self.make_client("a", "dc")
        branch = Branch.open(repos_url)
        self.assertEquals(0, 
                branch.lookup_revision_id(branch.last_revision()))

    def test_set_parent(self):
        repos_url = self.make_client('a', 'dc')
        branch = Branch.open(repos_url)
        branch.set_parent("foobar")

    def test_num_revnums(self):
        repos_url = self.make_client('a', 'dc')
        bzrdir = BzrDir.open("svn+"+repos_url)
        branch = bzrdir.open_branch()
        self.assertEqual(branch.generate_revision_id(0),
                         branch.last_revision())

        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.client_update("dc")
        
        bzrdir = BzrDir.open("svn+"+repos_url)
        branch = bzrdir.open_branch()
        repos = bzrdir.find_repository()

        self.assertEqual(repos.generate_revision_id(1, "", "none"), 
                branch.last_revision())

        self.build_tree({'dc/foo': "data2"})
        self.client_commit("dc", "My Message")

        branch = Branch.open("svn+"+repos_url)
        repos = Repository.open("svn+"+repos_url)

        self.assertEqual(repos.generate_revision_id(2, "", "none"),
                branch.last_revision())

    def test_set_revision_history(self):
        repos_url = self.make_client('a', 'dc')
        branch = Branch.open("svn+"+repos_url)
        self.assertRaises(NotImplementedError, branch.set_revision_history, [])

    def test_break_lock(self):
        repos_url = self.make_client('a', 'dc')
        branch = Branch.open("svn+"+repos_url)
        branch.control_files.break_lock()

    def test_repr(self):
        repos_url = self.make_client('a', 'dc')
        branch = Branch.open("svn+"+repos_url)
        self.assertEqual("SvnBranch('svn+%s')" % repos_url, branch.__repr__())

    def test_get_physical_lock_status(self):
        repos_url = self.make_client('a', 'dc')
        branch = Branch.open("svn+"+repos_url)
        self.assertFalse(branch.get_physical_lock_status())

    def test_set_push_location(self):
        repos_url = self.make_client('a', 'dc')
        branch = Branch.open("svn+"+repos_url)
        self.assertRaises(NotImplementedError, branch.set_push_location, [])

    def test_get_parent(self):
        repos_url = self.make_client('a', 'dc')
        branch = Branch.open("svn+"+repos_url)
        self.assertEqual("svn+"+repos_url, branch.get_parent())

    def test_append_revision(self):
        repos_url = self.make_client('a', 'dc')
        branch = Branch.open("svn+"+repos_url)
        branch.append_revision([])

    def test_get_push_location(self):
        repos_url = self.make_client('a', 'dc')
        branch = Branch.open("svn+"+repos_url)
        self.assertIs(None, branch.get_push_location())

    def test_revision_history(self):
        repos_url = self.make_client('a', 'dc')

        branch = Branch.open("svn+"+repos_url)
        self.assertEqual([branch.generate_revision_id(0)], 
                branch.revision_history())

        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_set_prop("dc", SVN_PROP_BZR_REVISION_ID+"none", 
                "42 mycommit\n")
        self.client_commit("dc", "My Message")
        self.client_update("dc")
        
        branch = Branch.open("svn+"+repos_url)
        repos = Repository.open("svn+"+repos_url)

        self.assertEqual([repos.generate_revision_id(0, "", "none"), 
                    repos.generate_revision_id(1, "", "none")], 
                branch.revision_history())

        self.build_tree({'dc/foo': "data34"})
        self.client_commit("dc", "My Message")

        branch = Branch.open("svn+"+repos_url)
        repos = Repository.open("svn+"+repos_url)

        self.assertEqual([
            repos.generate_revision_id(0, "", "none"),
            "mycommit",
            repos.generate_revision_id(2, "", "none")],
            branch.revision_history())

    def test_revision_id_to_revno_none(self):
        """The None revid should map to revno 0."""
        repos_url = self.make_client('a', 'dc')
        branch = Branch.open(repos_url)
        self.assertEquals(0, branch.revision_id_to_revno(None))

    def test_revision_id_to_revno_nonexistant(self):
        """revision_id_to_revno() should raise NoSuchRevision if
        the specified revision did not exist in the branch history."""
        repos_url = self.make_client('a', 'dc')
        branch = Branch.open(repos_url)
        self.assertRaises(NoSuchRevision, branch.revision_id_to_revno, "bla")
    
    def test_revision_id_to_revno_simple(self):
        repos_url = self.make_client('a', 'dc')
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_set_prop("dc", "bzr:revision-id:v%d-none" % MAPPING_VERSION, 
                            "2 myrevid\n")
        self.client_commit("dc", "My Message")
        branch = Branch.open(repos_url)
        self.assertEquals(2, branch.revision_id_to_revno("myrevid"))

    def test_revision_id_to_revno_older(self):
        repos_url = self.make_client('a', 'dc')
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_set_prop("dc", "bzr:revision-id:v%d-none" % MAPPING_VERSION, 
                            "2 myrevid\n")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/foo': "someotherdata"})
        self.client_set_prop("dc", "bzr:revision-id:v%d-none" % MAPPING_VERSION, 
                            "2 myrevid\n3 mysecondrevid\n")
        self.client_commit("dc", "My Message")
        branch = Branch.open(repos_url)
        self.assertEquals(3, branch.revision_id_to_revno("mysecondrevid"))
        self.assertEquals(2, branch.revision_id_to_revno("myrevid"))

    def test_get_nick_none(self):
        repos_url = self.make_client('a', 'dc')

        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")

        branch = Branch.open("svn+"+repos_url)

        self.assertIs(None, branch.nick)

    def test_get_nick_path(self):
        repos_url = self.make_client('a', 'dc')

        self.build_tree({'dc/trunk': None})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")

        branch = Branch.open("svn+"+repos_url+"/trunk")

        self.assertEqual("trunk", branch.nick)

    def test_get_revprops(self):
        repos_url = self.make_client('a', 'dc')

        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_set_prop("dc", "bzr:revision-info", 
                "properties: \n\tbranch-nick: mybranch\n")
        self.client_commit("dc", "My Message")

        branch = Branch.open("svn+"+repos_url)

        rev = branch.repository.get_revision(branch.last_revision())

        self.assertEqual("mybranch", rev.properties["branch-nick"])

    def test_fetch_replace(self):
        filename = os.path.join(self.test_dir, "dumpfile")
        open(filename, 'w').write("""SVN-fs-dump-format-version: 2

UUID: 6f95bc5c-e18d-4021-aca8-49ed51dbcb75

Revision-number: 0
Prop-content-length: 56
Content-length: 56

K 8
svn:date
V 27
2006-07-30T12:41:25.270824Z
PROPS-END

Revision-number: 1
Prop-content-length: 94
Content-length: 94

K 7
svn:log
V 0

K 10
svn:author
V 0

K 8
svn:date
V 27
2006-07-30T12:41:26.117512Z
PROPS-END

Node-path: trunk
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Node-path: trunk/hosts
Node-kind: file
Node-action: add
Prop-content-length: 10
Text-content-length: 4
Text-content-md5: 771ec3328c29d17af5aacf7f895dd885
Content-length: 14

PROPS-END
hej1

Revision-number: 2
Prop-content-length: 94
Content-length: 94

K 7
svn:log
V 0

K 10
svn:author
V 0

K 8
svn:date
V 27
2006-07-30T12:41:27.130044Z
PROPS-END

Node-path: trunk/hosts
Node-kind: file
Node-action: change
Text-content-length: 4
Text-content-md5: 6c2479dbb342b8df96d84db7ab92c412
Content-length: 4

hej2

Revision-number: 3
Prop-content-length: 94
Content-length: 94

K 7
svn:log
V 0

K 10
svn:author
V 0

K 8
svn:date
V 27
2006-07-30T12:41:28.114350Z
PROPS-END

Node-path: trunk/hosts
Node-kind: file
Node-action: change
Text-content-length: 4
Text-content-md5: 368cb8d3db6186e2e83d9434f165c525
Content-length: 4

hej3

Revision-number: 4
Prop-content-length: 94
Content-length: 94

K 7
svn:log
V 0

K 10
svn:author
V 0

K 8
svn:date
V 27
2006-07-30T12:41:29.129563Z
PROPS-END

Node-path: branches
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 5
Prop-content-length: 94
Content-length: 94

K 7
svn:log
V 0

K 10
svn:author
V 0

K 8
svn:date
V 27
2006-07-30T12:41:31.130508Z
PROPS-END

Node-path: branches/foobranch
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 4
Node-copyfrom-path: trunk


Revision-number: 6
Prop-content-length: 94
Content-length: 94

K 7
svn:log
V 0

K 10
svn:author
V 0

K 8
svn:date
V 27
2006-07-30T12:41:33.129149Z
PROPS-END

Node-path: branches/foobranch/hosts
Node-kind: file
Node-action: delete

Node-path: branches/foobranch/hosts
Node-kind: file
Node-action: add
Node-copyfrom-rev: 2
Node-copyfrom-path: trunk/hosts




Revision-number: 7
Prop-content-length: 94
Content-length: 94

K 7
svn:log
V 0

K 10
svn:author
V 0

K 8
svn:date
V 27
2006-07-30T12:41:34.136423Z
PROPS-END

Node-path: branches/foobranch/hosts
Node-kind: file
Node-action: change
Text-content-length: 8
Text-content-md5: 0e328d3517a333a4879ebf3d88fd82bb
Content-length: 8

foohosts""")
        os.mkdir("new")
        os.mkdir("old")

        load_dumpfile("dumpfile", "old")

        url = "old/branches/foobranch"
        mutter('open %r' % url)
        olddir = BzrDir.open(url)

        newdir = olddir.sprout("new")

        newbranch = newdir.open_branch()

        uuid = "6f95bc5c-e18d-4021-aca8-49ed51dbcb75"
        tree = newbranch.repository.revision_tree(
                generate_svn_revision_id(uuid, 7, "branches/foobranch", 
                "trunk0"))

        weave = newbranch.repository.weave_store.get_weave(
            tree.inventory.path2id("hosts"),
            newbranch.repository.get_transaction())
        self.assertEqual([
            generate_svn_revision_id(uuid, 6, "branches/foobranch", "trunk0"),
            generate_svn_revision_id(uuid, 7, "branches/foobranch", "trunk0")],
                          weave.versions())
 

    def test_fetch_odd(self):
        repos_url = self.make_client('d', 'dc')

        self.build_tree({'dc/trunk': None, 
                         'dc/trunk/hosts': 'hej1'})
        self.client_add("dc/trunk")
        self.client_commit("dc", "created trunk and added hosts") #1

        self.build_tree({'dc/trunk/hosts': 'hej2'})
        self.client_commit("dc", "rev 2") #2

        self.build_tree({'dc/trunk/hosts': 'hej3'})
        self.client_commit("dc", "rev 3") #3

        self.build_tree({'dc/branches': None})
        self.client_add("dc/branches")
        self.client_commit("dc", "added branches") #4

        self.client_copy("dc/trunk", "dc/branches/foobranch")
        self.client_commit("dc", "added branch foobranch") #5

        self.build_tree({'dc/branches/foobranch/hosts': 'foohosts'})
        self.client_commit("dc", "foohosts") #6

        os.mkdir("new")

        url = "svn+"+repos_url+"/branches/foobranch"
        mutter('open %r' % url)
        olddir = BzrDir.open(url)

        newdir = olddir.sprout("new")

        newbranch = newdir.open_branch()

        uuid = olddir.find_repository().uuid
        tree = newbranch.repository.revision_tree(
             generate_svn_revision_id(uuid, 6, "branches/foobranch", "trunk0"))

        weave = newbranch.repository.weave_store.get_weave(
                tree.inventory.path2id("hosts"), 
                newbranch.repository.get_transaction())
        self.assertEqual([
            generate_svn_revision_id(uuid, 1, "trunk", "trunk0"),
            generate_svn_revision_id(uuid, 2, "trunk", "trunk0"),
            generate_svn_revision_id(uuid, 3, "trunk", "trunk0"),
            generate_svn_revision_id(uuid, 6, "branches/foobranch", "trunk0")],
                          weave.versions())

    def test_check(self):
        self.make_client('d', 'dc')
        branch = Branch.open('d')
        result = branch.check()
        self.assertEqual(branch, result.branch) 
 
    def test_generate_revision_id(self):
        self.make_client('d', 'dc')
        self.build_tree({'dc/bla/bloe': None})
        self.client_add("dc/bla")
        self.client_commit("dc", "bla")
        branch = Branch.open('d')
        self.assertEqual("svn-v%d-none:%s::1" % (MAPPING_VERSION, branch.repository.uuid),  branch.generate_revision_id(1))

    def test_create_checkout(self):
        repos_url = self.make_client('d', 'dc')

        self.build_tree({'dc/trunk': None, 'dc/trunk/hosts': 'hej1'})
        self.client_add("dc/trunk")
        self.client_commit("dc", "created trunk and added hosts") #1

        url = "svn+"+repos_url+"/trunk"
        oldbranch = Branch.open(url)

        newtree = self.create_checkout(oldbranch, "e")
        self.assertTrue(newtree.branch.repository.has_revision(
           oldbranch.generate_revision_id(1)))

        self.assertTrue(os.path.exists("e/.bzr"))
        self.assertFalse(os.path.exists("e/.svn"))

    def test_create_checkout_lightweight(self):
        repos_url = self.make_client('d', 'dc')

        self.build_tree({'dc/trunk': None, 
                         'dc/trunk/hosts': 'hej1'})
        self.client_add("dc/trunk")
        self.client_commit("dc", "created trunk and added hosts") #1

        url = "svn+"+repos_url+"/trunk"
        oldbranch = Branch.open(url)

        newtree = self.create_checkout(oldbranch, "e", lightweight=True)
        self.assertEqual(oldbranch.generate_revision_id(1), newtree.base_revid)
        self.assertTrue(os.path.exists("e/.svn"))
        self.assertFalse(os.path.exists("e/.bzr"))

    def test_create_checkout_lightweight_stop_rev(self):
        repos_url = self.make_client('d', 'dc')

        self.build_tree({'dc/trunk': None, 
                         'dc/trunk/hosts': 'hej1'})
        self.client_add("dc/trunk")
        self.client_commit("dc", "created trunk and added hosts") #1
        
        self.build_tree({'dc/trunk/hosts': 'bloe'})
        self.client_commit("dc", "added another revision")

        url = "svn+"+repos_url+"/trunk"
        oldbranch = Branch.open(url)

        newtree = self.create_checkout(oldbranch, "e", revision_id=
           oldbranch.generate_revision_id(1), lightweight=True)
        self.assertEqual(oldbranch.generate_revision_id(1),
           newtree.base_revid)
        self.assertTrue(os.path.exists("e/.svn"))
        self.assertFalse(os.path.exists("e/.bzr"))

    def test_fetch_branch(self):
        self.make_client('d', 'sc')

        self.build_tree({'sc/foo/bla': "data"})
        self.client_add("sc/foo")
        self.client_commit("sc", "foo")

        olddir = self.open_checkout_bzrdir("sc")

        os.mkdir("dc")
        
        newdir = olddir.sprout('dc')

        self.assertEqual(
                olddir.open_branch().last_revision(),
                newdir.open_branch().last_revision())

    def test_fetch_dir_upgrade(self):
        repos_url = self.make_client('d', 'sc')

        self.build_tree({'sc/trunk/mylib/bla': "data", "sc/branches": None})
        self.client_add("sc/trunk")
        self.client_add("sc/branches")
        self.client_commit("sc", "foo")

        self.client_copy("sc/trunk/mylib", "sc/branches/abranch")
        self.client_commit("sc", "Promote mylib")

        olddir = self.open_checkout_bzrdir("sc/branches/abranch")

        os.mkdir("dc")
        
        newdir = olddir.sprout('dc')

        self.assertEqual(
                olddir.open_branch().last_revision(),
                newdir.open_branch().last_revision())

    def test_fetch_branch_downgrade(self):
        repos_url = self.make_client('d', 'sc')

        self.build_tree({'sc/trunk': None, "sc/branches/abranch/bla": 'foo'})
        self.client_add("sc/trunk")
        self.client_add("sc/branches")
        self.client_commit("sc", "foo")

        self.client_copy("sc/branches/abranch", "sc/trunk/mylib")
        self.client_commit("sc", "Demote mylib")

        olddir = self.open_checkout_bzrdir("sc/trunk")

        os.mkdir("dc")
        
        newdir = olddir.sprout('dc')

        self.assertEqual(
                olddir.open_branch().last_revision(),
                newdir.open_branch().last_revision())



    def test_ghost_workingtree(self):
        # Looks like bazaar has trouble creating a working tree of a 
        # revision that has ghost parents
        self.make_client('d', 'sc')

        self.build_tree({'sc/foo/bla': "data"})
        self.client_add("sc/foo")
        self.client_set_prop("sc", "bzr:ancestry:v3-none", "some-ghost\n")
        self.client_commit("sc", "foo")

        olddir = self.open_checkout_bzrdir("sc")

        os.mkdir("dc")
        
        newdir = olddir.sprout('dc')
        newdir.find_repository().get_revision(
                newdir.open_branch().last_revision())
        newdir.find_repository().get_revision_inventory(
                newdir.open_branch().last_revision())

class TestFakeControlFiles(TestCase):
    def test_get_utf8(self):
        f = FakeControlFiles()
        self.assertRaises(NoSuchFile, f.get_utf8, "foo")


    def test_get(self):
        f = FakeControlFiles()
        self.assertRaises(NoSuchFile, f.get, "foobla")

class BranchFormatTests(TestCase):
    def setUp(self):
        self.format = SvnBranchFormat()

    def test_initialize(self):
        self.assertRaises(NotImplementedError, self.format.initialize, None)

    def test_get_format_string(self):
        self.assertEqual("Subversion Smart Server", 
                         self.format.get_format_string())

    def test_get_format_description(self):
        self.assertEqual("Subversion Smart Server", 
                         self.format.get_format_description())
