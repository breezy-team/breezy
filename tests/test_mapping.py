# Copyright (C) 2007 Jelmer Vernooij <jelmer@samba.org>
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

from dulwich.objects import (
    Commit,
    )

from bzrlib.plugins.git import tests
from bzrlib.plugins.git.mapping import (
    BzrGitMappingv1,
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
        c._tree = "cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c._message = "Some message"
        c._committer = "Committer"
        c._commit_time = 4
        c._author = "Author"
        c.serialize()
        rev = BzrGitMappingv1().import_commit(c)
        self.assertEquals("Some message", rev.message)
        self.assertEquals("Committer", rev.committer)
        self.assertEquals("Author", rev.properties['author'])
        self.assertEquals(0, rev.timezone)
        self.assertEquals((), rev.parent_ids)
        self.assertEquals("git-v1:" + c.id, rev.revision_id)
