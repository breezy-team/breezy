# Copyright (C) 2005-2008, 2010 by Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
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

from unittest import TestLoader

from .... import config, tests
from ....bzr.bzrdir import BzrDir
from ....tests import TestCaseInTempDir
from ..emailer import EmailSender


def test_suite():
    return TestLoader().loadTestsFromName(__name__)


sample_config = (
    b"[DEFAULT]\n"
    b"post_commit_to=demo@example.com\n"
    b"post_commit_sender=Sample <foo@example.com>\n"
    b"revision_mail_headers=X-Cheese: to the rescue!\n"
)

unconfigured_config = b"[DEFAULT]\nemail=Robert <foo@example.com>\n"

sender_configured_config = b"[DEFAULT]\npost_commit_sender=Sample <foo@example.com>\n"

to_configured_config = b"[DEFAULT]\npost_commit_to=Sample <foo@example.com>\n"

multiple_to_configured_config = (
    b"[DEFAULT]\n"
    b"post_commit_sender=Sender <from@example.com>\n"
    b"post_commit_to=Sample <foo@example.com>, Other <baz@bar.com>\n"
)

customized_mail_config = (
    b"[DEFAULT]\n"
    b"post_commit_to=demo@example.com\n"
    b"post_commit_sender=Sample <foo@example.com>\n"
    b"post_commit_subject=[commit] $message\n"
    b"post_commit_body='''$committer has committed "
    b"revision 1 at $url.\n\n'''\n"
)

push_config = (
    b"[DEFAULT]\npost_commit_to=demo@example.com\npost_commit_push_pull=True\n"
)

with_url_config = (
    b"[DEFAULT]\n"
    b"post_commit_url=http://some.fake/url/\n"
    b"post_commit_to=demo@example.com\n"
    b"post_commit_sender=Sample <foo@example.com>\n"
)

# FIXME: this should not use a literal log, rather grab one from breezy.log
sample_log = (
    "------------------------------------------------------------\n"
    "revno: 1\n"
    "revision-id: %s\n"
    "committer: Sample <john@example.com>\n"
    "branch nick: work\n"
    "timestamp: Thu 1970-01-01 00:00:01 +0000\n"
    "message:\n"
    "  foo bar baz\n"
    "  fuzzy\n"
    "  wuzzy\n"
)


class TestGetTo(TestCaseInTempDir):
    def test_body(self):
        sender, revid = self.get_sender()
        self.assertEqual(
            "At {}\n\n{}".format(sender.url(), sample_log % revid.decode("utf-8")),
            sender.body(),
        )

    def test_custom_body(self):
        sender, revid = self.get_sender(customized_mail_config)
        self.assertEqual(
            "{} has committed revision 1 at {}.\n\n{}".format(
                sender.revision.committer,
                sender.url(),
                sample_log % revid.decode("utf-8"),
            ),
            sender.body(),
        )

    def test_command_line(self):
        sender, revid = self.get_sender()
        self.assertEqual(
            ["mail", "-s", sender.subject(), "-a", "From: " + sender.from_address()]
            + sender.to(),
            sender._command_line(),
        )

    def test_to(self):
        sender, revid = self.get_sender()
        self.assertEqual(["demo@example.com"], sender.to())

    def test_from(self):
        sender, revid = self.get_sender()
        self.assertEqual("Sample <foo@example.com>", sender.from_address())

    def test_from_default(self):
        sender, revid = self.get_sender(unconfigured_config)
        self.assertEqual("Robert <foo@example.com>", sender.from_address())

    def test_should_send(self):
        sender, revid = self.get_sender()
        self.assertEqual(True, sender.should_send())

    def test_should_not_send(self):
        sender, revid = self.get_sender(unconfigured_config)
        self.assertEqual(False, sender.should_send())

    def test_should_not_send_sender_configured(self):
        sender, revid = self.get_sender(sender_configured_config)
        self.assertEqual(False, sender.should_send())

    def test_should_not_send_to_configured(self):
        sender, revid = self.get_sender(to_configured_config)
        self.assertEqual(True, sender.should_send())

    def test_send_to_multiple(self):
        sender, revid = self.get_sender(multiple_to_configured_config)
        self.assertEqual(
            ["Sample <foo@example.com>", "Other <baz@bar.com>"], sender.to()
        )
        self.assertEqual(
            ["Sample <foo@example.com>", "Other <baz@bar.com>"],
            sender._command_line()[-2:],
        )

    def test_url_set(self):
        sender, revid = self.get_sender(with_url_config)
        self.assertEqual(sender.url(), "http://some.fake/url/")

    def test_public_url_set(self):
        config = b"[DEFAULT]\npublic_branch=http://the.publication/location/\n"
        sender, revid = self.get_sender(config)
        self.assertEqual(sender.url(), "http://the.publication/location/")

    def test_url_precedence(self):
        config = (
            b"[DEFAULT]\n"
            b"post_commit_url=http://some.fake/url/\n"
            b"public_branch=http://the.publication/location/\n"
        )
        sender, revid = self.get_sender(config)
        self.assertEqual(sender.url(), "http://some.fake/url/")

    def test_url_unset(self):
        sender, revid = self.get_sender()
        self.assertEqual(sender.url(), sender.branch.base)

    def test_subject(self):
        sender, revid = self.get_sender()
        self.assertEqual(
            "Rev 1: foo bar baz in {}".format(sender.branch.base), sender.subject()
        )

    def test_custom_subject(self):
        sender, revid = self.get_sender(customized_mail_config)
        self.assertEqual(
            "[commit] {}".format(sender.revision.get_summary()), sender.subject()
        )

    def test_diff_filename(self):
        sender, revid = self.get_sender()
        self.assertEqual("patch-1.diff", sender.diff_filename())

    def test_headers(self):
        sender, revid = self.get_sender()
        self.assertEqual({"X-Cheese": "to the rescue!"}, sender.extra_headers())

    def get_sender(self, text=sample_config):
        my_config = config.MemoryStack(text)
        self.branch = BzrDir.create_branch_convenience(".")
        tree = self.branch.controldir.open_workingtree()
        revid = tree.commit(
            "foo bar baz\nfuzzy\nwuzzy",
            allow_pointless=True,
            timestamp=1,
            timezone=0,
            committer="Sample <john@example.com>",
        )
        sender = EmailSender(self.branch, revid, my_config)
        # This is usually only done after the EmailSender has locked the branch
        # and repository during send(), however, for testing, we need to do it
        # earlier, since send() is not called.
        sender._setup_revision_and_revno()
        return sender, revid


class TestEmailerWithLocal(tests.TestCaseWithTransport):
    """Test that Emailer will use a local branch if supplied."""

    def test_local_has_revision(self):
        master_tree = self.make_branch_and_tree("master")
        self.build_tree(["master/a"])
        master_tree.add("a")
        master_tree.commit("a")

        child_tree = master_tree.controldir.sprout("child").open_workingtree()
        child_tree.branch.bind(master_tree.branch)

        self.build_tree(["child/b"])
        child_tree.add(["b"])
        revision_id = child_tree.commit("b")

        sender = EmailSender(
            master_tree.branch,
            revision_id,
            master_tree.branch.get_config(),
            local_branch=child_tree.branch,
        )

        # Make sure we are using the 'local_branch' repository, and not the
        # remote one.
        self.assertIs(child_tree.branch.repository, sender.repository)

    def test_local_missing_revision(self):
        master_tree = self.make_branch_and_tree("master")
        self.build_tree(["master/a"])
        master_tree.add("a")
        master_tree.commit("a")

        child_tree = master_tree.controldir.sprout("child").open_workingtree()
        child_tree.branch.bind(master_tree.branch)

        self.build_tree(["master/c"])
        master_tree.add(["c"])
        revision_id = master_tree.commit("c")

        self.assertFalse(child_tree.branch.repository.has_revision(revision_id))
        sender = EmailSender(
            master_tree.branch,
            revision_id,
            master_tree.branch.get_config(),
            local_branch=child_tree.branch,
        )
        # We should be using the master repository here, because the child
        # repository doesn't contain the revision.
        self.assertIs(master_tree.branch.repository, sender.repository)
