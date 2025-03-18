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

from email.message import Message
from email.parser import Parser
from io import StringIO

from ....revision import (
    NULL_REVISION,
)
from ....tests import (
    TestCase,
)
from ..dep3 import (
    describe_origin,
    determine_applied_upstream,
    gather_bugs_and_authors,
    write_dep3_bug_line,
    write_dep3_patch,
    write_dep3_patch_header,
)
from . import (
    TestCaseWithTransport,
)


class Dep3HeaderTests(TestCase):
    def dep3_header(
        self,
        description=None,
        origin=None,
        forwarded=None,
        bugs=None,
        authors=None,
        revision_id=None,
        last_update=None,
        applied_upstream=None,
    ):
        f = StringIO()
        write_dep3_patch_header(
            f,
            description=description,
            origin=origin,
            forwarded=forwarded,
            bugs=bugs,
            authors=authors,
            revision_id=revision_id,
            last_update=last_update,
            applied_upstream=applied_upstream,
        )
        f.seek(0)
        return Parser().parse(f)

    def test_description(self):
        ret = self.dep3_header(description="This patch fixes the foobar")
        self.assertEqual("This patch fixes the foobar", ret["Description"])

    def test_last_updated(self):
        ret = self.dep3_header(last_update=1304840034)
        self.assertEqual("2011-05-08", ret["Last-Update"])

    def test_revision_id(self):
        ret = self.dep3_header(revision_id=b"myrevid")
        self.assertEqual("myrevid", ret["X-Bzr-Revision-Id"])

    def test_authors(self):
        authors = [
            "Jelmer Vernooij <jelmer@canonical.com>",
            "James Westby <james.westby@canonical.com>",
        ]
        ret = self.dep3_header(authors=authors)
        self.assertEqual(
            [
                "Jelmer Vernooij <jelmer@canonical.com>",
                "James Westby <james.westby@canonical.com>",
            ],
            ret.get_all("Author"),
        )

    def test_origin(self):
        ret = self.dep3_header(origin="Cherrypick from upstream")
        self.assertEqual("Cherrypick from upstream", ret["Origin"])

    def test_forwarded(self):
        ret = self.dep3_header(forwarded="not needed")
        self.assertEqual("not needed", ret["Forwarded"])

    def test_applied_upstream(self):
        ret = self.dep3_header(applied_upstream="commit 45")
        self.assertEqual("commit 45", ret["Applied-Upstream"])

    def test_bugs(self):
        bugs = [
            ("http://bugs.debian.org/424242", "fixed"),
            ("https://bugs.launchpad.net/bugs/20110508", "fixed"),
            ("http://bugzilla.samba.org/bug.cgi?id=52", "fixed"),
        ]
        ret = self.dep3_header(bugs=bugs)
        self.assertEqual(
            [
                "https://bugs.launchpad.net/bugs/20110508",
                "http://bugzilla.samba.org/bug.cgi?id=52",
            ],
            ret.get_all("Bug"),
        )
        self.assertEqual(["http://bugs.debian.org/424242"], ret.get_all("Bug-Debian"))

    def test_write_bug_fix_only(self):
        # non-fixed bug lines are ignored
        message = Message()
        write_dep3_bug_line(message, "http://bar/", "pending")
        self.assertEqual("\n", str(message))

    def test_write_normal_bug(self):
        message = Message()
        write_dep3_bug_line(message, "http://bugzilla.samba.org/bug.cgi?id=42", "fixed")
        self.assertEqual(
            "Bug: http://bugzilla.samba.org/bug.cgi?id=42\n\n", str(message)
        )

    def test_write_debian_bug(self):
        message = Message()
        write_dep3_bug_line(message, "http://bugs.debian.org/234354", "fixed")
        self.assertEqual("Bug-Debian: http://bugs.debian.org/234354\n\n", str(message))


class GatherBugsAndAuthors(TestCaseWithTransport):
    def test_none(self):
        branch = self.make_branch(".")
        self.assertEqual(
            (set(), set(), None), gather_bugs_and_authors(branch.repository, [])
        )

    def test_multiple_authors(self):
        tree = self.make_branch_and_tree(".")
        revid1 = tree.commit(
            authors=["Jelmer Vernooij <jelmer@canonical.com>"],
            timestamp=1304844311,
            message="msg",
        )
        revid2 = tree.commit(
            authors=["Max Bowsher <maxb@f2s.com>"], timestamp=1304844278, message="msg"
        )
        self.assertEqual(
            (
                set(),
                {
                    "Jelmer Vernooij <jelmer@canonical.com>",
                    "Max Bowsher <maxb@f2s.com>",
                },
                1304844311,
            ),
            gather_bugs_and_authors(tree.branch.repository, [revid1, revid2]),
        )

    def test_bugs(self):
        tree = self.make_branch_and_tree(".")
        revid1 = tree.commit(
            authors=["Jelmer Vernooij <jelmer@canonical.com>"],
            timestamp=1304844311,
            message="msg",
            revprops={"bugs": "http://bugs.samba.org/bug.cgi?id=2011 fixed\n"},
        )
        self.assertEqual(
            (
                {("http://bugs.samba.org/bug.cgi?id=2011", "fixed")},
                {"Jelmer Vernooij <jelmer@canonical.com>"},
                1304844311,
            ),
            gather_bugs_and_authors(tree.branch.repository, [revid1]),
        )


class DetermineAppliedUpstreamTests(TestCaseWithTransport):
    def test_not_applied(self):
        upstream = self.make_branch_and_tree("upstream")
        feature = self.make_branch_and_tree("feature")
        feature.commit(message="every bloody emperor")
        self.addCleanup(feature.lock_read().unlock)
        self.assertEqual(
            "no", determine_applied_upstream(upstream.branch, feature.branch)
        )

    def test_merged(self):
        upstream = self.make_branch_and_tree("upstream")
        upstream.commit(message="initial upstream commit")
        feature = upstream.controldir.sprout("feature").open_workingtree()
        feature.commit(message="nutter alert")
        upstream.merge_from_branch(feature.branch)
        upstream.commit(message="merge feature")
        self.addCleanup(upstream.lock_read().unlock)
        self.addCleanup(feature.lock_read().unlock)
        self.assertEqual(
            "merged in revision 2",
            determine_applied_upstream(upstream.branch, feature.branch),
        )


class DescribeOriginTests(TestCaseWithTransport):
    def test_no_public_branch(self):
        tree = self.make_branch_and_tree(".")
        revid1 = tree.commit(message="msg1")
        self.assertEqual(
            "commit, revision id: {}".format(revid1.decode("utf-8")),
            describe_origin(tree.branch, revid1),
        )

    def test_public_branch(self):
        tree = self.make_branch_and_tree(".")
        tree.branch.set_public_branch("http://example.com/public")
        revid1 = tree.commit(message="msg1")
        self.assertEqual(
            "commit, http://example.com/public, revision: 1",
            describe_origin(tree.branch, revid1),
        )


class FullDep3PatchTests(TestCaseWithTransport):
    def test_simple(self):
        f = StringIO()
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents([("foo", "data")])
        tree.add("foo")
        revid = tree.commit("msg", rev_id=b"arevid", timestamp=1304849661, timezone=0)
        write_dep3_patch(
            f,
            tree.branch,
            NULL_REVISION,
            revid,
            description="Nutter alert",
            forwarded="not needed",
            authors={"Jelmer <jelmer@samba.org>"},
        )
        self.assertEqual(
            "Description: Nutter alert\n"
            "Forwarded: not needed\n"
            "Author: Jelmer <jelmer@samba.org>\n"
            "X-Bzr-Revision-Id: arevid\n"
            "\n"
            "=== added file 'foo'\n"
            "--- old/foo\t1970-01-01 00:00:00 +0000\n"
            "+++ new/foo\t2011-05-08 10:14:21 +0000\n"
            "@@ -0,0 +1,1 @@\n"
            "+data\n"
            "\\ No newline at end of file\n"
            "\n",
            f.getvalue(),
        )
