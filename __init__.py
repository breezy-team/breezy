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

"""Sending emails for commits and branch changes.

To have bzr send an email you need to configure an address to send mail
to for that branch. To do this set the configuration option ``post_commit_to``
and the address to send the mail from is read from the configuration option
``post_commit_sender`` (if not supplied defaults to the email address reported
by ``bzr whoami``).

By default, the diff for the commit will be included in the email, if the
length is less than 1000 lines. This limit can be changed (for instance, to 0
to disable the feature) by setting the configuration option
'post_commit_difflimit' to the number of lines you wish it to be limited to.

By default bzr-email only emails when a commit occurs, not when a push or
pull operation occurs. To email on push or pull set post_commit_push_pull=True
in the configuration.

If you are using a bzr release from before 0.15, you need to manually tell
bzr about the commit action, by setting
post_commit=bzrlib.plugins.email.post_commit in bazaar.conf or locations.conf.

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

"""


if __name__ != 'bzrlib.plugins.email':
    raise ImportError('The email plugin must be installed as'
                      ' bzrlib.plugins.email not %s'
                      % __name__)


# These three are used during import: No point lazy_importing them.
from bzrlib import errors
from bzrlib.branch import Branch
from bzrlib.lazy_import import lazy_import

# lazy_import emailer so that it doesn't get loaded if it isn't used
lazy_import(globals(), """\
from bzrlib.plugins.email import emailer as _emailer
""")


def post_commit(branch, revision_id):
    """This is the post_commit hook that should get run after commit."""
    if not use_legacy:
        return
    _emailer.EmailSender(branch, revision_id, branch.get_config()).send_maybe()


def branch_commit_hook(local, master, old_revno, old_revid, new_revno, new_revid):
    """This is the post_commit hook that runs after commit."""
    _emailer.EmailSender(master, new_revid, master.get_config(),
                         local_branch=local).send_maybe()


def branch_post_change_hook(params):
    """This is the post_change_branch_tip hook."""
    # (branch, old_revno, new_revno, old_revid, new_revid)
    _emailer.EmailSender(params.branch, params.new_revid,
        params.branch.get_config(), local_branch=None, op='change').send_maybe()


def install_hooks():
    """Install CommitSender to send after commits with bzr >= 0.15 """
    install_named_hook = getattr(Branch.hooks, 'install_named_hook', None)
    if install_named_hook is not None:
        install_named_hook('post_commit', branch_commit_hook, 'bzr-email')
        if 'post_change_branch_tip' in Branch.hooks:
            install_named_hook('post_change_branch_tip',
                branch_post_change_hook, 'bzr-email')
    else:
        Branch.hooks.install_hook('post_commit', branch_commit_hook)
        if getattr(Branch.hooks, 'name_hook', None) is not None:
            Branch.hooks.name_hook(branch_commit_hook, "bzr-email")


def test_suite():
    from unittest import TestSuite
    import bzrlib.plugins.email.tests
    result = TestSuite()
    result.addTest(bzrlib.plugins.email.tests.test_suite())
    return result


# setup the email plugin with > 0.15 hooks.
try:
    install_hooks()
    use_legacy = False
except AttributeError:
    # bzr < 0.15 - no Branch.hooks
    use_legacy = True
except errors.UnknownHook:
    # bzr 0.15 dev before post_commit was added
    use_legacy = True
