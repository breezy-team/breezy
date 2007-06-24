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

"""Full repository conversion tests."""

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir, format_registry
from bzrlib.errors import NotBranchError, NoSuchFile, IncompatibleRepositories
from bzrlib.repository import Repository
from bzrlib.tests import TestCaseInTempDir
from bzrlib.trace import mutter

import os
from convert import convert_repository, NotDumpFile, load_dumpfile
from format import get_rich_root_format
from repository import generate_svn_revision_id
from scheme import TrunkBranchingScheme, NoBranchingScheme
from tests import TestCaseWithSubversionRepository

import svn.repos

class TestLoadDumpfile(TestCaseInTempDir):
    def test_loaddumpfile(self):
        dumpfile = os.path.join(self.test_dir, "dumpfile")
        open(dumpfile, 'w').write(
"""SVN-fs-dump-format-version: 2

UUID: 6987ef2d-cd6b-461f-9991-6f1abef3bd59

Revision-number: 0
Prop-content-length: 56
Content-length: 56

K 8
svn:date
V 27
2006-07-02T13:14:51.972532Z
PROPS-END
""")
        load_dumpfile(dumpfile, "d")
        repos = svn.repos.open("d")
        fs = svn.repos.fs(repos)
        self.assertEqual("6987ef2d-cd6b-461f-9991-6f1abef3bd59", 
                svn.fs.get_uuid(fs))

    def test_loaddumpfile_invalid(self):
        dumpfile = os.path.join(self.test_dir, "dumpfile")
        open(dumpfile, 'w').write("""FooBar""")
        self.assertRaises(NotDumpFile, load_dumpfile, dumpfile, "d")


class TestConversion(TestCaseWithSubversionRepository):
    def setUp(self):
        super(TestConversion, self).setUp()
        self.repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/trunk/file': 'data', 'dc/branches/abranch/anotherfile': 'data2'})
        self.client_add("dc/trunk")
        self.client_add("dc/branches")
        self.client_commit("dc", "create repos")
        self.build_tree({'dc/trunk/file': 'otherdata'})
        self.client_commit("dc", "change")

    def test_sets_parent_urls(self):
        convert_repository(Repository.open(self.repos_url), "e", 
                           TrunkBranchingScheme(), 
                           all=False, create_shared_repo=True)
        self.assertEquals(self.repos_url+"/trunk", 
                Branch.open("e/trunk").get_parent())
        self.assertEquals(self.repos_url+"/branches/abranch", 
                Branch.open("e/branches/abranch").get_parent())

    def test_fetch_alive(self):
        self.build_tree({'dc/branches/somebranch/somefile': 'data'})
        self.client_add("dc/branches/somebranch")
        self.client_commit("dc", "add a branch")
        self.client_delete("dc/branches/somebranch")
        self.client_commit("dc", "remove branch")
        oldrepos = Repository.open(self.repos_url)
        convert_repository(oldrepos, "e", 
                           TrunkBranchingScheme(), 
                           all=False, create_shared_repo=True)
        newrepos = Repository.open("e")
        self.assertFalse(newrepos.has_revision(oldrepos.generate_revision_id(2, "branches/somebranch", "trunk0")))

    def test_fetch_filebranch(self):
        self.build_tree({'dc/branches/somebranch': 'data'})
        self.client_add("dc/branches/somebranch")
        self.client_commit("dc", "add a branch")
        oldrepos = Repository.open(self.repos_url)
        convert_repository(oldrepos, "e", TrunkBranchingScheme())
        newrepos = Repository.open("e")
        self.assertFalse(newrepos.has_revision(oldrepos.generate_revision_id(2, "branches/somebranch", "trunk0")))

    def test_fetch_dead(self):
        self.build_tree({'dc/branches/somebranch/somefile': 'data'})
        self.client_add("dc/branches/somebranch")
        self.client_commit("dc", "add a branch")
        self.client_delete("dc/branches/somebranch")
        self.client_commit("dc", "remove branch")
        oldrepos = Repository.open(self.repos_url)
        convert_repository(oldrepos, "e", TrunkBranchingScheme(), 
                           all=True, create_shared_repo=True)
        newrepos = Repository.open("e")
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(3, "branches/somebranch", "trunk0")))

    def test_shared_import_continue(self):
        BzrDir.create_repository("e", shared=True, 
                format=get_rich_root_format())

        convert_repository(Repository.open("svn+"+self.repos_url), "e", 
                TrunkBranchingScheme(), True)

        self.assertTrue(Repository.open("e").is_shared())

    def test_shared_import_continue_remove(self):
        convert_repository(Repository.open(self.repos_url), "e", 
                TrunkBranchingScheme(), True)
        self.client_update("dc")
        self.client_delete("dc/trunk")
        self.client_commit("dc", "blafoo")
        self.build_tree({'dc/trunk/file': 'otherdata'})
        self.client_add("dc/trunk")
        self.client_commit("dc", "change")
        convert_repository(Repository.open(self.repos_url), "e", 
                           TrunkBranchingScheme(), True)

    def test_shared_import_continue_with_wt(self):
        convert_repository(Repository.open("svn+"+self.repos_url), "e", 
                TrunkBranchingScheme(), working_trees=True)
        convert_repository(Repository.open("svn+"+self.repos_url), "e", 
                TrunkBranchingScheme(), working_trees=True)

    def test_shared_import_nonescheme_empty(self):
        BzrDir.create_repository("e", shared=True, format=get_rich_root_format())

        convert_repository(Repository.open("svn+"+self.repos_url), "e", 
                NoBranchingScheme(), True)

    def test_shared_import_with_wt(self):
        BzrDir.create_repository("e", shared=True, 
                format=get_rich_root_format())

        convert_repository(Repository.open("svn+"+self.repos_url), "e", 
                TrunkBranchingScheme(), True, True)

        self.assertTrue(os.path.isfile(os.path.join(
                        self.test_dir, "e", "trunk", "file")))

    def test_shared_import_without_wt(self):
        BzrDir.create_repository("e", shared=True, 
                format=get_rich_root_format())

        convert_repository(Repository.open("svn+"+self.repos_url), "e", 
                TrunkBranchingScheme(), True, False)

        self.assertFalse(os.path.isfile(os.path.join(
                        self.test_dir, "e", "trunk", "file")))

    def test_shared_import_old_repos_fails(self):
        BzrDir.create_repository("e", shared=True, 
                format=format_registry.make_bzrdir('knit'))

        self.assertRaises(IncompatibleRepositories, 
            lambda: convert_repository(Repository.open(self.repos_url), "e", 
                TrunkBranchingScheme(), True, False))

    def test_shared_import_continue_branch(self):
        convert_repository(Repository.open("svn+"+self.repos_url), "e", 
                TrunkBranchingScheme(), True)

        self.build_tree({'dc/trunk/file': 'foodata'})
        self.client_commit("dc", "msg")

        self.assertEqual(
                Repository.open(self.repos_url).generate_revision_id(2, "trunk", "trunk0"), 
                Branch.open("e/trunk").last_revision())

        convert_repository(Repository.open("svn+"+self.repos_url), "e", 
                TrunkBranchingScheme(), True)

        self.assertEqual(Repository.open(self.repos_url).generate_revision_id(3, "trunk", "trunk0"), 
                        Branch.open("e/trunk").last_revision())

 
    def test_shared_import(self):
        convert_repository(Repository.open("svn+"+self.repos_url), "e", 
                TrunkBranchingScheme(), True)

        self.assertTrue(Repository.open("e").is_shared())
    
    def test_simple(self):
        convert_repository(Repository.open("svn+"+self.repos_url), os.path.join(self.test_dir, "e"), TrunkBranchingScheme())
        self.assertTrue(os.path.isdir(os.path.join(self.test_dir, "e", "trunk")))
        self.assertTrue(os.path.isdir(os.path.join(self.test_dir, "e", "branches", "abranch")))

    def test_convert_to_nonexistant(self):
        self.assertRaises(NoSuchFile, convert_repository,Repository.open("svn+"+self.repos_url), os.path.join(self.test_dir, "e", "foo", "bar"), TrunkBranchingScheme())

    def test_notshared_import(self):
        convert_repository(Repository.open("svn+"+self.repos_url), "e", 
                           TrunkBranchingScheme(), False)

        self.assertRaises(NotBranchError, Repository.open, "e")

class TestConversionFromDumpfile(TestCaseWithSubversionRepository):
    def test_dumpfile_open_empty(self):
        dumpfile = os.path.join(self.test_dir, "dumpfile")
        open(dumpfile, 'w').write(
"""SVN-fs-dump-format-version: 2

UUID: 6987ef2d-cd6b-461f-9991-6f1abef3bd59

Revision-number: 0
Prop-content-length: 56
Content-length: 56

K 8
svn:date
V 27
2006-07-02T13:14:51.972532Z
PROPS-END
""")
        branch_path = os.path.join(self.test_dir, "f")
        repos = self.load_dumpfile(dumpfile, 'g')
        convert_repository(repos, branch_path, NoBranchingScheme())
        branch = Repository.open(branch_path)
        self.assertEqual(['svn-v3-none:6987ef2d-cd6b-461f-9991-6f1abef3bd59::0'], branch.all_revision_ids())
        Branch.open(branch_path)

    def load_dumpfile(self, dumpfile, target_path):
        load_dumpfile(dumpfile, target_path)
        return Repository.open(target_path)

    def test_dumpfile_open_empty_trunk(self):
        dumpfile = os.path.join(self.test_dir, "dumpfile")
        open(dumpfile, 'w').write(
"""SVN-fs-dump-format-version: 2

UUID: 6987ef2d-cd6b-461f-9991-6f1abef3bd59

Revision-number: 0
Prop-content-length: 56
Content-length: 56

K 8
svn:date
V 27
2006-07-02T13:14:51.972532Z
PROPS-END
""")
        branch_path = os.path.join(self.test_dir, "f")
        repos = self.load_dumpfile(dumpfile, 'g')
        convert_repository(repos, branch_path, TrunkBranchingScheme())
        repository = Repository.open(branch_path)
        self.assertEqual([], repository.all_revision_ids())
        self.assertRaises(NotBranchError, Branch.open, branch_path)

    def test_open_internal(self):
        filename = os.path.join(self.test_dir, "dumpfile")
        open(filename, 'w').write(
"""SVN-fs-dump-format-version: 2

UUID: 6987ef2d-cd6b-461f-9991-6f1abef3bd59

Revision-number: 0
Prop-content-length: 56
Content-length: 56

K 8
svn:date
V 27
2006-07-02T13:14:51.972532Z
PROPS-END

Revision-number: 1
Prop-content-length: 109
Content-length: 109

K 7
svn:log
V 9
Add trunk
K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-07-02T13:58:02.528258Z
PROPS-END

Node-path: trunk
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Node-path: trunk/bla
Node-kind: file
Node-action: add
Prop-content-length: 10
Text-content-length: 5
Text-content-md5: 6137cde4893c59f76f005a8123d8e8e6
Content-length: 15

PROPS-END
data


""")
        repos = self.load_dumpfile(filename, 'g')
        convert_repository(repos, os.path.join(self.test_dir, "e"), 
                           TrunkBranchingScheme())
        branch = Branch.open(os.path.join(self.test_dir, "e", "trunk"))
        self.assertEqual("file://%s/e/trunk" % self.test_dir, branch.base.rstrip("/"))
        self.assertEqual(generate_svn_revision_id("6987ef2d-cd6b-461f-9991-6f1abef3bd59", 1, 'trunk', "trunk0"), branch.last_revision())

