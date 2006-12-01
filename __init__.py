# Copyright (C) 2005 by Canonical Ltd
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

from StringIO import StringIO
import subprocess

import bzrlib.config as config
import bzrlib.errors as errors


class EmailSender(object):
    """An email message sender."""

    def __init__(self, branch, revision_id, config):
        self.config = config
        self.branch = branch
        self.revision = self.branch.repository.get_revision(revision_id)
        self.revno = self.branch.revision_id_to_revno(revision_id)

    def body(self):
        from bzrlib.log import log_formatter, show_log
        from bzrlib.diff import show_diff_trees
        import sys

        rev1 = rev2 = self.revno
        if rev1 == 0:
            rev1 = None
            rev2 = None

        # use 'replace' so that we don't abort if trying to write out
        # in e.g. the default C locale.

        outf = StringIO()
        lf = log_formatter('long',
                           show_ids=True,
                           to_file=outf
                           )

        show_log(self.branch,
                 lf,
                 start_revision=rev1,
                 end_revision=rev2,
                 verbose=True
                 )

        # optionally show the diff if its smaller than the post_commit_difflimit option
        revid1 = self.revision.revision_id
        if self.revision.parent_ids:
            revid2 = self.revision.parent_ids[0]
        else:
            revid2 = None
        tree1, tree2 = self.branch.repository.revision_trees((revid1, revid2))
        diff_content = StringIO()
        show_diff_trees(tree1, tree2, diff_content)
        lines = diff_content.getvalue().split("\n")
        numlines = len(lines)
        if (numlines <= self.difflimit()):
            outf.write(diff_content.getvalue())
        else:
            outf.write("\nDiff too large for email\n")

        return outf.getvalue()

    def difflimit(self):
        """maximum number of lines of diff to show."""
        result = self.config.get_user_option('post_commit_difflimit')
        if result is None:
            result = 0
        return int(result)

    def mailer(self):
        """What mail program to use."""
        result = self.config.get_user_option('post_commit_mailer')
        if result is None:
            result = "mail"
        return result

    def _command_line(self):
        return [self.mailer(), '-s', self.subject(), '-a', "From: " + self.from_address(),
                self.to()]

    def to(self):
        """What is the address the mail should go to."""
        return self.config.get_user_option('post_commit_to')

    def url(self):
        """What URL to display in the subject of the mail"""
        url = self.config.get_user_option('post_commit_url')
        if url is None:
            url = self.branch.base
        return url
    

    def from_address(self):
        """What address should I send from."""
        result = self.config.get_user_option('post_commit_sender')
        if result is None:
            result = self.config.username()
        return result

    def send(self):
        # TODO think up a good test for this, but I think it needs
        # a custom binary shipped with. RBC 20051021
        try:
            process = subprocess.Popen(self._command_line(),
                                       stdin=subprocess.PIPE)
            try:
                result = process.communicate(self.body().encode('utf8'))[0]
                if process.returncode is None:
                    process.wait()
                if process.returncode != 0:
                    raise errors.BzrError("Failed to send email")
                return result
            except OSError, e:
                if e.errno == errno.EPIPE:
                    raise errors.BzrError("Failed to send email.")
                else:
                    raise
        except ValueError:
            # bad subprocess parameters, should never happen.
            raise
        except OSError, e:
            if e.errno == errno.ENOENT:
                raise errors.BzrError("mail is not installed !?")
            else:
                raise

    def should_send(self):
        return self.to() is not None and self.from_address() is not None

    def send_maybe(self):
        if self.should_send():
            self.send()

    def subject(self):
        return ("Rev %d: %s in %s" % 
                (self.revno,
                 self.revision.get_summary(),
                 self.url()))


def post_commit(branch, revision_id):
    EmailSender(branch, revision_id, config.BranchConfig(branch)).send_maybe()


def test_suite():
    from unittest import TestSuite
    import bzrlib.plugins.email.tests 
    result = TestSuite()
    result.addTest(bzrlib.plugins.email.tests.test_suite())
    return result

