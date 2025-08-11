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

"""Sending emails for commits and branch changes.

To have Breezy send an email you need to configure an address to send mail
to for that branch. To do this set the configuration option ``post_commit_to``
and the address to send the mail from is read from the configuration option
``post_commit_sender`` (if not supplied defaults to the email address reported
by ``brz whoami``).

By default, the diff for the commit will be included in the email if the
length is less than 1000 lines. This limit can be changed by setting the
configuration option 'post_commit_difflimit' to the number of lines you wish
it to be limited to. Set it to 0 to unconditionally disable sending of diffs.

By default emails are sent only when a commit occurs, not when a push or
pull operation occurs. To email on push or pull set post_commit_push_pull=True
in the configuration.

The URL of the branch is determined from the following checks (in order):
 - If the configuration value 'post_commit_url' is set, it is used.
 - If the configuration value 'public_branch' is set, it is used.
 - The URL of the branch itself.

Setting public_branch is highly recommended if you commit via a protocol which
has a private address (e.g. bzr+ssh but anonymous access might be bzr:// or
http://).

How emails are sent is determined by the value of the configuration option
'post_commit_mailer':
 - Unset: use ``/usr/bin/mail``.
 - ``smtplib``: Use python's smtplib to send the mail. If you use 'smtplib' you
   can also configure the settings "smtp_server=host[:port]",
   "smtp_username=userid", "smtp_password". If "smtp_username" is set but
   "smtp_password" is not, you will be prompted for a password.

   Also, if using 'smtplib', the messages will be sent as a UTF-8 text message,
   with a 8-bit text diff attached (rather than all-as-one). Work has also been
   done to make sure usernames do not have to be ascii.
 - Any other value: Run the value expecting it to behave like ``/usr/bin/mail``
   - in particular supporting the -s and -a options.

When using smtplib, you can specify additional headers to be included in the
mail by setting the 'revision_mail_headers' configuration option - something
like::

  revision_mail_headers=X-Cheese: to the rescue!

Other supported options (use ``brz help <option>`` for more information)
are: post_commit_body, post_commit_subject, post_commit_log_format,
post_commit_diffoptions, post_commit_sender, post_commit_to.
"""

from ... import version_info  # noqa: F401
from ...config import option_registry


def post_commit(branch, revision_id):
    """This is the post_commit hook that should get run after commit."""
    from . import emailer

    emailer.EmailSender(branch, revision_id, branch.get_config_stack()).send_maybe()


def branch_commit_hook(local, master, old_revno, old_revid, new_revno, new_revid):
    """This is the post_commit hook that runs after commit."""
    from . import emailer

    emailer.EmailSender(
        master, new_revid, master.get_config_stack(), local_branch=local
    ).send_maybe()


def branch_post_change_hook(params):
    """This is the post_change_branch_tip hook."""
    # (branch, old_revno, new_revno, old_revid, new_revid)
    from . import emailer

    emailer.EmailSender(
        params.branch,
        params.new_revid,
        params.branch.get_config_stack(),
        local_branch=None,
        op="change",
    ).send_maybe()


def test_suite():
    """Return the test suite for the email plugin.

    Returns:
        TestSuite: A unittest TestSuite containing all tests for the email plugin.
    """
    from unittest import TestSuite

    from .tests import test_suite

    result = TestSuite()
    result.addTest(test_suite())
    return result


option_registry.register_lazy(
    "post_commit_body", "breezy.plugins.email.emailer", "opt_post_commit_body"
)
option_registry.register_lazy(
    "post_commit_subject", "breezy.plugins.email.emailer", "opt_post_commit_subject"
)
option_registry.register_lazy(
    "post_commit_log_format",
    "breezy.plugins.email.emailer",
    "opt_post_commit_log_format",
)
option_registry.register_lazy(
    "post_commit_difflimit", "breezy.plugins.email.emailer", "opt_post_commit_difflimit"
)
option_registry.register_lazy(
    "post_commit_push_pull", "breezy.plugins.email.emailer", "opt_post_commit_push_pull"
)
option_registry.register_lazy(
    "post_commit_diffoptions",
    "breezy.plugins.email.emailer",
    "opt_post_commit_diffoptions",
)
option_registry.register_lazy(
    "post_commit_sender", "breezy.plugins.email.emailer", "opt_post_commit_sender"
)
option_registry.register_lazy(
    "post_commit_to", "breezy.plugins.email.emailer", "opt_post_commit_to"
)
option_registry.register_lazy(
    "post_commit_mailer", "breezy.plugins.email.emailer", "opt_post_commit_mailer"
)
option_registry.register_lazy(
    "revision_mail_headers", "breezy.plugins.email.emailer", "opt_revision_mail_headers"
)

from ...hooks import install_lazy_named_hook

install_lazy_named_hook(
    "breezy.branch", "Branch.hooks", "post_commit", branch_commit_hook, "email"
)
install_lazy_named_hook(
    "breezy.branch",
    "Branch.hooks",
    "post_change_branch_tip",
    branch_post_change_hook,
    "email",
)
