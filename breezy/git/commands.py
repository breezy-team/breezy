# Copyright (C) 2006-2009 Canonical Ltd
# Copyright (C) 2012-2018 Jelmer Vernooij <jelmer@jelmer.uk>

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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Git-specific subcommands for Bazaar."""

import breezy.bzr  # noqa: F401
from breezy import controldir

from ..commands import Command, display_command
from ..option import Option, RegistryOption


class cmd_git_import(Command):
    """Import all branches from a git repository."""

    takes_args = ["src_location", "dest_location?"]

    takes_options = [
        Option("colocated", help="Create colocated branches."),
        RegistryOption(
            "dest-format",
            help="Specify a format for this branch. "
            'See "help formats" for a full list.',
            lazy_registry=("breezy.controldir", "format_registry"),
            converter=lambda name: controldir.format_registry.make_controldir(name),
            value_switches=True,
            title="Branch format",
        ),
    ]

    def _get_colocated_branch(self, target_controldir, name):
        from ..errors import NotBranchError

        try:
            return target_controldir.open_branch(name=name)
        except NotBranchError:
            return target_controldir.create_branch(name=name)

    def _get_nested_branch(self, dest_transport, dest_format, name):
        from ..controldir import ControlDir
        from ..errors import NotBranchError

        head_transport = dest_transport.clone(name)
        try:
            head_controldir = ControlDir.open_from_transport(head_transport)
        except NotBranchError:
            head_controldir = dest_format.initialize_on_transport_ex(
                head_transport, create_prefix=True
            )[1]
        try:
            return head_controldir.open_branch()
        except NotBranchError:
            return head_controldir.create_branch()

    def run(self, src_location, dest_location=None, colocated=False, dest_format=None):
        """Import all branches from a git repository.

        Args:
            src_location: Source git repository location.
            dest_location: Optional destination location (defaults to basename of source).
            colocated: Whether to create colocated branches.
            dest_format: Optional destination format.
        """
        import os

        from .. import controldir, trace, ui, urlutils
        from ..controldir import ControlDir
        from ..errors import CommandError, NoRepositoryPresent, NotBranchError
        from ..i18n import gettext
        from ..repository import InterRepository, Repository
        from ..transport import get_transport
        from .branch import LocalGitBranch
        from .refs import ref_to_branch_name
        from .repository import GitRepository

        if dest_format is None:
            dest_format = controldir.format_registry.make_controldir("default")

        if dest_location is None:
            dest_location = os.path.basename(src_location.rstrip("/\\"))

        dest_transport = get_transport(dest_location)

        source_repo = Repository.open(src_location)
        if not isinstance(source_repo, GitRepository):
            raise CommandError(gettext("%r is not a git repository") % src_location)
        try:
            target_controldir = ControlDir.open_from_transport(dest_transport)
        except NotBranchError:
            target_controldir = dest_format.initialize_on_transport_ex(
                dest_transport, shared_repo=True
            )[1]
        try:
            target_repo = target_controldir.find_repository()
        except NoRepositoryPresent:
            target_repo = target_controldir.create_repository(shared=True)

        if not target_repo.supports_rich_root():
            raise CommandError(gettext("Target repository doesn't support rich roots"))

        interrepo = InterRepository.get(source_repo, target_repo)
        mapping = source_repo.get_mapping()
        result = interrepo.fetch()
        with ui.ui_factory.nested_progress_bar() as pb:
            for i, (name, sha) in enumerate(result.refs.items()):
                try:
                    branch_name = ref_to_branch_name(name)
                except ValueError:
                    # Not a branch, ignore
                    continue
                pb.update(gettext("creating branches"), i, len(result.refs))
                if (
                    getattr(target_controldir._format, "colocated_branches", False)
                    and colocated
                ):
                    if name == "HEAD":
                        branch_name = None
                    head_branch = self._get_colocated_branch(
                        target_controldir, branch_name
                    )
                else:
                    head_branch = self._get_nested_branch(
                        dest_transport, dest_format, branch_name
                    )
                revid = mapping.revision_id_foreign_to_bzr(sha)
                source_branch = LocalGitBranch(source_repo.controldir, source_repo, sha)
                if head_branch.last_revision() != revid:
                    head_branch.generate_revision_history(revid)
                source_branch.tags.merge_to(head_branch.tags)
                if not head_branch.get_parent():
                    url = urlutils.join_segment_parameters(
                        source_branch.base, {"branch": urlutils.escape(branch_name)}
                    )
                    head_branch.set_parent(url)
        trace.note(
            gettext(
                "Use 'bzr checkout' to create a working tree in "
                "the newly created branches."
            )
        )


class cmd_git_object(Command):
    """List or display Git objects by SHA.

    Cat a particular object's Git representation if a SHA is specified.
    List all available SHAs otherwise.
    """

    hidden = True

    aliases = ["git-objects", "git-cat"]
    takes_args = ["sha1?"]
    takes_options = [
        Option("directory", short_name="d", help="Location of repository.", type=str),
        Option("pretty", help="Pretty-print objects."),
    ]
    encoding_type = "exact"

    @display_command
    def run(self, sha1=None, directory=".", pretty=False):
        """List or display Git objects.

        Args:
            sha1: Optional SHA1 to display (lists all if not provided).
            directory: Repository location (defaults to current directory).
            pretty: Whether to pretty-print objects.
        """
        from ..controldir import ControlDir
        from ..errors import CommandError
        from ..i18n import gettext
        from .object_store import get_object_store

        controldir, _ = ControlDir.open_containing(directory)
        repo = controldir.find_repository()
        object_store = get_object_store(repo)
        with object_store.lock_read():
            if sha1 is not None:
                try:
                    obj = object_store[sha1.encode("ascii")]
                except KeyError as err:
                    raise CommandError(gettext("Object not found: %s") % sha1) from err
                text = obj.as_pretty_string() if pretty else obj.as_raw_string()
                self.outf.write(text)
            else:
                for sha1 in object_store:
                    self.outf.write(f"{sha1.decode('ascii')}\n")


class cmd_git_refs(Command):
    """Output all of the virtual refs for a repository."""

    hidden = True

    takes_args = ["location?"]

    @display_command
    def run(self, location="."):
        """Output all virtual refs for a repository.

        Args:
            location: Repository location (defaults to current directory).
        """
        from ..controldir import ControlDir
        from .object_store import get_object_store
        from .refs import get_refs_container

        controldir, _ = ControlDir.open_containing(location)
        repo = controldir.find_repository()
        object_store = get_object_store(repo)
        with object_store.lock_read():
            refs = get_refs_container(controldir, object_store)
            for k, v in sorted(refs.as_dict().items()):
                self.outf.write(f"{k.decode('utf-8')} -> {v.decode('utf-8')}\n")


class cmd_git_apply(Command):
    """Apply a series of git-am style patches.

    This command will in the future probably be integrated into "bzr pull".
    """

    takes_options = [
        Option("signoff", short_name="s", help="Add a Signed-off-by line."),
        Option("force", help="Apply patches even if tree has uncommitted changes."),
    ]
    takes_args = ["patches*"]

    def _apply_patch(self, wt, f, signoff):
        """Apply a patch.

        :param wt: A Bazaar working tree object.
        :param f: Patch file to read.
        :param signoff: Add Signed-Off-By flag.
        """
        from dulwich.patch import git_am_patch_split

        from ..workingtree import patch_tree

        (c, diff, version) = git_am_patch_split(f)
        # FIXME: Cope with git-specific bits in patch
        # FIXME: Add new files to working tree
        from io import BytesIO

        b = BytesIO()
        patch_tree(wt, [diff], strip=1, out=b)
        self.outf.write(b.getvalue().decode("utf-8", "replace"))
        message = c.message.decode("utf-8")
        if signoff:
            signed_off_by = wt.branch.get_config().username()
            message += f"Signed-off-by: {signed_off_by}\n"
        wt.commit(authors=[c.author.decode("utf-8")], message=message)

    def run(self, patches_list=None, signoff=False, force=False):
        """Apply a series of git-am style patches.

        Args:
            patches_list: List of patch files to apply.
            signoff: Whether to add Signed-off-by line.
            force: Whether to apply patches even with uncommitted changes.
        """
        from ..errors import UncommittedChanges
        from ..workingtree import WorkingTree

        if patches_list is None:
            patches_list = []

        tree, _ = WorkingTree.open_containing(".")
        if tree.basis_tree().changes_from(tree).has_changed() and not force:
            raise UncommittedChanges(tree)
        with tree.lock_write():
            for patch in patches_list:
                with open(patch) as f:
                    self._apply_patch(tree, f, signoff=signoff)


class cmd_git_push_pristine_tar_deltas(Command):
    """Push pristine tar deltas to a git repository."""

    takes_options = [
        Option("directory", short_name="d", help="Location of repository.", type=str)
    ]
    takes_args = ["target", "package"]

    def run(self, target, package, directory="."):
        """Push pristine tar deltas to a git repository.

        Args:
            target: Target git repository.
            package: Package name for pristine tar files.
            directory: Source repository location (defaults to current directory).
        """
        from ..branch import Branch
        from ..errors import CommandError, NoSuchRevision
        from ..repository import Repository
        from ..trace import warning
        from .mapping import encode_git_path
        from .object_store import get_object_store
        from .pristine_tar import (
            revision_pristine_tar_data,
            store_git_pristine_tar_data,
        )

        source = Branch.open_containing(directory)[0]
        target_bzr = Repository.open(target)
        target = getattr(target_bzr, "_git", None)
        if target is None:
            raise CommandError("Target not a git repository")
        git_store = get_object_store(source.repository)
        with git_store.lock_read():
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
                if not (name.startswith("upstream/") or name.startswith("upstream-")):
                    warning(
                        "Unexpected pristine tar revision tagged %s. Ignoring.", name
                    )
                    continue
                upstream_version = name[len("upstream/") :]
                filename = f"{package}_{upstream_version}.orig.tar.{kind}"
                if gitid not in target:
                    warning(
                        "base git id %s for %s missing in target repository",
                        gitid,
                        filename,
                    )
                store_git_pristine_tar_data(
                    target, encode_git_path(filename), delta, gitid
                )
