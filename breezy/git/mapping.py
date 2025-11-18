# Copyright (C) 2008-2018 Jelmer Vernooij <jelmer@jelmer.uk>
# Copyright (C) 2007 Canonical Ltd
# Copyright (C) 2008 John Carr
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

"""Converters, etc for going between Bazaar and Git ids."""

import base64
import contextlib
import stat

import fastbencode as bencode

from .. import errors, foreign, trace
from ..foreign import ForeignRevision, ForeignVcs, VcsMappingRegistry
from ..revision import NULL_REVISION
from .errors import NoPushSupport
from .hg import extract_hg_metadata, format_hg_metadata
from .roundtrip import CommitSupplement, extract_bzr_metadata, inject_bzr_metadata

DEFAULT_FILE_MODE = stat.S_IFREG | 0o644
HG_RENAME_SOURCE = b"HG:rename-source"
HG_EXTRA = b"HG:extra"

# This HG extra is used to indicate the commit that this commit was based on.
HG_EXTRA_AMEND_SOURCE = b"amend_source"
HG_EXTRA_REBASE_SOURCE = b"rebase_source"
HG_EXTRA_ABSORB_SOURCE = b"absorb_source"
HG_EXTRA_SOURCE = b"source"
HG_EXTRA_INTERMEDIATE_SOURCE = b"intermediate-source"
HG_EXTRA_TOPIC = b"topic"
HG_EXTRA_REWRITE_NOISE = b"_rewrite_noise"

FILE_ID_PREFIX = b"git:"

# Always the same.
ROOT_ID = b"TREE_ROOT"


class UnknownCommitExtra(errors.BzrError):
    """Error for unknown extra fields in a commit."""

    _fmt = "Unknown extra fields in %(object)r: %(fields)r."

    def __init__(self, object, fields):
        """Initialize UnknownCommitExtra error.

        Args:
            object: The commit object containing unknown fields.
            fields: The unknown field names.
        """
        errors.BzrError.__init__(self)
        self.object = object
        self.fields = ",".join(fields)


class UnknownMercurialCommitExtra(errors.BzrError):
    """Error for unknown mercurial extra fields in a commit."""

    _fmt = "Unknown mercurial extra fields in %(object)r: %(fields)r."

    def __init__(self, object, fields):
        """Initialize UnknownMercurialCommitExtra error.

        Args:
            object: The commit object containing unknown fields.
            fields: The unknown mercurial field names.
        """
        errors.BzrError.__init__(self)
        self.object = object
        self.fields = b",".join(fields)


class UnknownCommitEncoding(errors.BzrError):
    """Error for unknown commit encoding."""

    _fmt = "Unknown commit encoding: %(encoding)s"

    def __init__(self, encoding):
        """Initialize UnknownCommitEncoding error.

        Args:
            encoding: The unknown encoding name.
        """
        errors.BzrError.__init__(self)
        self.encoding = encoding


def escape_file_id(file_id):
    """Escape special characters in a file ID for Git storage.

    Args:
        file_id: The file ID bytes to escape.

    Returns:
        Escaped file ID bytes.
    """
    file_id = file_id.replace(b"_", b"__")
    file_id = file_id.replace(b" ", b"_s")
    file_id = file_id.replace(b"\x0c", b"_c")
    return file_id


def unescape_file_id(file_id):
    """Unescape special characters in a file ID from Git storage.

    Args:
        file_id: The escaped file ID bytes to unescape.

    Returns:
        Unescaped file ID bytes.
    """
    ret = bytearray()
    i = 0
    while i < len(file_id):
        if file_id[i : i + 1] != b"_":
            ret.append(file_id[i])
        else:
            if file_id[i + 1 : i + 2] == b"_":
                ret.append(b"_"[0])
            elif file_id[i + 1 : i + 2] == b"s":
                ret.append(b" "[0])
            elif file_id[i + 1 : i + 2] == b"c":
                ret.append(b"\x0c"[0])
            else:
                raise ValueError(f"unknown escape character {file_id[i + 1 : i + 2]}")
            i += 1
        i += 1
    return bytes(ret)


def fix_person_identifier(text):
    """Fix person identifier format for Git compatibility.

    Args:
        text: Person identifier bytes to fix.

    Returns:
        Fixed person identifier in format 'name <email>'.
    """
    if b"<" not in text and b">" not in text:
        username = text
        email = text
    elif b">" not in text:
        return text + b">"
    else:
        if text.rindex(b">") < text.rindex(b"<"):
            raise ValueError(text)
        username, email = text.split(b"<", 2)[-2:]
        email = email.split(b">", 1)[0]
        if username.endswith(b" "):
            username = username[:-1]
    return b"%s <%s>" % (username, email)


def decode_git_path(path):
    """Take a git path and decode it."""
    return path.decode("utf-8", "surrogateescape")


def encode_git_path(path):
    """Take a regular path and encode it for git."""
    return path.encode("utf-8", "surrogateescape")


def warn_escaped(commit, num_escaped):
    """Warn about escaped XML-invalid characters in commit.

    Args:
        commit: The commit object.
        num_escaped: Number of characters that were escaped.
    """
    trace.warning(
        "Escaped %d XML-invalid characters in %s. Will be unable "
        "to regenerate the SHA map.",
        num_escaped,
        commit,
    )


def warn_unusual_mode(commit, path, mode):
    """Warn about unusual file mode in commit.

    Args:
        commit: The commit object.
        path: The file path.
        mode: The unusual file mode.
    """
    trace.mutter(
        "Unusual file mode %o for %s in %s. Storing as revision property. ",
        mode,
        path,
        commit,
    )


class BzrGitMapping(foreign.VcsMapping):
    """Class that maps between Git and Bazaar semantics."""

    experimental = False

    BZR_DUMMY_FILE: str | None = None

    def is_special_file(self, filename):
        """Check if a filename is special for this mapping.

        Args:
            filename: The filename to check.

        Returns:
            True if the filename is special, False otherwise.
        """
        return filename in (self.BZR_DUMMY_FILE,)

    def __init__(self):
        """Initialize BzrGitMapping."""
        super().__init__(foreign_vcs_git)

    def __eq__(self, other):
        """Check equality with another mapping.

        Args:
            other: Other mapping to compare with.

        Returns:
            True if mappings are equal, False otherwise.
        """
        return type(self) is type(other) and self.revid_prefix == other.revid_prefix

    @classmethod
    def revision_id_foreign_to_bzr(cls, git_rev_id):
        """Convert a git revision id handle to a Bazaar revision id."""
        from dulwich.protocol import ZERO_SHA

        if git_rev_id == ZERO_SHA:
            return NULL_REVISION
        return b"%s:%s" % (cls.revid_prefix, git_rev_id)

    @classmethod
    def revision_id_bzr_to_foreign(cls, bzr_rev_id):
        """Convert a Bazaar revision id to a git revision id handle."""
        if not bzr_rev_id.startswith(b"%s:" % cls.revid_prefix):
            raise errors.InvalidRevisionId(bzr_rev_id, cls)
        return bzr_rev_id[len(cls.revid_prefix) + 1 :], cls()

    def generate_file_id(self, path):
        """Generate a file ID for a path.

        Args:
            path: The file path (str or bytes).

        Returns:
            File ID bytes.
        """
        # Git paths are just bytestrings
        # We must just hope they are valid UTF-8..
        if isinstance(path, str):
            path = encode_git_path(path)
        if path == b"":
            return ROOT_ID
        return FILE_ID_PREFIX + escape_file_id(path)

    def parse_file_id(self, file_id):
        """Parse a file ID to extract the path.

        Args:
            file_id: The file ID bytes to parse.

        Returns:
            The decoded file path as string.
        """
        if file_id == ROOT_ID:
            return ""
        if not file_id.startswith(FILE_ID_PREFIX):
            raise ValueError
        return decode_git_path(unescape_file_id(file_id[len(FILE_ID_PREFIX) :]))

    def import_unusual_file_modes(self, rev, unusual_file_modes):
        """Import unusual file modes into revision properties.

        Args:
            rev: The revision object to modify.
            unusual_file_modes: Dictionary of paths to unusual modes.
        """
        if unusual_file_modes:
            ret = [
                (path, unusual_file_modes[path])
                for path in sorted(unusual_file_modes.keys())
            ]
            rev.properties["file-modes"] = bencode.bencode(ret)

    def export_unusual_file_modes(self, rev):
        """Export unusual file modes from revision properties.

        Args:
            rev: The revision object to examine.

        Returns:
            Dictionary mapping paths to file modes.
        """
        try:
            file_modes = rev.properties["file-modes"]
        except KeyError:
            return {}
        else:
            return dict(bencode.bdecode(file_modes.encode("utf-8")))

    def _generate_git_svn_metadata(self, rev, encoding):
        try:
            git_svn_id = rev.properties["git-svn-id"]
        except KeyError:
            return ""
        else:
            return f"\ngit-svn-id: {git_svn_id.encode(encoding)}\n"

    def _generate_hg_message_tail(self, rev):
        extra = {}
        renames = []
        branch = "default"
        for name in rev.properties:
            if name == "hg:extra:branch":
                branch = rev.properties["hg:extra:branch"]
            elif name.startswith("hg:extra"):
                extra[name[len("hg:extra:") :]] = base64.b64decode(rev.properties[name])
            elif name == "hg:renames":
                renames = bencode.bdecode(
                    base64.b64decode(rev.properties["hg:renames"])
                )
            # TODO: Export other properties as 'bzr:' extras?
        ret = format_hg_metadata(renames, branch, extra)
        if not isinstance(ret, bytes):
            raise TypeError(ret)
        return ret

    def _extract_git_svn_metadata(self, properties, message):
        lines = message.split("\n")
        if not (
            lines[-1] == "" and len(lines) >= 2 and lines[-2].startswith("git-svn-id:")
        ):
            return message
        git_svn_id = lines[-2].split(": ", 1)[1]
        properties["git-svn-id"] = git_svn_id
        (_url, _rev, _uuid) = parse_git_svn_id(git_svn_id)
        # FIXME: Convert this to converted-from property somehow..
        return "\n".join(lines[:-2])

    def _extract_hg_metadata(self, properties, message):
        (message, renames, branch, extra) = extract_hg_metadata(message)
        if branch is not None:
            properties["hg:extra:branch"] = branch
        for name, value in extra.items():
            properties["hg:extra:" + name] = base64.b64encode(value)
        if renames:
            properties["hg:renames"] = base64.b64encode(
                bencode.bencode([(new, old) for (old, new) in renames.items()])
            )
        return message

    def _extract_bzr_metadata(self, properties, message):
        (message, metadata) = extract_bzr_metadata(message)
        return message, metadata

    def _decode_commit_message(self, properties, message, encoding):
        decoded_message = None if message is None else message.decode(encoding)
        return decoded_message, CommitSupplement()

    def _encode_commit_message(self, rev, message, encoding):
        if message is None:
            return None
        else:
            return message.encode(encoding)

    def export_commit(self, rev, tree_sha, parent_lookup, lossy, verifiers):
        """Turn a Bazaar revision in to a Git commit.

        :param tree_sha: Tree sha for the commit
        :param parent_lookup: Function for looking up the GIT sha equiv of a
            bzr revision
        :param lossy: Whether to store roundtripping information.
        :param verifiers: Verifiers info
        :return dulwich.objects.Commit represent the revision:
        """
        from dulwich.objects import Commit, Tag

        commit = Commit()
        commit.tree = tree_sha
        if not lossy:
            metadata = CommitSupplement()
            metadata.verifiers = verifiers
        else:
            metadata = None
        parents = []
        for p in rev.parent_ids:
            try:
                git_p = parent_lookup(p)
            except KeyError:
                git_p = None
                if metadata is not None:
                    metadata.explicit_parent_ids = rev.parent_ids
            if git_p is not None:
                if len(git_p) != 40:
                    raise AssertionError(f"unexpected length for {git_p!r}")
                parents.append(git_p)
        commit.parents = parents
        try:
            encoding = rev.properties["git-explicit-encoding"]
        except KeyError:
            encoding = rev.properties.get("git-implicit-encoding", "utf-8")
        with contextlib.suppress(KeyError):
            commit.encoding = rev.properties["git-explicit-encoding"].encode("ascii")
        commit.committer = fix_person_identifier(rev.committer.encode(encoding))
        first_author = rev.get_apparent_authors()[0]
        if "," in first_author and first_author.count(">") > 1:
            first_author = first_author.split(",")[0]
        commit.author = fix_person_identifier(first_author.encode(encoding))
        # TODO(jelmer): Don't use this hack.
        long = getattr(__builtins__, "long", int)
        commit.commit_time = long(rev.timestamp)
        if "author-timestamp" in rev.properties:
            commit.author_time = long(rev.properties["author-timestamp"])
        else:
            commit.author_time = commit.commit_time
        commit._commit_timezone_neg_utc = "commit-timezone-neg-utc" in rev.properties
        commit.commit_timezone = rev.timezone
        commit._author_timezone_neg_utc = "author-timezone-neg-utc" in rev.properties
        if "author-timezone" in rev.properties:
            commit.author_timezone = int(rev.properties["author-timezone"])
        else:
            commit.author_timezone = commit.commit_timezone
        if "git-gpg-signature" in rev.properties:
            commit.gpgsig = rev.properties["git-gpg-signature"].encode(
                "utf-8", "surrogateescape"
            )
        if "git-missing-message" in rev.properties:
            if commit.message != "":
                raise AssertionError("git-missing-message set but message is not empty")
            commit.message = None
        else:
            commit.message = self._encode_commit_message(rev, rev.message, encoding)
        if not isinstance(commit.message, bytes):
            raise TypeError(commit.message)
        if metadata is not None:
            try:
                mapping_registry.parse_revision_id(rev.revision_id)
            except errors.InvalidRevisionId:
                metadata.revision_id = rev.revision_id
            mapping_properties = {
                "author",
                "author-timezone",
                "author-timezone-neg-utc",
                "commit-timezone-neg-utc",
                "git-implicit-encoding",
                "git-gpg-signature",
                "git-explicit-encoding",
                "author-timestamp",
                "file-modes",
            }
            for k, v in rev.properties.items():
                if k not in mapping_properties:
                    metadata.properties[k] = v
        if not lossy and metadata:
            if self.roundtripping:
                commit.message = inject_bzr_metadata(commit.message, metadata, encoding)
            else:
                raise NoPushSupport(None, None, self, revision_id=rev.revision_id)
        if not isinstance(commit.message, bytes):
            raise TypeError(commit.message)
        i = 0
        propname = "git-mergetag-0"
        while propname in rev.properties:
            commit.mergetag.append(
                Tag.from_string(
                    rev.properties[propname].encode("utf-8", "surrogateescape")
                )
            )
            i += 1
            propname = "git-mergetag-%d" % i
        try:
            extra = commit._extra
        except AttributeError:
            extra = commit.extra
        if "git-extra" in rev.properties:
            for l in rev.properties["git-extra"].splitlines():
                (k, v) = l.split(" ", 1)
                extra.append(
                    (
                        k.encode("utf-8", "surrogateescape"),
                        v.encode("utf-8", "surrogateescape"),
                    )
                )
        return commit

    def get_revision_id(self, commit):
        """Get the revision ID for a Git commit.

        Args:
            commit: The Git commit object.

        Returns:
            The Bazaar revision ID for this commit.
        """
        encoding = commit.encoding.decode("ascii") if commit.encoding else "utf-8"
        if commit.message is not None:
            try:
                _message, metadata = self._decode_commit_message(
                    None, commit.message, encoding
                )
            except UnicodeDecodeError:
                pass
            else:
                if metadata.revision_id:
                    return metadata.revision_id
        return self.revision_id_foreign_to_bzr(commit.id)

    def import_commit(self, commit, lookup_parent_revid, strict=True):
        """Convert a git commit to a bzr revision.

        :return: a `breezy.revision.Revision` object, foreign revid and a
            testament sha1
        """
        if commit is None:
            raise AssertionError("Commit object can't be None")
        committer = None
        message = None
        git_metadata = None
        properties = {}

        def decode_using_encoding(properties, commit, encoding):
            nonlocal committer, message, git_metadata
            try:
                committer = commit.committer.decode(encoding)
            except LookupError as err:
                raise UnknownCommitEncoding(encoding) from err
            try:
                if commit.committer != commit.author:
                    properties["author"] = commit.author.decode(encoding)
            except LookupError as err:
                raise UnknownCommitEncoding(encoding) from err
            message, git_metadata = self._decode_commit_message(
                properties, commit.message, encoding
            )

        if commit.encoding is not None:
            properties["git-explicit-encoding"] = commit.encoding.decode("ascii")
        if commit.encoding is not None and commit.encoding != b"false":
            decode_using_encoding(properties, commit, commit.encoding.decode("ascii"))
        else:
            for encoding in ("utf-8", "latin1"):
                try:
                    decode_using_encoding(properties, commit, encoding)
                except UnicodeDecodeError:
                    pass
                else:
                    if encoding != "utf-8":
                        properties["git-implicit-encoding"] = encoding
                    break
        if commit.commit_time != commit.author_time:
            properties["author-timestamp"] = str(commit.author_time)
        if commit.commit_timezone != commit.author_timezone:
            properties["author-timezone"] = "%d" % commit.author_timezone
        if commit._author_timezone_neg_utc:
            properties["author-timezone-neg-utc"] = ""
        if commit._commit_timezone_neg_utc:
            properties["commit-timezone-neg-utc"] = ""
        if commit.gpgsig:
            properties["git-gpg-signature"] = commit.gpgsig.decode(
                "utf-8", "surrogateescape"
            )
        if commit.mergetag:
            for i, tag in enumerate(commit.mergetag):
                properties["git-mergetag-%d" % i] = tag.as_raw_string().decode(
                    "utf-8", "surrogateescape"
                )
        timestamp = commit.commit_time
        timezone = commit.commit_timezone
        parent_ids = None
        if git_metadata is not None:
            md = git_metadata
            roundtrip_revid = md.revision_id
            if md.explicit_parent_ids:
                parent_ids = md.explicit_parent_ids
            properties.update(md.properties)
            verifiers = md.verifiers
        else:
            roundtrip_revid = None
            verifiers = {}
        if parent_ids is None:
            parents = []
            for p in commit.parents:
                try:
                    parents.append(lookup_parent_revid(p))
                except KeyError:
                    parents.append(self.revision_id_foreign_to_bzr(p))
            parent_ids = list(parents)
        unknown_extra_fields = []
        extra_lines = []
        try:
            extra = commit._extra
        except AttributeError:
            extra = commit.extra
        for k, v in extra:
            if k == HG_RENAME_SOURCE:
                extra_lines.append(
                    k.decode("utf-8", "surrogateescape")
                    + " "
                    + v.decode("utf-8", "surrogateescape")
                    + "\n"
                )
            elif k == HG_EXTRA:
                hgk, _hgv = v.split(b":", 1)
                if (
                    hgk
                    not in (
                        HG_EXTRA_AMEND_SOURCE,
                        HG_EXTRA_REBASE_SOURCE,
                        HG_EXTRA_ABSORB_SOURCE,
                        HG_EXTRA_INTERMEDIATE_SOURCE,
                        HG_EXTRA_SOURCE,
                        HG_EXTRA_TOPIC,
                        HG_EXTRA_REWRITE_NOISE,
                    )
                    and strict
                ):
                    raise UnknownMercurialCommitExtra(commit, [hgk])
                extra_lines.append(
                    k.decode("utf-8", "surrogateescape")
                    + " "
                    + v.decode("utf-8", "surrogateescape")
                    + "\n"
                )
            else:
                unknown_extra_fields.append(k)
        if unknown_extra_fields and strict:
            raise UnknownCommitExtra(
                commit, [f.decode("ascii", "replace") for f in unknown_extra_fields]
            )
        if extra_lines:
            properties["git-extra"] = "".join(extra_lines)

        if message is None:
            properties["git-missing-message"] = "true"
            message = ""

        rev = ForeignRevision(
            foreign_revid=commit.id,
            mapping=self,
            revision_id=self.revision_id_foreign_to_bzr(commit.id),
            properties=properties,
            parent_ids=parent_ids,
            timestamp=timestamp,
            timezone=timezone,
            committer=committer,
            message=message,
        )
        rev.git_metadata = git_metadata
        return rev, roundtrip_revid, verifiers


class BzrGitMappingv1(BzrGitMapping):
    """Bazaar-Git mapping version 1."""

    revid_prefix = b"git-v1"
    experimental = False

    def __str__(self):
        """Get string representation of this mapping.

        Returns:
            String representation of the revision ID prefix.
        """
        return self.revid_prefix.decode("utf-8")


class BzrGitMappingExperimental(BzrGitMappingv1):
    """Experimental Bazaar-Git mapping with roundtripping support."""

    revid_prefix = b"git-experimental"
    experimental = True
    roundtripping = False

    BZR_DUMMY_FILE = ".bzrdummy"

    def _decode_commit_message(self, properties, message, encoding):
        message = self._extract_hg_metadata(properties, message)
        message = self._extract_git_svn_metadata(properties, message)
        message, metadata = self._extract_bzr_metadata(properties, message)
        try:
            return message.decode(encoding), metadata
        except LookupError as err:
            raise UnknownCommitEncoding(encoding) from err

    def _encode_commit_message(self, rev, message, encoding):
        ret = message.encode(encoding)
        ret += self._generate_hg_message_tail(rev)
        ret += self._generate_git_svn_metadata(rev, encoding)
        return ret

    def import_commit(self, commit, lookup_parent_revid, strict=True):
        """Import a Git commit into a Bazaar revision.

        Args:
            commit: The Git commit object to import.
            lookup_parent_revid: Function to look up parent revision IDs.
            strict: Whether to be strict about unknown fields.

        Returns:
            Tuple of (revision, roundtrip_revid, verifiers).
        """
        rev, roundtrip_revid, verifiers = super().import_commit(
            commit, lookup_parent_revid, strict
        )
        rev.properties["converted_revision"] = f"git {commit.id}\n"
        return rev, roundtrip_revid, verifiers


class GitMappingRegistry(VcsMappingRegistry):
    """Registry with available git mappings."""

    def revision_id_bzr_to_foreign(self, bzr_revid):
        """Convert a Bazaar revision ID to a Git SHA.

        Args:
            bzr_revid: The Bazaar revision ID to convert.

        Returns:
            Tuple of (git_sha, mapping).
        """
        if bzr_revid == NULL_REVISION:
            from dulwich.protocol import ZERO_SHA

            return ZERO_SHA, None
        if not bzr_revid.startswith(b"git-"):
            raise errors.InvalidRevisionId(bzr_revid, None)
        (mapping_version, _git_sha) = bzr_revid.split(b":", 1)
        mapping = self.get(mapping_version)
        return mapping.revision_id_bzr_to_foreign(bzr_revid)

    parse_revision_id = revision_id_bzr_to_foreign


mapping_registry = GitMappingRegistry()
mapping_registry.register_lazy(b"git-v1", __name__, "BzrGitMappingv1")
mapping_registry.register_lazy(
    b"git-experimental", __name__, "BzrGitMappingExperimental"
)
# Uncomment the next line to enable the experimental bzr-git mappings.
# This will make sure all bzr metadata is pushed into git, allowing for
# full roundtripping later.
# NOTE: THIS IS EXPERIMENTAL. IT MAY EAT YOUR DATA OR CORRUPT
# YOUR BZR OR GIT REPOSITORIES. USE WITH CARE.
# mapping_registry.set_default('git-experimental')
mapping_registry.set_default(b"git-v1")


class ForeignGit(ForeignVcs):
    """The Git Stupid Content Tracker."""

    @property
    def branch_format(self):
        """Get the branch format for this VCS.

        Returns:
            The LocalGitBranchFormat instance.
        """
        from .branch import LocalGitBranchFormat

        return LocalGitBranchFormat()

    @property
    def repository_format(self):
        """Get the repository format for this VCS.

        Returns:
            The GitRepositoryFormat instance.
        """
        from .repository import GitRepositoryFormat

        return GitRepositoryFormat()

    def __init__(self):
        """Initialize ForeignGit VCS."""
        super().__init__(mapping_registry)
        self.abbreviation = "git"

    @classmethod
    def serialize_foreign_revid(self, foreign_revid):
        """Serialize a foreign revision ID.

        Args:
            foreign_revid: The foreign revision ID to serialize.

        Returns:
            The serialized revision ID.
        """
        return foreign_revid

    @classmethod
    def show_foreign_revid(cls, foreign_revid):
        """Show a foreign revision ID in human-readable format.

        Args:
            foreign_revid: The foreign revision ID to show.

        Returns:
            Dictionary with human-readable representation.
        """
        return {"git commit": foreign_revid.decode("utf-8")}


foreign_vcs_git = ForeignGit()
default_mapping = mapping_registry.get_default()()


def symlink_to_blob(symlink_target):
    """Convert a symlink target to a Git blob object.

    Args:
        symlink_target: The symlink target path (str or bytes).

    Returns:
        Git Blob object containing the symlink data.
    """
    from dulwich.objects import Blob

    blob = Blob()
    if isinstance(symlink_target, str):
        symlink_target = encode_git_path(symlink_target)
    blob.data = symlink_target
    return blob


def mode_is_executable(mode):
    """Check if mode should be considered executable."""
    return bool(mode & 0o111)


def mode_kind(mode):
    """Determine the Bazaar inventory kind based on Unix file mode."""
    if mode is None:
        return None
    entry_kind = (mode & 0o700000) / 0o100000
    if entry_kind == 0:
        return "directory"
    elif entry_kind == 1:
        file_kind = (mode & 0o70000) / 0o10000
        if file_kind == 0:
            return "file"
        elif file_kind == 2:
            return "symlink"
        elif file_kind == 6:
            return "tree-reference"
        else:
            raise AssertionError(
                "Unknown file kind %d, perms=%o."
                % (
                    file_kind,
                    mode,
                )
            )
    else:
        raise AssertionError(f"Unknown kind, perms={mode!r}.")


def object_mode(kind, executable):
    """Determine Git object mode for a file kind and executable flag.

    Args:
        kind: The file kind ('file', 'directory', 'symlink', 'tree-reference').
        executable: Whether the file is executable.

    Returns:
        The Git object mode.
    """
    if kind == "directory":
        return stat.S_IFDIR
    elif kind == "symlink":
        mode = stat.S_IFLNK
        if executable:
            mode |= 0o111
        return mode
    elif kind == "file":
        mode = stat.S_IFREG | 0o644
        if executable:
            mode |= 0o111
        return mode
    elif kind == "tree-reference":
        from dulwich.objects import S_IFGITLINK

        return S_IFGITLINK
    else:
        raise AssertionError


def entry_mode(entry):
    """Determine the git file mode for an inventory entry."""
    return object_mode(entry.kind, getattr(entry, "executable", False))


def extract_unusual_modes(rev):
    """Extract unusual file modes from a revision.

    Args:
        rev: The revision object to examine.

    Returns:
        Dictionary mapping paths to unusual file modes.
    """
    try:
        _foreign_revid, mapping = mapping_registry.parse_revision_id(rev.revision_id)
    except errors.InvalidRevisionId:
        return {}
    else:
        return mapping.export_unusual_file_modes(rev)


def parse_git_svn_id(text):
    """Parse a git-svn ID string.

    Args:
        text: The git-svn ID string to parse.

    Returns:
        Tuple of (url, revision, uuid).
    """
    (head, uuid) = text.rsplit(" ", 1)
    (full_url, rev) = head.rsplit("@", 1)
    return (full_url, int(rev), uuid)


def needs_roundtripping(repo, revid):
    """Check if a revision needs roundtripping metadata.

    Args:
        repo: The repository containing the revision.
        revid: The revision ID to check.

    Returns:
        True if roundtripping is needed, False otherwise.
    """
    try:
        mapping_registry.parse_revision_id(revid)
    except errors.InvalidRevisionId:
        return True
    else:
        return False
