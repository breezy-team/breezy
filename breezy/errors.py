# Copyright (C) 2005-2013, 2016 Canonical Ltd
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

__docformat__ = "google"

"""Exceptions for bzr, and reporting of them.

This module defines the exception hierarchy used throughout Breezy. All Breezy-specific
exceptions inherit from BzrError, which provides a consistent interface for formatting
error messages.

The module includes exceptions for:
- General errors (BzrError and its subclasses)
- Path and filesystem errors (PathError and subclasses)
- Version control errors (NotBranchError, NoSuchRevision, etc.)
- Lock-related errors (LockError and subclasses)
- Transport and network errors (TransportError and subclasses)
- Repository and format errors
- User interface errors (CommandError)
"""


# TODO: is there any value in providing the .args field used by standard
# python exceptions?   A list of values with no names seems less useful
# to me.

# TODO: Perhaps convert the exception to a string at the moment it's
# constructed to make sure it will succeed.  But that says nothing about
# exceptions that are never raised.

# TODO: selftest assertRaises should probably also check that every error
# raised can be formatted as a string successfully, and without giving
# 'unprintable'.


# return codes from the brz program
EXIT_OK = 0
EXIT_ERROR = 3
EXIT_INTERNAL_ERROR = 4


class BzrError(Exception):
    """Base class for errors raised by breezy.

    Attributes:
      internal_error: if True this was probably caused by a brz bug and
                      should be displayed with a traceback; if False (or
                      absent) this was probably a user or environment error
                      and they don't need the gory details.  (That can be
                      overridden by -Derror on the command line.)

      _fmt: Format string to display the error; this is expanded
            by the instance's dict.
    """

    internal_error = False

    def __init__(self, msg=None, **kwds):
        """Construct a new BzrError.

        There are two alternative forms for constructing these objects.
        Either a preformatted string may be passed, or a set of named
        arguments can be given.  The first is for generic "user" errors which
        are not intended to be caught and so do not need a specific subclass.
        The second case is for use with subclasses that provide a _fmt format
        string to print the arguments.

        Keyword arguments are taken as parameters to the error, which can
        be inserted into the format string template.  It's recommended
        that subclasses override the __init__ method to require specific
        parameters.

        Args:
          msg: If given, this is the literal complete text for the error, not
               subject to expansion. 'msg' is used instead of 'message' because
               python evolved and, in 2.6, forbids the use of 'message'.
          **kwds: Additional keyword arguments to be stored as instance attributes.
        """
        Exception.__init__(self)
        if msg is not None:
            # I was going to deprecate this, but it actually turns out to be
            # quite handy - mbp 20061103.
            self._preformatted_string = msg
        else:
            self._preformatted_string = None
            for key, value in kwds.items():
                setattr(self, key, value)

    def _format(self):
        s = getattr(self, "_preformatted_string", None)
        if s is not None:
            # contains a preformatted message
            return s
        err = None
        try:
            fmt = self._get_format_string()
            if fmt:
                d = dict(self.__dict__)
                s = fmt % d
                # __str__() should always return a 'str' object
                # never a 'unicode' object.
                return s
        except Exception as e:
            err = e
        return "Unprintable exception {}: dict={!r}, fmt={!r}, error={!r}".format(
            self.__class__.__name__, self.__dict__, getattr(self, "_fmt", None), err
        )

    __str__ = _format

    def __repr__(self):
        """Return a developer-friendly string representation of the exception."""
        return f"{self.__class__.__name__}({self!s})"

    def _get_format_string(self):
        """Return format string for this exception or None."""
        fmt = getattr(self, "_fmt", None)
        if fmt is not None:
            from .i18n import gettext

            return gettext(fmt)  # _fmt strings should be ascii

    def __eq__(self, other):
        """Check equality between two BzrError instances."""
        if self.__class__ is not other.__class__:
            return NotImplemented
        return self.__dict__ == other.__dict__

    def __hash__(self):
        """Return hash of the exception instance."""
        return id(self)


class InternalBzrError(BzrError):
    """Base class for errors that are internal in nature.

    This is a convenience class for errors that are internal. The
    internal_error attribute can still be altered in subclasses, if needed.
    Using this class is simply an easy way to get internal errors.
    """

    internal_error = True


class BranchError(BzrError):
    """Base class for concrete 'errors about a branch'."""

    def __init__(self, branch):
        """Initialize BranchError with the given branch.

        Args:
            branch: The branch that caused the error.
        """
        BzrError.__init__(self, branch=branch)


class BzrCheckError(InternalBzrError):
    """Internal consistency check failure.

    Raised when an internal consistency check fails, indicating a bug in bzr.
    """

    _fmt = "Internal check failed: %(msg)s"

    def __init__(self, msg):
        """Initialize with an error message.

        Args:
            msg: Description of what check failed.
        """
        BzrError.__init__(self)
        self.msg = msg


class IncompatibleVersion(BzrError):
    """Incompatible API version error.

    Raised when an API version mismatch is detected between components.
    """

    _fmt = (
        "API %(api)s is not compatible; one of versions %(wanted)r "
        "is required, but current version is %(current)r."
    )

    def __init__(self, api, wanted, current):
        """Initialize with version compatibility information.

        Args:
            api: Name of the API with the version mismatch.
            wanted: List of acceptable version numbers.
            current: The current version number.
        """
        self.api = api
        self.wanted = wanted
        self.current = current


class InProcessTransport(BzrError):
    """Transport is only accessible within the current process.

    Raised when attempting to use an in-process transport from outside the process.
    """

    _fmt = "The transport '%(transport)s' is only accessible within this process."

    def __init__(self, transport):
        """Initialize with the problematic transport.

        Args:
            transport: The transport that is only accessible within this process.
        """
        self.transport = transport


class InvalidRevisionNumber(BzrError):
    """Invalid revision number specified.

    Raised when a revision number is invalid or out of range.
    """

    _fmt = "Invalid revision number %(revno)s"

    def __init__(self, revno):
        """Initialize with the invalid revision number.

        Args:
            revno: The invalid revision number.
        """
        BzrError.__init__(self)
        self.revno = revno


class InvalidRevisionId(BzrError):
    """Invalid revision ID specified.

    Raised when a revision ID is not valid or not found in the branch.
    """

    _fmt = "Invalid revision-id {%(revision_id)s} in %(branch)s"

    def __init__(self, revision_id, branch):
        """Initialize with the invalid revision ID and branch.

        Args:
            revision_id: The invalid revision ID.
            branch: The branch where the revision ID was not found.
        """
        # branch can be any string or object with __str__ defined
        BzrError.__init__(self)
        self.revision_id = revision_id
        self.branch = branch


class ReservedId(BzrError):
    """Reserved revision ID used.

    Raised when attempting to use a revision ID that is reserved by the system.
    """

    _fmt = "Reserved revision-id {%(revision_id)s}"

    def __init__(self, revision_id):
        """Initialize with the reserved revision ID.

        Args:
            revision_id: The reserved revision ID that was attempted to be used.
        """
        self.revision_id = revision_id


class RootMissing(InternalBzrError):
    """Root entry missing from tree.

    The root entry of a tree must be the first entry supplied to the commit builder.
    This is an internal consistency error.
    """

    _fmt = (
        "The root entry of a tree must be the first entry supplied to "
        "the commit builder."
    )


class NoPublicBranch(BzrError):
    """No public branch configured.

    Raised when trying to access the public branch but none has been configured.
    """

    _fmt = 'There is no public branch set for "%(branch_url)s".'

    def __init__(self, branch):
        """Initialize with the branch that has no public branch set.

        Args:
            branch: The branch object that lacks a public branch setting.
        """
        from . import urlutils

        public_location = urlutils.unescape_for_display(branch.base, "ascii")
        BzrError.__init__(self, branch_url=public_location)


class NoSuchId(BzrError):
    """File ID not found in tree.

    Raised when a requested file ID is not present in the tree.
    """

    _fmt = 'The file id "%(file_id)s" is not present in the tree %(tree)s.'

    def __init__(self, tree, file_id):
        """Initialize with the tree and missing file ID.

        Args:
            tree: The tree where the file ID was not found.
            file_id: The file ID that was not found.
        """
        BzrError.__init__(self)
        self.file_id = file_id
        self.tree = tree


class NotStacked(BranchError):
    """Branch is not stacked.

    Raised when trying to perform a stacking operation on a branch that is not stacked.
    """

    _fmt = "The branch '%(branch)s' is not stacked."


class NoWorkingTree(BzrError):
    """No working tree exists.

    Raised when a working tree is required but none exists at the given location.
    """

    _fmt = 'No WorkingTree exists for "%(base)s".'

    def __init__(self, base):
        """Initialize with the base path where no working tree exists.

        Args:
            base: The path where a working tree was expected but not found.
        """
        BzrError.__init__(self)
        self.base = base


class NotLocalUrl(BzrError):
    """URL is not a local path.

    Raised when a local path is required but a non-local URL was provided.
    """

    _fmt = "%(url)s is not a local path."

    def __init__(self, url):
        """Initialize with the non-local URL.

        Args:
            url: The URL that is not a local path.
        """
        self.url = url


class WorkingTreeAlreadyPopulated(InternalBzrError):
    """Working tree is already populated.

    Raised when attempting to populate a working tree that already contains files.
    """

    _fmt = 'Working tree already populated in "%(base)s"'

    def __init__(self, base):
        """Initialize with the base path of the already populated working tree.

        Args:
            base: The path to the working tree that is already populated.
        """
        self.base = base


class NoWhoami(BzrError):
    """User identity not configured.

    Raised when the user's name and email address are not configured and are needed
    for an operation like committing.
    """

    _fmt = (
        "Unable to determine your name.\n"
        "Please, set your name with the 'whoami' command.\n"
        'E.g. brz whoami "Your Name <name@example.com>"'
    )


class CommandError(BzrError):
    """Error from user command.

    Raised when there is an error in user input or command usage.
    This is for malformed user commands; avoid raising this as a generic
    exception not caused by user input.
    """

    # Error from malformed user command; please avoid raising this as a
    # generic exception not caused by user input.
    #
    # I think it's a waste of effort to differentiate between errors that
    # are not intended to be caught anyway.  UI code need not subclass
    # CommandError, and non-UI code should not throw a subclass of
    # CommandError.  ADHB 20051211


# Provide the old name as backup, for the moment.
BzrCommandError = CommandError


class NotWriteLocked(BzrError):
    """Object is not write locked but needs to be.

    Raised when an operation requires a write lock but the object is not
    currently write locked.
    """

    _fmt = """%(not_locked)r is not write locked but needs to be."""

    def __init__(self, not_locked):
        """Initialize with the object that is not write locked.

        Args:
            not_locked: The object that needs to be write locked.
        """
        self.not_locked = not_locked


class StrictCommitFailed(BzrError):
    """Strict commit failed due to unknown files.

    Raised when a commit in strict mode is attempted but there are unknown
    files in the working tree.
    """

    _fmt = "Commit refused because there are unknown files in the tree"


# XXX: Should be unified with TransportError; they seem to represent the
# same thing
# RBC 20060929: I think that unifiying with TransportError would be a mistake
# - this is finer than a TransportError - and more useful as such. It
# differentiates between 'transport has failed' and 'operation on a transport
# has failed.'
class PathError(BzrError):
    """Generic path-related error.

    Base class for errors related to filesystem paths and operations.
    """

    _fmt = "Generic path error: %(path)r%(extra)s)"

    def __init__(self, path, extra=None):
        """Initialize with path and optional extra information.

        Args:
            path: The path that caused the error.
            extra: Optional additional error information.
        """
        BzrError.__init__(self)
        self.path = path
        if extra:
            self.extra = ": " + str(extra)
        else:
            self.extra = ""


class RenameFailedFilesExist(BzrError):
    """Rename failed because both source and destination exist.

    Raised when attempting to rename a file but both the source and destination
    files already exist, creating a conflict.
    """

    _fmt = (
        "Could not rename %(source)s => %(dest)s because both files exist."
        " (Use --after to tell brz about a rename that has already"
        " happened)%(extra)s"
    )

    def __init__(self, source, dest, extra=None):
        """Initialize with source and destination paths.

        Args:
            source: The source file path.
            dest: The destination file path.
            extra: Optional additional error information.
        """
        BzrError.__init__(self)
        self.source = str(source)
        self.dest = str(dest)
        if extra:
            self.extra = " " + str(extra)
        else:
            self.extra = ""


class NotADirectory(PathError):
    """Path is not a directory.

    Raised when a directory is expected but the path points to a non-directory.
    """

    _fmt = '"%(path)s" is not a directory %(extra)s'


class NotInWorkingDirectory(PathError):
    """Path is not in the working directory.

    Raised when a path is outside the working directory when it should be inside.
    """

    _fmt = '"%(path)s" is not in the working directory %(extra)s'


class DirectoryNotEmpty(PathError):
    """Directory is not empty.

    Raised when attempting to remove a directory that still contains files.
    """

    _fmt = 'Directory not empty: "%(path)s"%(extra)s'


class HardLinkNotSupported(PathError):
    """Hard linking is not supported.

    Raised when attempting to create a hard link on a filesystem that doesn't support it.
    """

    _fmt = 'Hard-linking "%(path)s" is not supported'


class ReadingCompleted(InternalBzrError):
    """Reading from request already completed.

    Raised when attempting to read from a MediumRequest that has already
    completed reading.
    """

    _fmt = (
        "The MediumRequest '%(request)s' has already had finish_reading "
        "called upon it - the request has been completed and no more "
        "data may be read."
    )

    def __init__(self, request):
        """Initialize with the completed request.

        Args:
            request: The MediumRequest that has already completed reading.
        """
        self.request = request


class ResourceBusy(PathError):
    """Device or resource is busy.

    Raised when a filesystem operation fails because the resource is busy.
    """

    _fmt = 'Device or resource busy: "%(path)s"%(extra)s'


class PermissionDenied(PathError):
    """Permission denied for path operation.

    Raised when a filesystem operation is denied due to insufficient permissions.
    """

    _fmt = 'Permission denied: "%(path)s"%(extra)s'


class UnstackableLocationError(BzrError):
    """Branch cannot be stacked on the specified target.

    Raised when attempting to stack a branch on a target that is not
    suitable for stacking.
    """

    _fmt = "The branch '%(branch_url)s' cannot be stacked on '%(target_url)s'."

    def __init__(self, branch_url, target_url):
        """Initialize with branch and target URLs.

        Args:
            branch_url: URL of the branch to be stacked.
            target_url: URL of the target that cannot be stacked on.
        """
        BzrError.__init__(self)
        self.branch_url = branch_url
        self.target_url = target_url


class UnstackableRepositoryFormat(BzrError):
    """Repository format does not support stacking.

    Raised when attempting to use stacking features with a repository format
    that does not support stacking.
    """

    _fmt = (
        "The repository '%(url)s'(%(format)s) is not a stackable format. "
        "You will need to upgrade the repository to permit branch stacking."
    )

    def __init__(self, format, url):
        """Initialize with format and URL information.

        Args:
            format: The repository format that doesn't support stacking.
            url: URL of the repository.
        """
        BzrError.__init__(self)
        self.format = format
        self.url = url


class ReadError(PathError):
    """Error reading from file.

    Raised when a read operation from a file fails.
    """

    _fmt = """Error reading from %(path)r%(extra)r."""


class ShortReadvError(PathError):
    """readv() operation read fewer bytes than expected.

    Raised when a readv() operation reads fewer bytes than requested,
    indicating a potential file corruption or read error.
    """

    _fmt = (
        "readv() read %(actual)s bytes rather than %(length)s bytes"
        ' at %(offset)s for "%(path)s"%(extra)s'
    )

    internal_error = True

    def __init__(self, path, offset, length, actual, extra=None):
        """Initialize with read operation details.

        Args:
            path: The file path where the short read occurred.
            offset: The offset where the read was attempted.
            length: The number of bytes requested.
            actual: The actual number of bytes read.
            extra: Optional additional error information.
        """
        PathError.__init__(self, path, extra=extra)
        self.offset = offset
        self.length = length
        self.actual = actual


class PathNotChild(PathError):
    """Path is not a child of the specified base path.

    Raised when a path is expected to be within a base directory but is not.
    """

    _fmt = 'Path "%(path)s" is not a child of path "%(base)s"%(extra)s'

    internal_error = False

    def __init__(self, path, base, extra=None):
        """Initialize with the path, base, and optional extra information.

        Args:
            path: The path that is not a child of base.
            base: The expected parent path.
            extra: Optional additional error information.
        """
        BzrError.__init__(self)
        self.path = path
        self.base = base
        if extra:
            self.extra = ": " + str(extra)
        else:
            self.extra = ""


class InvalidNormalization(PathError):
    """Path is not unicode normalized.

    Raised when a path contains characters that are not in unicode normalized form.
    """

    _fmt = 'Path "%(path)s" is not unicode normalized'


# TODO: This is given a URL; we try to unescape it but doing that from inside
# the exception object is a bit undesirable.
# TODO: Probably this behavior of should be a common superclass
class NotBranchError(PathError):
    """Location is not a branch.

    Raised when an operation expects a branch but the location does not contain one.
    """

    _fmt = 'Not a branch: "%(path)s"%(detail)s.'

    def __init__(self, path, detail=None, controldir=None):
        """Initialize with path and optional detail information.

        Args:
            path: The path that is not a branch.
            detail: Optional detail about why it's not a branch.
            controldir: Optional control directory object.
        """
        from . import urlutils

        path = urlutils.unescape_for_display(path, "ascii")
        if detail is not None:
            detail = ": " + detail
        self.detail = detail
        self.controldir = controldir
        PathError.__init__(self, path=path)

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.__dict__!r}>"

    def _get_format_string(self):
        # GZ 2017-06-08: Not the best place to lazy fill detail in.
        if self.detail is None:
            self.detail = self._get_detail()
        return super()._get_format_string()

    def _get_detail(self):
        if self.controldir is not None:
            try:
                self.controldir.open_repository()
            except NoRepositoryPresent:
                return ""
            except Exception as e:
                # Just ignore unexpected errors.  Raising arbitrary errors
                # during str(err) can provoke strange bugs.  Concretely
                # Launchpad's codehosting managed to raise NotBranchError
                # here, and then get stuck in an infinite loop/recursion
                # trying to str() that error.  All this error really cares
                # about that there's no working repository there, and if
                # open_repository() fails, there probably isn't.
                return ": " + e.__class__.__name__
            else:
                return ": location is a repository"
        return ""


class NoSubmitBranch(PathError):
    """No submit branch configured.

    Raised when trying to access the submit branch but none has been configured.
    """

    _fmt = 'No submit branch available for branch "%(path)s"'

    def __init__(self, branch):
        """Initialize with the branch that has no submit branch.

        Args:
            branch: The branch object that lacks a submit branch setting.
        """
        from . import urlutils

        self.path = urlutils.unescape_for_display(branch.base, "ascii")


class AlreadyControlDirError(PathError):
    """Control directory already exists.

    Raised when attempting to initialize a control directory where one already exists.
    """

    _fmt = 'A control directory already exists: "%(path)s".'


class AlreadyBranchError(PathError):
    """Location already contains a branch.

    Raised when attempting to create a branch where one already exists.
    """

    _fmt = 'Already a branch: "%(path)s".'


class InvalidBranchName(PathError):
    """Invalid branch name specified.

    Raised when a branch name contains invalid characters or format.
    """

    _fmt = "Invalid branch name: %(name)s"

    def __init__(self, name):
        """Initialize with the invalid branch name.

        Args:
            name: The invalid branch name.
        """
        BzrError.__init__(self)
        self.name = name


class ParentBranchExists(AlreadyBranchError):
    """Parent branch already exists.

    Raised when attempting to create a parent branch that already exists.
    """

    _fmt = 'Parent branch already exists: "%(path)s".'


class BranchExistsWithoutWorkingTree(PathError):
    """Directory contains a branch but no working tree.

    Raised when a directory contains a branch but no working tree,
    and a working tree is expected or required.
    """

    _fmt = 'Directory contains a branch, but no working tree \
(use brz checkout if you wish to build a working tree): "%(path)s"'


class InaccessibleParent(PathError):
    """Parent directory is not accessible.

    Raised when a parent directory cannot be accessed given a base path
    and relative path.
    """

    _fmt = 'Parent not accessible given base "%(base)s" and relative path "%(path)s"'

    def __init__(self, path, base):
        """Initialize with path and base information.

        Args:
            path: The relative path that cannot be accessed.
            base: The base path used for resolution.
        """
        PathError.__init__(self, path)
        self.base = base


class NoRepositoryPresent(BzrError):
    """No repository present at location.

    Raised when a repository is expected but none is found at the given location.
    """

    _fmt = 'No repository present: "%(path)s"'

    def __init__(self, controldir):
        """Initialize with the control directory that has no repository.

        Args:
            controldir: The control directory object that lacks a repository.
        """
        BzrError.__init__(self)
        self.path = controldir.transport.clone("..").base


class UnsupportedFormatError(BzrError):
    """Unsupported branch format.

    Raised when encountering a branch format that is not supported by this version.
    """

    _fmt = "Unsupported branch format: %(format)s\nPlease run 'brz upgrade'"


class UnsupportedVcs(UnsupportedFormatError):
    """Unsupported version control system.

    Raised when encountering a VCS that is not supported.
    """

    vcs: str

    _fmt = "Unsupported version control system: %(vcs)s"


class UnknownFormatError(BzrError):
    """Unknown format encountered.

    Raised when encountering a format that is not recognized.
    """

    _fmt = "Unknown %(kind)s format: %(format)r"

    def __init__(self, format, kind="branch"):
        """Initialize with the unknown format information.

        Args:
            format: The unrecognized format.
            kind: The type of object with the unknown format.
        """
        self.kind = kind
        self.format = format


class IncompatibleFormat(BzrError):
    """Format is not compatible with control directory version.

    Raised when a format is not compatible with the control directory
    version being used.
    """

    _fmt = "Format %(format)s is not compatible with .bzr version %(controldir)s."

    def __init__(self, format, controldir_format):
        """Initialize with format compatibility information.

        Args:
            format: The format that is incompatible.
            controldir_format: The control directory format.
        """
        BzrError.__init__(self)
        self.format = format
        self.controldir = controldir_format


class ParseFormatError(BzrError):
    """Parse error in format file.

    Raised when a format file cannot be parsed due to syntax errors or
    invalid content.
    """

    _fmt = "Parse error on line %(lineno)d of %(format)s format: %(line)s"

    def __init__(self, format, lineno, line, text):
        """Initialize with parse error details.

        Args:
            format: The format being parsed.
            lineno: The line number where the error occurred.
            line: The problematic line content.
            text: The full text being parsed.
        """
        BzrError.__init__(self)
        self.format = format
        self.lineno = lineno
        self.line = line
        self.text = text


class IncompatibleRepositories(BzrError):
    """Two repositories are not compatible.

    Raised when attempting an operation between two repositories that have
    incompatible formats or features.

    Note:
        The source and target repositories are permitted to be strings:
        this exception is thrown from the smart server and may refer to a
        repository the client hasn't opened.
    """

    _fmt = "%(target)s\nis not compatible with\n%(source)s\n%(details)s"

    def __init__(self, source, target, details=None):
        """Initialize with repository compatibility information.

        Args:
            source: The source repository (may be a string).
            target: The target repository (may be a string).
            details: Optional details about the incompatibility.
        """
        if details is None:
            details = "(no details)"
        BzrError.__init__(self, target=target, source=source, details=details)


class IncompatibleRevision(BzrError):
    """Revision is not compatible with repository format.

    Raised when a revision cannot be processed by the current repository
    format, typically during format upgrades or downgrades.
    """

    _fmt = "Revision is not compatible with %(repo_format)s"

    def __init__(self, repo_format):
        """Initialize with repository format information.

        Args:
            repo_format: The repository format that is incompatible.
        """
        BzrError.__init__(self)
        self.repo_format = repo_format


class AlreadyVersionedError(BzrError):
    """Path is already versioned but was expected not to be.

    Raised when attempting to add a path to version control that is
    already under version control.
    """

    _fmt = "%(context_info)s%(path)s is already versioned."

    def __init__(self, path, context_info=None):
        """Initialize with path and context information.

        Args:
            path: The path which is versioned, in user-friendly form.
            context_info: Optional context information explaining why this
                path was expected not to be versioned.
        """
        BzrError.__init__(self)
        self.path = path
        if context_info is None:
            self.context_info = ""
        else:
            self.context_info = context_info + ". "


class NotVersionedError(BzrError):
    """Path is not versioned but was expected to be.

    Raised when attempting to perform a version control operation on a path
    that is not under version control.
    """

    _fmt = "%(context_info)s%(path)s is not versioned."

    def __init__(self, path, context_info=None):
        """Initialize with path and context information.

        Args:
            path: The path which is not versioned, in user-friendly form.
            context_info: Optional context information explaining why this
                path was expected to be versioned.
        """
        BzrError.__init__(self)
        self.path = path
        if context_info is None:
            self.context_info = ""
        else:
            self.context_info = context_info + ". "


class PathsNotVersionedError(BzrError):
    """Multiple paths are not versioned.

    Raised when reporting that several paths are not under version control
    when they were expected to be.
    """

    _fmt = "Path(s) are not versioned: %(paths_as_string)s"

    def __init__(self, paths):
        """Initialize with a list of non-versioned paths.

        Args:
            paths: List of paths that are not versioned.
        """
        from .osutils import quotefn

        BzrError.__init__(self)
        self.paths = paths
        self.paths_as_string = " ".join([quotefn(p) for p in paths])


class PathsDoNotExist(BzrError):
    """Multiple paths do not exist.

    Raised when reporting that paths are neither versioned nor present in
    the working tree.
    """

    _fmt = "Path(s) do not exist: %(paths_as_string)s%(extra)s"

    def __init__(self, paths, extra=None):
        """Initialize with a list of non-existent paths.

        Args:
            paths: List of paths that do not exist.
            extra: Optional additional error information.
        """
        # circular import
        from .osutils import quotefn

        BzrError.__init__(self)
        self.paths = paths
        self.paths_as_string = " ".join([quotefn(p) for p in paths])
        if extra:
            self.extra = ": " + str(extra)
        else:
            self.extra = ""


class BadFileKindError(BzrError):
    """Cannot operate on file of unsupported kind.

    Raised when attempting to perform an operation on a file whose type
    (kind) is not supported by the current operation.
    """

    _fmt = 'Cannot operate on "%(filename)s" of unsupported kind "%(kind)s"'

    def __init__(self, filename, kind):
        """Initialize with filename and file kind.

        Args:
            filename: The name of the file with unsupported kind.
            kind: The unsupported file kind.
        """
        BzrError.__init__(self, filename=filename, kind=kind)


class ForbiddenControlFileError(BzrError):
    """Cannot operate on a control file.

    Raised when attempting to perform a user operation on a file that is
    part of the version control system's internal control structure.
    """

    _fmt = 'Cannot operate on "%(filename)s" because it is a control file'


class LockError(InternalBzrError):
    """Base class for lock-related errors.

    All exceptions from lock/unlock functions should inherit from this class.
    The original exception is available as e.original_error.
    """

    _fmt = "Lock error: %(msg)s"

    # All exceptions from the lock/unlock functions should be from
    # this exception class.  They will be translated as necessary. The
    # original exception is available as e.original_error
    #
    # New code should prefer to raise specific subclasses
    def __init__(self, msg):
        """Initialize with a lock error message.

        Args:
            msg: Description of the lock error.
        """
        self.msg = msg


class LockActive(LockError):
    """Lock is currently active and cannot be broken.

    Raised when attempting to break a lock that is still in use.
    """

    _fmt = "The lock for '%(lock_description)s' is in use and cannot be broken."

    internal_error = False

    def __init__(self, lock_description):
        """Initialize with a description of the active lock.

        Args:
            lock_description: Description of the lock that is active.
        """
        self.lock_description = lock_description


class CommitNotPossible(LockError):
    """Commit attempted without write lock.

    Raised when a commit is attempted but no write lock is held.
    """

    _fmt = "A commit was attempted but we do not have a write lock open."

    def __init__(self):
        pass


class AlreadyCommitted(LockError):
    """Rollback requested but not possible.

    Raised when a rollback is requested but cannot be accomplished.
    """

    _fmt = "A rollback was requested, but is not able to be accomplished."

    def __init__(self):
        pass


class ReadOnlyError(LockError):
    """Write attempted on read-only object.

    Raised when a write operation is attempted on an object that is read-only.
    """

    _fmt = "A write attempt was made in a read only transaction on %(obj)s"

    # TODO: There should also be an error indicating that you need a write
    # lock and don't have any lock at all... mbp 20070226

    def __init__(self, obj):
        """Initialize with the read-only object.

        Args:
            obj: The object that is read-only.
        """
        self.obj = obj


class LockFailed(LockError):
    """Lock acquisition failed.

    Raised when a lock cannot be acquired for a specified reason.
    """

    internal_error = False

    _fmt = "Cannot lock %(lock)s: %(why)s"

    def __init__(self, lock, why):
        """Initialize with lock and failure reason.

        Args:
            lock: The lock that failed to be acquired.
            why: The reason why the lock failed.
        """
        LockError.__init__(self, "")
        self.lock = lock
        self.why = why


class OutSideTransaction(BzrError):
    """Operation attempted outside of transaction.

    Raised when a transaction-related operation is attempted after the
    transaction has already finished.
    """

    _fmt = (
        "A transaction related operation was attempted after the transaction finished."
    )


class ObjectNotLocked(LockError):
    """Object is not locked.

    Raised when an operation requires a locked object but the object is
    not currently locked.

    Note:
        This indicates that any particular object is not locked. See also
        LockNotHeld which means that a particular *lock* object is not held
        by the caller -- perhaps they should be unified.
    """

    _fmt = "%(obj)r is not locked"

    def __init__(self, obj):
        """Initialize with the unlocked object.

        Args:
            obj: The object that is not locked.
        """
        self.obj = obj


class ReadOnlyObjectDirtiedError(ReadOnlyError):
    """Attempt to modify object in read-only transaction.

    Raised when attempting to modify an object within a read-only transaction.
    """

    _fmt = "Cannot change object %(obj)r in read only transaction"

    def __init__(self, obj):
        """Initialize with the object that was attempted to be modified.

        Args:
            obj: The object that cannot be changed in read-only mode.
        """
        self.obj = obj


class UnlockableTransport(LockError):
    """Transport cannot be locked because it is read-only.

    Raised when attempting to acquire a lock on a transport that is
    read-only and therefore cannot be locked.
    """

    internal_error = False

    _fmt = "Cannot lock: transport is read only: %(transport)s"

    def __init__(self, transport):
        """Initialize with the read-only transport.

        Args:
            transport: The transport that cannot be locked.
        """
        self.transport = transport


class LockContention(LockError):
    """Lock contention detected.

    Raised when a lock cannot be acquired because another process or
    thread is already holding it.
    """

    _fmt = 'Could not acquire lock "%(lock)s": %(msg)s'

    internal_error = False

    def __init__(self, lock, msg=""):
        """Initialize with lock and optional message.

        Args:
            lock: The lock that could not be acquired.
            msg: Optional message providing additional details.
        """
        self.lock = lock
        self.msg = msg


class LockBroken(LockError):
    """Lock was broken while still open.

    Raised when a lock is forcibly broken while it was still being used,
    which may indicate storage consistency issues.
    """

    _fmt = "Lock was broken while still open: %(lock)s - check storage consistency!"

    internal_error = False

    def __init__(self, lock):
        """Initialize with the broken lock.

        Args:
            lock: The lock that was broken while open.
        """
        self.lock = lock


class LockBreakMismatch(LockError):
    """Lock break attempted on wrong lock holder.

    Raised when attempting to break a lock that was released and re-acquired
    by a different holder than the one being targeted for breaking.
    """

    _fmt = (
        "Lock was released and re-acquired before being broken:"
        " %(lock)s: held by %(holder)r, wanted to break %(target)r"
    )

    internal_error = False

    def __init__(self, lock, holder, target):
        """Initialize with lock holder information.

        Args:
            lock: The lock that has a holder mismatch.
            holder: The current holder of the lock.
            target: The target holder that was expected to be broken.
        """
        self.lock = lock
        self.holder = holder
        self.target = target


class LockCorrupt(LockError):
    """Lock file is corrupted.

    Raised when a lock appears to be held but the lock file contains
    corrupted or invalid data.
    """

    _fmt = (
        "Lock is apparently held, but corrupted: %(corruption_info)s\n"
        "Use 'brz break-lock' to clear it"
    )

    internal_error = False

    def __init__(self, corruption_info, file_data=None):
        """Initialize with corruption information.

        Args:
            corruption_info: Information about how the lock is corrupted.
            file_data: Optional raw file data from the corrupted lock.
        """
        self.corruption_info = corruption_info
        self.file_data = file_data


class LockNotHeld(LockError):
    """Lock is not currently held.

    Raised when attempting an operation that requires holding a specific
    lock, but that lock is not currently held by the caller.
    """

    _fmt = "Lock not held: %(lock)s"

    internal_error = False

    def __init__(self, lock):
        """Initialize with the lock that is not held.

        Args:
            lock: The lock that is not held.
        """
        self.lock = lock


class TokenLockingNotSupported(LockError):
    """Object does not support token-based locking.

    Raised when attempting to use token-based locking on an object that
    does not support this feature.
    """

    _fmt = "The object %(obj)s does not support token specifying a token when locking."

    def __init__(self, obj):
        """Initialize with the object that doesn't support token locking.

        Args:
            obj: The object that does not support token locking.
        """
        self.obj = obj


class TokenMismatch(LockBroken):
    """Lock token mismatch.

    Raised when the provided lock token does not match the expected
    lock token, indicating that the lock may have been broken and
    re-acquired by another process.
    """

    _fmt = "The lock token %(given_token)r does not match lock token %(lock_token)r."

    internal_error = True

    def __init__(self, given_token, lock_token):
        """Initialize with token information.

        Args:
            given_token: The token that was provided.
            lock_token: The token that was expected.
        """
        self.given_token = given_token
        self.lock_token = lock_token


class UpgradeReadonly(BzrError):
    """Cannot upgrade read-only location.

    Raised when attempting to upgrade a repository or branch at a read-only
    URL where write access is required for the upgrade process.
    """

    _fmt = "Upgrade URL cannot work with readonly URLs."


class UpToDateFormat(BzrError):
    """Branch format is already up to date.

    Raised when attempting to upgrade a branch format that is already
    at the most recent version.
    """

    _fmt = "The branch format %(format)s is already at the most recent format."

    def __init__(self, format):
        """Initialize with the format that is already up to date.

        Args:
            format: The format that is already current.
        """
        BzrError.__init__(self)
        self.format = format


class NoSuchRevision(InternalBzrError):
    """Revision does not exist in branch.

    Raised when attempting to access a revision that does not exist
    in the specified branch or revision store.
    """

    revision: bytes

    _fmt = "%(branch)s has no revision %(revision)s"

    def __init__(self, branch, revision):
        """Initialize with branch and revision information.

        Args:
            branch: The branch where the revision was not found.
                   May be an internal object like a KnitRevisionStore.
            revision: The revision that was not found.
        """
        BzrError.__init__(self, branch=branch, revision=revision)


class RangeInChangeOption(BzrError):
    """Revision range provided to --change option.

    Raised when a revision range is provided to the --change option
    which only accepts single revisions.
    """

    _fmt = "Option --change does not accept revision ranges"


class NoSuchRevisionSpec(BzrError):
    """No revision specification namespace registered.

    Raised when attempting to parse a revision specification string
    that does not match any registered namespace.
    """

    _fmt = "No namespace registered for string: %(spec)r"

    def __init__(self, spec):
        """Initialize with the invalid revision specification.

        Args:
            spec: The revision specification string that has no namespace.
        """
        BzrError.__init__(self, spec=spec)


class NoSuchRevisionInTree(NoSuchRevision):
    """Revision is not accessible in tree.

    Raised when using Tree.revision_tree() and the requested revision
    is not present or accessible in the tree.
    """

    _fmt = "The revision id {%(revision_id)s} is not present in the tree %(tree)s."

    def __init__(self, tree, revision_id):
        """Initialize with tree and revision information.

        Args:
            tree: The tree where the revision was not found.
            revision_id: The revision ID that is not present in the tree.
        """
        BzrError.__init__(self)
        self.tree = tree
        self.revision_id = revision_id


class AppendRevisionsOnlyViolation(BzrError):
    """Operation would violate append_revisions_only setting.

    Raised when attempting an operation that would change the main history
    of a branch that has the append_revisions_only setting enabled.
    """

    _fmt = (
        "Operation denied because it would change the main history,"
        " which is not permitted by the append_revisions_only setting on"
        ' branch "%(location)s".'
    )

    def __init__(self, location):
        """Initialize with the branch location.

        Args:
            location: The location of the branch with append_revisions_only set.
        """
        import breezy.urlutils as urlutils

        location = urlutils.unescape_for_display(location, "ascii")
        BzrError.__init__(self, location=location)


class DivergedBranches(BzrError):
    """Branches have diverged.

    Raised when two branches have diverged and no longer share a common
    recent history, requiring a merge to reconcile them.
    """

    _fmt = (
        "These branches have diverged."
        " Use the missing command to see how.\n"
        "Use the merge command to reconcile them."
    )

    def __init__(self, branch1, branch2):
        """Initialize with the two diverged branches.

        Args:
            branch1: The first diverged branch.
            branch2: The second diverged branch.
        """
        self.branch1 = branch1
        self.branch2 = branch2


class NotLefthandHistory(InternalBzrError):
    """History does not follow left-hand parents.

    Raised when a supplied history does not follow the left-hand parent
    convention, which is required for certain operations.
    """

    _fmt = "Supplied history does not follow left-hand parents"

    def __init__(self, history):
        """Initialize with the invalid history.

        Args:
            history: The history that does not follow left-hand parents.
        """
        BzrError.__init__(self, history=history)


class UnrelatedBranches(BzrError):
    """Branches have no common ancestor.

    Raised when attempting to merge or compare branches that have no
    common ancestor and no merge base revision was specified.
    """

    _fmt = "Branches have no common ancestor, and no merge base revision was specified."


class CannotReverseCherrypick(BzrError):
    """Selected merge cannot perform reverse cherrypicks.

    Raised when the selected merge algorithm does not support reverse
    cherrypick operations. Alternative merge algorithms should be used.
    """

    _fmt = "Selected merge cannot perform reverse cherrypicks.  Try merge3 or diff3."


class NoCommonAncestor(BzrError):
    """Revisions have no common ancestor.

    Raised when attempting to find a common ancestor between two revisions
    that do not share any common history.
    """

    _fmt = "Revisions have no common ancestor: %(revision_a)s %(revision_b)s"

    def __init__(self, revision_a, revision_b):
        """Initialize with the two revisions.

        Args:
            revision_a: The first revision.
            revision_b: The second revision.
        """
        self.revision_a = revision_a
        self.revision_b = revision_b


class NoCommonRoot(BzrError):
    """Revisions are not derived from the same root.

    Raised when attempting an operation on revisions that do not share
    a common root revision.
    """

    _fmt = (
        "Revisions are not derived from the same root: %(revision_a)s %(revision_b)s."
    )

    def __init__(self, revision_a, revision_b):
        """Initialize with the two revisions.

        Args:
            revision_a: The first revision.
            revision_b: The second revision.
        """
        BzrError.__init__(self, revision_a=revision_a, revision_b=revision_b)


class NotAncestor(BzrError):
    """Revision is not an ancestor of another revision.

    Raised when attempting an operation that requires one revision to be
    an ancestor of another, but the ancestry relationship does not exist.
    """

    _fmt = "Revision %(rev_id)s is not an ancestor of %(not_ancestor_id)s"

    def __init__(self, rev_id, not_ancestor_id):
        """Initialize with revision information.

        Args:
            rev_id: The revision that is not an ancestor.
            not_ancestor_id: The revision that was expected to be a descendant.
        """
        BzrError.__init__(self, rev_id=rev_id, not_ancestor_id=not_ancestor_id)


class NoCommits(BranchError):
    """Branch has no commits.

    Raised when attempting an operation that requires commits on a branch
    that has no revision history.
    """

    _fmt = "Branch %(branch)s has no commits."


class UnlistableStore(BzrError):
    """Store is not listable.

    Raised when attempting to list the contents of a store that does
    not support listing operations.
    """

    def __init__(self, store):
        """Initialize with the non-listable store.

        Args:
            store: The store that is not listable.
        """
        BzrError.__init__(self, f"Store {store} is not listable")


class UnlistableBranch(BzrError):
    """Branch stores are not listable.

    Raised when attempting to list the stores of a branch that does
    not support listing operations.
    """

    def __init__(self, br):
        """Initialize with the branch with non-listable stores.

        Args:
            br: The branch whose stores are not listable.
        """
        BzrError.__init__(self, f"Stores for branch {br} are not listable")


class BoundBranchOutOfDate(BzrError):
    """Bound branch is out of date with master.

    Raised when a bound branch is behind its master branch and needs
    to be updated before certain operations can proceed.
    """

    _fmt = (
        "Bound branch %(branch)s is out of date with master branch"
        " %(master)s.%(extra_help)s"
    )

    def __init__(self, branch, master):
        """Initialize with branch and master information.

        Args:
            branch: The bound branch that is out of date.
            master: The master branch that is ahead.
        """
        BzrError.__init__(self)
        self.branch = branch
        self.master = master
        self.extra_help = ""


class CommitToDoubleBoundBranch(BzrError):
    """Cannot commit to a doubly-bound branch.

    Raised when attempting to commit to a branch that is bound to a master
    which is itself bound to another remote branch, creating an unsupported
    double-binding scenario.
    """

    _fmt = (
        "Cannot commit to branch %(branch)s."
        " It is bound to %(master)s, which is bound to %(remote)s."
    )

    def __init__(self, branch, master, remote):
        """Initialize with branch binding information.

        Args:
            branch: The branch being committed to.
            master: The master branch that the branch is bound to.
            remote: The remote branch that the master is bound to.
        """
        BzrError.__init__(self)
        self.branch = branch
        self.master = master
        self.remote = remote


class OverwriteBoundBranch(BzrError):
    """Cannot overwrite a bound branch.

    Raised when attempting to pull with --overwrite to a branch that is
    bound to a master, which is not allowed.
    """

    _fmt = "Cannot pull --overwrite to a branch which is bound %(branch)s"

    def __init__(self, branch):
        """Initialize with the bound branch.

        Args:
            branch: The bound branch that cannot be overwritten.
        """
        BzrError.__init__(self)
        self.branch = branch


class BoundBranchConnectionFailure(BzrError):
    """Failed to connect to target of bound branch.

    Raised when a bound branch cannot connect to its master branch,
    preventing synchronization operations.
    """

    _fmt = (
        "Unable to connect to target of bound branch %(branch)s"
        " => %(target)s: %(error)s"
    )

    def __init__(self, branch, target, error):
        """Initialize with connection failure details.

        Args:
            branch: The bound branch that failed to connect.
            target: The target master branch.
            error: The connection error that occurred.
        """
        BzrError.__init__(self)
        self.branch = branch
        self.target = target
        self.error = error


class VersionedFileError(BzrError):
    """Base class for versioned file errors.

    Raised when operations on versioned files encounter problems.
    """

    _fmt = "Versioned file error"


class RevisionNotPresent(VersionedFileError):
    """Revision not present in versioned file.

    Raised when attempting to access a revision that does not exist
    in the specified versioned file.
    """

    _fmt = 'Revision {%(revision_id)s} not present in "%(file_id)s".'

    def __init__(self, revision_id, file_id):
        """Initialize with revision and file information.

        Args:
            revision_id: The revision ID that is not present.
            file_id: The file ID where the revision was not found.
        """
        VersionedFileError.__init__(self)
        self.revision_id = revision_id
        self.file_id = file_id


class RevisionAlreadyPresent(VersionedFileError):
    """Revision already present in versioned file.

    Raised when attempting to add a revision that already exists
    in the specified versioned file.
    """

    _fmt = 'Revision {%(revision_id)s} already present in "%(file_id)s".'

    def __init__(self, revision_id, file_id):
        """Initialize with revision and file information.

        Args:
            revision_id: The revision ID that is already present.
            file_id: The file ID where the revision already exists.
        """
        VersionedFileError.__init__(self)
        self.revision_id = revision_id
        self.file_id = file_id


class VersionedFileInvalidChecksum(VersionedFileError):
    """Text checksum validation failed.

    Raised when the checksum of text in a versioned file does not match
    the expected checksum, indicating data corruption.
    """

    _fmt = "Text did not match its checksum: %(msg)s"


class NoSuchExportFormat(BzrError):
    """Export format not supported.

    Raised when attempting to export to a format that is not
    supported by the export system.
    """

    _fmt = "Export format %(format)r not supported"

    def __init__(self, format):
        """Initialize with the unsupported format.

        Args:
            format: The export format that is not supported.
        """
        BzrError.__init__(self)
        self.format = format


class TransportError(BzrError):
    """Base class for transport-related errors.

    Raised when operations on transports (network, filesystem, etc.) fail.
    """

    _fmt = "Transport error: %(msg)s %(orig_error)s"

    def __init__(self, msg=None, orig_error=None):
        """Initialize with transport error information.

        Args:
            msg: Optional error message.
            orig_error: Optional original exception that caused the error.
        """
        if msg is None and orig_error is not None:
            msg = str(orig_error)
        if orig_error is None:
            orig_error = ""
        if msg is None:
            msg = ""
        self.msg = msg
        self.orig_error = orig_error
        BzrError.__init__(self)


class SmartProtocolError(TransportError):
    """Generic smart protocol error.

    Raised when the smart protocol encounters an error.
    """

    _fmt = "Generic bzr smart protocol error: %(details)s"

    def __init__(self, details):
        """Initialize with error details.

        Args:
            details: Details about the smart protocol error.
        """
        self.details = details


class UnexpectedProtocolVersionMarker(TransportError):
    """Unexpected protocol version marker received.

    Raised when receiving a protocol version marker that is not
    recognized or expected.
    """

    _fmt = "Received bad protocol version marker: %(marker)r"

    def __init__(self, marker):
        """Initialize with the unexpected marker.

        Args:
            marker: The unexpected protocol version marker.
        """
        self.marker = marker


class UnknownSmartMethod(InternalBzrError):
    """Server does not recognize smart method.

    Raised when the server receives a smart protocol request with
    an unknown or unsupported method verb.
    """

    _fmt = "The server does not recognise the '%(verb)s' request."

    def __init__(self, verb):
        """Initialize with the unknown method verb.

        Args:
            verb: The smart method verb that is not recognized.
        """
        self.verb = verb


# A set of semi-meaningful errors which can be thrown
class TransportNotPossible(TransportError):
    """Transport operation not possible.

    Raised when a requested transport operation cannot be performed.
    """

    _fmt = "Transport operation not possible: %(msg)s %(orig_error)s"


class SocketConnectionError(ConnectionError):
    """Socket connection error.

    Raised when a socket connection fails.
    """

    def __init__(self, host, port=None, msg=None, orig_error=None):
        """Initialize with connection details.

        Args:
            host: The hostname that connection failed to.
            port: Optional port number.
            msg: Optional error message.
            orig_error: Optional original exception.
        """
        if msg is None:
            msg = "Failed to connect to"
        orig_error = "" if orig_error is None else "; " + str(orig_error)
        self.host = host
        port = "" if port is None else f":{port}"
        self.port = port
        ConnectionError.__init__(self, f"{msg} {host}{port}{orig_error}")


class ConnectionTimeout(ConnectionError):
    """Connection timeout error.

    Raised when a connection times out.
    """

    _fmt = "Connection Timeout: %(msg)s%(orig_error)s"

    def __init__(self, msg=None, orig_error=None):
        """Initialize with timeout details.

        Args:
            msg: Optional timeout message.
            orig_error: Optional original exception that caused the timeout.
        """
        if orig_error is None:
            orig_error = ""
        else:
            orig_error = "; " + str(orig_error)
        if msg is None:
            msg = "Connection timed out"
        ConnectionError.__init__(self, f"{msg}{orig_error}")


class InvalidRange(TransportError):
    """Invalid range access in file.

    Raised when attempting an invalid range access operation.
    """

    _fmt = "Invalid range access in %(path)s at %(offset)s: %(msg)s"

    def __init__(self, path, offset, msg=None):
        """Initialize with path, offset and optional message.

        Args:
            path: The path where the invalid range access was attempted.
            offset: The invalid offset.
            msg: Optional error message.
        """
        TransportError.__init__(self, msg)
        self.path = path
        self.offset = offset


class InvalidHttpResponse(TransportError):
    """Invalid HTTP response received.

    Raised when an HTTP response is malformed or does not conform
    to expected format.
    """

    _fmt = "Invalid http response for %(path)s: %(msg)s%(orig_error)s"

    def __init__(self, path, msg, orig_error=None, headers=None):
        """Initialize with response details.

        Args:
            path: The path that generated the invalid response.
            msg: Error message describing the invalid response.
            orig_error: Optional original exception.
            headers: Optional HTTP headers from the response.
        """
        self.path = path
        if orig_error is None:
            orig_error = ""
        else:
            # This is reached for obscure and unusual errors so we want to
            # preserve as much info as possible to ease debug.
            orig_error = f": {orig_error!r}"
        self.headers = headers
        TransportError.__init__(self, msg, orig_error=orig_error)


class UnexpectedHttpStatus(InvalidHttpResponse):
    """Unexpected HTTP status code received.

    Raised when an HTTP response contains a status code that was
    not expected for the operation.
    """

    _fmt = "Unexpected HTTP status %(code)d for %(path)s: %(extra)s"

    def __init__(self, path, code, extra=None, headers=None):
        """Initialize with HTTP status details.

        Args:
            path: The path that returned the unexpected status.
            code: The unexpected HTTP status code.
            extra: Optional additional information about the status.
            headers: Optional HTTP headers from the response.
        """
        self.path = path
        self.code = code
        self.extra = extra or ""
        full_msg = "status code %d unexpected" % code
        if extra is not None:
            full_msg += ": " + extra
        InvalidHttpResponse.__init__(self, path, full_msg, headers=headers)


class BadHttpRequest(UnexpectedHttpStatus):
    """Bad HTTP request error.

    Raised when an HTTP request is malformed or contains invalid parameters.
    """

    _fmt = "Bad http request for %(path)s: %(reason)s"

    def __init__(self, path, reason):
        self.path = path
        self.reason = reason
        TransportError.__init__(self, reason)


class InvalidHttpRange(InvalidHttpResponse):
    """Invalid HTTP range header.

    Raised when an HTTP range request contains an invalid range specification.
    """

    _fmt = "Invalid http range %(range)r for %(path)s: %(msg)s"

    def __init__(self, path, range, msg):
        self.range = range
        InvalidHttpResponse.__init__(self, path, msg)


class HttpBoundaryMissing(InvalidHttpResponse):
    """A multipart response ends with no boundary marker.

    This is a special case caused by buggy proxies, described in
    <https://bugs.launchpad.net/bzr/+bug/198646>.
    """

    _fmt = "HTTP MIME Boundary missing for %(path)s: %(msg)s"

    def __init__(self, path, msg):
        InvalidHttpResponse.__init__(self, path, msg)


class InvalidHttpContentType(InvalidHttpResponse):
    """Invalid HTTP Content-Type header.

    Raised when an HTTP response contains an unexpected or invalid Content-Type header.
    """

    _fmt = 'Invalid http Content-type "%(ctype)s" for %(path)s: %(msg)s'

    def __init__(self, path, ctype, msg):
        self.ctype = ctype
        InvalidHttpResponse.__init__(self, path, msg)


class RedirectRequested(TransportError):
    """HTTP redirect response received.

    Raised when an HTTP request receives a redirect response that needs to be handled.
    """

    _fmt = "%(source)s is%(permanently)s redirected to %(target)s"

    def __init__(self, source, target, is_permanent=False):
        self.source = source
        self.target = target
        if is_permanent:
            self.permanently = " permanently"
        else:
            self.permanently = ""
        TransportError.__init__(self)


class TooManyRedirections(TransportError):
    """Too many HTTP redirections encountered.

    Raised when the number of HTTP redirections exceeds the maximum allowed limit,
    potentially indicating a redirect loop.
    """

    _fmt = "Too many redirections"


class ConflictsInTree(BzrError):
    """Working tree has unresolved conflicts.

    Raised when attempting an operation that requires no conflicts but
    conflicts are present in the working tree.
    """

    _fmt = "Working tree has conflicts."


class DependencyNotPresent(BzrError):
    """Required dependency not present.

    Raised when a required Python library or external dependency is not available.
    """

    _fmt = 'Unable to import library "%(library)s": %(error)s'

    def __init__(self, library, error):
        """Initialize with the missing library and error information.

        Args:
            library: Name of the missing library.
            error: The import error that occurred.
        """
        BzrError.__init__(self, library=library, error=error)


class WorkingTreeNotRevision(BzrError):
    """Working tree has changed since last commit.

    Raised when the working tree has uncommitted changes but the operation
    requires it to be unchanged.
    """

    _fmt = (
        "The working tree for %(basedir)s has changed since"
        " the last commit, but weave merge requires that it be"
        " unchanged"
    )

    def __init__(self, tree):
        """Initialize with the changed working tree.

        Args:
            tree: The working tree that has uncommitted changes.
        """
        BzrError.__init__(self, basedir=tree.basedir)


class GraphCycleError(BzrError):
    """Cycle detected in graph.

    Raised when a cycle is detected in a directed graph that should be acyclic.
    """

    _fmt = "Cycle in graph %(graph)r"

    def __init__(self, graph):
        """Initialize with the graph containing the cycle.

        Args:
            graph: The graph object that contains a cycle.
        """
        BzrError.__init__(self)
        self.graph = graph


class WritingCompleted(InternalBzrError):
    """Writing to request already completed.

    Raised when attempting to write to a MediumRequest that has already
    finished its writing phase.
    """

    _fmt = (
        "The MediumRequest '%(request)s' has already had finish_writing "
        "called upon it - accept bytes may not be called anymore."
    )

    def __init__(self, request):
        self.request = request


class WritingNotComplete(InternalBzrError):
    """Writing to request not yet completed.

    Raised when attempting to read from a MediumRequest before the writing
    phase has been completed with finish_writing.
    """

    _fmt = (
        "The MediumRequest '%(request)s' has not has finish_writing "
        "called upon it - until the write phase is complete no "
        "data may be read."
    )

    def __init__(self, request):
        self.request = request


class NotConflicted(BzrError):
    """File is not conflicted.

    Raised when attempting a conflict resolution operation on a file that
    is not actually conflicted.
    """

    _fmt = "File %(filename)s is not conflicted."

    def __init__(self, filename):
        """Initialize with the non-conflicted filename.

        Args:
            filename: Name of the file that is not conflicted.
        """
        BzrError.__init__(self)
        self.filename = filename


class MediumNotConnected(InternalBzrError):
    """Medium is not connected.

    Raised when attempting to use a medium that is not connected.
    """

    _fmt = """The medium '%(medium)s' is not connected."""

    def __init__(self, medium):
        """Initialize with the disconnected medium.

        Args:
            medium: The medium that is not connected.
        """
        self.medium = medium


class MustUseDecorated(Exception):
    """Decorating function requests original command.

    Raised by a decorating function to indicate that the original command should be used.
    """

    _fmt = "A decorating function has requested its original command be used."


class NoBundleFound(BzrError):
    """No bundle found in file.

    Raised when expecting to find a bundle in a file but none is present.
    """

    _fmt = 'No bundle was found in "%(filename)s".'

    def __init__(self, filename):
        """Initialize with the filename that contains no bundle.

        Args:
            filename: The filename that was expected to contain a bundle.
        """
        BzrError.__init__(self)
        self.filename = filename


class BundleNotSupported(BzrError):
    """Bundle version not supported.

    Raised when encountering a bundle with an unsupported version.
    """

    _fmt = "Unable to handle bundle version %(version)s: %(msg)s"

    def __init__(self, version, msg):
        """Initialize with version and message information.

        Args:
            version: The unsupported bundle version.
            msg: Error message describing the issue.
        """
        BzrError.__init__(self)
        self.version = version
        self.msg = msg


class MissingText(BzrError):
    """Text revision missing from branch.

    Raised when a branch is missing a specific text revision for a file that is
    needed for an operation.
    """

    _fmt = "Branch %(base)s is missing revision %(text_revision)s of %(file_id)s"

    def __init__(self, branch, text_revision, file_id):
        BzrError.__init__(self)
        self.branch = branch
        self.base = branch.base
        self.text_revision = text_revision
        self.file_id = file_id


class DuplicateKey(BzrError):
    """Duplicate key in map.

    Raised when attempting to add a key that already exists in a map.
    """

    _fmt = "Key %(key)s is already present in map"


class DuplicateHelpPrefix(BzrError):
    """Help prefix appears multiple times in search path.

    Raised when a help prefix is registered multiple times in the help search path.
    """

    _fmt = "The prefix %(prefix)s is in the help search path twice."

    def __init__(self, prefix):
        self.prefix = prefix


class BzrBadParameter(InternalBzrError):
    """Base class for bad parameter errors.

    This exception should never be thrown directly, but serves as a base class for all
    parameter-to-function errors.
    """

    _fmt = "Bad parameter: %(param)r"

    def __init__(self, param):
        BzrError.__init__(self)
        self.param = param


class BzrBadParameterNotUnicode(BzrBadParameter):
    """Parameter is not unicode or UTF-8.

    Raised when a parameter that must be unicode or UTF-8 encoded is provided
    in a different encoding.
    """

    _fmt = "Parameter %(param)s is neither unicode nor utf8."


class BzrMoveFailedError(BzrError):
    """File move operation failed.

    Raised when a file or directory move operation cannot be completed.
    """

    _fmt = "Could not move %(from_path)s%(operator)s %(to_path)s%(_has_extra)s%(extra)s"

    def __init__(self, from_path="", to_path="", extra=None):
        from .osutils import splitpath

        BzrError.__init__(self)
        if extra:
            self.extra, self._has_extra = extra, ": "
        else:
            self.extra = self._has_extra = ""

        has_from = len(from_path) > 0
        has_to = len(to_path) > 0
        if has_from:
            self.from_path = splitpath(from_path)[-1]
        else:
            self.from_path = ""

        if has_to:
            self.to_path = splitpath(to_path)[-1]
        else:
            self.to_path = ""

        self.operator = ""
        if has_from and has_to:
            self.operator = " =>"
        elif has_from:
            self.from_path = "from " + from_path
        elif has_to:
            self.operator = "to"
        else:
            self.operator = "file"


class BzrRenameFailedError(BzrMoveFailedError):
    """File rename operation failed.

    Raised when a file or directory rename operation cannot be completed.
    """

    _fmt = (
        "Could not rename %(from_path)s%(operator)s %(to_path)s%(_has_extra)s%(extra)s"
    )

    def __init__(self, from_path, to_path, extra=None):
        BzrMoveFailedError.__init__(self, from_path, to_path, extra)


class BzrBadParameterNotString(BzrBadParameter):
    """Parameter is not a string.

    Raised when a parameter that must be a string or unicode string is provided
    with a different type.
    """

    _fmt = "Parameter %(param)s is not a string or unicode string."


class BzrBadParameterMissing(BzrBadParameter):
    """Required parameter is missing.

    Raised when a required parameter is not provided to a function or method.
    """

    _fmt = "Parameter %(param)s is required but not present."


class BzrBadParameterUnicode(BzrBadParameter):
    """Parameter is unicode but bytes expected.

    Raised when a unicode parameter is provided but only byte strings are permitted.
    """

    _fmt = "Parameter %(param)s is unicode but only byte-strings are permitted."


class BzrBadParameterContainsNewline(BzrBadParameter):
    """Parameter contains invalid newline character.

    Raised when a parameter contains a newline character where it is not permitted.
    """

    _fmt = "Parameter %(param)s contains a newline."


class ParamikoNotPresent(DependencyNotPresent):
    """Paramiko library is not available.

    Raised when paramiko is required for SFTP support but is not installed or cannot be imported.
    """

    _fmt = "Unable to import paramiko (required for sftp support): %(error)s"

    def __init__(self, error):
        DependencyNotPresent.__init__(self, "paramiko", error)


class UninitializableFormat(BzrError):
    """Format cannot be initialized by current Breezy version.

    Raised when attempting to initialize a format that is not supported by the current
    version of Breezy.
    """

    _fmt = "Format %(format)s cannot be initialised by this version of brz."

    def __init__(self, format):
        BzrError.__init__(self)
        self.format = format


class BadConversionTarget(BzrError):
    """Invalid conversion target format.

    Raised when attempting to convert from one format to another format that is
    not a valid conversion target.
    """

    _fmt = (
        "Cannot convert from format %(from_format)s to format %(format)s."
        "    %(problem)s"
    )

    def __init__(self, problem, format, from_format=None):
        BzrError.__init__(self)
        self.problem = problem
        self.format = format
        self.from_format = from_format or "(unspecified)"


class NoDiffFound(BzrError):
    """No appropriate diff tool found for file.

    Raised when no suitable diff tool can be found to generate differences for a specific file.
    """

    _fmt = 'Could not find an appropriate Differ for file "%(path)s"'

    def __init__(self, path):
        BzrError.__init__(self, path)


class ExecutableMissing(BzrError):
    """Required executable not found on system.

    Raised when a required external executable cannot be found in the system PATH.
    """

    _fmt = "%(exe_name)s could not be found on this machine"

    def __init__(self, exe_name):
        BzrError.__init__(self, exe_name=exe_name)


class NoDiff(BzrError):
    """Diff tool is not installed.

    Raised when the diff utility is not installed on the system but is required for an operation.
    """

    _fmt = "Diff is not installed on this machine: %(msg)s"

    def __init__(self, msg):
        BzrError.__init__(self, msg=msg)


class NoDiff3(BzrError):
    """Diff3 tool is not installed.

    Raised when the diff3 utility is not installed on the system but is required for three-way merging.
    """

    _fmt = "Diff3 is not installed on this machine."


class ExistingLimbo(BzrError):
    """Tree contains leftover limbo directory.

    Raised when a tree contains a leftover limbo directory from a failed operation
    that needs to be cleaned up before proceeding.
    """

    _fmt = """This tree contains left-over files from a failed operation.
    Please examine %(limbo_dir)s to see if it contains any files you wish to
    keep, and delete it when you are done."""

    def __init__(self, limbo_dir):
        BzrError.__init__(self)
        self.limbo_dir = limbo_dir


class ExistingPendingDeletion(BzrError):
    """Tree contains leftover pending deletion directory.

    Raised when a tree contains a leftover pending deletion directory from a failed
    operation that needs to be cleaned up before proceeding.
    """

    _fmt = """This tree contains left-over files from a failed operation.
    Please examine %(pending_deletion)s to see if it contains any files you
    wish to keep, and delete it when you are done."""

    def __init__(self, pending_deletion):
        BzrError.__init__(self, pending_deletion=pending_deletion)


class ImmortalPendingDeletion(BzrError):
    """Cannot delete transform temporary directory.

    Raised when a transform temporary directory cannot be deleted, possibly due to
    permission issues or files being in use.
    """

    _fmt = (
        "Unable to delete transform temporary directory "
        "%(pending_deletion)s.  Please examine %(pending_deletion)s to see if it "
        "contains any files you wish to keep, and delete it when you are done."
    )

    def __init__(self, pending_deletion):
        BzrError.__init__(self, pending_deletion=pending_deletion)


class OutOfDateTree(BzrError):
    """Working tree is out of date.

    Raised when the working tree is behind its branch and needs to be updated
    before an operation can proceed.
    """

    _fmt = "Working tree is out of date, please run 'brz update'.%(more)s"

    def __init__(self, tree, more=None):
        more = "" if more is None else " " + more
        BzrError.__init__(self)
        self.tree = tree
        self.more = more


class PublicBranchOutOfDate(BzrError):
    """Public branch is missing required revision.

    Raised when the public branch is missing a revision that is needed for an operation.
    """

    _fmt = 'Public branch "%(public_location)s" lacks revision "%(revstring)s".'

    def __init__(self, public_location, revstring):
        import breezy.urlutils as urlutils

        public_location = urlutils.unescape_for_display(public_location, "ascii")
        BzrError.__init__(self, public_location=public_location, revstring=revstring)


class MergeModifiedFormatError(BzrError):
    """Error in merge modified format.

    Raised when there is a formatting error in merge modified data.
    """

    _fmt = "Error in merge modified format"


class ConflictFormatError(BzrError):
    """Error in conflict listing format.

    Raised when there is a formatting error in conflict listing data.
    """

    _fmt = "Format error in conflict listings"


class CorruptRepository(BzrError):
    """Repository corruption detected.

    Raised when repository corruption is detected that requires reconciliation
    to repair.
    """

    _fmt = (
        "An error has been detected in the repository %(repo_path)s.\n"
        "Please run brz reconcile on this repository."
    )

    def __init__(self, repo):
        BzrError.__init__(self)
        self.repo_path = repo.user_url


class InconsistentDelta(BzrError):
    """Used when we get a delta that is not valid."""

    _fmt = (
        "An inconsistent delta was supplied involving %(path)r,"
        " %(file_id)r\nreason: %(reason)s"
    )

    def __init__(self, path, file_id, reason):
        BzrError.__init__(self)
        self.path = path
        self.file_id = file_id
        self.reason = reason


class InconsistentDeltaDelta(InconsistentDelta):
    """Used when we get a delta that is not valid."""

    _fmt = "An inconsistent delta was supplied: %(delta)r\nreason: %(reason)s"

    def __init__(self, delta, reason):
        BzrError.__init__(self)
        self.delta = delta
        self.reason = reason


class UpgradeRequired(BzrError):
    """Branch upgrade required for feature.

    Raised when a feature requires a newer branch format than what is currently available.
    """

    _fmt = "To use this feature you must upgrade your branch at %(path)s."

    def __init__(self, path):
        BzrError.__init__(self)
        self.path = path


class RepositoryUpgradeRequired(UpgradeRequired):
    """Repository upgrade required for feature.

    Raised when a feature requires a newer repository format than what is currently available.
    """

    _fmt = "To use this feature you must upgrade your repository at %(path)s."


class RichRootUpgradeRequired(UpgradeRequired):
    """Rich root support upgrade required.

    Raised when a feature requires rich root support but the current format does not support it.
    """

    _fmt = (
        "To use this feature you must upgrade your branch at %(path)s to"
        " a format which supports rich roots."
    )


class LocalRequiresBoundBranch(BzrError):
    """Local-only commit requires bound branch.

    Raised when attempting a local-only commit on a branch that is not bound to a master.
    """

    _fmt = "Cannot perform local-only commits on unbound branches."


class UnsupportedOperation(BzrError):
    """Operation is not supported on this object type.

    Raised when attempting an operation that is not supported by the particular object type.
    """

    _fmt = "The method %(mname)s is not supported on objects of type %(tname)s."

    def __init__(self, method, method_self):
        self.method = method
        self.mname = method.__name__
        self.tname = type(method_self).__name__


class FetchLimitUnsupported(UnsupportedOperation):
    """Fetch limit not supported by interbranch implementation.

    Raised when attempting to use fetch limits on an interbranch implementation that does not support them.
    """

    _fmt = "InterBranch %(interbranch)r does not support fetching limits."

    def __init__(self, interbranch):
        BzrError.__init__(self, interbranch=interbranch)


class NonAsciiRevisionId(UnsupportedOperation):
    """Raised when a commit is attempting to set a non-ascii revision id.

    This exception is raised when a commit operation tries to set a revision
    ID that contains non-ASCII characters but cannot do so.
    """


class SharedRepositoriesUnsupported(UnsupportedOperation):
    """Shared repositories not supported by format.

    Raised when attempting to use shared repositories with a format that does not support them.
    """

    _fmt = "Shared repositories are not supported by %(format)r."

    def __init__(self, format):
        BzrError.__init__(self, format=format)


class GhostTagsNotSupported(BzrError):
    """Ghost tags not supported by format.

    Raised when attempting to use ghost tags with a format that does not support them.
    """

    _fmt = "Ghost tags not supported by format %(format)r."

    def __init__(self, format):
        self.format = format


class BinaryFile(BzrError):
    """File is binary when text was expected.

    Raised when a binary file is encountered in a context where text is required.
    """

    _fmt = "File is binary but should be text."


class IllegalPath(BzrError):
    """Path contains illegal characters for current platform.

    Raised when a path contains characters or patterns that are not permitted
    on the current operating system platform.
    """

    _fmt = "The path %(path)s is not permitted on this platform"

    def __init__(self, path):
        BzrError.__init__(self)
        self.path = path


class TestamentMismatch(BzrError):
    """Testament verification failed.

    Raised when a revision's testament does not match its expected value,
    indicating potential data corruption.
    """

    _fmt = """Testament did not match expected value.
       For revision_id {%(revision_id)s}, expected {%(expected)s}, measured
       {%(measured)s}"""

    def __init__(self, revision_id, expected, measured):
        self.revision_id = revision_id
        self.expected = expected
        self.measured = measured


class NotABundle(BzrError):
    """Content is not a revision bundle.

    Raised when content that was expected to be a bzr revision bundle does not have the correct format.
    """

    _fmt = "Not a bzr revision-bundle: %(text)r"

    def __init__(self, text):
        BzrError.__init__(self)
        self.text = text


class BadBundle(BzrError):
    """Revision bundle is malformed.

    Raised when a revision bundle contains errors or is corrupted.
    """

    _fmt = "Bad bzr revision-bundle: %(text)r"

    def __init__(self, text):
        BzrError.__init__(self)
        self.text = text


class MalformedHeader(BadBundle):
    """Revision bundle header is malformed.

    Raised when a revision bundle has an invalid or corrupted header.
    """

    _fmt = "Malformed bzr revision-bundle header: %(text)r"


class MalformedPatches(BadBundle):
    """Revision bundle patches are malformed.

    Raised when a revision bundle contains invalid or corrupted patch data.
    """

    _fmt = "Malformed patches in bzr revision-bundle: %(text)r"


class MalformedFooter(BadBundle):
    """Revision bundle footer is malformed.

    Raised when a revision bundle has an invalid or corrupted footer.
    """

    _fmt = "Malformed footer in bzr revision-bundle: %(text)r"


class UnsupportedEOLMarker(BadBundle):
    """Unsupported end-of-line marker in bundle.

    Raised when a revision bundle uses an unsupported end-of-line marker
    instead of the expected newline character.
    """

    _fmt = "End of line marker was not \\n in bzr revision-bundle"

    def __init__(self):
        # XXX: BadBundle's constructor assumes there's explanatory text,
        # but for this there is not
        BzrError.__init__(self)


class IncompatibleBundleFormat(BzrError):
    """Bundle format is incompatible.

    Raised when attempting to use bundle formats that are incompatible with each other.
    """

    _fmt = "Bundle format %(bundle_format)s is incompatible with %(other)s"

    def __init__(self, bundle_format, other):
        BzrError.__init__(self)
        self.bundle_format = bundle_format
        self.other = other


class RootNotRich(BzrError):
    """Operation requires rich root data storage.

    Raised when an operation requires rich root support but the current format does not provide it.
    """

    _fmt = """This operation requires rich root data storage"""


class NoSmartMedium(InternalBzrError):
    """Transport cannot tunnel smart protocol.

    Raised when a transport does not support tunneling the smart protocol.
    """

    _fmt = "The transport '%(transport)s' cannot tunnel the smart protocol."

    def __init__(self, transport):
        self.transport = transport


class UnknownSSH(BzrError):
    """Unknown SSH implementation specified.

    Raised when the BRZ_SSH environment variable contains an unrecognized value.
    """

    _fmt = "Unrecognised value for BRZ_SSH environment variable: %(vendor)s"

    def __init__(self, vendor):
        BzrError.__init__(self)
        self.vendor = vendor


class SSHVendorNotFound(BzrError):
    """No SSH implementation available.

    Raised when no SSH implementation can be found and the BRZ_SSH environment
    variable is not set to specify one.
    """

    _fmt = (
        "Don't know how to handle SSH connections."
        " Please set BRZ_SSH environment variable."
    )


class GhostRevisionsHaveNoRevno(BzrError):
    """When searching for revnos, if we encounter a ghost, we are stuck."""

    _fmt = (
        "Could not determine revno for {%(revision_id)s} because"
        " its ancestry shows a ghost at {%(ghost_revision_id)s}"
    )

    def __init__(self, revision_id, ghost_revision_id):
        self.revision_id = revision_id
        self.ghost_revision_id = ghost_revision_id


class GhostRevisionUnusableHere(BzrError):
    """Ghost revision cannot be used in this context.

    Raised when a ghost revision is encountered in a context where it cannot be used.
    """

    _fmt = "Ghost revision {%(revision_id)s} cannot be used here."

    def __init__(self, revision_id):
        BzrError.__init__(self)
        self.revision_id = revision_id


class NotAMergeDirective(BzrError):
    """Content is not a merge directive.

    Raised when content that was expected to be a merge directive does not have the correct format.
    """

    _fmt = "File starting with %(firstline)r is not a merge directive."

    def __init__(self, firstline):
        BzrError.__init__(self, firstline=firstline)


class NoMergeSource(BzrError):
    """No merge source specified for merge directive.

    Raised when a merge directive does not specify either a bundle or a public branch location.
    """

    _fmt = "A merge directive must provide either a bundle or a public branch location."


class PatchVerificationFailed(BzrError):
    """A patch from a merge directive could not be verified."""

    _fmt = "Preview patch does not match requested changes."


class PatchMissing(BzrError):
    """Raise a patch type was specified but no patch supplied."""

    _fmt = "Patch_type was %(patch_type)s, but no patch was supplied."

    def __init__(self, patch_type):
        BzrError.__init__(self)
        self.patch_type = patch_type


class TargetNotBranch(BzrError):
    """A merge directive's target branch is required, but isn't a branch."""

    _fmt = (
        "Your branch does not have all of the revisions required in "
        "order to merge this merge directive and the target "
        "location specified in the merge directive is not a branch: "
        "%(location)s."
    )

    def __init__(self, location):
        BzrError.__init__(self)
        self.location = location


class BadSubsumeSource(BzrError):
    _fmt = "Can't subsume %(other_tree)s into %(tree)s. %(reason)s"

    def __init__(self, tree, other_tree, reason):
        self.tree = tree
        self.other_tree = other_tree
        self.reason = reason


class SubsumeTargetNeedsUpgrade(BzrError):
    _fmt = """Subsume target %(other_tree)s needs to be upgraded."""

    def __init__(self, other_tree):
        self.other_tree = other_tree


class NoSuchTag(BzrError):
    _fmt = "No such tag: %(tag_name)s"

    def __init__(self, tag_name):
        self.tag_name = tag_name


class TagsNotSupported(BzrError):
    _fmt = (
        "Tags not supported by %(branch)s;"
        " you may be able to use 'brz upgrade %(branch_url)s'."
    )

    def __init__(self, branch):
        self.branch = branch
        self.branch_url = branch.user_url


class TagAlreadyExists(BzrError):
    _fmt = "Tag %(tag_name)s already exists."

    def __init__(self, tag_name):
        self.tag_name = tag_name


class UnexpectedSmartServerResponse(BzrError):
    _fmt = "Could not understand response from smart server: %(response_tuple)r"

    def __init__(self, response_tuple):
        self.response_tuple = response_tuple


class ErrorFromSmartServer(BzrError):
    """An error was received from a smart server.

    :seealso: UnknownErrorFromSmartServer
    """

    _fmt = "Error received from smart server: %(error_tuple)r"

    internal_error = True

    def __init__(self, error_tuple):
        self.error_tuple = error_tuple
        try:
            self.error_verb = error_tuple[0]
        except IndexError:
            self.error_verb = None
        self.error_args = error_tuple[1:]


class RepositoryDataStreamError(BzrError):
    _fmt = "Corrupt or incompatible data stream: %(reason)s"

    def __init__(self, reason):
        self.reason = reason


class UncommittedChanges(BzrError):
    _fmt = (
        'Working tree "%(display_url)s" has uncommitted changes'
        " (See brz status).%(more)s"
    )

    def __init__(self, tree, more=None):
        more = "" if more is None else " " + more
        import breezy.urlutils as urlutils

        user_url = getattr(tree, "user_url", None)
        if user_url is None:
            display_url = str(tree)
        else:
            display_url = urlutils.unescape_for_display(user_url, "ascii")
        BzrError.__init__(self, tree=tree, display_url=display_url, more=more)


class StoringUncommittedNotSupported(BzrError):
    _fmt = 'Branch "%(display_url)s" does not support storing uncommitted changes.'

    def __init__(self, branch):
        import breezy.urlutils as urlutils

        user_url = getattr(branch, "user_url", None)
        if user_url is None:
            display_url = str(branch)
        else:
            display_url = urlutils.unescape_for_display(user_url, "ascii")
        BzrError.__init__(self, branch=branch, display_url=display_url)


class ShelvedChanges(UncommittedChanges):
    _fmt = (
        'Working tree "%(display_url)s" has shelved changes'
        " (See brz shelve --list).%(more)s"
    )


class UnableEncodePath(BzrError):
    _fmt = "Unable to encode %(kind)s path %(path)r in user encoding %(user_encoding)s"

    def __init__(self, path, kind):
        from .osutils import get_user_encoding

        self.path = path
        self.kind = kind
        self.user_encoding = get_user_encoding()


class CannotBindAddress(BzrError):
    _fmt = 'Cannot bind address "%(host)s:%(port)i": %(orig_error)s.'

    def __init__(self, host, port, orig_error):
        # nb: in python2.4 socket.error doesn't have a useful repr
        BzrError.__init__(self, host=host, port=port, orig_error=repr(orig_error.args))


class TipChangeRejected(BzrError):
    """Branch tip change was rejected by hook.

    A pre_change_branch_tip hook function may raise this to cleanly and
    explicitly abort a change to a branch tip.
    """

    _fmt = "Tip change rejected: %(msg)s"

    def __init__(self, msg):
        self.msg = msg


class JailBreak(BzrError):
    _fmt = "An attempt to access a url outside the server jail was made: '%(url)s'."

    def __init__(self, url):
        BzrError.__init__(self, url=url)


class UserAbort(BzrError):
    _fmt = "The user aborted the operation."


class UnresumableWriteGroup(BzrError):
    _fmt = (
        "Repository %(repository)s cannot resume write group "
        "%(write_groups)r: %(reason)s"
    )

    internal_error = True

    def __init__(self, repository, write_groups, reason):
        self.repository = repository
        self.write_groups = write_groups
        self.reason = reason


class UnsuspendableWriteGroup(BzrError):
    _fmt = "Repository %(repository)s cannot suspend a write group."

    internal_error = True

    def __init__(self, repository):
        self.repository = repository


class LossyPushToSameVCS(BzrError):
    _fmt = (
        "Lossy push not possible between %(source_branch)r and "
        "%(target_branch)r that are in the same VCS."
    )

    internal_error = True

    def __init__(self, source_branch, target_branch):
        self.source_branch = source_branch
        self.target_branch = target_branch


class NoRoundtrippingSupport(BzrError):
    _fmt = (
        "Roundtripping is not supported between %(source_branch)r and "
        "%(target_branch)r."
    )

    internal_error = True

    def __init__(self, source_branch, target_branch):
        self.source_branch = source_branch
        self.target_branch = target_branch


class RecursiveBind(BzrError):
    _fmt = (
        'Branch "%(branch_url)s" appears to be bound to itself. '
        "Please use `brz unbind` to fix."
    )

    def __init__(self, branch_url):
        self.branch_url = branch_url


class UnsupportedKindChange(BzrError):
    _fmt = (
        "Kind change from %(from_kind)s to %(to_kind)s for "
        "%(path)s not supported by format %(format)r"
    )

    def __init__(self, path, from_kind, to_kind, format):
        self.path = path
        self.from_kind = from_kind
        self.to_kind = to_kind
        self.format = format


class ChangesAlreadyStored(CommandError):
    _fmt = (
        "Cannot store uncommitted changes because this branch already"
        " stores uncommitted changes."
    )


class RevnoOutOfBounds(InternalBzrError):
    _fmt = (
        "The requested revision number %(revno)d is outside of the "
        "expected boundaries (%(minimum)d <= %(maximum)d)."
    )

    def __init__(self, revno, bounds):
        InternalBzrError.__init__(
            self, revno=revno, minimum=bounds[0], maximum=bounds[1]
        )
