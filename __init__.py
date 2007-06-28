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

"""Allow sending an email after a new commit.

This plugin provides a 'post_commit' hook, which is used to send an email (like
to a developer mailing list) with the basic contents of the change.

See the README file for basic information on how to configure this plugin.
"""


if __name__ != 'bzrlib.plugins.email':
    raise ImportError('The email plugin must be installed as'
                      ' bzrlib.plugins.email not %s'
                      % __name__)


from bzrlib import errors
from bzrlib.branch import Branch
from bzrlib.lazy_import import lazy_import

# lazy_import emailer so that it doesn't get loaded if it isn't used
lazy_import(globals(), """\
from bzrlib.plugins.email import emailer as _emailer
""")


def post_commit(branch, revision_id):
    if not use_legacy:
        return
    """This is the post_commit hook that should get run after commit."""
    _emailer.EmailSender(branch, revision_id, branch.get_config()).send_maybe()


def branch_commit_hook(local, master, old_revno, old_revid, new_revno, new_revid):
    """This is the post_commit hook that runs after commit."""
    _emailer.EmailSender(master, new_revid, master.get_config(),
                         local_branch=local).send_maybe()


def install_hooks():
    """Install CommitSender to send after commits with bzr >= 0.15 """
    Branch.hooks.install_hook('post_commit', branch_commit_hook)
    if getattr(Branch.hooks, 'name_hook', None):
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
