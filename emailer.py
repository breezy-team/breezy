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

from StringIO import StringIO
from email.Header import Header
from email.Message import Message
try:
    # python <= 2.4
    from email.MIMEText import MIMEText
    from email.MIMEMultipart import MIMEMultipart
except ImportError:
    # python 2.5 moved MIMEText into a better namespace
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
import errno
import smtplib
import subprocess

from bzrlib import (
    config,
    errors,
    lazy_regex,
    revision as _mod_revision,
    ui,
    __version__ as _bzrlib_version,
    )


class EmailSender(object):
    """An email message sender."""

    def __init__(self, branch, revision_id, config):
        self.config = config
        self.branch = branch
        self.revision = self.branch.repository.get_revision(revision_id)
        self.revno = self.branch.revision_id_to_revno(revision_id)

    def body(self):
        from bzrlib.log import log_formatter, show_log

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

        if self.difflimit():
            self.add_diff(outf, self.difflimit())
        return outf.getvalue()

    def add_diff(self, outf, difflimit):
        """Add the diff from the commit to the output.

        If the diff has more than difflimit lines, it will be skipped.
        """
        from bzrlib.diff import show_diff_trees
        # optionally show the diff if its smaller than the post_commit_difflimit option
        revid_new = self.revision.revision_id
        if self.revision.parent_ids:
            revid_old = self.revision.parent_ids[0]
            tree_new, tree_old = self.branch.repository.revision_trees((revid_new, revid_old))
        else:
            # revision_trees() doesn't allow None or 'null:' to be passed as a
            # revision. So we need to call revision_tree() twice.
            revid_old = _mod_revision.NULL_REVISION
            tree_new = self.branch.repository.revision_tree(revid_new)
            tree_old = self.branch.repository.revision_tree(revid_old)
        diff_content = StringIO()
        show_diff_trees(tree_old, tree_new, diff_content)
        lines = diff_content.getvalue().split("\n")
        numlines = len(lines)
        difflimit = self.difflimit()
        if difflimit:
            if numlines <= difflimit:
                outf.write(diff_content.getvalue())
            else:
                outf.write("\nDiff too large for email (%d, the limit is %d).\n"
                    % (numlines, difflimit))

    def difflimit(self):
        """maximum number of lines of diff to show."""
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
        return [self.mailer(), '-s', self.subject(), '-a',
                "From: " + self.from_address(), self.to()]

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
        mailer = self.mailer()
        if mailer == 'smtplib':
            self._send_using_smtplib()
        else:
            self._send_using_mail()

    def _send_using_mail(self):
        """Spawn a 'mail' subprocess to send the email."""
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

    def _send_using_smtplib(self):
        """Use python's smtplib to send the email."""

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


class SMTPConnection(object):
    """Connecting to an SMTP server and send an email.

    This is a gateway between bzrlib.config.Config and smtplib.SMTP. It
    understands the basic bzr SMTP configuration information.
    """

    _default_smtp_server = 'localhost'
    _user_and_email_re = lazy_regex.lazy_compile(
        r'(?P<username>.*?)\s*<?' # user and optional opening '<'
        r'(?P<email>[\w+.-]+@[\w+.-]+)>?' # email and closing '>'
        )

    def __init__(self, config):
        self._config = config
        self._smtp_server = config.get_user_option('smtp_server')
        if self._smtp_server is None:
            self._smtp_server = self._default_smtp_server

        self._smtp_username = config.get_user_option('smtp_username')
        self._smtp_password = config.get_user_option('smtp_password')

        self._connection = None

    def _connect(self):
        """If we haven't connected, connect and authenticate."""
        if self._connection is not None:
            return

        self._create_connection()
        self._authenticate()

    def _create_connection(self):
        """Create an SMTP connection."""
        self._connection = smtplib.SMTP()
        self._connection.connect(self._smtp_server)

        # If this fails, it just returns an error, but it shouldn't raise an
        # exception unless something goes really wrong (in which case we want
        # to fail anyway).
        self._connection.starttls()

    def _authenticate(self):
        """If necessary authenticate yourself to the server."""
        if self._smtp_username is None:
            return

        if self._smtp_password is None:
            self._smtp_password = ui.ui_factory.get_password(
                'Please enter the SMTP password: %(user)@%(host)s',
                user=self._smtp_username,
                host=self._smtp_server)
        try:
            self._connection.login(self._smtp_username, self._smtp_password)
        except smtplib.SMTPHeloError, e:
            raise BzrCommandError('SMTP server refused HELO: %d %s'
                                  % (e.smtp_code, e.smtp_error))
        except smtplib.SMTPAuthenticationError, e:
            raise BzrCommandError('SMTP server refused authentication: %d %s'
                                  % (e.smtp_code, e.smtp_error))
        except smtplib.SMTPException, e:
            raise BzrCommandError(str(e))

    @staticmethod
    def _split_address(address):
        """Split an username + email address into its parts.

        This takes "Joe Foo <joe@foo.com>" and returns "Joe Foo",
        "joe@foo.com".
        :param address: A combined username
        :return: (username, email)
        """
        m = SMTPConnection._user_and_email_re.match(address)
        if m is None:
            # We didn't find an email address, so lets just assume that the
            # username == address
            # That way if someone configures "user" then we send an email to:
            # user <user>, which could actually be correct.
            return address, address

        return m.group('username'), m.group('email').encode('ascii')

    def _basic_message(self, from_address, to_addresses, subject):
        """Create the basic Message using the right Header info.

        This creates an email Message with no payload.
        :param from_address: The Unicode from address.
        :param to_addresses: A list of Unicode destination addresses.
        :param subject: A Unicode subject for the email.
        """
        # It would be nice to use a single part if we only had one, but we
        # would have to know ahead of time how many parts we needed.
        # So instead, just default to multipart.
        msg = MIMEMultipart()

        # Header() does a good job of doing the proper encoding. However it
        # confuses my SMTP server because it doesn't decode the strings. So it
        # is better to send the addresses as:
        #   =?utf-8?q?username?= <email@addr.com>
        # Which is how Thunderbird does it

        from_user, from_email = self._split_address(from_address)
        msg['From'] = '%s <%s>' % (Header(from_user, 'utf8'), from_email)
        msg['User-Agent'] = 'bzr/%s' % _bzrlib_version

        to_emails = []
        to_header = []
        for addr in to_addresses:
            to_user, to_email = self._split_address(addr)
            to_emails.append(to_email)
            to_header.append('%s <%s>' % (Header(to_user, 'utf8'), to_email))

        msg['To'] = ', '.join(to_header)
        msg['Subject'] = Header(subject)
        return msg, from_email, to_emails

    def send_text_email(self, from_address, to_addresses, subject, message):
        """Send a single text-only email.

        This is a helper when you know you are just sending a simple text
        message. See create_email for an explanation of parameters.
        """
        msg, from_email, to_emails = self.create_email(from_address,
                                            to_addresses, subject, message)
        self._send_message(msg, from_email, to_emails)

    def create_email(self, from_address, to_addresses, subject, message):
        """Create an email.Message object.

        This function allows you to create a basic email, and then add extra
        payload to it.

        :param from_address: A Unicode string with the source email address.
            Example: u'Joe B\xe5 <joe@bar.com>'
        :param to_addresses: A list of addresses to send to.
            Example: [u'Joe B\xe5 <joe@bar.com>', u'Lilly <lilly@nowhere.com>']
        :param subject: A Unicode Subject for the email.
            Example: u'Use Bazaar, its c\xb5l'
        :param message: A Unicode message (will be encoded into utf-8)
            Example: u'I started using Bazaar today.\nI highly recommend it.\n'
        :return: (message, from_email, to_emails)
            message: is a MIME wrapper with the email headers setup. You can add
                more payload by using .attach()
            from_email: the email address extracted from from_address
            to_emails: the list of email addresses extracted from to_addresses
        """
        msg, from_email, to_emails = self._basic_message(from_address,
                                                         to_addresses, subject)
        payload = MIMEText(message.encode('utf-8'), 'plain', 'utf-8')
        msg.attach(payload)
        return msg, from_email, to_emails

    def _send_message(self, msg, from_email, to_emails):
        """Actually send an email to the server."""
        self._connect()
        self._connection.sendmail(from_email, to_emails, msg.as_string())

    def send_text_and_diff_email(self, from_address, to_addresses, subject,
                                 message, diff_txt, fname='patch.diff'):
        """Send a message with a Unicode message and an 8-bit text diff.

        See create_email for common parameter definitions.
        :param diff_txt: The 8-bit diff text. This will not be translated.
            It must be an 8-bit string, since we don't do any encoding.
        """
        msg, from_email, to_emails = self.create_email(from_address,
                                            to_addresses, subject, message)
        # Must be an 8-bit string
        assert isinstance(diff_txt, str)

        diff_payload = MIMEText(diff_txt, 'plain', '8-bit')
        # Override Content-Type so that we can include the name
        content_type = diff_payload['Content-Type']
        content_type += '; name="%s"' % (fname,)
        diff_payload.replace_header('Content-Type', content_type)
        diff_payload['Content-Disposition'] = 'inline; filename="%s"' % (fname,)
        msg.attach(diff_payload)
        self._send_message(msg, from_email, to_emails)
