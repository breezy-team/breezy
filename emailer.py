# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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

import errno
import subprocess

from bzrlib import (
    errors,
    revision as _mod_revision,
    )

from smtp_connection import SMTPConnection


class EmailSender(object):
    """An email message sender."""

    _smtplib_implementation = SMTPConnection

    def __init__(self, branch, revision_id, config, local_branch=None,
        op='commit'):
        self.config = config
        self.branch = branch
        self.repository = branch.repository
        if (local_branch is not None and
            local_branch.repository.has_revision(revision_id)):
            self.repository = local_branch.repository
        self._revision_id = revision_id
        self.revision = None
        self.revno = None
        self.op = op

    def _setup_revision_and_revno(self):
        self.revision = self.repository.get_revision(self._revision_id)
        self.revno = self.branch.revision_id_to_revno(self._revision_id)

    def body(self):
        from bzrlib import log

        rev1 = rev2 = self.revno
        if rev1 == 0:
            rev1 = None
            rev2 = None

        # use 'replace' so that we don't abort if trying to write out
        # in e.g. the default C locale.

        # We must use StringIO.StringIO because we want a Unicode string that
        # we can pass to send_email and have that do the proper encoding.
        from StringIO import StringIO
        outf = StringIO()

        outf.write('At %s\n\n' % self.url())

        lf = log.log_formatter('long',
                               show_ids=True,
                               to_file=outf
                               )

        if len(self.revision.parent_ids) <= 1:
            # This is not a merge, so we can special case the display of one
            # revision, and not have to encur the show_log overhead.
            lr = log.LogRevision(self.revision, self.revno, 0, None)
            lf.log_revision(lr)
        else:
            # let the show_log code figure out what revisions need to be
            # displayed, as this is a merge
            log.show_log(self.branch,
                         lf,
                         start_revision=rev1,
                         end_revision=rev2,
                         verbose=True
                         )

        return outf.getvalue()

    def get_diff(self):
        """Add the diff from the commit to the output.

        If the diff has more than difflimit lines, it will be skipped.
        """
        difflimit = self.difflimit()
        if not difflimit:
            # No need to compute a diff if we aren't going to display it
            return

        from bzrlib.diff import show_diff_trees
        # optionally show the diff if its smaller than the post_commit_difflimit option
        revid_new = self.revision.revision_id
        if self.revision.parent_ids:
            revid_old = self.revision.parent_ids[0]
            tree_new, tree_old = self.repository.revision_trees((revid_new, revid_old))
        else:
            # revision_trees() doesn't allow None or 'null:' to be passed as a
            # revision. So we need to call revision_tree() twice.
            revid_old = _mod_revision.NULL_REVISION
            tree_new = self.repository.revision_tree(revid_new)
            tree_old = self.repository.revision_tree(revid_old)

        # We can use a cStringIO because show_diff_trees should only write
        # 8-bit strings. It is an error to write a Unicode string here.
        from cStringIO import StringIO
        diff_content = StringIO()
        show_diff_trees(tree_old, tree_new, diff_content)
        numlines = diff_content.getvalue().count('\n')+1
        if numlines <= difflimit:
            return diff_content.getvalue()
        else:
            return ("\nDiff too large for email"
                    " (%d lines, the limit is %d).\n"
                    % (numlines, difflimit))

    def difflimit(self):
        """Maximum number of lines of diff to show."""
        result = self.config.get_user_option('post_commit_difflimit')
        if result is None:
            result = 1000
        return int(result)

    def mailer(self):
        """What mail program to use."""
        result = self.config.get_user_option('post_commit_mailer')
        if result is None:
            result = "mail"
        return result

    def _command_line(self):
        cmd = [self.mailer(), '-s', self.subject(), '-a',
                "From: " + self.from_address()]
        to = self.to()
        if isinstance(to, basestring):
            cmd.append(to)
        else:
            cmd.extend(to)
        return cmd

    def to(self):
        """What is the address the mail should go to."""
        return self.config.get_user_option('post_commit_to')

    def url(self):
        """What URL to display in the subject of the mail"""
        url = self.config.get_user_option('post_commit_url')
        if url is None:
            url = self.config.get_user_option('public_branch')
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
        """Send the email.

        Depending on the configuration, this will either use smtplib, or it
        will call out to the 'mail' program.
        """
        self.branch.lock_read()
        self.repository.lock_read()
        try:
            # Do this after we have locked, to make things faster.
            self._setup_revision_and_revno()
            mailer = self.mailer()
            if mailer == 'smtplib':
                self._send_using_smtplib()
            else:
                self._send_using_process()
        finally:
            self.repository.unlock()
            self.branch.unlock()

    def _send_using_process(self):
        """Spawn a 'mail' subprocess to send the email."""
        # TODO think up a good test for this, but I think it needs
        # a custom binary shipped with. RBC 20051021
        try:
            process = subprocess.Popen(self._command_line(),
                                       stdin=subprocess.PIPE)
            try:
                message = self.body().encode('utf8') + self.get_diff()
                result = process.communicate(message)[0]
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

    def _send_using_smtplib(self):
        """Use python's smtplib to send the email."""
        body = self.body()
        diff = self.get_diff()
        subject = self.subject()
        from_addr = self.from_address()
        to_addrs = self.to()
        if isinstance(to_addrs, basestring):
            to_addrs = [to_addrs]

        smtp = self._smtplib_implementation(self.config)
        smtp.send_text_and_attachment_email(from_addr, to_addrs,
                                            subject, body, diff,
                                            self.diff_filename())

    def should_send(self):
        result = self.config.get_user_option('post_commit_difflimit')
        post_commit_push_pull = self.config.get_user_option(
            'post_commit_push_pull') == 'True'
        if post_commit_push_pull and self.op == 'commit':
            # We will be called again with a push op, send the mail then.
            return False
        if not post_commit_push_pull and self.op != 'commit':
            # Mailing on commit only, and this is a push/pull operation.
            return False
        return bool(self.to() and self.from_address())

    def send_maybe(self):
        if self.should_send():
            self.send()

    def subject(self):
        return ("Rev %d: %s in %s" %
                (self.revno,
                 self.revision.get_summary(),
                 self.url()))

    def diff_filename(self):
        return "patch-%s.diff" % (self.revno,)

