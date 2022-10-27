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
    """
    Base class for errors raised by breezy.

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
        s = getattr(self, '_preformatted_string', None)
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
        return 'Unprintable exception %s: dict=%r, fmt=%r, error=%r' \
            % (self.__class__.__name__,
               self.__dict__,
               getattr(self, '_fmt', None),
               err)

    __str__ = _format

    def __repr__(self):
        return '%s(%s)' % (self.__class__.__name__, str(self))

    def _get_format_string(self):
        """Return format string for this exception or None"""
        fmt = getattr(self, '_fmt', None)
        if fmt is not None:
            from breezy.i18n import gettext
            return gettext(fmt)  # _fmt strings should be ascii

    def __eq__(self, other):
        if self.__class__ is not other.__class__:
            return NotImplemented
        return self.__dict__ == other.__dict__

    def __hash__(self):
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
        BzrError.__init__(self, branch=branch)


class BzrCheckError(InternalBzrError):

    _fmt = "Internal check failed: %(msg)s"

    def __init__(self, msg):
        BzrError.__init__(self)
        self.msg = msg


class IncompatibleVersion(BzrError):

    _fmt = 'API %(api)s is not compatible; one of versions %(wanted)r '\
           'is required, but current version is %(current)r.'

    def __init__(self, api, wanted, current):
        self.api = api
        self.wanted = wanted
        self.current = current


class InProcessTransport(BzrError):

    _fmt = "The transport '%(transport)s' is only accessible within this " \
        "process."

    def __init__(self, transport):
        self.transport = transport


class InvalidRevisionNumber(BzrError):

    _fmt = "Invalid revision number %(revno)s"

    def __init__(self, revno):
        BzrError.__init__(self)
        self.revno = revno


class InvalidRevisionId(BzrError):

    _fmt = "Invalid revision-id {%(revision_id)s} in %(branch)s"

    def __init__(self, revision_id, branch):
        # branch can be any string or object with __str__ defined
        BzrError.__init__(self)
        self.revision_id = revision_id
        self.branch = branch


class ReservedId(BzrError):

    _fmt = "Reserved revision-id {%(revision_id)s}"

    def __init__(self, revision_id):
        self.revision_id = revision_id


class RootMissing(InternalBzrError):

    _fmt = ("The root entry of a tree must be the first entry supplied to "
            "the commit builder.")


class NoPublicBranch(BzrError):

    _fmt = 'There is no public branch set for "%(branch_url)s".'

    def __init__(self, branch):
        from . import urlutils
        public_location = urlutils.unescape_for_display(branch.base, 'ascii')
        BzrError.__init__(self, branch_url=public_location)


class NoSuchId(BzrError):

    _fmt = 'The file id "%(file_id)s" is not present in the tree %(tree)s.'

    def __init__(self, tree, file_id):
        BzrError.__init__(self)
        self.file_id = file_id
        self.tree = tree


class NotStacked(BranchError):

    _fmt = "The branch '%(branch)s' is not stacked."


class NoWorkingTree(BzrError):

    _fmt = 'No WorkingTree exists for "%(base)s".'

    def __init__(self, base):
        BzrError.__init__(self)
        self.base = base


class NotLocalUrl(BzrError):

    _fmt = "%(url)s is not a local path."

    def __init__(self, url):
        self.url = url


class WorkingTreeAlreadyPopulated(InternalBzrError):

    _fmt = 'Working tree already populated in "%(base)s"'

    def __init__(self, base):
        self.base = base


class NoWhoami(BzrError):

    _fmt = ('Unable to determine your name.\n'
            "Please, set your name with the 'whoami' command.\n"
            'E.g. brz whoami "Your Name <name@example.com>"')


class CommandError(BzrError):
    """Error from user command"""

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

    _fmt = """%(not_locked)r is not write locked but needs to be."""

    def __init__(self, not_locked):
        self.not_locked = not_locked


class StrictCommitFailed(BzrError):

    _fmt = "Commit refused because there are unknown files in the tree"


# XXX: Should be unified with TransportError; they seem to represent the
# same thing
# RBC 20060929: I think that unifiying with TransportError would be a mistake
# - this is finer than a TransportError - and more useful as such. It
# differentiates between 'transport has failed' and 'operation on a transport
# has failed.'
class PathError(BzrError):

    _fmt = "Generic path error: %(path)r%(extra)s)"

    def __init__(self, path, extra=None):
        BzrError.__init__(self)
        self.path = path
        if extra:
            self.extra = ': ' + str(extra)
        else:
            self.extra = ''


class RenameFailedFilesExist(BzrError):
    """Used when renaming and both source and dest exist."""

    _fmt = ("Could not rename %(source)s => %(dest)s because both files exist."
            " (Use --after to tell brz about a rename that has already"
            " happened)%(extra)s")

    def __init__(self, source, dest, extra=None):
        BzrError.__init__(self)
        self.source = str(source)
        self.dest = str(dest)
        if extra:
            self.extra = ' ' + str(extra)
        else:
            self.extra = ''


class NotADirectory(PathError):

    _fmt = '"%(path)s" is not a directory %(extra)s'


class NotInWorkingDirectory(PathError):

    _fmt = '"%(path)s" is not in the working directory %(extra)s'


class DirectoryNotEmpty(PathError):

    _fmt = 'Directory not empty: "%(path)s"%(extra)s'


class HardLinkNotSupported(PathError):

    _fmt = 'Hard-linking "%(path)s" is not supported'


class ReadingCompleted(InternalBzrError):

    _fmt = ("The MediumRequest '%(request)s' has already had finish_reading "
            "called upon it - the request has been completed and no more "
            "data may be read.")

    def __init__(self, request):
        self.request = request


class ResourceBusy(PathError):

    _fmt = 'Device or resource busy: "%(path)s"%(extra)s'


class PermissionDenied(PathError):

    _fmt = 'Permission denied: "%(path)s"%(extra)s'


class UnstackableLocationError(BzrError):

    _fmt = "The branch '%(branch_url)s' cannot be stacked on '%(target_url)s'."

    def __init__(self, branch_url, target_url):
        BzrError.__init__(self)
        self.branch_url = branch_url
        self.target_url = target_url


class UnstackableRepositoryFormat(BzrError):

    _fmt = ("The repository '%(url)s'(%(format)s) is not a stackable format. "
            "You will need to upgrade the repository to permit branch stacking.")

    def __init__(self, format, url):
        BzrError.__init__(self)
        self.format = format
        self.url = url


class ReadError(PathError):

    _fmt = """Error reading from %(path)r."""


class ShortReadvError(PathError):

    _fmt = ('readv() read %(actual)s bytes rather than %(length)s bytes'
            ' at %(offset)s for "%(path)s"%(extra)s')

    internal_error = True

    def __init__(self, path, offset, length, actual, extra=None):
        PathError.__init__(self, path, extra=extra)
        self.offset = offset
        self.length = length
        self.actual = actual


class PathNotChild(PathError):

    _fmt = 'Path "%(path)s" is not a child of path "%(base)s"%(extra)s'

    internal_error = False

    def __init__(self, path, base, extra=None):
        BzrError.__init__(self)
        self.path = path
        self.base = base
        if extra:
            self.extra = ': ' + str(extra)
        else:
            self.extra = ''


class InvalidNormalization(PathError):

    _fmt = 'Path "%(path)s" is not unicode normalized'


# TODO: This is given a URL; we try to unescape it but doing that from inside
# the exception object is a bit undesirable.
# TODO: Probably this behavior of should be a common superclass
class NotBranchError(PathError):

    _fmt = 'Not a branch: "%(path)s"%(detail)s.'

    def __init__(self, path, detail=None, controldir=None):
        from . import urlutils
        path = urlutils.unescape_for_display(path, 'ascii')
        if detail is not None:
            detail = ': ' + detail
        self.detail = detail
        self.controldir = controldir
        PathError.__init__(self, path=path)

    def __repr__(self):
        return '<%s %r>' % (self.__class__.__name__, self.__dict__)

    def _get_format_string(self):
        # GZ 2017-06-08: Not the best place to lazy fill detail in.
        if self.detail is None:
            self.detail = self._get_detail()
        return super(NotBranchError, self)._get_format_string()

    def _get_detail(self):
        if self.controldir is not None:
            try:
                self.controldir.open_repository()
            except NoRepositoryPresent:
                return ''
            except Exception as e:
                # Just ignore unexpected errors.  Raising arbitrary errors
                # during str(err) can provoke strange bugs.  Concretely
                # Launchpad's codehosting managed to raise NotBranchError
                # here, and then get stuck in an infinite loop/recursion
                # trying to str() that error.  All this error really cares
                # about that there's no working repository there, and if
                # open_repository() fails, there probably isn't.
                return ': ' + e.__class__.__name__
            else:
                return ': location is a repository'
        return ''


class NoSubmitBranch(PathError):

    _fmt = 'No submit branch available for branch "%(path)s"'

    def __init__(self, branch):
        from . import urlutils
        self.path = urlutils.unescape_for_display(branch.base, 'ascii')


class AlreadyControlDirError(PathError):

    _fmt = 'A control directory already exists: "%(path)s".'


class AlreadyBranchError(PathError):

    _fmt = 'Already a branch: "%(path)s".'


class InvalidBranchName(PathError):

    _fmt = "Invalid branch name: %(name)s"

    def __init__(self, name):
        BzrError.__init__(self)
        self.name = name


class ParentBranchExists(AlreadyBranchError):

    _fmt = 'Parent branch already exists: "%(path)s".'


class BranchExistsWithoutWorkingTree(PathError):

    _fmt = 'Directory contains a branch, but no working tree \
(use brz checkout if you wish to build a working tree): "%(path)s"'


class InaccessibleParent(PathError):

    _fmt = ('Parent not accessible given base "%(base)s" and'
            ' relative path "%(path)s"')

    def __init__(self, path, base):
        PathError.__init__(self, path)
        self.base = base


class NoRepositoryPresent(BzrError):

    _fmt = 'No repository present: "%(path)s"'

    def __init__(self, controldir):
        BzrError.__init__(self)
        self.path = controldir.transport.clone('..').base


class UnsupportedFormatError(BzrError):

    _fmt = "Unsupported branch format: %(format)s\nPlease run 'brz upgrade'"


class UnknownFormatError(BzrError):

    _fmt = "Unknown %(kind)s format: %(format)r"

    def __init__(self, format, kind='branch'):
        self.kind = kind
        self.format = format


class IncompatibleFormat(BzrError):

    _fmt = "Format %(format)s is not compatible with .bzr version %(controldir)s."

    def __init__(self, format, controldir_format):
        BzrError.__init__(self)
        self.format = format
        self.controldir = controldir_format


class ParseFormatError(BzrError):

    _fmt = "Parse error on line %(lineno)d of %(format)s format: %(line)s"

    def __init__(self, format, lineno, line, text):
        BzrError.__init__(self)
        self.format = format
        self.lineno = lineno
        self.line = line
        self.text = text


class IncompatibleRepositories(BzrError):
    """Report an error that two repositories are not compatible.

    Note that the source and target repositories are permitted to be strings:
    this exception is thrown from the smart server and may refer to a
    repository the client hasn't opened.
    """

    _fmt = "%(target)s\n" \
        "is not compatible with\n" \
        "%(source)s\n" \
        "%(details)s"

    def __init__(self, source, target, details=None):
        if details is None:
            details = "(no details)"
        BzrError.__init__(self, target=target, source=source, details=details)


class IncompatibleRevision(BzrError):

    _fmt = "Revision is not compatible with %(repo_format)s"

    def __init__(self, repo_format):
        BzrError.__init__(self)
        self.repo_format = repo_format


class AlreadyVersionedError(BzrError):
    """Used when a path is expected not to be versioned, but it is."""

    _fmt = "%(context_info)s%(path)s is already versioned."

    def __init__(self, path, context_info=None):
        """Construct a new AlreadyVersionedError.

        :param path: This is the path which is versioned,
            which should be in a user friendly form.
        :param context_info: If given, this is information about the context,
            which could explain why this is expected to not be versioned.
        """
        BzrError.__init__(self)
        self.path = path
        if context_info is None:
            self.context_info = ''
        else:
            self.context_info = context_info + ". "


class NotVersionedError(BzrError):
    """Used when a path is expected to be versioned, but it is not."""

    _fmt = "%(context_info)s%(path)s is not versioned."

    def __init__(self, path, context_info=None):
        """Construct a new NotVersionedError.

        :param path: This is the path which is not versioned,
            which should be in a user friendly form.
        :param context_info: If given, this is information about the context,
            which could explain why this is expected to be versioned.
        """
        BzrError.__init__(self)
        self.path = path
        if context_info is None:
            self.context_info = ''
        else:
            self.context_info = context_info + ". "


class PathsNotVersionedError(BzrError):
    """Used when reporting several paths which are not versioned"""

    _fmt = "Path(s) are not versioned: %(paths_as_string)s"

    def __init__(self, paths):
        from breezy.osutils import quotefn
        BzrError.__init__(self)
        self.paths = paths
        self.paths_as_string = ' '.join([quotefn(p) for p in paths])


class PathsDoNotExist(BzrError):

    _fmt = "Path(s) do not exist: %(paths_as_string)s%(extra)s"

    # used when reporting that paths are neither versioned nor in the working
    # tree

    def __init__(self, paths, extra=None):
        # circular import
        from breezy.osutils import quotefn
        BzrError.__init__(self)
        self.paths = paths
        self.paths_as_string = ' '.join([quotefn(p) for p in paths])
        if extra:
            self.extra = ': ' + str(extra)
        else:
            self.extra = ''


class BadFileKindError(BzrError):

    _fmt = 'Cannot operate on "%(filename)s" of unsupported kind "%(kind)s"'

    def __init__(self, filename, kind):
        BzrError.__init__(self, filename=filename, kind=kind)


class ForbiddenControlFileError(BzrError):

    _fmt = 'Cannot operate on "%(filename)s" because it is a control file'


class LockError(InternalBzrError):

    _fmt = "Lock error: %(msg)s"

    # All exceptions from the lock/unlock functions should be from
    # this exception class.  They will be translated as necessary. The
    # original exception is available as e.original_error
    #
    # New code should prefer to raise specific subclasses
    def __init__(self, msg):
        self.msg = msg


class LockActive(LockError):

    _fmt = "The lock for '%(lock_description)s' is in use and cannot be broken."

    internal_error = False

    def __init__(self, lock_description):
        self.lock_description = lock_description


class CommitNotPossible(LockError):

    _fmt = "A commit was attempted but we do not have a write lock open."

    def __init__(self):
        pass


class AlreadyCommitted(LockError):

    _fmt = "A rollback was requested, but is not able to be accomplished."

    def __init__(self):
        pass


class ReadOnlyError(LockError):

    _fmt = "A write attempt was made in a read only transaction on %(obj)s"

    # TODO: There should also be an error indicating that you need a write
    # lock and don't have any lock at all... mbp 20070226

    def __init__(self, obj):
        self.obj = obj


class LockFailed(LockError):

    internal_error = False

    _fmt = "Cannot lock %(lock)s: %(why)s"

    def __init__(self, lock, why):
        LockError.__init__(self, '')
        self.lock = lock
        self.why = why


class OutSideTransaction(BzrError):

    _fmt = ("A transaction related operation was attempted after"
            " the transaction finished.")


class ObjectNotLocked(LockError):

    _fmt = "%(obj)r is not locked"

    # this can indicate that any particular object is not locked; see also
    # LockNotHeld which means that a particular *lock* object is not held by
    # the caller -- perhaps they should be unified.
    def __init__(self, obj):
        self.obj = obj


class ReadOnlyObjectDirtiedError(ReadOnlyError):

    _fmt = "Cannot change object %(obj)r in read only transaction"

    def __init__(self, obj):
        self.obj = obj


class UnlockableTransport(LockError):

    internal_error = False

    _fmt = "Cannot lock: transport is read only: %(transport)s"

    def __init__(self, transport):
        self.transport = transport


class LockContention(LockError):

    _fmt = 'Could not acquire lock "%(lock)s": %(msg)s'

    internal_error = False

    def __init__(self, lock, msg=''):
        self.lock = lock
        self.msg = msg


class LockBroken(LockError):

    _fmt = ("Lock was broken while still open: %(lock)s"
            " - check storage consistency!")

    internal_error = False

    def __init__(self, lock):
        self.lock = lock


class LockBreakMismatch(LockError):

    _fmt = ("Lock was released and re-acquired before being broken:"
            " %(lock)s: held by %(holder)r, wanted to break %(target)r")

    internal_error = False

    def __init__(self, lock, holder, target):
        self.lock = lock
        self.holder = holder
        self.target = target


class LockCorrupt(LockError):

    _fmt = ("Lock is apparently held, but corrupted: %(corruption_info)s\n"
            "Use 'brz break-lock' to clear it")

    internal_error = False

    def __init__(self, corruption_info, file_data=None):
        self.corruption_info = corruption_info
        self.file_data = file_data


class LockNotHeld(LockError):

    _fmt = "Lock not held: %(lock)s"

    internal_error = False

    def __init__(self, lock):
        self.lock = lock


class TokenLockingNotSupported(LockError):

    _fmt = "The object %(obj)s does not support token specifying a token when locking."

    def __init__(self, obj):
        self.obj = obj


class TokenMismatch(LockBroken):

    _fmt = "The lock token %(given_token)r does not match lock token %(lock_token)r."

    internal_error = True

    def __init__(self, given_token, lock_token):
        self.given_token = given_token
        self.lock_token = lock_token


class UpgradeReadonly(BzrError):

    _fmt = "Upgrade URL cannot work with readonly URLs."


class UpToDateFormat(BzrError):

    _fmt = "The branch format %(format)s is already at the most recent format."

    def __init__(self, format):
        BzrError.__init__(self)
        self.format = format


class NoSuchRevision(InternalBzrError):

    _fmt = "%(branch)s has no revision %(revision)s"

    def __init__(self, branch, revision):
        # 'branch' may sometimes be an internal object like a KnitRevisionStore
        BzrError.__init__(self, branch=branch, revision=revision)


class RangeInChangeOption(BzrError):

    _fmt = "Option --change does not accept revision ranges"


class NoSuchRevisionSpec(BzrError):

    _fmt = "No namespace registered for string: %(spec)r"

    def __init__(self, spec):
        BzrError.__init__(self, spec=spec)


class NoSuchRevisionInTree(NoSuchRevision):
    """When using Tree.revision_tree, and the revision is not accessible."""

    _fmt = "The revision id {%(revision_id)s} is not present in the tree %(tree)s."

    def __init__(self, tree, revision_id):
        BzrError.__init__(self)
        self.tree = tree
        self.revision_id = revision_id


class AppendRevisionsOnlyViolation(BzrError):

    _fmt = ('Operation denied because it would change the main history,'
            ' which is not permitted by the append_revisions_only setting on'
            ' branch "%(location)s".')

    def __init__(self, location):
        import breezy.urlutils as urlutils
        location = urlutils.unescape_for_display(location, 'ascii')
        BzrError.__init__(self, location=location)


class DivergedBranches(BzrError):

    _fmt = ("These branches have diverged."
            " Use the missing command to see how.\n"
            "Use the merge command to reconcile them.")

    def __init__(self, branch1, branch2):
        self.branch1 = branch1
        self.branch2 = branch2


class NotLefthandHistory(InternalBzrError):

    _fmt = "Supplied history does not follow left-hand parents"

    def __init__(self, history):
        BzrError.__init__(self, history=history)


class UnrelatedBranches(BzrError):

    _fmt = ("Branches have no common ancestor, and"
            " no merge base revision was specified.")


class CannotReverseCherrypick(BzrError):

    _fmt = ('Selected merge cannot perform reverse cherrypicks.  Try merge3'
            ' or diff3.')


class NoCommonAncestor(BzrError):

    _fmt = "Revisions have no common ancestor: %(revision_a)s %(revision_b)s"

    def __init__(self, revision_a, revision_b):
        self.revision_a = revision_a
        self.revision_b = revision_b


class NoCommonRoot(BzrError):

    _fmt = ("Revisions are not derived from the same root: "
            "%(revision_a)s %(revision_b)s.")

    def __init__(self, revision_a, revision_b):
        BzrError.__init__(self, revision_a=revision_a, revision_b=revision_b)


class NotAncestor(BzrError):

    _fmt = "Revision %(rev_id)s is not an ancestor of %(not_ancestor_id)s"

    def __init__(self, rev_id, not_ancestor_id):
        BzrError.__init__(self, rev_id=rev_id,
                          not_ancestor_id=not_ancestor_id)


class NoCommits(BranchError):

    _fmt = "Branch %(branch)s has no commits."


class UnlistableStore(BzrError):

    def __init__(self, store):
        BzrError.__init__(self, "Store %s is not listable" % store)


class UnlistableBranch(BzrError):

    def __init__(self, br):
        BzrError.__init__(self, "Stores for branch %s are not listable" % br)


class BoundBranchOutOfDate(BzrError):

    _fmt = ("Bound branch %(branch)s is out of date with master branch"
            " %(master)s.%(extra_help)s")

    def __init__(self, branch, master):
        BzrError.__init__(self)
        self.branch = branch
        self.master = master
        self.extra_help = ''


class CommitToDoubleBoundBranch(BzrError):

    _fmt = ("Cannot commit to branch %(branch)s."
            " It is bound to %(master)s, which is bound to %(remote)s.")

    def __init__(self, branch, master, remote):
        BzrError.__init__(self)
        self.branch = branch
        self.master = master
        self.remote = remote


class OverwriteBoundBranch(BzrError):

    _fmt = "Cannot pull --overwrite to a branch which is bound %(branch)s"

    def __init__(self, branch):
        BzrError.__init__(self)
        self.branch = branch


class BoundBranchConnectionFailure(BzrError):

    _fmt = ("Unable to connect to target of bound branch %(branch)s"
            " => %(target)s: %(error)s")

    def __init__(self, branch, target, error):
        BzrError.__init__(self)
        self.branch = branch
        self.target = target
        self.error = error


class VersionedFileError(BzrError):

    _fmt = "Versioned file error"


class RevisionNotPresent(VersionedFileError):

    _fmt = 'Revision {%(revision_id)s} not present in "%(file_id)s".'

    def __init__(self, revision_id, file_id):
        VersionedFileError.__init__(self)
        self.revision_id = revision_id
        self.file_id = file_id


class RevisionAlreadyPresent(VersionedFileError):

    _fmt = 'Revision {%(revision_id)s} already present in "%(file_id)s".'

    def __init__(self, revision_id, file_id):
        VersionedFileError.__init__(self)
        self.revision_id = revision_id
        self.file_id = file_id


class VersionedFileInvalidChecksum(VersionedFileError):

    _fmt = "Text did not match its checksum: %(msg)s"


class NoSuchExportFormat(BzrError):

    _fmt = "Export format %(format)r not supported"

    def __init__(self, format):
        BzrError.__init__(self)
        self.format = format


class TransportError(BzrError):

    _fmt = "Transport error: %(msg)s %(orig_error)s"

    def __init__(self, msg=None, orig_error=None):
        if msg is None and orig_error is not None:
            msg = str(orig_error)
        if orig_error is None:
            orig_error = ''
        if msg is None:
            msg = ''
        self.msg = msg
        self.orig_error = orig_error
        BzrError.__init__(self)


class SmartProtocolError(TransportError):

    _fmt = "Generic bzr smart protocol error: %(details)s"

    def __init__(self, details):
        self.details = details


class UnexpectedProtocolVersionMarker(TransportError):

    _fmt = "Received bad protocol version marker: %(marker)r"

    def __init__(self, marker):
        self.marker = marker


class UnknownSmartMethod(InternalBzrError):

    _fmt = "The server does not recognise the '%(verb)s' request."

    def __init__(self, verb):
        self.verb = verb


# A set of semi-meaningful errors which can be thrown
class TransportNotPossible(TransportError):

    _fmt = "Transport operation not possible: %(msg)s %(orig_error)s"


class ConnectionError(TransportError):

    _fmt = "Connection error: %(msg)s %(orig_error)s"


class SocketConnectionError(ConnectionError):

    _fmt = "%(msg)s %(host)s%(port)s%(orig_error)s"

    def __init__(self, host, port=None, msg=None, orig_error=None):
        if msg is None:
            msg = 'Failed to connect to'
        if orig_error is None:
            orig_error = ''
        else:
            orig_error = '; ' + str(orig_error)
        ConnectionError.__init__(self, msg=msg, orig_error=orig_error)
        self.host = host
        if port is None:
            self.port = ''
        else:
            self.port = ':%s' % port


# XXX: This is also used for unexpected end of file, which is different at the
# TCP level from "connection reset".
class ConnectionReset(TransportError):

    _fmt = "Connection closed: %(msg)s %(orig_error)s"


class ConnectionTimeout(ConnectionError):

    _fmt = "Connection Timeout: %(msg)s%(orig_error)s"


class InvalidRange(TransportError):

    _fmt = "Invalid range access in %(path)s at %(offset)s: %(msg)s"

    def __init__(self, path, offset, msg=None):
        TransportError.__init__(self, msg)
        self.path = path
        self.offset = offset


class InvalidHttpResponse(TransportError):

    _fmt = "Invalid http response for %(path)s: %(msg)s%(orig_error)s"

    def __init__(self, path, msg, orig_error=None, headers=None):
        self.path = path
        if orig_error is None:
            orig_error = ''
        else:
            # This is reached for obscure and unusual errors so we want to
            # preserve as much info as possible to ease debug.
            orig_error = ': %r' % (orig_error,)
        self.headers = headers
        TransportError.__init__(self, msg, orig_error=orig_error)


class UnexpectedHttpStatus(InvalidHttpResponse):

    _fmt = "Unexpected HTTP status %(code)d for %(path)s: %(extra)s"

    def __init__(self, path, code, extra=None, headers=None):
        self.path = path
        self.code = code
        self.extra = extra or ''
        full_msg = 'status code %d unexpected' % code
        if extra is not None:
            full_msg += ': ' + extra
        InvalidHttpResponse.__init__(
            self, path, full_msg, headers=headers)


class BadHttpRequest(UnexpectedHttpStatus):

    _fmt = "Bad http request for %(path)s: %(reason)s"

    def __init__(self, path, reason):
        self.path = path
        self.reason = reason
        TransportError.__init__(self, reason)


class InvalidHttpRange(InvalidHttpResponse):

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

    _fmt = 'Invalid http Content-type "%(ctype)s" for %(path)s: %(msg)s'

    def __init__(self, path, ctype, msg):
        self.ctype = ctype
        InvalidHttpResponse.__init__(self, path, msg)


class RedirectRequested(TransportError):

    _fmt = '%(source)s is%(permanently)s redirected to %(target)s'

    def __init__(self, source, target, is_permanent=False):
        self.source = source
        self.target = target
        if is_permanent:
            self.permanently = ' permanently'
        else:
            self.permanently = ''
        TransportError.__init__(self)


class TooManyRedirections(TransportError):

    _fmt = "Too many redirections"


class ConflictsInTree(BzrError):

    _fmt = "Working tree has conflicts."


class DependencyNotPresent(BzrError):

    _fmt = 'Unable to import library "%(library)s": %(error)s'

    def __init__(self, library, error):
        BzrError.__init__(self, library=library, error=error)


class WorkingTreeNotRevision(BzrError):

    _fmt = ("The working tree for %(basedir)s has changed since"
            " the last commit, but weave merge requires that it be"
            " unchanged")

    def __init__(self, tree):
        BzrError.__init__(self, basedir=tree.basedir)


class GraphCycleError(BzrError):

    _fmt = "Cycle in graph %(graph)r"

    def __init__(self, graph):
        BzrError.__init__(self)
        self.graph = graph


class WritingCompleted(InternalBzrError):

    _fmt = ("The MediumRequest '%(request)s' has already had finish_writing "
            "called upon it - accept bytes may not be called anymore.")

    def __init__(self, request):
        self.request = request


class WritingNotComplete(InternalBzrError):

    _fmt = ("The MediumRequest '%(request)s' has not has finish_writing "
            "called upon it - until the write phase is complete no "
            "data may be read.")

    def __init__(self, request):
        self.request = request


class NotConflicted(BzrError):

    _fmt = "File %(filename)s is not conflicted."

    def __init__(self, filename):
        BzrError.__init__(self)
        self.filename = filename


class MediumNotConnected(InternalBzrError):

    _fmt = """The medium '%(medium)s' is not connected."""

    def __init__(self, medium):
        self.medium = medium


class MustUseDecorated(Exception):

    _fmt = "A decorating function has requested its original command be used."


class NoBundleFound(BzrError):

    _fmt = 'No bundle was found in "%(filename)s".'

    def __init__(self, filename):
        BzrError.__init__(self)
        self.filename = filename


class BundleNotSupported(BzrError):

    _fmt = "Unable to handle bundle version %(version)s: %(msg)s"

    def __init__(self, version, msg):
        BzrError.__init__(self)
        self.version = version
        self.msg = msg


class MissingText(BzrError):

    _fmt = ("Branch %(base)s is missing revision"
            " %(text_revision)s of %(file_id)s")

    def __init__(self, branch, text_revision, file_id):
        BzrError.__init__(self)
        self.branch = branch
        self.base = branch.base
        self.text_revision = text_revision
        self.file_id = file_id


class DuplicateKey(BzrError):

    _fmt = "Key %(key)s is already present in map"


class DuplicateHelpPrefix(BzrError):

    _fmt = "The prefix %(prefix)s is in the help search path twice."

    def __init__(self, prefix):
        self.prefix = prefix


class BzrBadParameter(InternalBzrError):

    _fmt = "Bad parameter: %(param)r"

    # This exception should never be thrown, but it is a base class for all
    # parameter-to-function errors.

    def __init__(self, param):
        BzrError.__init__(self)
        self.param = param


class BzrBadParameterNotUnicode(BzrBadParameter):

    _fmt = "Parameter %(param)s is neither unicode nor utf8."


class BzrMoveFailedError(BzrError):

    _fmt = ("Could not move %(from_path)s%(operator)s %(to_path)s"
            "%(_has_extra)s%(extra)s")

    def __init__(self, from_path='', to_path='', extra=None):
        from breezy.osutils import splitpath
        BzrError.__init__(self)
        if extra:
            self.extra, self._has_extra = extra, ': '
        else:
            self.extra = self._has_extra = ''

        has_from = len(from_path) > 0
        has_to = len(to_path) > 0
        if has_from:
            self.from_path = splitpath(from_path)[-1]
        else:
            self.from_path = ''

        if has_to:
            self.to_path = splitpath(to_path)[-1]
        else:
            self.to_path = ''

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

    _fmt = ("Could not rename %(from_path)s%(operator)s %(to_path)s"
            "%(_has_extra)s%(extra)s")

    def __init__(self, from_path, to_path, extra=None):
        BzrMoveFailedError.__init__(self, from_path, to_path, extra)


class BzrBadParameterNotString(BzrBadParameter):

    _fmt = "Parameter %(param)s is not a string or unicode string."


class BzrBadParameterMissing(BzrBadParameter):

    _fmt = "Parameter %(param)s is required but not present."


class BzrBadParameterUnicode(BzrBadParameter):

    _fmt = ("Parameter %(param)s is unicode but"
            " only byte-strings are permitted.")


class BzrBadParameterContainsNewline(BzrBadParameter):

    _fmt = "Parameter %(param)s contains a newline."


class ParamikoNotPresent(DependencyNotPresent):

    _fmt = "Unable to import paramiko (required for sftp support): %(error)s"

    def __init__(self, error):
        DependencyNotPresent.__init__(self, 'paramiko', error)


class UninitializableFormat(BzrError):

    _fmt = "Format %(format)s cannot be initialised by this version of brz."

    def __init__(self, format):
        BzrError.__init__(self)
        self.format = format


class BadConversionTarget(BzrError):

    _fmt = "Cannot convert from format %(from_format)s to format %(format)s." \
        "    %(problem)s"

    def __init__(self, problem, format, from_format=None):
        BzrError.__init__(self)
        self.problem = problem
        self.format = format
        self.from_format = from_format or '(unspecified)'


class NoDiffFound(BzrError):

    _fmt = 'Could not find an appropriate Differ for file "%(path)s"'

    def __init__(self, path):
        BzrError.__init__(self, path)


class ExecutableMissing(BzrError):

    _fmt = "%(exe_name)s could not be found on this machine"

    def __init__(self, exe_name):
        BzrError.__init__(self, exe_name=exe_name)


class NoDiff(BzrError):

    _fmt = "Diff is not installed on this machine: %(msg)s"

    def __init__(self, msg):
        BzrError.__init__(self, msg=msg)


class NoDiff3(BzrError):

    _fmt = "Diff3 is not installed on this machine."


class ExistingLimbo(BzrError):

    _fmt = """This tree contains left-over files from a failed operation.
    Please examine %(limbo_dir)s to see if it contains any files you wish to
    keep, and delete it when you are done."""

    def __init__(self, limbo_dir):
        BzrError.__init__(self)
        self.limbo_dir = limbo_dir


class ExistingPendingDeletion(BzrError):

    _fmt = """This tree contains left-over files from a failed operation.
    Please examine %(pending_deletion)s to see if it contains any files you
    wish to keep, and delete it when you are done."""

    def __init__(self, pending_deletion):
        BzrError.__init__(self, pending_deletion=pending_deletion)


class ImmortalPendingDeletion(BzrError):

    _fmt = ("Unable to delete transform temporary directory "
            "%(pending_deletion)s.  Please examine %(pending_deletion)s to see if it "
            "contains any files you wish to keep, and delete it when you are done.")

    def __init__(self, pending_deletion):
        BzrError.__init__(self, pending_deletion=pending_deletion)


class OutOfDateTree(BzrError):

    _fmt = "Working tree is out of date, please run 'brz update'.%(more)s"

    def __init__(self, tree, more=None):
        if more is None:
            more = ''
        else:
            more = ' ' + more
        BzrError.__init__(self)
        self.tree = tree
        self.more = more


class PublicBranchOutOfDate(BzrError):

    _fmt = 'Public branch "%(public_location)s" lacks revision '\
        '"%(revstring)s".'

    def __init__(self, public_location, revstring):
        import breezy.urlutils as urlutils
        public_location = urlutils.unescape_for_display(public_location,
                                                        'ascii')
        BzrError.__init__(self, public_location=public_location,
                          revstring=revstring)


class MergeModifiedFormatError(BzrError):

    _fmt = "Error in merge modified format"


class ConflictFormatError(BzrError):

    _fmt = "Format error in conflict listings"


class CorruptRepository(BzrError):

    _fmt = ("An error has been detected in the repository %(repo_path)s.\n"
            "Please run brz reconcile on this repository.")

    def __init__(self, repo):
        BzrError.__init__(self)
        self.repo_path = repo.user_url


class InconsistentDelta(BzrError):
    """Used when we get a delta that is not valid."""

    _fmt = ("An inconsistent delta was supplied involving %(path)r,"
            " %(file_id)r\nreason: %(reason)s")

    def __init__(self, path, file_id, reason):
        BzrError.__init__(self)
        self.path = path
        self.file_id = file_id
        self.reason = reason


class InconsistentDeltaDelta(InconsistentDelta):
    """Used when we get a delta that is not valid."""

    _fmt = ("An inconsistent delta was supplied: %(delta)r"
            "\nreason: %(reason)s")

    def __init__(self, delta, reason):
        BzrError.__init__(self)
        self.delta = delta
        self.reason = reason


class UpgradeRequired(BzrError):

    _fmt = "To use this feature you must upgrade your branch at %(path)s."

    def __init__(self, path):
        BzrError.__init__(self)
        self.path = path


class RepositoryUpgradeRequired(UpgradeRequired):

    _fmt = "To use this feature you must upgrade your repository at %(path)s."


class RichRootUpgradeRequired(UpgradeRequired):

    _fmt = ("To use this feature you must upgrade your branch at %(path)s to"
            " a format which supports rich roots.")


class LocalRequiresBoundBranch(BzrError):

    _fmt = "Cannot perform local-only commits on unbound branches."


class UnsupportedOperation(BzrError):

    _fmt = ("The method %(mname)s is not supported on"
            " objects of type %(tname)s.")

    def __init__(self, method, method_self):
        self.method = method
        self.mname = method.__name__
        self.tname = type(method_self).__name__


class FetchLimitUnsupported(UnsupportedOperation):

    fmt = ("InterBranch %(interbranch)r does not support fetching limits.")

    def __init__(self, interbranch):
        BzrError.__init__(self, interbranch=interbranch)


class NonAsciiRevisionId(UnsupportedOperation):
    """Raised when a commit is attempting to set a non-ascii revision id
       but cant.
    """


class SharedRepositoriesUnsupported(UnsupportedOperation):
    _fmt = "Shared repositories are not supported by %(format)r."

    def __init__(self, format):
        BzrError.__init__(self, format=format)


class GhostTagsNotSupported(BzrError):

    _fmt = "Ghost tags not supported by format %(format)r."

    def __init__(self, format):
        self.format = format


class BinaryFile(BzrError):

    _fmt = "File is binary but should be text."


class IllegalPath(BzrError):

    _fmt = "The path %(path)s is not permitted on this platform"

    def __init__(self, path):
        BzrError.__init__(self)
        self.path = path


class TestamentMismatch(BzrError):

    _fmt = """Testament did not match expected value.
       For revision_id {%(revision_id)s}, expected {%(expected)s}, measured
       {%(measured)s}"""

    def __init__(self, revision_id, expected, measured):
        self.revision_id = revision_id
        self.expected = expected
        self.measured = measured


class NotABundle(BzrError):

    _fmt = "Not a bzr revision-bundle: %(text)r"

    def __init__(self, text):
        BzrError.__init__(self)
        self.text = text


class BadBundle(BzrError):

    _fmt = "Bad bzr revision-bundle: %(text)r"

    def __init__(self, text):
        BzrError.__init__(self)
        self.text = text


class MalformedHeader(BadBundle):

    _fmt = "Malformed bzr revision-bundle header: %(text)r"


class MalformedPatches(BadBundle):

    _fmt = "Malformed patches in bzr revision-bundle: %(text)r"


class MalformedFooter(BadBundle):

    _fmt = "Malformed footer in bzr revision-bundle: %(text)r"


class UnsupportedEOLMarker(BadBundle):

    _fmt = "End of line marker was not \\n in bzr revision-bundle"

    def __init__(self):
        # XXX: BadBundle's constructor assumes there's explanatory text,
        # but for this there is not
        BzrError.__init__(self)


class IncompatibleBundleFormat(BzrError):

    _fmt = "Bundle format %(bundle_format)s is incompatible with %(other)s"

    def __init__(self, bundle_format, other):
        BzrError.__init__(self)
        self.bundle_format = bundle_format
        self.other = other


class RootNotRich(BzrError):

    _fmt = """This operation requires rich root data storage"""


class NoSmartMedium(InternalBzrError):

    _fmt = "The transport '%(transport)s' cannot tunnel the smart protocol."

    def __init__(self, transport):
        self.transport = transport


class UnknownSSH(BzrError):

    _fmt = "Unrecognised value for BRZ_SSH environment variable: %(vendor)s"

    def __init__(self, vendor):
        BzrError.__init__(self)
        self.vendor = vendor


class SSHVendorNotFound(BzrError):

    _fmt = ("Don't know how to handle SSH connections."
            " Please set BRZ_SSH environment variable.")


class GhostRevisionsHaveNoRevno(BzrError):
    """When searching for revnos, if we encounter a ghost, we are stuck"""

    _fmt = ("Could not determine revno for {%(revision_id)s} because"
            " its ancestry shows a ghost at {%(ghost_revision_id)s}")

    def __init__(self, revision_id, ghost_revision_id):
        self.revision_id = revision_id
        self.ghost_revision_id = ghost_revision_id


class GhostRevisionUnusableHere(BzrError):

    _fmt = "Ghost revision {%(revision_id)s} cannot be used here."

    def __init__(self, revision_id):
        BzrError.__init__(self)
        self.revision_id = revision_id


class NotAMergeDirective(BzrError):
    """File starting with %(firstline)r is not a merge directive"""

    def __init__(self, firstline):
        BzrError.__init__(self, firstline=firstline)


class NoMergeSource(BzrError):
    """Raise if no merge source was specified for a merge directive"""

    _fmt = "A merge directive must provide either a bundle or a public"\
        " branch location."


class PatchVerificationFailed(BzrError):
    """A patch from a merge directive could not be verified"""

    _fmt = "Preview patch does not match requested changes."


class PatchMissing(BzrError):
    """Raise a patch type was specified but no patch supplied"""

    _fmt = "Patch_type was %(patch_type)s, but no patch was supplied."

    def __init__(self, patch_type):
        BzrError.__init__(self)
        self.patch_type = patch_type


class TargetNotBranch(BzrError):
    """A merge directive's target branch is required, but isn't a branch"""

    _fmt = ("Your branch does not have all of the revisions required in "
            "order to merge this merge directive and the target "
            "location specified in the merge directive is not a branch: "
            "%(location)s.")

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

    _fmt = ("Tags not supported by %(branch)s;"
            " you may be able to use 'brz upgrade %(branch_url)s'.")

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

    _fmt = ('Working tree "%(display_url)s" has uncommitted changes'
            ' (See brz status).%(more)s')

    def __init__(self, tree, more=None):
        if more is None:
            more = ''
        else:
            more = ' ' + more
        import breezy.urlutils as urlutils
        user_url = getattr(tree, "user_url", None)
        if user_url is None:
            display_url = str(tree)
        else:
            display_url = urlutils.unescape_for_display(user_url, 'ascii')
        BzrError.__init__(self, tree=tree, display_url=display_url, more=more)


class StoringUncommittedNotSupported(BzrError):

    _fmt = ('Branch "%(display_url)s" does not support storing uncommitted'
            ' changes.')

    def __init__(self, branch):
        import breezy.urlutils as urlutils
        user_url = getattr(branch, "user_url", None)
        if user_url is None:
            display_url = str(branch)
        else:
            display_url = urlutils.unescape_for_display(user_url, 'ascii')
        BzrError.__init__(self, branch=branch, display_url=display_url)


class ShelvedChanges(UncommittedChanges):

    _fmt = ('Working tree "%(display_url)s" has shelved changes'
            ' (See brz shelve --list).%(more)s')


class UnableEncodePath(BzrError):

    _fmt = ('Unable to encode %(kind)s path %(path)r in '
            'user encoding %(user_encoding)s')

    def __init__(self, path, kind):
        from breezy.osutils import get_user_encoding
        self.path = path
        self.kind = kind
        self.user_encoding = get_user_encoding()


class CannotBindAddress(BzrError):

    _fmt = 'Cannot bind address "%(host)s:%(port)i": %(orig_error)s.'

    def __init__(self, host, port, orig_error):
        # nb: in python2.4 socket.error doesn't have a useful repr
        BzrError.__init__(self, host=host, port=port,
                          orig_error=repr(orig_error.args))


class TipChangeRejected(BzrError):
    """A pre_change_branch_tip hook function may raise this to cleanly and
    explicitly abort a change to a branch tip.
    """

    _fmt = u"Tip change rejected: %(msg)s"

    def __init__(self, msg):
        self.msg = msg


class JailBreak(BzrError):

    _fmt = "An attempt to access a url outside the server jail was made: '%(url)s'."

    def __init__(self, url):
        BzrError.__init__(self, url=url)


class UserAbort(BzrError):

    _fmt = 'The user aborted the operation.'


class UnresumableWriteGroup(BzrError):

    _fmt = ("Repository %(repository)s cannot resume write group "
            "%(write_groups)r: %(reason)s")

    internal_error = True

    def __init__(self, repository, write_groups, reason):
        self.repository = repository
        self.write_groups = write_groups
        self.reason = reason


class UnsuspendableWriteGroup(BzrError):

    _fmt = ("Repository %(repository)s cannot suspend a write group.")

    internal_error = True

    def __init__(self, repository):
        self.repository = repository


class LossyPushToSameVCS(BzrError):

    _fmt = ("Lossy push not possible between %(source_branch)r and "
            "%(target_branch)r that are in the same VCS.")

    internal_error = True

    def __init__(self, source_branch, target_branch):
        self.source_branch = source_branch
        self.target_branch = target_branch


class NoRoundtrippingSupport(BzrError):

    _fmt = ("Roundtripping is not supported between %(source_branch)r and "
            "%(target_branch)r.")

    internal_error = True

    def __init__(self, source_branch, target_branch):
        self.source_branch = source_branch
        self.target_branch = target_branch


class RecursiveBind(BzrError):

    _fmt = ('Branch "%(branch_url)s" appears to be bound to itself. '
            'Please use `brz unbind` to fix.')

    def __init__(self, branch_url):
        self.branch_url = branch_url


class UnsupportedKindChange(BzrError):

    _fmt = ("Kind change from %(from_kind)s to %(to_kind)s for "
            "%(path)s not supported by format %(format)r")

    def __init__(self, path, from_kind, to_kind, format):
        self.path = path
        self.from_kind = from_kind
        self.to_kind = to_kind
        self.format = format


class ChangesAlreadyStored(CommandError):

    _fmt = ('Cannot store uncommitted changes because this branch already'
            ' stores uncommitted changes.')


class RevnoOutOfBounds(InternalBzrError):

    _fmt = ("The requested revision number %(revno)d is outside of the "
            "expected boundaries (%(minimum)d <= %(maximum)d).")

    def __init__(self, revno, bounds):
        InternalBzrError.__init__(
            self, revno=revno, minimum=bounds[0], maximum=bounds[1])
