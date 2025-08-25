"""Merge directive support for Breezy.

This module provides infrastructure for creating, parsing, and working with
merge directives - structured requests to merge changes between branches.
Merge directives can contain patches, bundles, or references to branches
to facilitate code review and collaboration workflows.
"""

# Copyright (C) 2007-2011 Canonical Ltd
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

import base64
import contextlib
import re
from io import BytesIO
from typing import Optional

from . import lazy_import

lazy_import.lazy_import(
    globals(),
    """
from breezy import (
    diff,
    email_message,
    gpg,
    patch as _mod_patch,
    )
from breezy.bzr import (
    rio_patch,
    )
from breezy.bzr import rio
from breezy.bzr.bundle import (
    serializer as bundle_serializer,
    )
""",
)
from . import branch as _mod_branch
from . import errors, hooks, registry, trace
from . import revision as _mod_revision


class IllegalMergeDirectivePayload(errors.BzrError):
    """A merge directive contained something other than a patch or bundle."""

    _fmt = "Bad merge directive payload %(start)r"

    def __init__(self, start):
        """Initialize IllegalMergeDirectivePayload.

        Args:
            start: The invalid payload content that was encountered.
        """
        errors.BzrError(self)
        self.start = start


class MergeRequestBodyParams:
    """Parameter object for the merge_request_body hook."""

    def __init__(
        self, body, orig_body, directive, to, basename, subject, branch, tree=None
    ):
        """Initialize MergeRequestBodyParams.

        Args:
            body: The processed body text.
            orig_body: The original body text.
            directive: The merge directive.
            to: Email recipient.
            basename: Base name for attachments.
            subject: Email subject line.
            branch: Source branch.
            tree: Source tree (optional).
        """
        self.body = body
        self.orig_body = orig_body
        self.directive = directive
        self.branch = branch
        self.tree = tree
        self.to = to
        self.basename = basename
        self.subject = subject


class MergeDirectiveHooks(hooks.Hooks):
    """Hooks for MergeDirective classes."""

    def __init__(self):
        """Initialize MergeDirectiveHooks."""
        hooks.Hooks.__init__(self, "breezy.merge_directive", "BaseMergeDirective.hooks")
        self.add_hook(
            "merge_request_body",
            "Called with a MergeRequestBodyParams when a body is needed for"
            " a merge request.  Callbacks must return a body.  If more"
            " than one callback is registered, the output of one callback is"
            " provided to the next.",
            (1, 15, 0),
        )


class BaseMergeDirective:
    """A request to perform a merge into a branch.

    This is the base class that all merge directive implementations
    should derive from.

    :cvar multiple_output_files: Whether or not this merge directive
        stores a set of revisions in more than one file
    """

    hooks = MergeDirectiveHooks()

    multiple_output_files = False

    revision_id: _mod_revision.RevisionID
    message: str

    def __init__(
        self,
        revision_id: _mod_revision.RevisionID,
        testament_sha1: bytes,
        time,
        timezone,
        target_branch,
        patch=None,
        source_branch=None,
        message=None,
        bundle=None,
    ):
        """Constructor.

        :param revision_id: The revision to merge
        :param testament_sha1: The sha1 of the testament of the revision to
            merge.
        :param time: The current POSIX timestamp time
        :param timezone: The timezone offset
        :param target_branch: Location of branch to apply the merge to
        :param patch: The text of a diff or bundle
        :param source_branch: A public location to merge the revision from
        :param message: The message to use when committing this merge
        """
        self.revision_id = revision_id
        self.testament_sha1 = testament_sha1
        self.time = time
        self.timezone = timezone
        self.target_branch = target_branch
        self.patch = patch
        self.source_branch = source_branch
        self.message = message

    def to_lines(self):
        """Serialize as a list of lines.

        :return: a list of lines
        """
        raise NotImplementedError(self.to_lines)

    def to_files(self):
        """Serialize as a set of files.

        :return: List of tuples with filename and contents as lines
        """
        raise NotImplementedError(self.to_files)

    def get_raw_bundle(self):
        """Return the bundle for this merge directive.

        :return: bundle text or None if there is no bundle
        """
        return None

    def _to_lines(self, base_revision=False):
        """Serialize as a list of lines.

        :return: a list of lines
        """
        time_str = _mod_patch.format_patch_date(self.time, self.timezone)
        stanza = rio.Stanza(
            revision_id=self.revision_id.decode("utf-8"),
            timestamp=time_str,
            target_branch=self.target_branch,
            testament_sha1=self.testament_sha1.decode("utf-8"),
        )
        for key in ("source_branch", "message"):
            if self.__dict__[key] is not None:
                stanza.add(key, self.__dict__[key])
        if base_revision:
            stanza.add("base_revision_id", self.base_revision_id.decode("utf-8"))
        lines = [b"# " + self._format_string + b"\n"]
        lines.extend(rio_patch.to_patch_lines(stanza))
        lines.append(b"# \n")
        return lines

    def write_to_directory(self, path):
        """Write this merge directive to a series of files in a directory.

        Args:
            path: Filesystem path to write to.
        """
        raise NotImplementedError(self.write_to_directory)

    @classmethod
    def from_objects(
        cls,
        repository,
        revision_id: _mod_revision.RevisionID,
        time,
        timezone,
        target_branch,
        patch_type="bundle",
        local_target_branch=None,
        public_branch=None,
        message=None,
    ):
        """Generate a merge directive from various objects.

        :param repository: The repository containing the revision
        :param revision_id: The revision to merge
        :param time: The POSIX timestamp of the date the request was issued.
        :param timezone: The timezone of the request
        :param target_branch: The url of the branch to merge into
        :param patch_type: 'bundle', 'diff' or None, depending on the type of
            patch desired.
        :param local_target_branch: the submit branch, either itself or a local copy
        :param public_branch: location of a public branch containing
            the target revision.
        :param message: Message to use when committing the merge
        :return: The merge directive

        The public branch is always used if supplied.  If the patch_type is
        not 'bundle', the public branch must be supplied, and will be verified.

        If the message is not supplied, the message from revision_id will be
        used for the commit.
        """
        t_revision_id: Optional[_mod_revision.RevisionID] = revision_id
        if revision_id == _mod_revision.NULL_REVISION:
            t_revision_id = None
        from .bzr.testament import StrictTestament3

        t = StrictTestament3.from_revision(repository, t_revision_id)
        if local_target_branch is None:
            submit_branch = _mod_branch.Branch.open(target_branch)
        else:
            submit_branch = local_target_branch
        if submit_branch.get_public_branch() is not None:
            target_branch = submit_branch.get_public_branch()
        if patch_type is None:
            patch = None
        else:
            submit_revision_id = submit_branch.last_revision()
            repository.fetch(submit_branch.repository, submit_revision_id)
            graph = repository.get_graph()
            ancestor_id = graph.find_unique_lca(revision_id, submit_revision_id)
            type_handler = {
                "bundle": cls._generate_bundle,
                "diff": cls._generate_diff,
                None: lambda x, y, z: None,
            }
            patch = type_handler[patch_type](repository, revision_id, ancestor_id)

        if public_branch is not None and patch_type != "bundle":
            public_branch_obj = _mod_branch.Branch.open(public_branch)
            if not public_branch_obj.repository.has_revision(revision_id):
                raise errors.PublicBranchOutOfDate(public_branch, revision_id)

        return cls(
            revision_id,
            t.as_sha1(),
            time,
            timezone,
            target_branch,
            patch,
            patch_type,
            public_branch,
            message,
        )

    def get_disk_name(self, branch):
        """Generate a suitable basename for storing this directive on disk.

        Args:
            branch: The Branch this merge directive was generated from.

        Returns:
            A string suitable for use as a filename.
        """
        revno, revision_id = branch.last_revision_info()
        if self.revision_id == revision_id:
            revno = [revno]
        else:
            try:
                revno = branch.revision_id_to_dotted_revno(self.revision_id)
            except errors.NoSuchRevision:
                revno = ["merge"]
        nick = re.sub("(\\W+)", "-", branch.nick).strip("-")
        return f"{nick}-{'.'.join(str(n) for n in revno)}"

    @staticmethod
    def _generate_diff(repository, revision_id, ancestor_id):
        """Generate a diff between two revisions.

        Args:
            repository: Repository containing the revisions.
            revision_id: The newer revision.
            ancestor_id: The older revision to diff against.

        Returns:
            Diff content as bytes.
        """
        tree_1 = repository.revision_tree(ancestor_id)
        tree_2 = repository.revision_tree(revision_id)
        s = BytesIO()
        diff.show_diff_trees(tree_1, tree_2, s, old_label="", new_label="")
        return s.getvalue()

    @classmethod
    def _generate_bundle(cls, repository, revision_id, ancestor_id):
        """Generate a bundle between two revisions.

        Args:
            repository: Repository containing the revisions.
            revision_id: The newer revision.
            ancestor_id: The older revision to use as base.

        Returns:
            Bundle content as bytes.
        """
        s = BytesIO()
        bundle_serializer.write_bundle(repository, revision_id, ancestor_id, s)
        return s.getvalue()

    def to_signed(self, branch):
        """Serialize as a signed string.

        Args:
            branch: The source branch, to get the signing strategy.

        Returns:
            A signed string representation.
        """
        my_gpg = gpg.GPGStrategy(branch.get_config_stack())
        return my_gpg.sign(b"".join(self.to_lines()), gpg.MODE_CLEAR)

    def to_email(self, mail_to, branch, sign=False):
        """Serialize as an email message.

        Args:
            mail_to: The address to mail the message to.
            branch: The source branch, to get signing strategy and source email.
            sign: If True, gpg-sign the email.

        Returns:
            An email message object.
        """
        mail_from = branch.get_config_stack().get("email")
        if self.message is not None:
            subject = self.message
        else:
            revision = branch.repository.get_revision(self.revision_id)
            subject = revision.message
        body = self.to_signed(branch) if sign else b"".join(self.to_lines())
        message = email_message.EmailMessage(mail_from, mail_to, subject, body)
        return message

    def install_revisions(self, target_repo):
        """Install revisions and return the target revision.

        Args:
            target_repo: Repository to install revisions into.

        Returns:
            The revision ID that was installed.
        """
        if not target_repo.has_revision(self.revision_id):
            if self.patch_type == "bundle":
                info = bundle_serializer.read_bundle(BytesIO(self.get_raw_bundle()))
                # We don't use the bundle's target revision, because
                # MergeDirective.revision_id is authoritative.
                try:
                    info.install_revisions(target_repo, stream_input=False)
                except errors.RevisionNotPresent:
                    # At least one dependency isn't present.  Try installing
                    # missing revisions from the submit branch
                    try:
                        submit_branch = _mod_branch.Branch.open(self.target_branch)
                    except errors.NotBranchError as e:
                        raise errors.TargetNotBranch(self.target_branch) from e
                    missing_revisions = []
                    bundle_revisions = {r.revision_id for r in info.real_revisions}
                    for revision in info.real_revisions:
                        for parent_id in revision.parent_ids:
                            if (
                                parent_id not in bundle_revisions
                                and not target_repo.has_revision(parent_id)
                            ):
                                missing_revisions.append(parent_id)
                    # reverse missing revisions to try to get heads first
                    unique_missing = []
                    unique_missing_set = set()
                    for revision in reversed(missing_revisions):
                        if revision in unique_missing_set:
                            continue
                        unique_missing.append(revision)
                        unique_missing_set.add(revision)
                    for missing_revision in unique_missing:
                        target_repo.fetch(submit_branch.repository, missing_revision)
                    info.install_revisions(target_repo, stream_input=False)
            else:
                source_branch = _mod_branch.Branch.open(self.source_branch)
                target_repo.fetch(source_branch.repository, self.revision_id)
        return self.revision_id

    def compose_merge_request(self, mail_client, to, body, branch, tree=None):
        """Compose a request to merge this directive.

        Args:
            mail_client: The mail client to use for composing this request.
            to: The address to compose the request to.
            body: Body text for the request.
            branch: The Branch that was used to produce this directive.
            tree: The Tree (if any) for the Branch used to produce this directive.
        """
        basename = self.get_disk_name(branch)
        subject = "[MERGE] "
        if self.message is not None:
            subject += self.message
        else:
            revision = branch.repository.get_revision(self.revision_id)
            subject += revision.get_summary()
        if getattr(mail_client, "supports_body", False):
            orig_body = body
            for hook in self.hooks["merge_request_body"]:
                params = MergeRequestBodyParams(
                    body, orig_body, self, to, basename, subject, branch, tree
                )
                body = hook(params)
        elif len(self.hooks["merge_request_body"]) > 0:
            trace.warning(
                "Cannot run merge_request_body hooks because mail"
                " client %s does not support message bodies.",
                mail_client.__class__.__name__,
            )
        mail_client.compose_merge_request(
            to, subject, b"".join(self.to_lines()), basename, body
        )


class MergeDirective(BaseMergeDirective):
    """A request to perform a merge into a branch.

    Designed to be serialized and mailed.  It provides all the information
    needed to perform a merge automatically, by providing at minimum a revision
    bundle or the location of a branch.

    The serialization format is robust against certain common forms of
    deterioration caused by mailing.

    The format is also designed to be patch-compatible.  If the directive
    includes a diff or revision bundle, it should be possible to apply it
    directly using the standard patch program.
    """

    _format_string = b"Bazaar merge directive format 1"

    def __init__(
        self,
        revision_id,
        testament_sha1,
        time,
        timezone,
        target_branch,
        patch=None,
        patch_type=None,
        source_branch=None,
        message=None,
        bundle=None,
    ):
        """Constructor.

        :param revision_id: The revision to merge
        :param testament_sha1: The sha1 of the testament of the revision to
            merge.
        :param time: The current POSIX timestamp time
        :param timezone: The timezone offset
        :param target_branch: Location of the branch to apply the merge to
        :param patch: The text of a diff or bundle
        :param patch_type: None, "diff" or "bundle", depending on the contents
            of patch
        :param source_branch: A public location to merge the revision from
        :param message: The message to use when committing this merge
        """
        BaseMergeDirective.__init__(
            self,
            revision_id=revision_id,
            testament_sha1=testament_sha1,
            time=time,
            timezone=timezone,
            target_branch=target_branch,
            patch=patch,
            source_branch=source_branch,
            message=message,
        )
        if patch_type not in (None, "diff", "bundle"):
            raise ValueError(patch_type)
        if patch_type != "bundle" and source_branch is None:
            raise errors.NoMergeSource()
        if patch_type is not None and patch is None:
            raise errors.PatchMissing(patch_type)
        self.patch_type = patch_type

    def clear_payload(self):
        """Clear the patch payload from this directive."""
        self.patch = None
        self.patch_type = None

    def get_raw_bundle(self):
        """Return the raw bundle data for this directive."""
        return self.bundle

    def _bundle(self):
        """Return bundle data if this directive contains a bundle."""
        if self.patch_type == "bundle":
            return self.patch
        else:
            return None

    bundle = property(_bundle)

    @classmethod
    def from_lines(cls, lines):
        """Deserialize a MergeRequest from an iterable of lines.

        :param lines: An iterable of lines
        :return: a MergeRequest
        """
        line_iter = iter(lines)
        firstline = b""
        for line in line_iter:
            if line.startswith(b"# Bazaar merge directive format "):
                return _format_registry.get(line[2:].rstrip())._from_lines(line_iter)
            firstline = firstline or line.strip()
        raise errors.NotAMergeDirective(firstline)

    @classmethod
    def _from_lines(cls, line_iter):
        stanza = rio_patch.read_patch_stanza(line_iter)
        patch_lines = list(line_iter)
        if len(patch_lines) == 0:
            patch = None
            patch_type = None
        else:
            patch = b"".join(patch_lines)
            try:
                bundle_serializer.read_bundle(BytesIO(patch))
            except (errors.NotABundle, errors.BundleNotSupported, errors.BadBundle):
                patch_type = "diff"
            else:
                patch_type = "bundle"
        time, timezone = _mod_patch.parse_patch_date(stanza.get("timestamp"))
        kwargs = {}
        for key in (
            "revision_id",
            "testament_sha1",
            "target_branch",
            "source_branch",
            "message",
        ):
            with contextlib.suppress(KeyError):
                kwargs[key] = stanza.get(key)
        kwargs["revision_id"] = kwargs["revision_id"].encode("utf-8")
        if "testament_sha1" in kwargs:
            kwargs["testament_sha1"] = kwargs["testament_sha1"].encode("ascii")
        return MergeDirective(
            time=time, timezone=timezone, patch_type=patch_type, patch=patch, **kwargs
        )

    def to_lines(self):
        """Serialize this merge directive as lines.

        Returns:
            List of byte strings representing the serialized directive.
        """
        lines = self._to_lines()
        if self.patch is not None:
            lines.extend(self.patch.splitlines(True))
        return lines

    @classmethod
    def _generate_bundle(
        cls, repository, revision_id: _mod_revision.RevisionID, ancestor_id
    ):
        s = BytesIO()
        bundle_serializer.write_bundle(repository, revision_id, ancestor_id, s, "0.9")  # type: ignore
        return s.getvalue()

    def get_merge_request(self, repository):
        """Provide data for performing a merge.

        Args:
            repository: Repository to use for merge operations.

        Returns:
            Tuple of (suggested_base, suggested_target, patch_verification_status).
        """
        return None, self.revision_id, "inapplicable"


class MergeDirective2(BaseMergeDirective):
    """Version 2 merge directive format supporting separate patches and bundles."""

    _format_string = b"Bazaar merge directive format 2 (Bazaar 0.90)"

    def __init__(
        self,
        *,
        revision_id,
        testament_sha1,
        time,
        timezone,
        target_branch,
        patch=None,
        source_branch=None,
        message=None,
        bundle=None,
        base_revision_id=None,
    ):
        """Initialize MergeDirective2.

        Args:
            revision_id: The revision to merge.
            testament_sha1: SHA1 of the testament.
            time: Timestamp of the directive.
            timezone: Timezone of the directive.
            target_branch: Target branch URL.
            patch: Patch content (optional).
            source_branch: Source branch URL (optional).
            message: Commit message (optional).
            bundle: Bundle content (optional).
            base_revision_id: Base revision for the patch (optional).
        """
        if source_branch is None and bundle is None:
            raise errors.NoMergeSource()
        BaseMergeDirective.__init__(
            self,
            revision_id=revision_id,
            testament_sha1=testament_sha1,
            time=time,
            timezone=timezone,
            target_branch=target_branch,
            patch=patch,
            source_branch=source_branch,
            message=message,
        )
        self.bundle = bundle
        self.base_revision_id = base_revision_id

    def _patch_type(self):
        if self.bundle is not None:
            return "bundle"
        elif self.patch is not None:
            return "diff"
        else:
            return None

    patch_type = property(_patch_type)

    def clear_payload(self):
        """Clear the patch and bundle payload from this directive."""
        self.patch = None
        self.bundle = None

    def get_raw_bundle(self):
        """Return the decoded raw bundle data for this directive."""
        if self.bundle is None:
            return None
        else:
            return base64.b64decode(self.bundle)

    @classmethod
    def _from_lines(cls, line_iter):
        stanza = rio_patch.read_patch_stanza(line_iter)
        patch = None
        bundle = None
        try:
            start = next(line_iter)
        except StopIteration:
            pass
        else:
            if start.startswith(b"# Begin patch"):
                patch_lines = []
                for line in line_iter:
                    if line.startswith(b"# Begin bundle"):
                        start = line
                        break
                    patch_lines.append(line)
                else:
                    start = None
                patch = b"".join(patch_lines)
            if start is not None:
                if start.startswith(b"# Begin bundle"):
                    bundle = b"".join(line_iter)
                else:
                    raise IllegalMergeDirectivePayload(start)
        time, timezone = _mod_patch.parse_patch_date(stanza.get("timestamp"))
        kwargs = {}
        for key in (
            "revision_id",
            "testament_sha1",
            "target_branch",
            "source_branch",
            "message",
            "base_revision_id",
        ):
            with contextlib.suppress(KeyError):
                kwargs[key] = stanza.get(key)
        kwargs["revision_id"] = kwargs["revision_id"].encode("utf-8")
        kwargs["base_revision_id"] = kwargs["base_revision_id"].encode("utf-8")
        if "testament_sha1" in kwargs:
            kwargs["testament_sha1"] = kwargs["testament_sha1"].encode("ascii")
        return cls(time=time, timezone=timezone, patch=patch, bundle=bundle, **kwargs)

    def to_lines(self):
        """Serialize this merge directive as lines.

        Returns:
            List of byte strings representing the serialized directive.
        """
        lines = self._to_lines(base_revision=True)
        if self.patch is not None:
            lines.append(b"# Begin patch\n")
            lines.extend(self.patch.splitlines(True))
        if self.bundle is not None:
            lines.append(b"# Begin bundle\n")
            lines.extend(self.bundle.splitlines(True))
        return lines

    @classmethod
    def from_objects(
        cls,
        *,
        repository,
        revision_id,
        time,
        timezone,
        target_branch,
        include_patch=True,
        include_bundle=True,
        local_target_branch=None,
        public_branch=None,
        message=None,
        base_revision_id=None,
    ):
        """Generate a merge directive from various objects.

        :param repository: The repository containing the revision
        :param revision_id: The revision to merge
        :param time: The POSIX timestamp of the date the request was issued.
        :param timezone: The timezone of the request
        :param target_branch: The url of the branch to merge into
        :param include_patch: If true, include a preview patch
        :param include_bundle: If true, include a bundle
        :param local_target_branch: the target branch, either itself or a local copy
        :param public_branch: location of a public branch containing
            the target revision.
        :param message: Message to use when committing the merge
        :return: The merge directive

        The public branch is always used if supplied.  If no bundle is
        included, the public branch must be supplied, and will be verified.

        If the message is not supplied, the message from revision_id will be
        used for the commit.
        """
        with contextlib.ExitStack() as exit_stack:
            exit_stack.enter_context(repository.lock_write())
            t_revision_id = revision_id
            if revision_id == b"null:":
                t_revision_id = None
            from .bzr.testament import StrictTestament3

            t = StrictTestament3.from_revision(repository, t_revision_id)
            if local_target_branch is None:
                submit_branch = _mod_branch.Branch.open(target_branch)
            else:
                submit_branch = local_target_branch
            exit_stack.enter_context(submit_branch.lock_read())
            if submit_branch.get_public_branch() is not None:
                target_branch = submit_branch.get_public_branch()
            submit_revision_id = submit_branch.last_revision()
            graph = repository.get_graph(submit_branch.repository)
            ancestor_id = graph.find_unique_lca(revision_id, submit_revision_id)
            if base_revision_id is None:
                base_revision_id = ancestor_id
            if (include_patch, include_bundle) != (False, False):
                repository.fetch(submit_branch.repository, submit_revision_id)
            if include_patch:
                patch = cls._generate_diff(repository, revision_id, base_revision_id)
            else:
                patch = None

            if include_bundle:
                bundle = base64.b64encode(
                    cls._generate_bundle(repository, revision_id, ancestor_id)
                )
            else:
                bundle = None

            if public_branch is not None and not include_bundle:
                public_branch_obj = _mod_branch.Branch.open(public_branch)
                exit_stack.enter_context(public_branch_obj.lock_read())
                if not public_branch_obj.repository.has_revision(revision_id):
                    raise errors.PublicBranchOutOfDate(public_branch, revision_id)
            testament_sha1 = t.as_sha1()
        return cls(
            revision_id=revision_id,
            testament_sha1=testament_sha1,
            time=time,
            timezone=timezone,
            target_branch=target_branch,
            patch=patch,
            source_branch=public_branch,
            message=message,
            bundle=bundle,
            base_revision_id=base_revision_id,
        )

    def _verify_patch(self, repository):
        calculated_patch = self._generate_diff(
            repository, self.revision_id, self.base_revision_id
        )
        # Convert line-endings to UNIX
        stored_patch = re.sub(b"\r\n?", b"\n", self.patch)
        calculated_patch = re.sub(b"\r\n?", b"\n", calculated_patch)
        # Strip trailing whitespace
        calculated_patch = re.sub(b" *\n", b"\n", calculated_patch)
        stored_patch = re.sub(b" *\n", b"\n", stored_patch)
        return calculated_patch == stored_patch

    def get_merge_request(self, repository):
        """Provide data for performing a merge.

        Args:
            repository: Repository to use for merge operations.

        Returns:
            Tuple of (suggested_base, suggested_target, patch_verification_status).
        """
        verified = self._maybe_verify(repository)
        return self.base_revision_id, self.revision_id, verified

    def _maybe_verify(self, repository):
        """Verify the patch if present.

        Args:
            repository: Repository to use for verification.

        Returns:
            String indicating verification status: 'verified', 'failed', or 'inapplicable'.
        """
        if self.patch is not None:
            if self._verify_patch(repository):
                return "verified"
            else:
                return "failed"
        else:
            return "inapplicable"


class MergeDirectiveFormatRegistry(registry.Registry):
    """Registry for merge directive format handlers."""

    def register(self, directive, format_string=None):
        """Register a merge directive format.

        Args:
            directive: The directive class to register.
            format_string: Format string to use (defaults to directive._format_string).
        """
        if format_string is None:
            format_string = directive._format_string
        registry.Registry.register(self, format_string, directive)


_format_registry = MergeDirectiveFormatRegistry()
_format_registry.register(MergeDirective)
_format_registry.register(MergeDirective2)
# 0.19 never existed.  It got renamed to 0.90.  But by that point, there were
# already merge directives in the wild that used 0.19. Registering with the old
# format string to retain compatibility with those merge directives.
_format_registry.register(
    MergeDirective2, b"Bazaar merge directive format 2 (Bazaar 0.19)"
)
