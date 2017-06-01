# Copyright (C) 2006-2009 Canonical Ltd

# Authors: Robert Collins <robert.collins@canonical.com>
#          Jelmer Vernooij <jelmer@samba.org>
#          John Carr <john.carr@unrouted.co.uk>
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

"""Git-specific subcommands for Bazaar."""

from __future__ import absolute_import

from ...commands import (
    Command,
    display_command,
    )
from ...option import (
    Option,
    )


class cmd_git_import(Command):
    """Import all branches from a git repository.

    """

    takes_args = ["src_location", "dest_location?"]

    takes_options = [
                     Option('colocated', help='Create colocated branches.'),
                     ]

    def _get_colocated_branch(self, target_bzrdir, name):
        from bzrlib.errors import NotBranchError
        try:
            return target_bzrdir.open_branch(name=name)
        except NotBranchError:
            return target_bzrdir.create_branch(name=name)

    def _get_nested_branch(self, dest_transport, dest_format, name):
        from bzrlib.bzrdir import BzrDir
        from bzrlib.errors import NotBranchError
        head_transport = dest_transport.clone(name)
        try:
            head_bzrdir = BzrDir.open_from_transport(head_transport)
        except NotBranchError:
            head_bzrdir = dest_format.initialize_on_transport_ex(
                head_transport, create_prefix=True)[1]
        try:
            return head_bzrdir.open_branch()
        except NotBranchError:
            return head_bzrdir.create_branch()

    def run(self, src_location, dest_location=None, colocated=False):
        import os
        import urllib
        from bzrlib import (
            controldir,
            trace,
            ui,
            urlutils,
            )
        from bzrlib.bzrdir import (
            BzrDir,
            )
        from bzrlib.errors import (
            BzrCommandError,
            NoRepositoryPresent,
            NotBranchError,
            )
        from bzrlib.plugins.git import gettext
        from bzrlib.repository import (
            InterRepository,
            Repository,
            )
        from bzrlib.transport import get_transport
        from bzrlib.plugins.git.branch import (
            GitBranch,
            )
        from bzrlib.plugins.git.refs import (
            ref_to_branch_name,
            )
        from bzrlib.plugins.git.repository import GitRepository

        dest_format = controldir.ControlDirFormat.get_default_format()

        if dest_location is None:
            dest_location = os.path.basename(src_location.rstrip("/\\"))

        dest_transport = get_transport(dest_location)

        source_repo = Repository.open(src_location)
        if not isinstance(source_repo, GitRepository):
            raise BzrCommandError(gettext("%r is not a git repository") % src_location)
        try:
            target_bzrdir = BzrDir.open_from_transport(dest_transport)
        except NotBranchError:
            target_bzrdir = dest_format.initialize_on_transport_ex(
                dest_transport, shared_repo=True)[1]
        try:
            target_repo = target_bzrdir.find_repository()
        except NoRepositoryPresent:
            target_repo = target_bzrdir.create_repository(shared=True)

        if not target_repo.supports_rich_root():
            raise BzrCommandError(gettext("Target repository doesn't support rich roots"))

        interrepo = InterRepository.get(source_repo, target_repo)
        mapping = source_repo.get_mapping()
        refs = interrepo.fetch()
        refs_dict = refs.as_dict()
        pb = ui.ui_factory.nested_progress_bar()
        try:
            for i, (name, sha) in enumerate(refs_dict.iteritems()):
                try:
                    branch_name = ref_to_branch_name(name)
                except ValueError:
                    # Not a branch, ignore
                    continue
                pb.update(gettext("creating branches"), i, len(refs_dict))
                if getattr(target_bzrdir._format, "colocated_branches", False) and colocated:
                    if name == "HEAD":
                        branch_name = None
                    head_branch = self._get_colocated_branch(target_bzrdir, branch_name)
                else:
                    head_branch = self._get_nested_branch(dest_transport, dest_format, branch_name)
                revid = mapping.revision_id_foreign_to_bzr(sha)
                source_branch = GitBranch(source_repo.bzrdir, source_repo,
                    sha)
                source_branch.head = sha
                if head_branch.last_revision() != revid:
                    head_branch.generate_revision_history(revid)
                source_branch.tags.merge_to(head_branch.tags)
                if not head_branch.get_parent():
                    url = urlutils.join_segment_parameters(
                        source_branch.base, {"ref": urllib.quote(name, '')})
                    head_branch.set_parent(url)
        finally:
            pb.finished()
        trace.note(gettext(
            "Use 'bzr checkout' to create a working tree in "
            "the newly created branches."))


class cmd_git_object(Command):
    """List or display Git objects by SHA.

    Cat a particular object's Git representation if a SHA is specified.
    List all available SHAs otherwise.
    """

    hidden = True

    aliases = ["git-objects", "git-cat"]
    takes_args = ["sha1?"]
    takes_options = [Option('directory',
        short_name='d',
        help='Location of repository.', type=unicode),
        Option('pretty', help='Pretty-print objects.')]
    encoding_type = 'exact'

    @display_command
    def run(self, sha1=None, directory=".", pretty=False):
        from bzrlib.errors import (
            BzrCommandError,
            )
        from bzrlib.bzrdir import (
            BzrDir,
            )
        from bzrlib.plugins.git.object_store import (
            get_object_store,
            )
        from bzrlib.plugins.git import gettext
        bzrdir, _ = BzrDir.open_containing(directory)
        repo = bzrdir.find_repository()
        object_store = get_object_store(repo)
        object_store.lock_read()
        try:
            if sha1 is not None:
                try:
                    obj = object_store[str(sha1)]
                except KeyError:
                    raise BzrCommandError(gettext("Object not found: %s") % sha1)
                if pretty:
                    text = obj.as_pretty_string()
                else:
                    text = obj.as_raw_string()
                self.outf.write(text)
            else:
                for sha1 in object_store:
                    self.outf.write("%s\n" % sha1)
        finally:
            object_store.unlock()


class cmd_git_refs(Command):
    """Output all of the virtual refs for a repository.

    """

    hidden = True

    takes_args = ["location?"]

    @display_command
    def run(self, location="."):
        from bzrlib.bzrdir import (
            BzrDir,
            )
        from bzrlib.plugins.git.refs import (
            get_refs_container,
            )
        from bzrlib.plugins.git.object_store import (
            get_object_store,
            )
        bzrdir, _ = BzrDir.open_containing(location)
        repo = bzrdir.find_repository()
        object_store = get_object_store(repo)
        object_store.lock_read()
        try:
            refs = get_refs_container(bzrdir, object_store)
            for k, v in refs.as_dict().iteritems():
                self.outf.write("%s -> %s\n" % (k, v))
        finally:
            object_store.unlock()


class cmd_git_apply(Command):
    """Apply a series of git-am style patches.

    This command will in the future probably be integrated into 
    "bzr pull".
    """

    takes_options = [
        Option('signoff', short_name='s', help='Add a Signed-off-by line.'),
        Option('force',
            help='Apply patches even if tree has uncommitted changes.')
        ]
    takes_args = ["patches*"]

    def _apply_patch(self, wt, f, signoff):
        """Apply a patch.

        :param wt: A Bazaar working tree object.
        :param f: Patch file to read.
        :param signoff: Add Signed-Off-By flag.
        """
        from bzrlib.plugins.git import gettext
        from bzrlib.errors import BzrCommandError
        from dulwich.patch import git_am_patch_split
        import subprocess
        (c, diff, version) = git_am_patch_split(f)
        # FIXME: Cope with git-specific bits in patch
        # FIXME: Add new files to working tree
        p = subprocess.Popen(["patch", "-p1"], stdin=subprocess.PIPE,
            cwd=wt.basedir)
        p.communicate(diff)
        exitcode = p.wait()
        if exitcode != 0:
            raise BzrCommandError(gettext("error running patch"))
        message = c.message
        if signoff:
            signed_off_by = wt.branch.get_config().username()
            message += "Signed-off-by: %s\n" % signed_off_by.encode('utf-8')
        wt.commit(authors=[c.author], message=message)

    def run(self, patches_list=None, signoff=False, force=False):
        from bzrlib.errors import UncommittedChanges
        from bzrlib.workingtree import WorkingTree
        if patches_list is None:
            patches_list = []

        tree, _ = WorkingTree.open_containing(".")
        if tree.basis_tree().changes_from(tree).has_changed() and not force:
            raise UncommittedChanges(tree)
        tree.lock_write()
        try:
            for patch in patches_list:
                f = open(patch, 'r')
                try:
                    self._apply_patch(tree, f, signoff=signoff)
                finally:
                    f.close()
        finally:
            tree.unlock()


class cmd_git_push_pristine_tar_deltas(Command):
    """Push pristine tar deltas to a git repository."""

    takes_options = [Option('directory',
        short_name='d',
        help='Location of repository.', type=unicode)]
    takes_args = ['target', 'package']

    def run(self, target, package, directory='.'):
        from bzrlib.branch import Branch
        from bzrlib.errors import (
            BzrCommandError,
            NoSuchRevision,
            )
        from bzrlib.trace import warning
        from bzrlib.repository import Repository
        from bzrlib.plugins.git.object_store import get_object_store
        from bzrlib.plugins.git.pristine_tar import (
            revision_pristine_tar_data,
            store_git_pristine_tar_data,
            )
        source = Branch.open_containing(directory)[0]
        target_bzr = Repository.open(target)
        target = getattr(target_bzr, '_git', None)
        git_store = get_object_store(source.repository)
        self.add_cleanup(git_store.unlock)
        git_store.lock_read()
        if target is None:
            raise BzrCommandError("Target not a git repository")
        tag_dict = source.tags.get_tag_dict()
        for name, revid in tag_dict.iteritems():
            try:
                rev = source.repository.get_revision(revid)
            except NoSuchRevision:
                continue
            try:
                delta, kind = revision_pristine_tar_data(rev)
            except KeyError:
                continue
            gitid = git_store._lookup_revision_sha1(revid)
            if not (name.startswith('upstream/') or name.startswith('upstream-')):
                warning("Unexpected pristine tar revision tagged %s. Ignoring.",
                     name)
                continue
            upstream_version = name[len("upstream/"):]
            filename = '%s_%s.orig.tar.%s' % (package, upstream_version, kind)
            if not gitid in target:
                warning("base git id %s for %s missing in target repository",
                        gitid, filename)
            store_git_pristine_tar_data(target, filename.encode('utf-8'),
                delta, gitid)
