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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Launchpad.net integration plugin for Bazaar."""

# The XMLRPC server address can be overridden by setting the environment
# variable $BZR_LP_XMLRPL_URL

# see http://bazaar-vcs.org/Specs/BranchRegistrationTool

# Since we are a built-in plugin we share the bzrlib version
from bzrlib import version_info

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    branch as _mod_branch,
    trace,
    )
""")

from bzrlib.commands import Command, Option, register_command
from bzrlib.directory_service import directories
from bzrlib.errors import (
    BzrCommandError,
    InvalidURL,
    NoPublicBranch,
    NotBranchError,
    )
from bzrlib.help_topics import topic_registry
from bzrlib.plugins.launchpad.lp_registration import (
    LaunchpadService,
    NotLaunchpadBranch,
    )


class cmd_register_branch(Command):
    """Register a branch with launchpad.net.

    This command lists a bzr branch in the directory of branches on
    launchpad.net.  Registration allows the branch to be associated with
    bugs or specifications.

    Before using this command you must register the project to which the
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
        bzr register-branch http://foo.com/bzr/fooproject.mine \\
                --project fooproject
    """
    takes_args = ['public_url?']
    takes_options = [
         Option('project',
                'Launchpad project short name to associate with the branch.',
                unicode),
         Option('product',
                'Launchpad product short name to associate with the branch.', 
                unicode,
                hidden=True),
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
            project='',
            product=None,
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
                b = _mod_branch.Branch.open_containing('.')[0]
            except NotBranchError:
                raise BzrCommandError('register-branch requires a public '
                    'branch url - see bzr help register-branch.')
            public_url = b.get_public_branch()
            if public_url is None:
                raise NoPublicBranch(b)
        if product is not None:
            project = product
            trace.note('--product is deprecated; please use --project.')


        rego = BranchRegistrationRequest(branch_url=public_url,
                                         branch_name=branch_name,
                                         branch_title=branch_title,
                                         branch_description=branch_description,
                                         product_name=project,
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


class cmd_launchpad_open(Command):
    """Open a Launchpad branch page in your web browser."""

    aliases = ['lp-open']
    takes_options = [
        Option('dry-run',
               'Do not actually open the browser. Just say the URL we would '
               'use.'),
        ]
    takes_args = ['location?']

    def _possible_locations(self, location):
        """Yield possible external locations for the branch at 'location'."""
        yield location
        try:
            branch = _mod_branch.Branch.open(location)
        except NotBranchError:
            return
        branch_url = branch.get_public_branch()
        if branch_url is not None:
            yield branch_url
        branch_url = branch.get_push_location()
        if branch_url is not None:
            yield branch_url

    def _get_web_url(self, service, location):
        for branch_url in self._possible_locations(location):
            try:
                return service.get_web_url_from_branch_url(branch_url)
            except (NotLaunchpadBranch, InvalidURL):
                pass
        raise NotLaunchpadBranch(branch_url)

    def run(self, location=None, dry_run=False):
        if location is None:
            location = u'.'
        web_url = self._get_web_url(LaunchpadService(), location)
        trace.note('Opening %s in web browser' % web_url)
        if not dry_run:
            import webbrowser   # this import should not be lazy
                                # otherwise bzr.exe lacks this module
            webbrowser.open(web_url)

register_command(cmd_launchpad_open)


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
        'verbose',
        Option('no-check',
               "Don't check that the user name is valid."),
        ]

    def run(self, name=None, no_check=False, verbose=False):
        from bzrlib.plugins.launchpad import account
        check_account = not no_check

        if name is None:
            username = account.get_lp_login()
            if username:
                if check_account:
                    account.check_lp_login(username)
                    if verbose:
                        self.outf.write(
                            "Launchpad user ID exists and has SSH keys.\n")
                self.outf.write(username + '\n')
            else:
                self.outf.write('No Launchpad user ID configured.\n')
                return 1
        else:
            name = name.lower()
            if check_account:
                account.check_lp_login(name)
                if verbose:
                    self.outf.write(
                        "Launchpad user ID exists and has SSH keys.\n")
            account.set_lp_login(name)
            if verbose:
                self.outf.write("Launchpad user ID set to '%s'.\n" % (name,))

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
        test_account,
        test_lp_directory,
        test_lp_login,
        test_lp_open,
        test_lp_service,
        test_register,
        )

    loader = TestLoader()
    suite = TestSuite()
    for module in [
        test_account,
        test_register,
        test_lp_directory,
        test_lp_login,
        test_lp_open,
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

    * The 'lp:' transport uses Launchpad as a directory service: for example
      'lp:bzr' and 'lp:python' refer to the main branches of the relevant
      projects and may be branched, logged, etc. You can also use the 'lp:'
      transport to refer to specific branches, e.g. lp:~bzr/bzr/trunk.

    * The 'lp:' bug tracker alias can expand launchpad bug numbers to their
      URLs for use with 'bzr commit --fixes', e.g. 'bzr commit --fixes lp:12345'
      will record a revision property that marks that revision as fixing
      Launchpad bug 12345. When you push that branch to Launchpad it will
      automatically be linked to the bug report.

    * The register-branch command tells Launchpad about the url of a
      public branch.  Launchpad will then mirror the branch, display
      its contents and allow it to be attached to bugs and other
      objects.

For more information see http://help.launchpad.net/
"""
topic_registry.register('launchpad',
    _launchpad_help,
    'Using Bazaar with Launchpad.net')
