# Copyright (C) 2005-2007 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""
Support for Subversion branches
"""
import bzrlib
from bzrlib.bzrdir import BzrDirFormat, format_registry
from bzrlib.commands import Command, register_command, display_command, Option
from bzrlib.help_topics import topic_registry
from bzrlib.revisionspec import SPEC_TYPES
from bzrlib.trace import warning
from bzrlib.transport import register_lazy_transport, register_transport_proto

import format
import revspec

# versions ending in 'exp' mean experimental mappings
# versions ending in 'dev' mean development version
# versions ending in 'final' mean release (well tested, etc)
version_info = (0, 4, 10, 'exp', 0)

if version_info[3] == 'final':
    version_string = '%d.%d.%d' % version_info[:3]
else:
    version_string = '%d.%d.%d%s%d' % version_info
__version__ = version_string

COMPATIBLE_BZR_VERSIONS = [(1, 4)]

def check_bzrlib_version(desired):
    """Check that bzrlib is compatible.

    If version is < all compatible version, assume incompatible.
    If version is compatible version + 1, assume compatible, with deprecations
    Otherwise, assume incompatible.
    """
    import bzrlib
    bzrlib_version = bzrlib.version_info[:2]
    if (bzrlib_version in desired or 
        ((bzrlib_version[0], bzrlib_version[1]-1) in desired and 
         bzrlib.version_info[3] == 'dev')):
        return
    from bzrlib.errors import BzrError
    if bzrlib_version < desired[0]:
        raise BzrError('Installed bzr version %s is too old to be used with bzr-svn, at least %s.%s required' % (bzrlib.__version__, desired[0][0], desired[0][1]))
    else:
        warning('bzr-svn is not up to date with installed bzr version %s.'
                ' \nThere should be a newer version of bzr-svn available.' 
                % (bzrlib.__version__))
        if not (bzrlib_version[0], bzrlib_version[1]-1) in desired:
            raise BzrError('Version mismatch')

def check_subversion_version():
    """Check that Subversion is compatible.

    """
    try:
        import svn.delta
    except ImportError:
        warning('No Python bindings for Subversion installed. See the '
                'bzr-svn README for details.')
        raise bzrlib.errors.BzrError("missing python subversion bindings")
    if (not hasattr(svn.delta, 'svn_delta_invoke_txdelta_window_handler') and 
        not hasattr(svn.delta, 'tx_invoke_window_handler')):
        warning('Installed Subversion version does not have updated Python '
                'bindings. See the bzr-svn README for details.')
        raise bzrlib.errors.BzrError("incompatible python subversion bindings")

check_subversion_version()

register_transport_proto('svn+ssh://', 
    help="Access using the Subversion smart server tunneled over SSH.")
register_transport_proto('svn+file://', 
    help="Access of local Subversion repositories.")
register_transport_proto('svn+http://',
    help="Access of Subversion smart servers over HTTP.")
register_transport_proto('svn+https://',
    help="Access of Subversion smart servers over secure HTTP.")
register_transport_proto('svn://', 
    help="Access using the Subversion smart server.")
register_lazy_transport('svn://', 'bzrlib.plugins.svn.transport', 
                        'SvnRaTransport')
register_lazy_transport('svn+', 'bzrlib.plugins.svn.transport', 
                        'SvnRaTransport')
topic_registry.register_lazy('svn-branching-schemes', 
                             'bzrlib.plugins.svn.scheme',
                             'help_schemes', 'Subversion branching schemes')

BzrDirFormat.register_control_format(format.SvnRemoteFormat)
BzrDirFormat.register_control_format(format.SvnWorkingTreeDirFormat)
format_registry.register("subversion", format.SvnRemoteFormat, 
                         "Subversion repository. ", 
                         native=False)
format_registry.register("subversion-wc", format.SvnWorkingTreeDirFormat, 
                         "Subversion working copy. ", 
                         native=False, hidden=True)
SPEC_TYPES.append(revspec.RevisionSpec_svn)

versions_checked = False
def lazy_check_versions():
    """Check whether all dependencies have the right versions.
    
    :note: Only checks once, caches the result."""
    global versions_checked
    if versions_checked:
        return
    versions_checked = True
    check_bzrlib_version(COMPATIBLE_BZR_VERSIONS)

optimizers_registered = False
def lazy_register_optimizers():
    """Register optimizers for fetching between Subversion and Bazaar 
    repositories.
    
    :note: Only registers on the first call."""
    global optimizers_registered
    if optimizers_registered:
        return
    from bzrlib.repository import InterRepository
    import commit
    import fetch
    optimizers_registered = True
    InterRepository.register_optimiser(fetch.InterFromSvnRepository)
    InterRepository.register_optimiser(commit.InterToSvnRepository)


def get_scheme(schemename):
    """Parse scheme identifier and return a branching scheme.
    
    :param schemename: Name of the scheme to retrieve.
    """
    if isinstance(schemename, unicode):
        schemename = schemename.encode("ascii")
    from scheme import BranchingScheme
    from bzrlib.errors import BzrCommandError
    
    ret = BranchingScheme.find_scheme(schemename)
    if ret is None:
        raise BzrCommandError('No such branching scheme %r' % schemename)
    return ret


class cmd_svn_import(Command):
    """Convert a Subversion repository to a Bazaar repository.
    
    """
    takes_args = ['from_location', 'to_location?']
    takes_options = [Option('trees', help='Create working trees.'),
                     Option('standalone', help='Create standalone branches.'),
                     Option('all', 
                         help='Convert all revisions, even those not in '
                              'current branch history (forbids --standalone).'),
                     Option('scheme', type=get_scheme,
                         help='Branching scheme (none, trunk, etc). '
                              'Default: auto.'),
                     Option('prefix', type=str, 
                         help='Only consider branches of which path starts '
                              'with prefix.')
                    ]

    @display_command
    def run(self, from_location, to_location=None, trees=False, 
            standalone=False, scheme=None, all=False, prefix=None):
        from bzrlib.branch import Branch
        from bzrlib.bzrdir import BzrDir
        from bzrlib.errors import BzrCommandError, NoRepositoryPresent, NotBranchError
        from bzrlib import urlutils
        from convert import convert_repository
        from repository import SvnRepository
        import os

        if to_location is None:
            to_location = os.path.basename(from_location.rstrip("/\\"))

        if all:
            # All implies shared repository 
            # (otherwise there is no repository to store revisions in)
            standalone = False

        if os.path.isfile(from_location):
            from convert import load_dumpfile
            import tempfile
            tmp_repos = tempfile.mkdtemp(prefix='bzr-svn-dump-')
            load_dumpfile(from_location, tmp_repos)
            from_location = tmp_repos
        else:
            tmp_repos = None

        from_dir = BzrDir.open(from_location)
        try:
            from_repos = from_dir.open_repository()
        except NoRepositoryPresent, e:
            try:
                Branch.open(from_location)
                raise BzrCommandError("No Repository found at %s. "
                    "For individual branches, use 'bzr branch'." % from_location)
            except NotBranchError:
                if prefix is not None:
                    raise BzrCommandError("Path inside repository specified and --prefix specified")
                from_repos = from_dir.find_repository()
                prefix = urlutils.relative_url(from_repos.base, from_location)
                self.outf.write("Importing branches below %s\n" % 
                        urlutils.unescape_for_display(prefix, self.outf.encoding))

        if prefix is not None:
            prefix = prefix.strip("/") + "/"

        if not isinstance(from_repos, SvnRepository):
            raise BzrCommandError(
                    "Not a Subversion repository: %s" % from_location)

        def filter_branch(branch):
            if prefix is not None and not branch.get_branch_path().startswith(prefix):
                return False
            return True

        convert_repository(from_repos, to_location, scheme, not standalone, 
                trees, all, filter_branch=filter_branch)

        if tmp_repos is not None:
            from bzrlib import osutils
            osutils.rmtree(tmp_repos)


register_command(cmd_svn_import)

class cmd_svn_upgrade(Command):
    """Upgrade revisions mapped from Subversion in a Bazaar branch.
    
    This will change the revision ids of revisions whose parents 
    were mapped from svn revisions.
    """
    takes_args = ['from_repository?']
    takes_options = ['verbose']

    @display_command
    def run(self, from_repository=None, verbose=False):
        from upgrade import upgrade_branch, upgrade_workingtree
        from bzrlib.branch import Branch
        from bzrlib.errors import NoWorkingTree, BzrCommandError
        from bzrlib.repository import Repository
        from bzrlib.trace import info
        from bzrlib.workingtree import WorkingTree
        try:
            wt_to = WorkingTree.open(".")
            branch_to = wt_to.branch
        except NoWorkingTree:
            wt_to = None
            branch_to = Branch.open(".")

        stored_loc = branch_to.get_parent()
        if from_repository is None:
            if stored_loc is None:
                raise BzrCommandError("No pull location known or"
                                             " specified.")
            else:
                import bzrlib.urlutils as urlutils
                display_url = urlutils.unescape_for_display(stored_loc,
                        self.outf.encoding)
                self.outf.write("Using saved location: %s\n" % display_url)
                from_repository = Branch.open(stored_loc).repository
        else:
            from_repository = Repository.open(from_repository)

        if wt_to is not None:
            renames = upgrade_workingtree(wt_to, from_repository, 
                                          allow_changes=True, verbose=verbose)
        else:
            renames = upgrade_branch(branch_to, from_repository, 
                                     allow_changes=True, verbose=verbose)

        if renames == {}:
            info("Nothing to do.")

        if wt_to is not None:
            wt_to.set_last_revision(branch_to.last_revision())

register_command(cmd_svn_upgrade)

class cmd_svn_push(Command):
    """Push revisions to Subversion, creating a new branch if necessary.

    The behaviour of this command is the same as that of "bzr push", except 
    that it also creates new branches.
    
    This command is experimental and will be removed in the future when all 
    functionality is included in "bzr push".
    """
    takes_args = ['location?']
    takes_options = ['revision', 'remember', Option('directory',
            help='Branch to push from, '
                 'rather than the one containing the working directory.',
            short_name='d',
            type=unicode,
            )]

    def run(self, location=None, revision=None, remember=False, 
            directory=None):
        from bzrlib.bzrdir import BzrDir
        from bzrlib.branch import Branch
        from bzrlib.errors import NotBranchError, BzrCommandError
        from bzrlib import urlutils

        if directory is None:
            directory = "."
        source_branch = Branch.open_containing(directory)[0]
        stored_loc = source_branch.get_push_location()
        if location is None:
            if stored_loc is None:
                raise BzrCommandError("No push location known or specified.")
            else:
                display_url = urlutils.unescape_for_display(stored_loc,
                        self.outf.encoding)
                self.outf.write("Using saved location: %s\n" % display_url)
                location = stored_loc

        bzrdir = BzrDir.open(location)
        if revision is not None:
            if len(revision) > 1:
                raise BzrCommandError(
                    'bzr svn-push --revision takes exactly one revision' 
                    ' identifier')
            revision_id = revision[0].in_history(source_branch).rev_id
        else:
            revision_id = None
        try:
            target_branch = bzrdir.open_branch()
            target_branch.pull(source_branch, revision_id)
        except NotBranchError:
            target_branch = bzrdir.import_branch(source_branch, revision_id)
        # We successfully created the target, remember it
        if source_branch.get_push_location() is None or remember:
            source_branch.set_push_location(target_branch.base)

register_command(cmd_svn_push)


class cmd_svn_branching_scheme(Command):
    """Show or change the branching scheme for a Subversion repository.

    See 'bzr help svn-branching-schemes' for details.
    """
    takes_args = ['location?']
    takes_options = [
        Option('set', help="Change the branching scheme. "),
        Option('repository-wide', 
            help="Act on repository-wide setting rather than local.")
        ]

    def run(self, location=".", set=False, repository_wide=False):
        from bzrlib.bzrdir import BzrDir
        from bzrlib.errors import BzrCommandError
        from bzrlib.msgeditor import edit_commit_message
        from bzrlib.repository import Repository
        from bzrlib.trace import info
        from repository import SvnRepository
        from scheme import scheme_from_branch_list
        def scheme_str(scheme):
            if scheme is None:
                return ""
            return "".join(map(lambda x: x+"\n", scheme.to_lines()))
        dir = BzrDir.open_containing(location)[0]
        repos = dir.find_repository()
        if not isinstance(repos, SvnRepository):
            raise BzrCommandError("Not a Subversion repository: %s" % location)
        if repository_wide:
            scheme = repos._get_property_scheme()
        else:
            scheme = repos.get_scheme()
        if set:
            schemestr = edit_commit_message("", 
                                            start_message=scheme_str(scheme))
            scheme = scheme_from_branch_list(
                map(lambda x:x.strip("\n"), schemestr.splitlines()))
            if repository_wide:
                repos.set_property_scheme(scheme)
            else:
                repos.set_branching_scheme(scheme, mandatory=True)
        elif scheme is not None:
            info(scheme_str(scheme))


register_command(cmd_svn_branching_scheme)


class cmd_svn_set_revprops(Command):
    """Migrate Bazaar metadata to Subversion revision properties.

    This requires that you have permission to change the 
    revision properties on the repository.

    To change these permissions, edit the hooks/pre-revprop-change 
    file in the Subversion repository.
    """
    takes_args = ['location']

    def run(self, location="."):
        raise NotImplementedError(self.run)


register_command(cmd_svn_set_revprops)


def test_suite():
    """Returns the testsuite for bzr-svn."""
    from unittest import TestSuite
    import tests
    suite = TestSuite()
    suite.addTest(tests.test_suite())
    return suite


if __name__ == '__main__':
    print ("This is a Bazaar plugin. Copy this directory to ~/.bazaar/plugins "
          "to use it.\n")
elif __name__ != 'bzrlib.plugins.svn':
    raise ImportError('The Subversion plugin must be installed as'
                      ' bzrlib.plugins.svn not %s' % __name__)
else:
    import os, sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
