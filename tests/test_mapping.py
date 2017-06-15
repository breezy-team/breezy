# Copyright (C) 2007 Jelmer Vernooij <jelmer@samba.org>
# -*- encoding: utf-8 -*-
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

from ....bzr.inventory import (
    InventoryDirectory,
    InventoryFile,
    )
from ....revision import (
    Revision,
    )

from dulwich.objects import (
    Blob,
    Commit,
    Tree,
    parse_timezone,
    )

from .. import tests
from ..errors import UnknownCommitExtra
from ..mapping import (
    BzrGitMappingv1,
    directory_to_tree,
    escape_file_id,
    unescape_file_id,
    )


class TestRevidConversionV1(tests.TestCase):

    def test_simple_git_to_bzr_revision_id(self):
        self.assertEqual("git-v1:"
                         "c6a4d8f1fa4ac650748e647c4b1b368f589a7356",
                         BzrGitMappingv1().revision_id_foreign_to_bzr(
                            "c6a4d8f1fa4ac650748e647c4b1b368f589a7356"))

    def test_simple_bzr_to_git_revision_id(self):
        self.assertEqual(("c6a4d8f1fa4ac650748e647c4b1b368f589a7356", 
                         BzrGitMappingv1()),
                         BzrGitMappingv1().revision_id_bzr_to_foreign(
                            "git-v1:"
                            "c6a4d8f1fa4ac650748e647c4b1b368f589a7356"))

    def test_is_control_file(self):
        mapping = BzrGitMappingv1()
        if mapping.roundtripping:
            self.assertTrue(mapping.is_control_file(".bzrdummy"))
            self.assertTrue(mapping.is_control_file(".bzrfileids"))
        self.assertFalse(mapping.is_control_file(".bzrfoo"))

    def test_generate_file_id(self):
        mapping = BzrGitMappingv1()
        self.assertIsInstance(mapping.generate_file_id("la"), str)
        self.assertIsInstance(mapping.generate_file_id(u"é"), str)


class FileidTests(tests.TestCase):

    def test_escape_space(self):
        self.assertEquals("bla_s", escape_file_id("bla "))

    def test_escape_control_l(self):
        self.assertEquals("bla_c", escape_file_id("bla\x0c"))

    def test_unescape_control_l(self):
        self.assertEquals("bla\x0c", unescape_file_id("bla_c"))

    def test_escape_underscore(self):
        self.assertEquals("bla__", escape_file_id("bla_"))

    def test_escape_underscore_space(self):
        self.assertEquals("bla___s", escape_file_id("bla_ "))

    def test_unescape_underscore(self):
        self.assertEquals("bla ", unescape_file_id("bla_s"))

    def test_unescape_underscore_space(self):
        self.assertEquals("bla _", unescape_file_id("bla_s__"))


class TestImportCommit(tests.TestCase):

    def test_commit(self):
        c = Commit()
        c.tree = "cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = "Some message"
        c.committer = "Committer"
        c.commit_time = 4
        c.author_time = 5
        c.commit_timezone = 60 * 5
        c.author_timezone = 60 * 3
        c.author = "Author"
        mapping = BzrGitMappingv1()
        rev, roundtrip_revid, verifiers = mapping.import_commit(c,
            mapping.revision_id_foreign_to_bzr)
        self.assertEquals(None, roundtrip_revid)
        self.assertEquals({}, verifiers)
        self.assertEquals("Some message", rev.message)
        self.assertEquals("Committer", rev.committer)
        self.assertEquals("Author", rev.properties['author'])
        self.assertEquals(300, rev.timezone)
        self.assertEquals((), rev.parent_ids)
        self.assertEquals("5", rev.properties['author-timestamp'])
        self.assertEquals("180", rev.properties['author-timezone'])
        self.assertEquals("git-v1:" + c.id, rev.revision_id)

    def test_explicit_encoding(self):
        c = Commit()
        c.tree = "cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = "Some message"
        c.committer = "Committer"
        c.commit_time = 4
        c.author_time = 5
        c.commit_timezone = 60 * 5
        c.author_timezone = 60 * 3
        c.author = u"Authér".encode("iso8859-1")
        c.encoding = "iso8859-1"
        mapping = BzrGitMappingv1()
        rev, roundtrip_revid, verifiers = mapping.import_commit(c,
            mapping.revision_id_foreign_to_bzr)
        self.assertEquals(None, roundtrip_revid)
        self.assertEquals({}, verifiers)
        self.assertEquals(u"Authér", rev.properties['author'])
        self.assertEquals("iso8859-1", rev.properties["git-explicit-encoding"])
        self.assertTrue("git-implicit-encoding" not in rev.properties)

    def test_implicit_encoding_fallback(self):
        c = Commit()
        c.tree = "cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = "Some message"
        c.committer = "Committer"
        c.commit_time = 4
        c.author_time = 5
        c.commit_timezone = 60 * 5
        c.author_timezone = 60 * 3
        c.author = u"Authér".encode("latin1")
        mapping = BzrGitMappingv1()
        rev, roundtrip_revid, verifiers = mapping.import_commit(c,
            mapping.revision_id_foreign_to_bzr)
        self.assertEquals(None, roundtrip_revid)
        self.assertEquals({}, verifiers)
        self.assertEquals(u"Authér", rev.properties['author'])
        self.assertEquals("latin1", rev.properties["git-implicit-encoding"])
        self.assertTrue("git-explicit-encoding" not in rev.properties)

    def test_implicit_encoding_utf8(self):
        c = Commit()
        c.tree = "cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = "Some message"
        c.committer = "Committer"
        c.commit_time = 4
        c.author_time = 5
        c.commit_timezone = 60 * 5
        c.author_timezone = 60 * 3
        c.author = u"Authér".encode("utf-8")
        mapping = BzrGitMappingv1()
        rev, roundtrip_revid, verifiers = mapping.import_commit(c,
            mapping.revision_id_foreign_to_bzr)
        self.assertEquals(None, roundtrip_revid)
        self.assertEquals({}, verifiers)
        self.assertEquals(u"Authér", rev.properties['author'])
        self.assertTrue("git-explicit-encoding" not in rev.properties)
        self.assertTrue("git-implicit-encoding" not in rev.properties)

    def test_unknown_extra(self):
        c = Commit()
        c.tree = "cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = "Some message"
        c.committer = "Committer"
        c.commit_time = 4
        c.author_time = 5
        c.commit_timezone = 60 * 5
        c.author_timezone = 60 * 3
        c.author = "Author"
        c._extra.append(("iamextra", "foo"))
        mapping = BzrGitMappingv1()
        self.assertRaises(UnknownCommitExtra, mapping.import_commit, c,
            mapping.revision_id_foreign_to_bzr)


class RoundtripRevisionsFromBazaar(tests.TestCase):

    def setUp(self):
        super(RoundtripRevisionsFromBazaar, self).setUp()
        self.mapping = BzrGitMappingv1()
        self._parent_map = {}
        self._lookup_parent = self._parent_map.__getitem__

    def assertRoundtripRevision(self, orig_rev):
        commit = self.mapping.export_commit(orig_rev, "mysha",
            self._lookup_parent, True, "testamentsha")
        rev, roundtrip_revid, verifiers = self.mapping.import_commit(
            commit, self.mapping.revision_id_foreign_to_bzr)
        self.assertEquals(rev.revision_id,
            self.mapping.revision_id_foreign_to_bzr(commit.id))
        if self.mapping.roundtripping:
            self.assertEquals({"testament3-sha1": "testamentsha"} , verifiers)
            self.assertEquals(orig_rev.revision_id, roundtrip_revid)
            self.assertEquals(orig_rev.properties, rev.properties)
            self.assertEquals(orig_rev.committer, rev.committer)
            self.assertEquals(orig_rev.timestamp, rev.timestamp)
            self.assertEquals(orig_rev.timezone, rev.timezone)
            self.assertEquals(orig_rev.message, rev.message)
            self.assertEquals(list(orig_rev.parent_ids), list(rev.parent_ids))
        else:
            self.assertEquals({}, verifiers)

    def test_simple_commit(self):
        r = Revision(self.mapping.revision_id_foreign_to_bzr("edf99e6c56495c620f20d5dacff9859ff7119261"))
        r.message = "MyCommitMessage"
        r.parent_ids = []
        r.committer = "Jelmer Vernooij <jelmer@apache.org>"
        r.timestamp = 453543543
        r.timezone = 0
        r.properties = {}
        self.assertRoundtripRevision(r)

    def test_revision_id(self):
        r = Revision("myrevid")
        r.message = "MyCommitMessage"
        r.parent_ids = []
        r.committer = "Jelmer Vernooij <jelmer@apache.org>"
        r.timestamp = 453543543
        r.timezone = 0
        r.properties = {}
        self.assertRoundtripRevision(r)

    def test_ghost_parent(self):
        r = Revision("myrevid")
        r.message = "MyCommitMessage"
        r.parent_ids = ["iamaghost"]
        r.committer = "Jelmer Vernooij <jelmer@apache.org>"
        r.timestamp = 453543543
        r.timezone = 0
        r.properties = {}
        self.assertRoundtripRevision(r)

    def test_custom_property(self):
        r = Revision("myrevid")
        r.message = "MyCommitMessage"
        r.parent_ids = []
        r.properties = {"fool": "bar"}
        r.committer = "Jelmer Vernooij <jelmer@apache.org>"
        r.timestamp = 453543543
        r.timezone = 0
        self.assertRoundtripRevision(r)


class RoundtripRevisionsFromGit(tests.TestCase):

    def setUp(self):
        super(RoundtripRevisionsFromGit, self).setUp()
        self.mapping = BzrGitMappingv1()

    def assertRoundtripTree(self, tree):
        raise NotImplementedError(self.assertRoundtripTree)

    def assertRoundtripBlob(self, blob):
        raise NotImplementedError(self.assertRoundtripBlob)

    def assertRoundtripCommit(self, commit1):
        rev, roundtrip_revid, verifiers = self.mapping.import_commit(
            commit1, self.mapping.revision_id_foreign_to_bzr)
        commit2 = self.mapping.export_commit(rev, "12341212121212", None,
            True, None)
        self.assertEquals(commit1.committer, commit2.committer)
        self.assertEquals(commit1.commit_time, commit2.commit_time)
        self.assertEquals(commit1.commit_timezone, commit2.commit_timezone)
        self.assertEquals(commit1.author, commit2.author)
        self.assertEquals(commit1.author_time, commit2.author_time)
        self.assertEquals(commit1.author_timezone, commit2.author_timezone)
        self.assertEquals(commit1.message, commit2.message)
        self.assertEquals(commit1.encoding, commit2.encoding)

    def test_commit(self):
        c = Commit()
        c.tree = "cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = "Some message"
        c.committer = "Committer <Committer>"
        c.commit_time = 4
        c.commit_timezone = -60 * 3
        c.author_time = 5
        c.author_timezone = 60 * 2
        c.author = "Author <author>"
        self.assertRoundtripCommit(c)

    def test_commit_double_negative_timezone(self):
        c = Commit()
        c.tree = "cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = "Some message"
        c.committer = "Committer <Committer>"
        c.commit_time = 4
        (c.commit_timezone, c._commit_timezone_neg_utc) = parse_timezone("--700")
        c.author_time = 5
        c.author_timezone = 60 * 2
        c.author = "Author <author>"
        self.assertRoundtripCommit(c)

    def test_commit_zero_utc_timezone(self):
        c = Commit()
        c.tree = "cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = "Some message"
        c.committer = "Committer <Committer>"
        c.commit_time = 4
        c.commit_timezone = 0
        c._commit_timezone_neg_utc = True
        c.author_time = 5
        c.author_timezone = 60 * 2
        c.author = "Author <author>"
        self.assertRoundtripCommit(c)

    def test_commit_encoding(self):
        c = Commit()
        c.tree = "cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = "Some message"
        c.committer = "Committer <Committer>"
        c.encoding = 'iso8859-1'
        c.commit_time = 4
        c.commit_timezone = -60 * 3
        c.author_time = 5
        c.author_timezone = 60 * 2
        c.author = "Author <author>"
        self.assertRoundtripCommit(c)

    def test_commit_extra(self):
        c = Commit()
        c.tree = "cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = "Some message"
        c.committer = "Committer <Committer>"
        c.commit_time = 4
        c.commit_timezone = -60 * 3
        c.author_time = 5
        c.author_timezone = 60 * 2
        c.author = "Author <author>"
        c._extra = [("HG:rename-source", "hg")]
        self.assertRoundtripCommit(c)


class DirectoryToTreeTests(tests.TestCase):

    def test_empty(self):
        t = directory_to_tree({}, None, {}, None, allow_empty=False)
        self.assertEquals(None, t)

    def test_empty_dir(self):
        child_ie = InventoryDirectory('bar', 'bar', 'bar')
        children = {'bar': child_ie}
        t = directory_to_tree(children, lambda x: None, {}, None,
                allow_empty=False)
        self.assertEquals(None, t)

    def test_empty_dir_dummy_files(self):
        child_ie = InventoryDirectory('bar', 'bar', 'bar')
        children = {'bar':child_ie}
        t = directory_to_tree(children, lambda x: None, {}, ".mydummy",
                allow_empty=False)
        self.assertTrue(".mydummy" in t)

    def test_empty_root(self):
        child_ie = InventoryDirectory('bar', 'bar', 'bar')
        children = {'bar': child_ie}
        t = directory_to_tree(children, lambda x: None, {}, None,
                allow_empty=True)
        self.assertEquals(Tree(), t)

    def test_with_file(self):
        child_ie = InventoryFile('bar', 'bar', 'bar')
        children = {"bar": child_ie}
        b = Blob.from_string("bla")
        t1 = directory_to_tree(children, lambda x: b.id, {}, None,
                allow_empty=False)
        t2 = Tree()
        t2.add("bar", 0100644, b.id)
        self.assertEquals(t1, t2)
