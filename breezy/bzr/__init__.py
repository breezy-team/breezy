# Copyright (C) 2017 Breezy Developers
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

from typing import TYPE_CHECKING

from .. import config, controldir, errors, pyutils, registry
from .. import transport as _mod_transport
from ..branch import format_registry as branch_format_registry
from ..repository import format_registry as repository_format_registry
from ..workingtree import format_registry as workingtree_format_registry

if TYPE_CHECKING:
    from .bzrdir import BzrDirFormat


class LineEndingError(errors.BzrError):
    _fmt = (
        "Line ending corrupted for file: %(file)s; "
        "Maybe your files got corrupted in transport?"
    )

    def __init__(self, file):
        self.file = file


class BzrProber(controldir.Prober):
    """Prober for formats that use a .bzr/ control directory."""

    formats = registry.FormatRegistry["BzrDirFormat"](
        controldir.network_format_registry
    )
    """The known .bzr formats."""

    @classmethod
    def priority(klass, transport):
        return 10

    @classmethod
    def probe_transport(klass, transport):
        """Return the .bzrdir style format present in a directory."""
        try:
            format_string = transport.get_bytes(".bzr/branch-format")
        except _mod_transport.NoSuchFile as e:
            raise errors.NotBranchError(path=transport.base) from e
        except errors.BadHttpRequest as e:
            if e.reason == "no such method: .bzr":
                # hgweb
                raise errors.NotBranchError(path=transport.base) from e
            raise

        try:
            first_line = format_string[: format_string.index(b"\n") + 1]
        except ValueError:
            first_line = format_string
        if first_line.startswith(b"<!DOCTYPE") or first_line.startswith(b"<html"):
            raise errors.NotBranchError(
                path=transport.base, detail="format file looks like HTML"
            )
        try:
            cls = klass.formats.get(first_line)
        except KeyError as e:
            if first_line.endswith(b"\r\n"):
                raise LineEndingError(file=".bzr/branch-format") from e
            else:
                raise errors.UnknownFormatError(format=first_line, kind="bzrdir") from e
        return cls.from_string(format_string)

    @classmethod
    def known_formats(cls):
        result = []
        for _name, format in cls.formats.items():
            if callable(format):
                format = format()
            result.append(format)
        return result


controldir.ControlDirFormat.register_prober(BzrProber)


class RemoteBzrProber(controldir.Prober):
    """Prober for remote servers that provide a Bazaar smart server."""

    @classmethod
    def priority(klass, transport):
        return -10

    @classmethod
    def probe_transport(klass, transport):
        """Return a RemoteBzrDirFormat object if it looks possible."""
        try:
            medium = transport.get_smart_medium()
        except (
            NotImplementedError,
            AttributeError,
            errors.TransportNotPossible,
            errors.NoSmartMedium,
            errors.SmartProtocolError,
        ) as e:
            # no smart server, so not a branch for this format type.
            raise errors.NotBranchError(path=transport.base) from e
        else:
            # Decline to open it if the server doesn't support our required
            # version (3) so that the VFS-based transport will do it.
            if medium.should_probe():
                try:
                    server_version = medium.protocol_version()
                except errors.SmartProtocolError as e:
                    # Apparently there's no usable smart server there, even though
                    # the medium supports the smart protocol.
                    raise errors.NotBranchError(path=transport.base) from e
                if server_version != "2":
                    raise errors.NotBranchError(path=transport.base)
            from .remote import RemoteBzrDirFormat

            return RemoteBzrDirFormat()

    @classmethod
    def known_formats(cls):
        from .remote import RemoteBzrDirFormat

        return [RemoteBzrDirFormat()]


controldir.ControlDirFormat.register_prober(RemoteBzrProber)

# Register bzr formats
BzrProber.formats.register_lazy(
    b"Bazaar-NG meta directory, format 1\n", __name__ + ".bzrdir", "BzrDirMetaFormat1"
)
BzrProber.formats.register_lazy(
    b"Bazaar meta directory, format 1 (with colocated branches)\n",
    __name__ + ".bzrdir",
    "BzrDirMetaFormat1Colo",
)


def register_metadir(
    registry,
    key,
    repository_format,
    help,
    native=True,
    deprecated=False,
    branch_format=None,
    tree_format=None,
    hidden=False,
    experimental=False,
    bzrdir_format=None,
):
    """Register a metadir subformat.

    These all use a meta bzrdir, but can be parameterized by the
    Repository/Branch/WorkingTreeformats.

    :param repository_format: The fully-qualified repository format class
        name as a string.
    :param branch_format: Fully-qualified branch format class name as
        a string.
    :param tree_format: Fully-qualified tree format class name as
        a string.
    """
    if bzrdir_format is None:
        bzrdir_format = "breezy.bzr.bzrdir.BzrDirMetaFormat1"
    # This should be expanded to support setting WorkingTree and Branch
    # formats, once the API supports that.

    def _load(full_name):
        mod_name, factory_name = full_name.rsplit(".", 1)
        try:
            factory = pyutils.get_named_object(mod_name, factory_name)
        except ImportError as e:
            raise ImportError(f"failed to load {full_name}: {e}") from e
        except AttributeError as e:
            raise AttributeError(
                "no factory {} in module {!r}".format(full_name, sys.modules[mod_name])
            ) from e
        return factory()

    def helper():
        bd = _load(bzrdir_format)
        if branch_format is not None:
            bd.set_branch_format(_load(branch_format))
        if tree_format is not None:
            bd.workingtree_format = _load(tree_format)
        if repository_format is not None:
            bd.repository_format = _load(repository_format)
        return bd

    registry.register(key, helper, help, native, deprecated, hidden, experimental)


# formats which have no format string are not discoverable
# and not independently creatable, so are not registered.
branch_format_registry.register_lazy(
    b"Bazaar-NG branch format 5\n", "breezy.bzr.fullhistory", "BzrBranchFormat5"
)
branch_format_registry.register_lazy(
    b"Bazaar Branch Format 6 (bzr 0.15)\n", "breezy.bzr.branch", "BzrBranchFormat6"
)
branch_format_registry.register_lazy(
    b"Bazaar Branch Format 7 (needs bzr 1.6)\n", "breezy.bzr.branch", "BzrBranchFormat7"
)
branch_format_registry.register_lazy(
    b"Bazaar Branch Format 8 (needs bzr 1.15)\n",
    "breezy.bzr.branch",
    "BzrBranchFormat8",
)
branch_format_registry.register_lazy(
    b"Bazaar-NG Branch Reference Format 1\n",
    "breezy.bzr.branch",
    "BranchReferenceFormat",
)

branch_format_registry.set_default_key(b"Bazaar Branch Format 7 (needs bzr 1.6)\n")


# formats which have no format string are not discoverable or independently
# creatable on disk, so are not registered in format_registry.  They're
# all in breezy.bzr.knitreponow.  When an instance of one of these is
# needed, it's constructed directly by the ControlDir.  Non-native formats where
# the repository is not separately opened are similar.

repository_format_registry.register_lazy(
    b"Bazaar-NG Knit Repository Format 1",
    "breezy.bzr.knitrepo",
    "RepositoryFormatKnit1",
)

repository_format_registry.register_lazy(
    b"Bazaar Knit Repository Format 3 (bzr 0.15)\n",
    "breezy.bzr.knitrepo",
    "RepositoryFormatKnit3",
)

repository_format_registry.register_lazy(
    b"Bazaar Knit Repository Format 4 (bzr 1.0)\n",
    "breezy.bzr.knitrepo",
    "RepositoryFormatKnit4",
)

# Pack-based formats. There is one format for pre-subtrees, and one for
# post-subtrees to allow ease of testing.
# NOTE: These are experimental in 0.92. Stable in 1.0 and above
repository_format_registry.register_lazy(
    b"Bazaar pack repository format 1 (needs bzr 0.92)\n",
    "breezy.bzr.knitpack_repo",
    "RepositoryFormatKnitPack1",
)
repository_format_registry.register_lazy(
    b"Bazaar pack repository format 1 with subtree support (needs bzr 0.92)\n",
    "breezy.bzr.knitpack_repo",
    "RepositoryFormatKnitPack3",
)
repository_format_registry.register_lazy(
    b"Bazaar pack repository format 1 with rich root (needs bzr 1.0)\n",
    "breezy.bzr.knitpack_repo",
    "RepositoryFormatKnitPack4",
)
repository_format_registry.register_lazy(
    b"Bazaar RepositoryFormatKnitPack5 (bzr 1.6)\n",
    "breezy.bzr.knitpack_repo",
    "RepositoryFormatKnitPack5",
)
repository_format_registry.register_lazy(
    b"Bazaar RepositoryFormatKnitPack5RichRoot (bzr 1.6.1)\n",
    "breezy.bzr.knitpack_repo",
    "RepositoryFormatKnitPack5RichRoot",
)
repository_format_registry.register_lazy(
    b"Bazaar RepositoryFormatKnitPack5RichRoot (bzr 1.6)\n",
    "breezy.bzr.knitpack_repo",
    "RepositoryFormatKnitPack5RichRootBroken",
)
repository_format_registry.register_lazy(
    b"Bazaar RepositoryFormatKnitPack6 (bzr 1.9)\n",
    "breezy.bzr.knitpack_repo",
    "RepositoryFormatKnitPack6",
)
repository_format_registry.register_lazy(
    b"Bazaar RepositoryFormatKnitPack6RichRoot (bzr 1.9)\n",
    "breezy.bzr.knitpack_repo",
    "RepositoryFormatKnitPack6RichRoot",
)
repository_format_registry.register_lazy(
    b"Bazaar repository format 2a (needs bzr 1.16 or later)\n",
    "breezy.bzr.groupcompress_repo",
    "RepositoryFormat2a",
)

# Development formats.
# Check their docstrings to see if/when they are obsolete.
repository_format_registry.register_lazy(
    (
        b"Bazaar development format 2 with subtree support "
        b"(needs bzr.dev from before 1.8)\n"
    ),
    "breezy.bzr.knitpack_repo",
    "RepositoryFormatPackDevelopment2Subtree",
)
repository_format_registry.register_lazy(
    b"Bazaar development format 8\n",
    "breezy.bzr.groupcompress_repo",
    "RepositoryFormat2aSubtree",
)


workingtree_format_registry.register_lazy(
    b"Bazaar Working Tree Format 4 (bzr 0.15)\n",
    "breezy.bzr.workingtree_4",
    "WorkingTreeFormat4",
)
workingtree_format_registry.register_lazy(
    b"Bazaar Working Tree Format 5 (bzr 1.11)\n",
    "breezy.bzr.workingtree_4",
    "WorkingTreeFormat5",
)
workingtree_format_registry.register_lazy(
    b"Bazaar Working Tree Format 6 (bzr 1.14)\n",
    "breezy.bzr.workingtree_4",
    "WorkingTreeFormat6",
)
workingtree_format_registry.register_lazy(
    b"Bazaar-NG Working Tree format 3", "breezy.bzr.workingtree_3", "WorkingTreeFormat3"
)
workingtree_format_registry.set_default_key(
    b"Bazaar Working Tree Format 6 (bzr 1.14)\n"
)


register_metadir(
    controldir.format_registry,
    "knit",
    "breezy.bzr.knitrepo.RepositoryFormatKnit1",
    "Format using knits.  Recommended for interoperation with bzr <= 0.14.",
    branch_format="breezy.bzr.fullhistory.BzrBranchFormat5",
    tree_format="breezy.bzr.workingtree_3.WorkingTreeFormat3",
    hidden=True,
    deprecated=True,
)
register_metadir(
    controldir.format_registry,
    "dirstate",
    "breezy.bzr.knitrepo.RepositoryFormatKnit1",
    help="Format using dirstate for working trees. "
    "Compatible with bzr 0.8 and "
    "above when accessed over the network. Introduced in bzr 0.15.",
    branch_format="breezy.bzr.fullhistory.BzrBranchFormat5",
    tree_format="breezy.bzr.workingtree_4.WorkingTreeFormat4",
    hidden=True,
    deprecated=True,
)
register_metadir(
    controldir.format_registry,
    "dirstate-tags",
    "breezy.bzr.knitrepo.RepositoryFormatKnit1",
    help="Variant of dirstate with support for tags. Introduced in bzr 0.15.",
    branch_format="breezy.bzr.branch.BzrBranchFormat6",
    tree_format="breezy.bzr.workingtree_4.WorkingTreeFormat4",
    hidden=True,
    deprecated=True,
)
register_metadir(
    controldir.format_registry,
    "rich-root",
    "breezy.bzr.knitrepo.RepositoryFormatKnit4",
    help="Variant of dirstate with better handling of tree roots. "
    "Introduced in bzr 1.0.",
    branch_format="breezy.bzr.branch.BzrBranchFormat6",
    tree_format="breezy.bzr.workingtree_4.WorkingTreeFormat4",
    hidden=True,
    deprecated=True,
)
register_metadir(
    controldir.format_registry,
    "dirstate-with-subtree",
    "breezy.bzr.knitrepo.RepositoryFormatKnit3",
    help="Variant of dirstate with support for nested trees. Introduced in 0.15.",
    branch_format="breezy.bzr.branch.BzrBranchFormat6",
    tree_format="breezy.bzr.workingtree_4.WorkingTreeFormat4",
    experimental=True,
    deprecated=True,
    hidden=True,
)
register_metadir(
    controldir.format_registry,
    "pack-0.92",
    "breezy.bzr.knitpack_repo.RepositoryFormatKnitPack1",
    help="Pack-based format used in 1.x series. Introduced in 0.92. "
    "Interoperates with bzr repositories before 0.92 but cannot be "
    "read by bzr < 0.92.",
    branch_format="breezy.bzr.branch.BzrBranchFormat6",
    tree_format="breezy.bzr.workingtree_4.WorkingTreeFormat4",
    deprecated=True,
    hidden=True,
)
register_metadir(
    controldir.format_registry,
    "pack-0.92-subtree",
    "breezy.bzr.knitpack_repo.RepositoryFormatKnitPack3",
    help="Pack-based format used in 1.x series, with subtree support. "
    "Introduced in 0.92. Interoperates with "
    "bzr repositories before 0.92 but cannot be read by bzr < 0.92.",
    branch_format="breezy.bzr.branch.BzrBranchFormat6",
    tree_format="breezy.bzr.workingtree_4.WorkingTreeFormat4",
    hidden=True,
    deprecated=True,
    experimental=True,
)
register_metadir(
    controldir.format_registry,
    "rich-root-pack",
    "breezy.bzr.knitpack_repo.RepositoryFormatKnitPack4",
    help="A variant of pack-0.92 that supports rich-root data "
    "(needed for bzr-svn and bzr-git). Introduced in 1.0.",
    branch_format="breezy.bzr.branch.BzrBranchFormat6",
    tree_format="breezy.bzr.workingtree_4.WorkingTreeFormat4",
    hidden=True,
    deprecated=True,
)
register_metadir(
    controldir.format_registry,
    "1.6",
    "breezy.bzr.knitpack_repo.RepositoryFormatKnitPack5",
    help="A format that allows a branch to indicate that there is another "
    "(stacked) repository that should be used to access data that is "
    "not present locally.",
    branch_format="breezy.bzr.branch.BzrBranchFormat7",
    tree_format="breezy.bzr.workingtree_4.WorkingTreeFormat4",
    hidden=True,
    deprecated=True,
)
register_metadir(
    controldir.format_registry,
    "1.6.1-rich-root",
    "breezy.bzr.knitpack_repo.RepositoryFormatKnitPack5RichRoot",
    help="A variant of 1.6 that supports rich-root data "
    "(needed for bzr-svn and bzr-git).",
    branch_format="breezy.bzr.branch.BzrBranchFormat7",
    tree_format="breezy.bzr.workingtree_4.WorkingTreeFormat4",
    hidden=True,
    deprecated=True,
)
register_metadir(
    controldir.format_registry,
    "1.9",
    "breezy.bzr.knitpack_repo.RepositoryFormatKnitPack6",
    help="A repository format using B+tree indexes. These indexes "
    "are smaller in size, have smarter caching and provide faster "
    "performance for most operations.",
    branch_format="breezy.bzr.branch.BzrBranchFormat7",
    tree_format="breezy.bzr.workingtree_4.WorkingTreeFormat4",
    hidden=True,
    deprecated=True,
)
register_metadir(
    controldir.format_registry,
    "1.9-rich-root",
    "breezy.bzr.knitpack_repo.RepositoryFormatKnitPack6RichRoot",
    help="A variant of 1.9 that supports rich-root data "
    "(needed for bzr-svn and bzr-git).",
    branch_format="breezy.bzr.branch.BzrBranchFormat7",
    tree_format="breezy.bzr.workingtree_4.WorkingTreeFormat4",
    hidden=True,
    deprecated=True,
)
register_metadir(
    controldir.format_registry,
    "1.14",
    "breezy.bzr.knitpack_repo.RepositoryFormatKnitPack6",
    help="A working-tree format that supports content filtering.",
    branch_format="breezy.bzr.branch.BzrBranchFormat7",
    tree_format="breezy.bzr.workingtree_4.WorkingTreeFormat5",
    hidden=True,
    deprecated=True,
)
register_metadir(
    controldir.format_registry,
    "1.14-rich-root",
    "breezy.bzr.knitpack_repo.RepositoryFormatKnitPack6RichRoot",
    help="A variant of 1.14 that supports rich-root data "
    "(needed for bzr-svn and bzr-git).",
    branch_format="breezy.bzr.branch.BzrBranchFormat7",
    tree_format="breezy.bzr.workingtree_4.WorkingTreeFormat5",
    hidden=True,
    deprecated=True,
)
# The following un-numbered 'development' formats should always just be aliases.
register_metadir(
    controldir.format_registry,
    "development-subtree",
    "breezy.bzr.groupcompress_repo.RepositoryFormat2aSubtree",
    help="Current development format, subtree variant. Can convert data to and "
    "from pack-0.92-subtree (and anything compatible with "
    "pack-0.92-subtree) format repositories. Repositories and branches in "
    "this format can only be read by bzr.dev. Please read "
    "https://www.breezy-vcs.org/developers/development-repo.html "
    "before use.",
    branch_format="breezy.bzr.branch.BzrBranchFormat8",
    tree_format="breezy.bzr.workingtree_4.WorkingTreeFormat6",
    experimental=True,
    deprecated=True,
    hidden=True,
)
register_metadir(
    controldir.format_registry,
    "development5-subtree",
    "breezy.bzr.knitpack_repo.RepositoryFormatPackDevelopment2Subtree",
    help="Development format, subtree variant. Can convert data to and "
    "from pack-0.92-subtree (and anything compatible with "
    "pack-0.92-subtree) format repositories. Repositories and branches in "
    "this format can only be read by bzr.dev. Please read "
    "https://www.breezy-vcs.org/developers/development-repo.html "
    "before use.",
    branch_format="breezy.bzr.branch.BzrBranchFormat7",
    tree_format="breezy.bzr.workingtree_4.WorkingTreeFormat6",
    experimental=True,
    deprecated=True,
    hidden=True,
)

register_metadir(
    controldir.format_registry,
    "development-colo",
    "breezy.bzr.groupcompress_repo.RepositoryFormat2a",
    help="The 2a format with experimental support for colocated branches.\n",
    branch_format="breezy.bzr.branch.BzrBranchFormat7",
    tree_format="breezy.bzr.workingtree_4.WorkingTreeFormat6",
    experimental=True,
    bzrdir_format="breezy.bzr.bzrdir.BzrDirMetaFormat1Colo",
    hidden=True,
)


# And the development formats above will have aliased one of the following:

# Finally, the current format.
register_metadir(
    controldir.format_registry,
    "2a",
    "breezy.bzr.groupcompress_repo.RepositoryFormat2a",
    help="Format for the bzr 2.0 series.\n",
    branch_format="breezy.bzr.branch.BzrBranchFormat7",
    tree_format="breezy.bzr.workingtree_4.WorkingTreeFormat6",
    experimental=False,
    deprecated=False,
)

# The following format should be an alias for the rich root equivalent
# of the default format

controldir.format_registry.register_alias("default-rich-root", "2a", hidden=True)

# The following format should is just an alias for the default bzr format.
controldir.format_registry.register_alias("bzr", "2a")

# The current format that is made on 'bzr init'.
format_name = config.GlobalStack().get("default_format")
controldir.format_registry.set_default(format_name)
