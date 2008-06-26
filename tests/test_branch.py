# Copyright (C) 2006-2007 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
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
from bzrlib.revision import NULL_REVISION
from bzrlib.trace import mutter

import os
from unittest import TestCase

from bzrlib.plugins.svn.branch import FakeControlFiles, SvnBranchFormat
from bzrlib.plugins.svn.convert import load_dumpfile
from bzrlib.plugins.svn.mapping import SVN_PROP_BZR_REVISION_ID
from bzrlib.plugins.svn.mapping3 import BzrSvnMappingv3FileProps
from bzrlib.plugins.svn.mapping3.scheme import TrunkBranchingScheme
from bzrlib.plugins.svn.tests import TestCaseWithSubversionRepository

class WorkingSubversionBranch(TestCaseWithSubversionRepository):
    def test_last_rev_rev_hist(self):
        repos_url = self.make_repository("a")
        branch = Branch.open(repos_url)
        branch.revision_history()
        self.assertEqual(branch.generate_revision_id(0), branch.last_revision())

    def test_get_branch_path_root(self):
        repos_url = self.make_repository("a")
        branch = Branch.open(repos_url)
        self.assertEqual("", branch.get_branch_path())

    def test_get_branch_path_subdir(self):
        repos_url = self.make_repository("a")

        dc = self.get_commit_editor(repos_url)
        dc.add_dir("trunk")
        dc.close()

        branch = Branch.open(repos_url+"/trunk")
        self.assertEqual("trunk", branch.get_branch_path())

    def test_open_nonexistant(self):
        repos_url = self.make_repository("a")
        self.assertRaises(NotBranchError, Branch.open, repos_url + "/trunk")

    def test_last_rev_rev_info(self):
        repos_url = self.make_repository("a")
        branch = Branch.open(repos_url)
        self.assertEqual((1, branch.generate_revision_id(0)),
                branch.last_revision_info())
        branch.revision_history()
        self.assertEqual((1, branch.generate_revision_id(0)),
                branch.last_revision_info())

    def test_lookup_revision_id_unknown(self):
        repos_url = self.make_repository("a")
        branch = Branch.open(repos_url)
        self.assertRaises(NoSuchRevision, 
                lambda: branch.lookup_revision_id("bla"))

    def test_lookup_revision_id(self):
        repos_url = self.make_repository("a")
        branch = Branch.open(repos_url)
        self.assertEquals(0, 
                branch.lookup_revision_id(branch.last_revision()))

    def test_set_parent(self):
        repos_url = self.make_repository('a')
        branch = Branch.open(repos_url)
        branch.set_parent("foobar")

    def test_num_revnums(self):
        repos_url = self.make_repository('a')
        bzrdir = BzrDir.open("svn+"+repos_url)
        branch = bzrdir.open_branch()
        self.assertEqual(branch.generate_revision_id(0),
                         branch.last_revision())

        dc = self.get_commit_editor(repos_url)
        dc.add_file("foo").modify()
        dc.close()
        
        bzrdir = BzrDir.open("svn+"+repos_url)
        branch = bzrdir.open_branch()
        repos = bzrdir.find_repository()
        
        mapping = repos.get_mapping()

        self.assertEqual(repos.generate_revision_id(1, "", mapping), 
                branch.last_revision())

        dc = self.get_commit_editor(repos_url)
        dc.open_file("foo").modify()
        dc.close()

        branch = Branch.open("svn+"+repos_url)
        repos = Repository.open("svn+"+repos_url)

        self.assertEqual(repos.generate_revision_id(2, "", mapping),
                branch.last_revision())

    def test_set_revision_history(self):
        repos_url = self.make_repository('a')
        branch = Branch.open("svn+"+repos_url)
        self.assertRaises(NotImplementedError, branch.set_revision_history, [])

    def test_break_lock(self):
        repos_url = self.make_repository('a')
        branch = Branch.open("svn+"+repos_url)
        branch.control_files.break_lock()

    def test_repr(self):
        repos_url = self.make_repository('a')
        branch = Branch.open("svn+"+repos_url)
        self.assertEqual("SvnBranch('svn+%s')" % repos_url, branch.__repr__())

    def test_get_physical_lock_status(self):
        repos_url = self.make_repository('a')
        branch = Branch.open("svn+"+repos_url)
        self.assertFalse(branch.get_physical_lock_status())

    def test_set_push_location(self):
        repos_url = self.make_repository('a')
        branch = Branch.open("svn+"+repos_url)
        self.assertRaises(NotImplementedError, branch.set_push_location, [])

    def test_get_parent(self):
        repos_url = self.make_repository('a')
        branch = Branch.open("svn+"+repos_url)
        self.assertEqual(None, branch.get_parent())

    def test_append_revision(self):
        repos_url = self.make_repository('a')
        branch = Branch.open("svn+"+repos_url)
        branch.append_revision([])

    def test_get_push_location(self):
        repos_url = self.make_repository('a')
        branch = Branch.open("svn+"+repos_url)
        self.assertIs(None, branch.get_push_location())

    def test_revision_history(self):
        repos_url = self.make_repository('a')

        branch = Branch.open("svn+"+repos_url)
        self.assertEqual([branch.generate_revision_id(0)], 
                branch.revision_history())

        dc = self.get_commit_editor(repos_url)
        dc.add_file("foo").modify()
        dc.change_prop(SVN_PROP_BZR_REVISION_ID+"none", 
                "42 mycommit\n")
        dc.close()
        
        branch = Branch.open("svn+"+repos_url)
        repos = Repository.open("svn+"+repos_url)
        
        mapping = repos.get_mapping()

        self.assertEqual([repos.generate_revision_id(0, "", mapping), 
                    repos.generate_revision_id(1, "", mapping)], 
                branch.revision_history())

        dc = self.get_commit_editor(repos_url)
        dc.open_file("foo").modify()
        dc.close()

        branch = Branch.open("svn+"+repos_url)
        repos = Repository.open("svn+"+repos_url)

        mapping = repos.get_mapping()

        self.assertEqual([
            repos.generate_revision_id(0, "", mapping),
            "mycommit",
            repos.generate_revision_id(2, "", mapping)],
            branch.revision_history())

    def test_revision_id_to_revno_none(self):
        """The None revid should map to revno 0."""
        repos_url = self.make_repository('a')
        branch = Branch.open(repos_url)
        self.assertEquals(0, branch.revision_id_to_revno(NULL_REVISION))

    def test_revision_id_to_revno_nonexistant(self):
        """revision_id_to_revno() should raise NoSuchRevision if
        the specified revision did not exist in the branch history."""
        repos_url = self.make_repository('a')
        branch = Branch.open(repos_url)
        self.assertRaises(NoSuchRevision, branch.revision_id_to_revno, "bla")
    
    def test_revision_id_to_revno_simple(self):
        repos_url = self.make_repository('a')

        dc = self.get_commit_editor(repos_url)
        dc.add_file("foo").modify()
        dc.change_prop("bzr:revision-id:v3-none", 
                            "2 myrevid\n")
        dc.close()

        branch = Branch.open(repos_url)
        self.assertEquals(2, branch.revision_id_to_revno("myrevid"))

    def test_revision_id_to_revno_older(self):
        repos_url = self.make_repository('a')

        dc = self.get_commit_editor(repos_url)
        dc.add_file("foo").modify()
        dc.change_prop("bzr:revision-id:v3-none", 
                            "2 myrevid\n")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.open_file("foo").modify()
        dc.change_prop("bzr:revision-id:v3-none", 
                            "2 myrevid\n3 mysecondrevid\n")
        dc.close()

        branch = Branch.open(repos_url)
        self.assertEquals(3, branch.revision_id_to_revno("mysecondrevid"))
        self.assertEquals(2, branch.revision_id_to_revno("myrevid"))

    def test_get_nick_none(self):
        repos_url = self.make_repository('a')

        dc = self.get_commit_editor(repos_url)
        dc.add_file("foo").modify()
        dc.close()

        branch = Branch.open("svn+"+repos_url)

        self.assertIs(None, branch.nick)

    def test_get_nick_path(self):
        repos_url = self.make_repository('a')

        dc = self.get_commit_editor(repos_url)
        dc.add_dir("trunk")
        dc.close()

        branch = Branch.open("svn+"+repos_url+"/trunk")

        self.assertEqual("trunk", branch.nick)

    def test_get_revprops(self):
        repos_url = self.make_repository('a')

        dc = self.get_commit_editor(repos_url)
        dc.add_file("foo").modify()
        dc.change_prop("bzr:revision-info", 
                "properties: \n\tbranch-nick: mybranch\n")
        dc.close()

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

        oldbranch = Branch.open(url)

        uuid = "6f95bc5c-e18d-4021-aca8-49ed51dbcb75"
        newbranch.lock_read()
        tree = newbranch.repository.revision_tree(oldbranch.generate_revision_id(7))

        weave = newbranch.repository.weave_store.get_weave(
            tree.inventory.path2id("hosts"),
            newbranch.repository.get_transaction())

        self.assertEqual(set([
            oldbranch.generate_revision_id(6),
            oldbranch.generate_revision_id(7)]),
                          set(weave.versions()))
        newbranch.unlock()
 

    def test_fetch_odd(self):
        repos_url = self.make_repository('d')

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        trunk.add_file("trunk/hosts").modify()
        dc.close()

        dc = self.get_commit_editor(repos_url)
        trunk = dc.open_dir("trunk")
        trunk.open_file("trunk/hosts").modify()
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.open_file("trunk/hosts").modify()
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.add_dir("branches")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        branches = dc.open_dir("branches")
        branches.add_dir("branches/foobranch", "trunk")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        branches = dc.open_dir("branches")
        foobranch = branches.open_dir("branches/foobranch")
        foobranch.open_file("branches/foobranch/hosts").modify()
        dc.close()

        os.mkdir("new")

        url = "svn+"+repos_url+"/branches/foobranch"
        mutter('open %r' % url)
        olddir = BzrDir.open(url)

        newdir = olddir.sprout("new")

        newbranch = newdir.open_branch()
        oldbranch = olddir.open_branch()

        uuid = olddir.find_repository().uuid
        tree = newbranch.repository.revision_tree(
             oldbranch.generate_revision_id(6))
        transaction = newbranch.repository.get_transaction()
        newbranch.repository.lock_read()
        texts = newbranch.repository.texts
        host_fileid = tree.inventory.path2id("hosts")
        mapping = BzrSvnMappingv3FileProps(TrunkBranchingScheme())
        self.assertEqual(set([
            (host_fileid, mapping.generate_revision_id(uuid, 1, "trunk")),
            (host_fileid, mapping.generate_revision_id(uuid, 2, "trunk")),
            (host_fileid, mapping.generate_revision_id(uuid, 3, "trunk")),
            (host_fileid, oldbranch.generate_revision_id(6))]),
            set(filter(lambda (fid, rid): fid == host_fileid, texts.keys())))
        newbranch.repository.unlock()

    def test_check(self):
        self.make_repository('d')
        branch = Branch.open('d')
        result = branch.check()
        self.assertEqual(branch, result.branch) 
 
    def test_generate_revision_id(self):
        repos_url = self.make_repository('d')

        dc = self.get_commit_editor(repos_url)
        bla = dc.add_dir("bla")
        bla.add_dir("bla/bloe")
        dc.close()

        branch = Branch.open('d')
        self.assertEqual("svn-v3-none:%s::1" % (branch.repository.uuid),  branch.generate_revision_id(1))

    def test_create_checkout(self):
        repos_url = self.make_repository('d')

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        trunk.add_file("trunk/hosts").modify()
        dc.close()

        url = "svn+"+repos_url+"/trunk"
        oldbranch = Branch.open(url)

        newtree = self.create_checkout(oldbranch, "e")
        self.assertTrue(newtree.branch.repository.has_revision(
           oldbranch.generate_revision_id(1)))

        self.assertTrue(os.path.exists("e/.bzr"))
        self.assertFalse(os.path.exists("e/.svn"))

    def test_create_checkout_lightweight(self):
        repos_url = self.make_repository('d')

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        trunk.add_file("trunk/hosts")
        dc.close()

        url = "svn+"+repos_url+"/trunk"
        oldbranch = Branch.open(url)

        newtree = self.create_checkout(oldbranch, "e", lightweight=True)
        self.assertEqual(oldbranch.generate_revision_id(1), newtree.base_revid)
        self.assertTrue(os.path.exists("e/.svn"))
        self.assertFalse(os.path.exists("e/.bzr"))

    def test_create_checkout_lightweight_stop_rev(self):
        repos_url = self.make_repository('d')

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        trunk.add_file("trunk/hosts").modify()
        dc.close()

        dc = self.get_commit_editor(repos_url)
        trunk = dc.open_dir("trunk")
        trunk.open_file("trunk/hosts").modify()
        dc.close()

        url = "svn+"+repos_url+"/trunk"
        oldbranch = Branch.open(url)

        newtree = self.create_checkout(oldbranch, "e", revision_id=
           oldbranch.generate_revision_id(1), lightweight=True)
        self.assertEqual(oldbranch.generate_revision_id(1),
           newtree.base_revid)
        self.assertTrue(os.path.exists("e/.svn"))
        self.assertFalse(os.path.exists("e/.bzr"))

    def test_fetch_branch(self):
        repos_url = self.make_client('d', 'sc')

        sc = self.get_commit_editor(repos_url)
        foo = sc.add_dir("foo")
        foo.add_file("foo/bla").modify()
        sc.close()

        olddir = self.open_checkout_bzrdir("sc")

        os.mkdir("dc")
        
        newdir = olddir.sprout('dc')

        self.assertEqual(
                olddir.open_branch().last_revision(),
                newdir.open_branch().last_revision())

    def test_fetch_dir_upgrade(self):
        repos_url = self.make_client('d', 'sc')

        sc = self.get_commit_editor(repos_url)
        trunk = sc.add_dir("trunk")
        mylib = trunk.add_dir("trunk/mylib")
        mylib.add_file("trunk/mylib/bla").modify()
        sc.add_dir("branches")
        sc.close()

        sc = self.get_commit_editor(repos_url)
        branches = sc.open_dir("branches")
        branches.add_dir("branches/abranch", "trunk/mylib")
        sc.close()

        self.client_update('sc')
        olddir = self.open_checkout_bzrdir("sc/branches/abranch")

        os.mkdir("dc")
        
        newdir = olddir.sprout('dc')

        self.assertEqual(
                olddir.open_branch().last_revision(),
                newdir.open_branch().last_revision())

    def test_fetch_branch_downgrade(self):
        repos_url = self.make_client('d', 'sc')

        sc = self.get_commit_editor(repos_url)
        sc.add_dir("trunk")
        branches = sc.add_dir("branches")
        abranch = branches.add_dir("branches/abranch")
        abranch.add_file("branches/abranch/bla").modify()
        sc.close()

        sc = self.get_commit_editor(repos_url)
        trunk = sc.open_dir("trunk")
        sc.add_dir("trunk/mylib", "branches/abranch")
        sc.close()

        self.client_update('sc')
        olddir = self.open_checkout_bzrdir("sc/trunk")

        os.mkdir("dc")
        
        newdir = olddir.sprout('dc')

        self.assertEqual(
                olddir.open_branch().last_revision(),
                newdir.open_branch().last_revision())



    def test_ghost_workingtree(self):
        # Looks like bazaar has trouble creating a working tree of a 
        # revision that has ghost parents
        repos_url = self.make_client('d', 'sc')

        sc = self.get_commit_editor(repos_url)
        foo = sc.add_dir("foo")
        foo.add_file("foo/bla").modify()
        sc.change_prop("bzr:ancestry:v3-none", "some-ghost\n")
        sc.close()

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
