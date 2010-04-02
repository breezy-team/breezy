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

from bzrlib.inventory import (
    InventoryDirectory,
    InventoryFile,
    )

from dulwich.objects import (
    Blob,
    Commit,
    Tree,
    )

from bzrlib.plugins.git import tests
from bzrlib.plugins.git.mapping import (
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


class FileidTests(tests.TestCase):

    def test_escape_space(self):
        self.assertEquals("bla_s", escape_file_id("bla "))

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
        rev = BzrGitMappingv1().import_commit(c)
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
        rev = BzrGitMappingv1().import_commit(c)
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
        rev = BzrGitMappingv1().import_commit(c)
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
        rev = BzrGitMappingv1().import_commit(c)
        self.assertEquals(u"Authér", rev.properties['author'])
        self.assertTrue("git-explicit-encoding" not in rev.properties)
        self.assertTrue("git-implicit-encoding" not in rev.properties)


class RoundtripRevisionsFromGit(tests.TestCase):

    def setUp(self):
        super(RoundtripRevisionsFromGit, self).setUp()
        self.mapping = BzrGitMappingv1()

    def assertRoundtripTree(self, tree):
        raise NotImplementedError(self.assertRoundtripTree)

    def assertRoundtripBlob(self, blob):
        raise NotImplementedError(self.assertRoundtripBlob)

    def assertRoundtripCommit(self, commit1):
        rev = self.mapping.import_commit(commit1)
        commit2 = self.mapping.export_commit(rev, "12341212121212", None)
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


class DirectoryToTreeTests(tests.TestCase):

    def test_empty(self):
        ie = InventoryDirectory('foo', 'foo', 'foo')
        t = directory_to_tree(ie, None, {})
        self.assertEquals(None, t)

    def test_empty_dir(self):
        ie = InventoryDirectory('foo', 'foo', 'foo')
        child_ie = InventoryDirectory('bar', 'bar', 'bar')
        ie.children['bar'] = child_ie
        t = directory_to_tree(ie, lambda x: None, {})
        self.assertEquals(None, t)

    def test_empty_root(self):
        ie = InventoryDirectory('foo', 'foo', None)
        child_ie = InventoryDirectory('bar', 'bar', 'bar')
        ie.children['bar'] = child_ie
        t = directory_to_tree(ie, lambda x: None, {})
        self.assertEquals(Tree(), t)

    def test_with_file(self):
        ie = InventoryDirectory('foo', 'foo', 'foo')
        child_ie = InventoryFile('bar', 'bar', 'bar')
        ie.children['bar'] = child_ie
        b = Blob.from_string("bla")
        t1 = directory_to_tree(ie, lambda x: b.id, {})
        t2 = Tree()
        t2.add(0100644, "bar", b.id)
        self.assertEquals(t1, t2)
