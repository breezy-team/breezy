# Copyright (C) 2006 - 2008 Canonical Ltd
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

"""Launchpad.net integration plugin for Bazaar."""

# The XMLRPC server address can be overridden by setting the environment
# variable $BZR_LP_XMLRPL_URL

# see http://bazaar-vcs.org/Specs/BranchRegistrationTool

from bzrlib.branch import Branch
from bzrlib.commands import Command, Option, register_command
from bzrlib.directory_service import directories
from bzrlib.errors import BzrCommandError, NoPublicBranch, NotBranchError
from bzrlib.help_topics import topic_registry


class cmd_register_branch(Command):
    """Register a branch with launchpad.net.

    This command lists a bzr branch in the directory of branches on
    launchpad.net.  Registration allows the branch to be associated with
    bugs or specifications.
    
    Before using this command you must register the product to which the
    branch belongs, and create an account for yourself on launchpad.net.

    arguments:
        public_url: The publicly visible url for the branch to register.
                    This must be an http or https url (which Launchpad can read
                    from to access the branch). Local file urls, SFTP urls, and
                    bzr+ssh urls will not work.
                    If no public_url is provided, bzr will use the configured
                    public_url if there is one for the current branch, and
                    otherwise error.

    example:
        bzr register-branch http://foo.com/bzr/fooproduct.mine \\
                --product fooproduct
    """
    takes_args = ['public_url?']
    takes_options = [
         Option('product',
                'Launchpad product short name to associate with the branch.',
                unicode),
         Option('branch-name',
                'Short name for the branch; '
                'by default taken from the last component of the url.',
                unicode),
         Option('branch-title',
                'One-sentence description of the branch.',
                unicode),
         Option('branch-description',
                'Longer description of the purpose or contents of the branch.',
                unicode),
         Option('author',
                "Branch author's email address, if not yourself.",
                unicode),
         Option('link-bug',
                'The bug this branch fixes.',
                int),
         Option('dry-run',
                'Prepare the request but don\'t actually send it.')
        ]


    def run(self,
            public_url=None,
            product='',
            branch_name='',
            branch_title='',
            branch_description='',
            author='',
            link_bug=None,
            dry_run=False):
        from bzrlib.plugins.launchpad.lp_registration import (
            LaunchpadService, BranchRegistrationRequest, BranchBugLinkRequest,
            DryRunLaunchpadService)
        if public_url is None:
            try:
                b = Branch.open_containing('.')[0]
            except NotBranchError:
                raise BzrCommandError('register-branch requires a public '
                    'branch url - see bzr help register-branch.')
            public_url = b.get_public_branch()
            if public_url is None:
                raise NoPublicBranch(b)

        rego = BranchRegistrationRequest(branch_url=public_url,
                                         branch_name=branch_name,
                                         branch_title=branch_title,
                                         branch_description=branch_description,
                                         product_name=product,
                                         author_email=author,
                                         )
        linko = BranchBugLinkRequest(branch_url=public_url,
                                     bug_id=link_bug)
        if not dry_run:
            service = LaunchpadService()
            # This gives back the xmlrpc url that can be used for future
            # operations on the branch.  It's not so useful to print to the
            # user since they can't do anything with it from a web browser; it
            # might be nice for the server to tell us about an html url as
            # well.
        else:
            # Run on service entirely in memory
            service = DryRunLaunchpadService()
        service.gather_user_credentials()
        branch_object_url = rego.submit(service)
        if link_bug:
            link_bug_url = linko.submit(service)
        print 'Branch registered.'

register_command(cmd_register_branch)


class cmd_launchpad_login(Command):
    """Show or set the Launchpad user ID.

    When communicating with Launchpad, some commands need to know your
    Launchpad user ID.  This command can be used to set or show the
    user ID that Bazaar will use for such communication.

    :Examples:
      Show the Launchpad ID of the current user::

          bzr launchpad-login

      Set the Launchpad ID of the current user to 'bob'::

          bzr launchpad-login bob
    """
    aliases = ['lp-login']
    takes_args = ['name?']
    takes_options = [
        Option('no-check',
               "Don't check that the user name is valid."),
        ]

    def run(self, name=None, no_check=False):
        from bzrlib.plugins.launchpad import account
        check_account = not no_check

        if name is None:
            username = account.get_lp_login()
            if username:
                if check_account:
                    account.check_lp_login(username)
                self.outf.write(username + '\n')
            else:
                self.outf.write('No Launchpad user ID configured.\n')
                return 1
        else:
            if check_account:
                account.check_lp_login(name)
            account.set_lp_login(name)

register_command(cmd_launchpad_login)


def _register_directory():
    directories.register_lazy('lp:', 'bzrlib.plugins.launchpad.lp_directory',
                              'LaunchpadDirectory',
                              'Launchpad-based directory service',)
_register_directory()


def test_suite():
    """Called by bzrlib to fetch tests for this plugin"""
    from unittest import TestSuite, TestLoader
    from bzrlib.plugins.launchpad import (
         test_account, test_lp_directory, test_lp_service, test_register,
         )

    loader = TestLoader()
    suite = TestSuite()
    for module in [
        test_account,
        test_register,
        test_lp_directory,
        test_lp_service,
        ]:
        suite.addTests(loader.loadTestsFromModule(module))
    return suite

_launchpad_help = """Integration with Launchpad.net

Launchpad.net provides free Bazaar branch hosting with integrated bug and
specification tracking.

The bzr client (through the plugin called 'launchpad') has special
features to communicate with Launchpad:

    * The launchpad-login command tells Bazaar your Launchpad user name. This
      is then used by the 'lp:' transport to download your branches using
      bzr+ssh://.

    * The register-branch command tells Launchpad about the url of a
      public branch.  Launchpad will then mirror the branch, display
      its contents and allow it to be attached to bugs and other
      objects.

    * The 'lp:' transport uses Launchpad as a directory service: for example
      'lp:bzr' and 'lp:python' refer to the main branches of the relevant
      projects and may be branched, logged, etc. You can also use the 'lp:'
      transport to refer to specific branches, e.g. lp:///~bzr/bzr/trunk.

For more information see http://help.launchpad.net/
"""
topic_registry.register('launchpad',
    _launchpad_help,
    'Using Bazaar with Launchpad.net')
