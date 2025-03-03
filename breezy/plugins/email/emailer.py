# Copyright (C) 2005-2011 Canonical Ltd
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

import subprocess
import tempfile

from ... import errors
from ... import revision as _mod_revision
from ...config import ListOption, Option, bool_from_store, int_from_store
from ...email_message import EmailMessage
from ...smtp_connection import SMTPConnection


class EmailSender:
    """An email message sender."""

    _smtplib_implementation = SMTPConnection

    def __init__(self, branch, revision_id, config, local_branch=None, op="commit"):
        self.config = config
        self.branch = branch
        self.repository = branch.repository
        if local_branch is not None and local_branch.repository.has_revision(
            revision_id
        ):
            self.repository = local_branch.repository
        self._revision_id = revision_id
        self.revision = None
        self.revno = None
        self.op = op

    def _setup_revision_and_revno(self):
        self.revision = self.repository.get_revision(self._revision_id)
        self.revno = self.branch.revision_id_to_revno(self._revision_id)

    def _format(self, text):
        fields = {
            "committer": self.revision.committer,
            "message": self.revision.get_summary(),
            "revision": str(self.revno),
            "url": self.url(),
        }
        for name, value in fields.items():
            text = text.replace("${}".format(name), value)
        return text

    def body(self):
        from ... import log

        rev1 = rev2 = self.revno
        if rev1 == 0:
            rev1 = None
            rev2 = None

        # use 'replace' so that we don't abort if trying to write out
        # in e.g. the default C locale.

        # We must use StringIO.StringIO because we want a Unicode string that
        # we can pass to send_email and have that do the proper encoding.
        from io import StringIO

        outf = StringIO()

        _body = self.config.get("post_commit_body")
        if _body is None:
            _body = "At {}\n\n".format(self.url())
        outf.write(self._format(_body))

        log_format = self.config.get("post_commit_log_format")
        lf = log.log_formatter(log_format, show_ids=True, to_file=outf)

        if len(self.revision.parent_ids) <= 1:
            # This is not a merge, so we can special case the display of one
            # revision, and not have to encur the show_log overhead.
            lr = log.LogRevision(self.revision, self.revno, 0, None)
            lf.log_revision(lr)
        else:
            # let the show_log code figure out what revisions need to be
            # displayed, as this is a merge
            log.show_log(
                self.branch, lf, start_revision=rev1, end_revision=rev2, verbose=True
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

        from ...diff import show_diff_trees

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

        # We can use a StringIO because show_diff_trees should only write
        # 8-bit strings. It is an error to write a Unicode string here.
        from io import BytesIO

        diff_content = BytesIO()
        diff_options = self.config.get("post_commit_diffoptions")
        show_diff_trees(tree_old, tree_new, diff_content, None, diff_options)
        numlines = diff_content.getvalue().count(b"\n") + 1
        if numlines <= difflimit:
            return diff_content.getvalue()
        else:
            return f"\nDiff too large for email ({numlines} lines, the limit is {difflimit}).\n"

    def difflimit(self):
        """Maximum number of lines of diff to show."""
        return self.config.get("post_commit_difflimit")

    def mailer(self):
        """What mail program to use."""
        return self.config.get("post_commit_mailer")

    def _command_line(self):
        cmd = [
            self.mailer(),
            "-s",
            self.subject(),
            "-a",
            "From: " + self.from_address(),
        ]
        cmd.extend(self.to())
        return cmd

    def to(self):
        """What is the address the mail should go to."""
        return self.config.get("post_commit_to")

    def url(self):
        """What URL to display in the subject of the mail."""
        url = self.config.get("post_commit_url")
        if url is None:
            url = self.config.get("public_branch")
        if url is None:
            url = self.branch.base
        return url

    def from_address(self):
        """What address should I send from."""
        result = self.config.get("post_commit_sender")
        if result is None:
            result = self.config.get("email")
        return result

    def extra_headers(self):
        """Additional headers to include when sending."""
        result = {}
        headers = self.config.get("revision_mail_headers")
        if not headers:
            return
        for line in headers:
            key, value = line.split(": ", 1)
            result[key] = value
        return result

    def send(self):
        """Send the email.

        Depending on the configuration, this will either use smtplib, or it
        will call out to the 'mail' program.
        """
        with self.branch.lock_read(), self.repository.lock_read():
            # Do this after we have locked, to make things faster.
            self._setup_revision_and_revno()
            mailer = self.mailer()
            if mailer == "smtplib":
                self._send_using_smtplib()
            else:
                self._send_using_process()

    def _send_using_process(self):
        """Spawn a 'mail' subprocess to send the email."""
        # TODO think up a good test for this, but I think it needs
        # a custom binary shipped with. RBC 20051021
        with tempfile.NamedTemporaryFile() as msgfile:
            msgfile.write(self.body().encode("utf8"))
            diff = self.get_diff()
            if diff:
                msgfile.write(diff)
            msgfile.flush()
            msgfile.seek(0)

            process = subprocess.Popen(self._command_line(), stdin=msgfile.fileno())

            rc = process.wait()
            if rc != 0:
                raise errors.BzrError("Failed to send email: exit status {}".format(rc))

    def _send_using_smtplib(self):
        """Use python's smtplib to send the email."""
        body = self.body()
        diff = self.get_diff()
        subject = self.subject()
        from_addr = self.from_address()
        to_addrs = self.to()
        header = self.extra_headers()

        msg = EmailMessage(from_addr, to_addrs, subject, body)

        if diff:
            msg.add_inline_attachment(diff, self.diff_filename())

        # Add revision_mail_headers to the headers
        if header is not None:
            for k, v in header.items():
                msg[k] = v

        smtp = self._smtplib_implementation(self.config)
        smtp.send_email(msg)

    def should_send(self):
        post_commit_push_pull = self.config.get("post_commit_push_pull")
        if post_commit_push_pull and self.op == "commit":
            # We will be called again with a push op, send the mail then.
            return False
        if not post_commit_push_pull and self.op != "commit":
            # Mailing on commit only, and this is a push/pull operation.
            return False
        return bool(self.to() and self.from_address())

    def send_maybe(self):
        if self.should_send():
            self.send()

    def subject(self):
        _subject = self.config.get("post_commit_subject")
        if _subject is None:
            _subject = (
                f"Rev {self.revno}: {self.revision.get_summary()} in {self.url()}"
            )
        return self._format(_subject)

    def diff_filename(self):
        return "patch-{}.diff".format(self.revno)


opt_post_commit_body = Option("post_commit_body", help="Body for post commit emails.")
opt_post_commit_subject = Option(
    "post_commit_subject", help="Subject for post commit emails."
)
opt_post_commit_log_format = Option(
    "post_commit_log_format", default="long", help="Log format for option."
)
opt_post_commit_difflimit = Option(
    "post_commit_difflimit",
    default=1000,
    from_unicode=int_from_store,
    help="Maximum number of lines in diffs.",
)
opt_post_commit_push_pull = Option(
    "post_commit_push_pull",
    from_unicode=bool_from_store,
    help="Whether to send emails on push and pull.",
)
opt_post_commit_diffoptions = Option(
    "post_commit_diffoptions", help="Diff options to use."
)
opt_post_commit_sender = Option(
    "post_commit_sender", help="From address to use for emails."
)
opt_post_commit_to = ListOption(
    "post_commit_to", help="Address to send commit emails to."
)
opt_post_commit_mailer = Option(
    "post_commit_mailer", help="Mail client to use.", default="mail"
)
opt_post_commit_url = Option(
    "post_commit_url", help="URL to mention for branch in post commit messages."
)
opt_revision_mail_headers = ListOption(
    "revision_mail_headers", help="Extra revision headers."
)
