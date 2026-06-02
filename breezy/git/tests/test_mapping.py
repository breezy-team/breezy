# Copyright (C) 2007-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Tests for mapping."""

from dulwich.objects import Blob, Commit, Tag, parse_timezone
from dulwich.tests.utils import make_object

from ...revision import Revision
from .. import tests
from ..mapping import (
    BzrGitMappingv1,
    UnknownCommitEncoding,
    UnknownCommitExtra,
    UnknownMercurialCommitExtra,
    escape_file_id,
    fix_person_identifier,
    unescape_file_id,
)


class TestRevidConversionV1(tests.TestCase):
    def test_simple_git_to_bzr_revision_id(self):
        self.assertEqual(
            b"git-v1:c6a4d8f1fa4ac650748e647c4b1b368f589a7356",
            BzrGitMappingv1().revision_id_foreign_to_bzr(
                b"c6a4d8f1fa4ac650748e647c4b1b368f589a7356"
            ),
        )

    def test_simple_bzr_to_git_revision_id(self):
        self.assertEqual(
            (b"c6a4d8f1fa4ac650748e647c4b1b368f589a7356", BzrGitMappingv1()),
            BzrGitMappingv1().revision_id_bzr_to_foreign(
                b"git-v1:c6a4d8f1fa4ac650748e647c4b1b368f589a7356"
            ),
        )

    def test_is_control_file(self):
        mapping = BzrGitMappingv1()
        if mapping.roundtripping:
            self.assertTrue(mapping.is_special_file(".bzrdummy"))
            self.assertTrue(mapping.is_special_file(".bzrfileids"))
        self.assertFalse(mapping.is_special_file(".bzrfoo"))

    def test_generate_file_id(self):
        mapping = BzrGitMappingv1()
        self.assertIsInstance(mapping.generate_file_id("la"), bytes)
        self.assertIsInstance(mapping.generate_file_id("é"), bytes)


class FileidTests(tests.TestCase):
    def test_escape_space(self):
        self.assertEqual(b"bla_s", escape_file_id(b"bla "))

    def test_escape_control_l(self):
        self.assertEqual(b"bla_c", escape_file_id(b"bla\x0c"))

    def test_unescape_control_l(self):
        self.assertEqual(b"bla\x0c", unescape_file_id(b"bla_c"))

    def test_escape_underscore(self):
        self.assertEqual(b"bla__", escape_file_id(b"bla_"))

    def test_escape_underscore_space(self):
        self.assertEqual(b"bla___s", escape_file_id(b"bla_ "))

    def test_unescape_underscore(self):
        self.assertEqual(b"bla ", unescape_file_id(b"bla_s"))

    def test_unescape_underscore_space(self):
        self.assertEqual(b"bla _", unescape_file_id(b"bla_s__"))


class TestImportCommit(tests.TestCase):
    def test_commit(self):
        c = Commit()
        c.tree = b"cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = b"Some message"
        c.committer = b"Committer"
        c.commit_time = 4
        c.author_time = 5
        c.commit_timezone = 60 * 5
        c.author_timezone = 60 * 3
        c.author = b"Author"
        mapping = BzrGitMappingv1()
        rev, roundtrip_revid, verifiers = mapping.import_commit(
            c, mapping.revision_id_foreign_to_bzr
        )
        self.assertEqual(None, roundtrip_revid)
        self.assertEqual({}, verifiers)
        self.assertEqual("Some message", rev.message)
        self.assertEqual("Committer", rev.committer)
        self.assertEqual("Author", rev.properties["author"])
        self.assertEqual(300, rev.timezone)
        self.assertEqual([], rev.parent_ids)
        self.assertEqual("5", rev.properties["author-timestamp"])
        self.assertEqual("180", rev.properties["author-timezone"])
        self.assertEqual(b"git-v1:" + c.id, rev.revision_id)

    def test_missing_message(self):
        c = Commit()
        c.tree = b"cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = None
        c.committer = b"Committer"
        c.commit_time = 4
        c.author_time = 5
        c.commit_timezone = 60 * 5
        c.author_timezone = 60 * 3
        c.author = b"Author"
        try:
            c.id  # noqa: B018
        except TypeError:  # old version of dulwich
            self.skipTest("dulwich too old")
        mapping = BzrGitMappingv1()
        rev, _roundtrip_revid, _verifiers = mapping.import_commit(
            c, mapping.revision_id_foreign_to_bzr
        )
        self.assertEqual(rev.message, "")

    def test_unknown_encoding(self):
        c = Commit()
        c.tree = b"cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = b"Some message"
        c.committer = b"Committer"
        c.commit_time = 4
        c.author_time = 5
        c.commit_timezone = 60 * 5
        c.author_timezone = 60 * 3
        c.author = "Authér".encode("iso8859-1")
        c.encoding = b"Unknown"
        mapping = BzrGitMappingv1()
        e = self.assertRaises(
            UnknownCommitEncoding,
            mapping.import_commit,
            c,
            mapping.revision_id_foreign_to_bzr,
        )
        self.assertEqual(e.encoding, "Unknown")

    def test_explicit_encoding(self):
        c = Commit()
        c.tree = b"cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = b"Some message"
        c.committer = b"Committer"
        c.commit_time = 4
        c.author_time = 5
        c.commit_timezone = 60 * 5
        c.author_timezone = 60 * 3
        c.author = "Authér".encode("iso8859-1")
        c.encoding = b"iso8859-1"
        mapping = BzrGitMappingv1()
        rev, roundtrip_revid, verifiers = mapping.import_commit(
            c, mapping.revision_id_foreign_to_bzr
        )
        self.assertEqual(None, roundtrip_revid)
        self.assertEqual({}, verifiers)
        self.assertEqual("Authér", rev.properties["author"])
        self.assertEqual("iso8859-1", rev.properties["git-explicit-encoding"])
        self.assertNotIn("git-implicit-encoding", rev.properties)

    def test_explicit_encoding_false(self):
        c = Commit()
        c.tree = b"cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = b"Some message"
        c.committer = b"Committer"
        c.commit_time = 4
        c.author_time = 5
        c.commit_timezone = 60 * 5
        c.author_timezone = 60 * 3
        c.author = "Authér".encode()
        c.encoding = b"false"
        mapping = BzrGitMappingv1()
        rev, roundtrip_revid, verifiers = mapping.import_commit(
            c, mapping.revision_id_foreign_to_bzr
        )
        self.assertEqual(None, roundtrip_revid)
        self.assertEqual({}, verifiers)
        self.assertEqual("Authér", rev.properties["author"])
        self.assertEqual("false", rev.properties["git-explicit-encoding"])
        self.assertNotIn("git-implicit-encoding", rev.properties)

    def test_implicit_encoding_fallback(self):
        c = Commit()
        c.tree = b"cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = b"Some message"
        c.committer = b"Committer"
        c.commit_time = 4
        c.author_time = 5
        c.commit_timezone = 60 * 5
        c.author_timezone = 60 * 3
        c.author = "Authér".encode("latin1")
        mapping = BzrGitMappingv1()
        rev, roundtrip_revid, verifiers = mapping.import_commit(
            c, mapping.revision_id_foreign_to_bzr
        )
        self.assertEqual(None, roundtrip_revid)
        self.assertEqual({}, verifiers)
        self.assertEqual("Authér", rev.properties["author"])
        self.assertEqual("latin1", rev.properties["git-implicit-encoding"])
        self.assertNotIn("git-explicit-encoding", rev.properties)

    def test_implicit_encoding_utf8(self):
        c = Commit()
        c.tree = b"cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = b"Some message"
        c.committer = b"Committer"
        c.commit_time = 4
        c.author_time = 5
        c.commit_timezone = 60 * 5
        c.author_timezone = 60 * 3
        c.author = "Authér".encode()
        mapping = BzrGitMappingv1()
        rev, roundtrip_revid, verifiers = mapping.import_commit(
            c, mapping.revision_id_foreign_to_bzr
        )
        self.assertEqual(None, roundtrip_revid)
        self.assertEqual({}, verifiers)
        self.assertEqual("Authér", rev.properties["author"])
        self.assertNotIn("git-explicit-encoding", rev.properties)
        self.assertNotIn("git-implicit-encoding", rev.properties)

    def test_unknown_extra(self):
        c = Commit()
        c.tree = b"cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = b"Some message"
        c.committer = b"Committer"
        c.commit_time = 4
        c.author_time = 5
        c.commit_timezone = 60 * 5
        c.author_timezone = 60 * 3
        c.author = b"Author"
        c._extra.append((b"iamextra", b"foo"))
        mapping = BzrGitMappingv1()
        self.assertRaises(
            UnknownCommitExtra,
            mapping.import_commit,
            c,
            mapping.revision_id_foreign_to_bzr,
        )
        mapping.import_commit(c, mapping.revision_id_foreign_to_bzr, strict=False)

    def test_mergetag(self):
        c = Commit()
        c.tree = b"cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = b"Some message"
        c.committer = b"Committer"
        c.commit_time = 4
        c.author_time = 5
        c.commit_timezone = 60 * 5
        c.author_timezone = 60 * 3
        c.author = b"Author"
        tag = make_object(
            Tag,
            tagger=b"Jelmer Vernooij <jelmer@samba.org>",
            name=b"0.1",
            message=None,
            object=(Blob, b"d80c186a03f423a81b39df39dc87fd269736ca86"),
            tag_time=423423423,
            tag_timezone=0,
        )
        c.mergetag = [tag]
        mapping = BzrGitMappingv1()
        rev, _roundtrip_revid, _verifiers = mapping.import_commit(
            c, mapping.revision_id_foreign_to_bzr
        )
        self.assertEqual(
            rev.properties["git-mergetag-0"].encode("utf-8"), tag.as_raw_string()
        )

    def test_unknown_hg_fields(self):
        c = Commit()
        c.tree = b"cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = b"Some message"
        c.committer = b"Committer"
        c.commit_time = 4
        c.author_time = 5
        c.commit_timezone = 60 * 5
        c.author_timezone = 60 * 3
        c.author = b"Author"
        c._extra = [(b"HG:extra", b"bla:Foo")]
        mapping = BzrGitMappingv1()
        self.assertRaises(
            UnknownMercurialCommitExtra,
            mapping.import_commit,
            c,
            mapping.revision_id_foreign_to_bzr,
        )
        mapping.import_commit(c, mapping.revision_id_foreign_to_bzr, strict=False)
        self.assertEqual(
            mapping.revision_id_foreign_to_bzr(c.id), mapping.get_revision_id(c)
        )

    def test_invalid_utf8(self):
        c = Commit()
        c.tree = b"cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = b"Some message \xc1"
        c.committer = b"Committer"
        c.commit_time = 4
        c.author_time = 5
        c.commit_timezone = 60 * 5
        c.author_timezone = 60 * 3
        c.author = b"Author"
        mapping = BzrGitMappingv1()
        self.assertEqual(
            mapping.revision_id_foreign_to_bzr(c.id), mapping.get_revision_id(c)
        )


class RoundtripRevisionsFromBazaar(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.mapping = BzrGitMappingv1()
        self._parent_map = {}
        self._lookup_parent = self._parent_map.__getitem__

    def assertRoundtripRevision(self, orig_rev):
        commit = self.mapping.export_commit(
            orig_rev, b"mysha", self._lookup_parent, True, b"testamentsha"
        )
        rev, roundtrip_revid, verifiers = self.mapping.import_commit(
            commit, self.mapping.revision_id_foreign_to_bzr, strict=True
        )
        self.assertEqual(
            rev.revision_id, self.mapping.revision_id_foreign_to_bzr(commit.id)
        )
        if self.mapping.roundtripping:
            self.assertEqual({"testament3-sha1": b"testamentsha"}, verifiers)
            self.assertEqual(orig_rev.revision_id, roundtrip_revid)
            self.assertEqual(orig_rev.properties, rev.properties)
            self.assertEqual(orig_rev.committer, rev.committer)
            self.assertEqual(orig_rev.timestamp, rev.timestamp)
            self.assertEqual(orig_rev.timezone, rev.timezone)
            self.assertEqual(orig_rev.message, rev.message)
            self.assertEqual(list(orig_rev.parent_ids), list(rev.parent_ids))
        else:
            self.assertEqual({}, verifiers)
        return commit

    def test_simple_commit(self):
        r = Revision(
            self.mapping.revision_id_foreign_to_bzr(
                b"edf99e6c56495c620f20d5dacff9859ff7119261"
            ),
            message="MyCommitMessage",
            parent_ids=[],
            committer="Jelmer Vernooij <jelmer@apache.org>",
            timestamp=453543543,
            timezone=0,
            properties={},
            inventory_sha1=None,
        )
        self.assertRoundtripRevision(r)

    def test_revision_id(self):
        r = Revision(
            b"myrevid",
            message="MyCommitMessage",
            parent_ids=[],
            committer="Jelmer Vernooij <jelmer@apache.org>",
            timestamp=453543543,
            timezone=0,
            properties={},
            inventory_sha1=None,
        )
        self.assertRoundtripRevision(r)

    def test_ghost_parent(self):
        r = Revision(
            b"myrevid",
            message="MyCommitMessage",
            parent_ids=[b"iamaghost"],
            committer="Jelmer Vernooij <jelmer@apache.org>",
            timestamp=453543543,
            timezone=0,
            properties={},
            inventory_sha1=None,
        )
        self.assertRoundtripRevision(r)

    def test_custom_property(self):
        r = Revision(
            b"myrevid",
            message="MyCommitMessage",
            parent_ids=[],
            properties={"fool": "bar"},
            committer="Jelmer Vernooij <jelmer@apache.org>",
            timestamp=453543543,
            timezone=0,
            inventory_sha1=None,
        )
        self.assertRoundtripRevision(r)

    def test_multiple_authors(self):
        r = Revision(
            b"myrevid",
            message="MyCommitMessage",
            parent_ids=[],
            properties={
                "authors": "Jelmer Vernooij <jelmer@jelmer.uk>\n"
                "Alex <alexa@example.com>"
            },
            committer="Jelmer Vernooij <jelmer@apache.org>",
            timestamp=453543543,
            timezone=0,
            inventory_sha1=None,
        )
        c = self.assertRoundtripRevision(r)
        self.assertEqual(c.author, b"Jelmer Vernooij <jelmer@jelmer.uk>")

    def test_multiple_authors_comma(self):
        r = Revision(
            b"myrevid",
            message="MyCommitMessage",
            parent_ids=[],
            properties={
                "authors": "Jelmer Vernooij <jelmer@jelmer.uk>, "
                "Alex <alexa@example.com>"
            },
            committer="Jelmer Vernooij <jelmer@apache.org>",
            timestamp=453543543,
            timezone=0,
            inventory_sha1=None,
        )
        c = self.assertRoundtripRevision(r)
        self.assertEqual(c.author, b"Jelmer Vernooij <jelmer@jelmer.uk>")


class RoundtripRevisionsFromGit(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.mapping = BzrGitMappingv1()

    def assertRoundtripTree(self, tree):
        raise NotImplementedError(self.assertRoundtripTree)

    def assertRoundtripBlob(self, blob):
        raise NotImplementedError(self.assertRoundtripBlob)

    def assertRoundtripCommit(self, commit1):
        rev, _roundtrip_revid, _verifiers = self.mapping.import_commit(
            commit1, self.mapping.revision_id_foreign_to_bzr, strict=True
        )
        commit2 = self.mapping.export_commit(rev, "12341212121212", None, True, None)
        self.assertEqual(commit1.committer, commit2.committer)
        self.assertEqual(commit1.commit_time, commit2.commit_time)
        self.assertEqual(commit1.commit_timezone, commit2.commit_timezone)
        self.assertEqual(commit1.author, commit2.author)
        self.assertEqual(commit1.author_time, commit2.author_time)
        self.assertEqual(commit1.author_timezone, commit2.author_timezone)
        self.assertEqual(commit1.message, commit2.message)
        self.assertEqual(commit1.encoding, commit2.encoding)

    def test_commit(self):
        c = Commit()
        c.tree = b"cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = b"Some message"
        c.committer = b"Committer <Committer>"
        c.commit_time = 4
        c.commit_timezone = -60 * 3
        c.author_time = 5
        c.author_timezone = 60 * 2
        c.author = b"Author <author>"
        self.assertRoundtripCommit(c)

    def test_commit_double_negative_timezone(self):
        c = Commit()
        c.tree = b"cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = b"Some message"
        c.committer = b"Committer <Committer>"
        c.commit_time = 4
        (c.commit_timezone, c._commit_timezone_neg_utc) = parse_timezone(b"--700")
        c.author_time = 5
        c.author_timezone = 60 * 2
        c.author = b"Author <author>"
        self.assertRoundtripCommit(c)

    def test_commit_zero_utc_timezone(self):
        c = Commit()
        c.tree = b"cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = b"Some message"
        c.committer = b"Committer <Committer>"
        c.commit_time = 4
        c.commit_timezone = 0
        c._commit_timezone_neg_utc = True
        c.author_time = 5
        c.author_timezone = 60 * 2
        c.author = b"Author <author>"
        self.assertRoundtripCommit(c)

    def test_commit_encoding(self):
        c = Commit()
        c.tree = b"cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = b"Some message"
        c.committer = b"Committer <Committer>"
        c.encoding = b"iso8859-1"
        c.commit_time = 4
        c.commit_timezone = -60 * 3
        c.author_time = 5
        c.author_timezone = 60 * 2
        c.author = b"Author <author>"
        self.assertRoundtripCommit(c)

    def test_commit_extra(self):
        c = Commit()
        c.tree = b"cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = b"Some message"
        c.committer = b"Committer <Committer>"
        c.commit_time = 4
        c.commit_timezone = -60 * 3
        c.author_time = 5
        c.author_timezone = 60 * 2
        c.author = b"Author <author>"
        c._extra = [(b"HG:rename-source", b"hg")]
        self.assertRoundtripCommit(c)

    def test_commit_mergetag(self):
        c = Commit()
        c.tree = b"cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        c.message = b"Some message"
        c.committer = b"Committer <Committer>"
        c.commit_time = 4
        c.commit_timezone = -60 * 3
        c.author_time = 5
        c.author_timezone = 60 * 2
        c.author = b"Author <author>"
        tag = make_object(
            Tag,
            tagger=b"Jelmer Vernooij <jelmer@samba.org>",
            name=b"0.1",
            message=None,
            object=(Blob, b"d80c186a03f423a81b39df39dc87fd269736ca86"),
            tag_time=423423423,
            tag_timezone=0,
        )
        c.mergetag = [tag]
        self.assertRoundtripCommit(c)


class FixPersonIdentifierTests(tests.TestCase):
    def test_valid(self):
        self.assertEqual(
            b"foo <bar@blah.nl>", fix_person_identifier(b"foo <bar@blah.nl>")
        )
        self.assertEqual(
            b"bar@blah.nl <bar@blah.nl>", fix_person_identifier(b"bar@blah.nl")
        )

    def test_fix(self):
        self.assertEqual(
            b"person <bar@blah.nl>",
            fix_person_identifier(b"somebody <person <bar@blah.nl>>"),
        )
        self.assertEqual(
            b"person <bar@blah.nl>", fix_person_identifier(b"person<bar@blah.nl>")
        )
        self.assertEqual(
            b"Rohan Garg <rohangarg@kubuntu.org>",
            fix_person_identifier(b"Rohan Garg <rohangarg@kubuntu.org"),
        )
        self.assertRaises(ValueError, fix_person_identifier, b"person >bar@blah.nl<")
