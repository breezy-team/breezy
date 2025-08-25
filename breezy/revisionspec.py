# Copyright (C) 2005-2010 Canonical Ltd
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

"""Revision specification parsing and handling.

This module provides functionality for parsing and resolving revision specifications,
which allow users to specify particular revisions in various ways (by number, date,
tag, etc.). It includes RevisionSpec classes for different revision specification
types and utilities for resolving them to actual revision identifiers.
"""

from typing import Optional

from breezy import revision, workingtree

from . import errors, lazy_regex, registry, trace
from . import revision as _mod_revision
from .i18n import gettext


class InvalidRevisionSpec(errors.BzrError):
    """Exception raised when a revision specification cannot be resolved."""

    _fmt = (
        "Requested revision: '%(spec)s' does not exist in branch:"
        " %(branch_url)s%(extra)s"
    )

    def __init__(self, spec, branch, extra=None):
        """Initialize the exception.

        Args:
            spec: The revision specification that couldn't be resolved.
            branch: The branch where the resolution was attempted.
            extra: Optional additional error information.
        """
        errors.BzrError.__init__(self, branch=branch, spec=spec)
        self.branch_url = getattr(branch, "user_url", str(branch))
        if extra:
            self.extra = "\n" + str(extra)
        else:
            self.extra = ""


class RevisionInfo:
    """The results of applying a revision specification to a branch."""

    help_txt = """The results of applying a revision specification to a branch.

    An instance has two useful attributes: revno, and rev_id.

    They can also be accessed as spec[0] and spec[1] respectively,
    so that you can write code like:
    revno, rev_id = RevisionSpec(branch, spec)
    although this is probably going to be deprecated later.

    This class exists mostly to be the return value of a RevisionSpec,
    so that you can access the member you're interested in (number or id)
    or treat the result as a tuple.
    """

    def __init__(self, branch, revno=None, rev_id=None):
        """Initialize revision info.

        Args:
            branch: The branch this revision info is for.
            revno: Optional revision number.
            rev_id: Optional revision identifier.
        """
        self.branch = branch
        self._has_revno = revno is not None
        self._revno = revno
        self.rev_id = rev_id
        if self.rev_id is None and self._revno is not None:
            # allow caller to be lazy
            self.rev_id = branch.get_rev_id(self._revno)

    @property
    def revno(self):
        """Get the revision number, computing it if needed.

        Returns:
            The revision number, or None if not available.
        """
        if not self._has_revno and self.rev_id is not None:
            try:
                self._revno = self.branch.revision_id_to_revno(self.rev_id)
            except (errors.NoSuchRevision, errors.RevnoOutOfBounds):
                self._revno = None
            self._has_revno = True
        return self._revno

    def __bool__(self):
        """Return True if this represents a valid revision.

        Returns:
            True if the revision exists in the repository.
        """
        if self.rev_id is None:
            return False
        # TODO: otherwise, it should depend on how I was built -
        # if it's in_history(branch), then check revision_history(),
        # if it's in_store(branch), do the check below
        return self.branch.repository.has_revision(self.rev_id)

    __nonzero__ = __bool__

    def __len__(self):
        """Return length for tuple-like interface.

        Returns:
            Always returns 2 (revno, rev_id).
        """
        return 2

    def __getitem__(self, index):
        """Support tuple-like access to (revno, rev_id).

        Args:
            index: Index to access (0 for revno, 1 for rev_id).

        Returns:
            The revno (index 0) or rev_id (index 1).
        """
        if index == 0:
            return self.revno
        if index == 1:
            return self.rev_id
        raise IndexError(index)

    def get(self):
        """Get the actual Revision object.

        Returns:
            The Revision object from the repository.
        """
        return self.branch.repository.get_revision(self.rev_id)

    def __eq__(self, other):
        """Compare with another RevisionInfo or tuple.

        Args:
            other: Object to compare with.

        Returns:
            True if equal.
        """
        if type(other) not in (tuple, list, type(self)):
            return False
        if isinstance(other, type(self)) and self.branch is not other.branch:
            return False
        return tuple(self) == tuple(other)

    def __repr__(self):
        """Return string representation for debugging.

        Returns:
            String representation of this RevisionInfo.
        """
        return "<breezy.revisionspec.RevisionInfo object {}, {} for {!r}>".format(
            self.revno, self.rev_id, self.branch
        )

    @staticmethod
    def from_revision_id(branch, revision_id):
        """Construct a RevisionInfo given just the id.

        Use this if you don't know or care what the revno is.
        """
        return RevisionInfo(branch, revno=None, rev_id=revision_id)


class RevisionSpec:
    """A parsed revision specification."""

    help_txt = """A parsed revision specification.

    A revision specification is a string, which may be unambiguous about
    what it represents by giving a prefix like 'date:' or 'revid:' etc,
    or it may have no prefix, in which case it's tried against several
    specifier types in sequence to determine what the user meant.

    Revision specs are an UI element, and they have been moved out
    of the branch class to leave "back-end" classes unaware of such
    details.  Code that gets a revno or rev_id from other code should
    not be using revision specs - revnos and revision ids are the
    accepted ways to refer to revisions internally.

    (Equivalent to the old Branch method get_revision_info())
    """

    prefix: Optional[str] = None
    dwim_catchable_exceptions: list[type[Exception]] = [InvalidRevisionSpec]
    """Exceptions that RevisionSpec_dwim._match_on will catch.

    If the revspec is part of ``dwim_revspecs``, it may be tried with an
    invalid revspec and raises some exception. The exceptions mentioned here
    will not be reported to the user but simply ignored without stopping the
    dwim processing.
    """

    @staticmethod
    def from_string(spec):
        """Parse a revision spec string into a RevisionSpec object.

        :param spec: A string specified by the user
        :return: A RevisionSpec object that understands how to parse the
            supplied notation.
        """
        if spec is None:
            return RevisionSpec(None, _internal=True)
        if not isinstance(spec, str):
            raise TypeError("revision spec needs to be text")
        match = revspec_registry.get_prefix(spec)
        if match is not None:
            spectype, specsuffix = match
            trace.mutter("Returning RevisionSpec %s for %s", spectype.__name__, spec)
            return spectype(spec, _internal=True)
        else:
            # Otherwise treat it as a DWIM, build the RevisionSpec object and
            # wait for _match_on to be called.
            return RevisionSpec_dwim(spec, _internal=True)

    def __init__(self, spec, _internal=False):
        """Create a RevisionSpec referring to the Null revision.

        :param spec: The original spec supplied by the user
        :param _internal: Used to ensure that RevisionSpec is not being
            called directly. Only from RevisionSpec.from_string()
        """
        if not _internal:
            raise AssertionError(
                "Creating a RevisionSpec directly is not supported. "
                "Use RevisionSpec.from_string() instead."
            )
        self.user_spec = spec
        if self.prefix and spec.startswith(self.prefix):
            spec = spec[len(self.prefix) :]
        self.spec = spec

    def _match_on(self, branch, revs):
        trace.mutter("Returning RevisionSpec._match_on: None")
        return RevisionInfo(branch, None, None)

    def _match_on_and_check(self, branch, revs):
        info = self._match_on(branch, revs)
        if info:
            return info
        elif info == (None, None):
            # special case - nothing supplied
            return info
        elif self.prefix:
            raise InvalidRevisionSpec(self.user_spec, branch)
        else:
            raise InvalidRevisionSpec(self.spec, branch)

    def in_history(self, branch):
        """Resolve this revision spec within a branch's history.

        Args:
            branch: Branch to resolve the revision spec within.

        Returns:
            RevisionInfo object representing the resolved revision.
        """
        return self._match_on_and_check(branch, revs=None)

        # FIXME: in_history is somewhat broken,
        # it will return non-history revisions in many
        # circumstances. The expected facility is that
        # in_history only returns revision-history revs,
        # in_store returns any rev. RBC 20051010

    # aliases for now, when we fix the core logic, then they
    # will do what you expect.
    in_store = in_history
    in_branch = in_store

    def as_revision_id(self, context_branch):
        """Return just the revision_id for this revisions spec.

        Some revision specs require a context_branch to be able to determine
        their value. Not all specs will make use of it.
        """
        return self._as_revision_id(context_branch)

    def _as_revision_id(self, context_branch):
        """Implementation of as_revision_id().

        Classes should override this function to provide appropriate
        functionality. The default is to just call '.in_history().rev_id'
        """
        return self.in_history(context_branch).rev_id

    def as_tree(self, context_branch):
        """Return the tree object for this revisions spec.

        Some revision specs require a context_branch to be able to determine
        the revision id and access the repository. Not all specs will make
        use of it.
        """
        return self._as_tree(context_branch)

    def _as_tree(self, context_branch):
        """Implementation of as_tree().

        Classes should override this function to provide appropriate
        functionality. The default is to just call '.as_revision_id()'
        and get the revision tree from context_branch's repository.
        """
        revision_id = self.as_revision_id(context_branch)
        return context_branch.repository.revision_tree(revision_id)

    def __repr__(self):
        """Return string representation for debugging.

        Returns:
            String representation of this RevisionSpec.
        """
        # this is mostly for helping with testing
        return f"<{self.__class__.__name__} {self.user_spec}>"

    def needs_branch(self):
        """Whether this revision spec needs a branch.

        Set this to False the branch argument of _match_on is not used.
        """
        return True

    def get_branch(self):
        """When the revision specifier contains a branch location, return it.

        Otherwise, return None.
        """
        return None


# private API


class RevisionSpec_dwim(RevisionSpec):
    """Provides a DWIMish revision specifier lookup.

    Note that this does not go in the revspec_registry because by definition
    there is no prefix to identify it.  It's solely called from
    RevisionSpec.from_string() because the DWIMification happen when _match_on
    is called so the string describing the revision is kept here until needed.
    """

    help_txt: str

    _revno_regex = lazy_regex.lazy_compile(r"^(?:(\d+(\.\d+)*)|-\d+)(:.*)?$")

    # The revspecs to try
    _possible_revspecs: list[type[registry._ObjectGetter]] = []

    def _try_spectype(self, rstype, branch):
        rs = rstype(self.spec, _internal=True)
        # Hit in_history to find out if it exists, or we need to try the
        # next type.
        return rs.in_history(branch)

    def _match_on(self, branch, revs):
        """Run the lookup and see what we can get."""
        # First, see if it's a revno
        if self._revno_regex.match(self.spec) is not None:
            try:
                return self._try_spectype(RevisionSpec_revno, branch)
            except tuple(RevisionSpec_revno.dwim_catchable_exceptions):
                pass

        # Next see what has been registered
        for objgetter in self._possible_revspecs:
            rs_class = objgetter.get_obj()
            try:
                return self._try_spectype(rs_class, branch)
            except tuple(rs_class.dwim_catchable_exceptions):
                pass

        # Well, I dunno what it is. Note that we don't try to keep track of the
        # first of last exception raised during the DWIM tries as none seems
        # really relevant.
        raise InvalidRevisionSpec(self.spec, branch)

    @classmethod
    def append_possible_revspec(cls, revspec):
        """Append a possible DWIM revspec.

        :param revspec: Revision spec to try.
        """
        cls._possible_revspecs.append(registry._ObjectGetter(revspec))

    @classmethod
    def append_possible_lazy_revspec(cls, module_name, member_name):
        """Append a possible lazily loaded DWIM revspec.

        :param module_name: Name of the module with the revspec
        :param member_name: Name of the revspec within the module
        """
        cls._possible_revspecs.append(
            registry._LazyObjectGetter(module_name, member_name)
        )


class RevisionSpec_revno(RevisionSpec):
    """Selects a revision using a number."""

    help_txt = """Selects a revision using a number.

    Use an integer to specify a revision in the history of the branch.
    Optionally a branch can be specified.  A negative number will count
    from the end of the branch (-1 is the last revision, -2 the previous
    one). If the negative number is larger than the branch's history, the
    first revision is returned.
    Examples::

      revno:1                   -> return the first revision of this branch
      revno:3:/path/to/branch   -> return the 3rd revision of
                                   the branch '/path/to/branch'
      revno:-1                  -> The last revision in a branch.
      -2:http://other/branch    -> The second to last revision in the
                                   remote branch.
      -1000000                  -> Most likely the first revision, unless
                                   your history is very long.
    """
    prefix = "revno:"

    def _match_on(self, branch, revs):
        """Lookup a revision by revision number."""
        branch, revno, revision_id = self._lookup(branch)
        return RevisionInfo(branch, revno, revision_id)

    def _lookup(self, branch):
        loc = self.spec.find(":")
        if loc == -1:
            revno_spec = self.spec
            branch_spec = None
        else:
            revno_spec = self.spec[:loc]
            branch_spec = self.spec[loc + 1 :]

        if revno_spec == "":
            if not branch_spec:
                raise InvalidRevisionSpec(
                    self.user_spec, branch, "cannot have an empty revno and no branch"
                )
            revno = None
        else:
            try:
                revno = int(revno_spec)
                dotted = False
            except ValueError:
                # dotted decimal. This arguably should not be here
                # but the from_string method is a little primitive
                # right now - RBC 20060928
                try:
                    match_revno = tuple(int(number) for number in revno_spec.split("."))
                except ValueError as e:
                    raise InvalidRevisionSpec(self.user_spec, branch, e) from e

                dotted = True

        if branch_spec:
            from .branch import Branch

            # the user has overriden the branch to look in.
            branch = Branch.open(branch_spec)

        if dotted:
            try:
                revision_id = branch.dotted_revno_to_revision_id(
                    match_revno, _cache_reverse=True
                )
            except (errors.NoSuchRevision, errors.RevnoOutOfBounds) as err:
                raise InvalidRevisionSpec(self.user_spec, branch) from err
            else:
                # there is no traditional 'revno' for dotted-decimal revnos.
                # so for API compatibility we return None.
                return branch, None, revision_id
        else:
            last_revno, last_revision_id = branch.last_revision_info()
            if revno < 0:
                # if get_rev_id supported negative revnos, there would not be a
                # need for this special case.
                revno = 1 if -revno >= last_revno else last_revno + revno + 1
            try:
                revision_id = branch.get_rev_id(revno)
            except (errors.NoSuchRevision, errors.RevnoOutOfBounds) as err:
                raise InvalidRevisionSpec(self.user_spec, branch) from err
        return branch, revno, revision_id

    def _as_revision_id(self, context_branch):
        # We would have the revno here, but we don't really care
        branch, revno, revision_id = self._lookup(context_branch)
        return revision_id

    def needs_branch(self):
        """Check if this revision spec needs a branch context to resolve.

        Returns:
            True if a branch is needed for resolution.
        """
        return self.spec.find(":") == -1

    def get_branch(self):
        """Get the branch location if specified in the revision spec.

        Returns:
            Branch location string, or None if not specified.
        """
        if self.spec.find(":") == -1:
            return None
        else:
            return self.spec[self.spec.find(":") + 1 :]


# Old compatibility
RevisionSpec_int = RevisionSpec_revno


class RevisionIDSpec(RevisionSpec):
    """Base class for revision specs that work with revision IDs.

    This class provides common functionality for revision specs that
    resolve to specific revision identifiers.
    """

    def _match_on(self, branch, revs):
        revision_id = self.as_revision_id(branch)
        return RevisionInfo.from_revision_id(branch, revision_id)


class RevisionSpec_revid(RevisionIDSpec):
    """Selects a revision using the revision id."""

    help_txt = """Selects a revision using the revision id.

    Supply a specific revision id, that can be used to specify any
    revision id in the ancestry of the branch.
    Including merges, and pending merges.
    Examples::

      revid:aaaa@bbbb-123456789 -> Select revision 'aaaa@bbbb-123456789'
    """

    prefix = "revid:"

    def _as_revision_id(self, context_branch):
        # self.spec comes straight from parsing the command line arguments,
        # so we expect it to be a Unicode string. Switch it to the internal
        # representation.
        if isinstance(self.spec, str):
            return self.spec.encode("utf-8")
        return self.spec


class RevisionSpec_last(RevisionSpec):
    """Selects the nth revision from the end."""

    help_txt = """Selects the nth revision from the end.

    Supply a positive number to get the nth revision from the end.
    This is the same as supplying negative numbers to the 'revno:' spec.
    Examples::

      last:1        -> return the last revision
      last:3        -> return the revision 2 before the end.
    """

    prefix = "last:"

    def _match_on(self, branch, revs):
        revno, revision_id = self._revno_and_revision_id(branch)
        return RevisionInfo(branch, revno, revision_id)

    def _revno_and_revision_id(self, context_branch):
        last_revno, last_revision_id = context_branch.last_revision_info()

        if self.spec == "":
            if not last_revno:
                raise errors.NoCommits(context_branch)
            return last_revno, last_revision_id

        try:
            offset = int(self.spec)
        except ValueError as e:
            raise InvalidRevisionSpec(self.user_spec, context_branch, e) from e

        if offset <= 0:
            raise InvalidRevisionSpec(
                self.user_spec, context_branch, "you must supply a positive value"
            )

        revno = last_revno - offset + 1
        try:
            revision_id = context_branch.get_rev_id(revno)
        except (errors.NoSuchRevision, errors.RevnoOutOfBounds) as err:
            raise InvalidRevisionSpec(self.user_spec, context_branch) from err
        return revno, revision_id

    def _as_revision_id(self, context_branch):
        # We compute the revno as part of the process, but we don't really care
        # about it.
        revno, revision_id = self._revno_and_revision_id(context_branch)
        return revision_id


class RevisionSpec_before(RevisionSpec):
    """Selects the parent of the revision specified."""

    help_txt = """Selects the parent of the revision specified.

    Supply any revision spec to return the parent of that revision.  This is
    mostly useful when inspecting revisions that are not in the revision history
    of a branch.

    It is an error to request the parent of the null revision (before:0).

    Examples::

      before:1913    -> Return the parent of revno 1913 (revno 1912)
      before:revid:aaaa@bbbb-1234567890  -> return the parent of revision
                                            aaaa@bbbb-1234567890
      bzr diff -r before:1913..1913
            -> Find the changes between revision 1913 and its parent (1912).
               (What changes did revision 1913 introduce).
               This is equivalent to:  bzr diff -c 1913
    """

    prefix = "before:"

    def _match_on(self, branch, revs):
        r = RevisionSpec.from_string(self.spec)._match_on(branch, revs)
        if r.revno == 0:
            raise InvalidRevisionSpec(
                self.user_spec, branch, "cannot go before the null: revision"
            )
        if r.revno is None:
            # We need to use the repository history here
            rev = branch.repository.get_revision(r.rev_id)
            if not rev.parent_ids:
                revision_id = revision.NULL_REVISION
            else:
                revision_id = rev.parent_ids[0]
            revno = None
        else:
            revno = r.revno - 1
            try:
                revision_id = branch.get_rev_id(revno, revs)
            except (errors.NoSuchRevision, errors.RevnoOutOfBounds) as err:
                raise InvalidRevisionSpec(self.user_spec, branch) from err
        return RevisionInfo(branch, revno, revision_id)

    def _as_revision_id(self, context_branch):
        base_revision_id = RevisionSpec.from_string(self.spec)._as_revision_id(
            context_branch
        )
        if base_revision_id == revision.NULL_REVISION:
            raise InvalidRevisionSpec(
                self.user_spec, context_branch, "cannot go before the null: revision"
            )
        context_repo = context_branch.repository
        with context_repo.lock_read():
            parent_map = context_repo.get_parent_map([base_revision_id])
        if base_revision_id not in parent_map:
            # Ghost, or unknown revision id
            raise InvalidRevisionSpec(
                self.user_spec, context_branch, "cannot find the matching revision"
            )
        parents = parent_map[base_revision_id]
        if len(parents) < 1:
            raise InvalidRevisionSpec(
                self.user_spec, context_branch, "No parents for revision."
            )
        return parents[0]


class RevisionSpec_tag(RevisionSpec):
    """Select a revision identified by tag name."""

    help_txt = """Selects a revision identified by a tag name.

    Tags are stored in the branch and created by the 'tag' command.
    """

    prefix = "tag:"
    dwim_catchable_exceptions = [errors.NoSuchTag, errors.TagsNotSupported]

    def _match_on(self, branch, revs):
        # Can raise tags not supported, NoSuchTag, etc
        return RevisionInfo.from_revision_id(branch, branch.tags.lookup_tag(self.spec))

    def _as_revision_id(self, context_branch):
        return context_branch.tags.lookup_tag(self.spec)


class _RevListToTimestamps:
    """This takes a list of revisions, and allows you to bisect by date."""

    __slots__ = ["branch"]

    def __init__(self, branch):
        self.branch = branch

    def __getitem__(self, index):
        """Get the date of the index'd item."""
        r = self.branch.repository.get_revision(self.branch.get_rev_id(index))
        return r.datetime()


_date_regex = lazy_regex.lazy_compile(
    r"(?P<date>(?P<year>\d\d\d\d)-(?P<month>\d\d)-(?P<day>\d\d))?"
    r"(,|T)?\s*"
    r"(?P<time>(?P<hour>\d\d):(?P<minute>\d\d)(:(?P<second>\d\d))?)?"
)


def _parse_datespec(spec):
    import datetime

    #  XXX: This doesn't actually work
    #  So the proper way of saying 'give me all entries for today' is:
    #      -r date:yesterday..date:today
    today = datetime.datetime.fromordinal(datetime.date.today().toordinal())
    if spec.lower() == "yesterday":
        return today - datetime.timedelta(days=1)
    elif spec.lower() == "today":
        return today
    elif spec.lower() == "tomorrow":
        return today + datetime.timedelta(days=1)
    else:
        m = _date_regex.match(spec)
        if not m or (not m.group("date") and not m.group("time")):
            raise ValueError

        if m.group("date"):
            year = int(m.group("year"))
            month = int(m.group("month"))
            day = int(m.group("day"))
        else:
            year = today.year
            month = today.month
            day = today.day

        if m.group("time"):
            hour = int(m.group("hour"))
            minute = int(m.group("minute"))
            second = int(m.group("second")) if m.group("second") else 0
        else:
            hour, minute, second = 0, 0, 0

        return datetime.datetime(
            year=year, month=month, day=day, hour=hour, minute=minute, second=second
        )


class RevisionSpec_date(RevisionSpec):
    """Selects a revision on the basis of a datestamp."""

    help_txt = """Selects a revision on the basis of a datestamp.

    Supply a datestamp to select the first revision that matches the date.
    Date can be 'yesterday', 'today', 'tomorrow' or a YYYY-MM-DD string.
    Matches the first entry after a given date (either at midnight or
    at a specified time).

    One way to display all the changes since yesterday would be::

        brz log -r date:yesterday..

    Examples::

      date:yesterday            -> select the first revision since yesterday
      date:2006-08-14,17:10:14  -> select the first revision after
                                   August 14th, 2006 at 5:10pm.
    """
    prefix = "date:"

    def _scan_backwards(self, branch, dt):
        with branch.lock_read():
            graph = branch.repository.get_graph()
            last_match = None
            for revid in graph.iter_lefthand_ancestry(
                branch.last_revision(), (_mod_revision.NULL_REVISION,)
            ):
                r = branch.repository.get_revision(revid)
                if r.datetime() < dt:
                    if last_match is None:
                        raise InvalidRevisionSpec(self.user_spec, branch)
                    return RevisionInfo(branch, None, last_match)
                last_match = revid
            return RevisionInfo(branch, None, last_match)

    def _bisect_backwards(self, branch, dt, hi):
        import bisect

        with branch.lock_read():
            rev = bisect.bisect(_RevListToTimestamps(branch), dt, 1, hi)
        if rev == branch.revno():
            raise InvalidRevisionSpec(self.user_spec, branch)
        return RevisionInfo(branch, rev)

    def _match_on(self, branch, revs):
        """Spec for date revisions:
        date:value
        value can be 'yesterday', 'today', 'tomorrow' or a YYYY-MM-DD string.
        matches the first entry after a given date (either at midnight or
        at a specified time).
        """
        try:
            dt = _parse_datespec(self.spec)
        except ValueError as err:
            raise InvalidRevisionSpec(self.user_spec, branch, "invalid date") from err
        revno = branch.revno()
        if revno is None:
            return self._scan_backwards(branch, dt)
        else:
            return self._bisect_backwards(branch, dt, revno)


class RevisionSpec_ancestor(RevisionSpec):
    """Selects a common ancestor with a second branch."""

    help_txt = """Selects a common ancestor with a second branch.

    Supply the path to a branch to select the common ancestor.

    The common ancestor is the last revision that existed in both
    branches. Usually this is the branch point, but it could also be
    a revision that was merged.

    This is frequently used with 'diff' to return all of the changes
    that your branch introduces, while excluding the changes that you
    have not merged from the remote branch.

    Examples::

      ancestor:/path/to/branch
      $ bzr diff -r ancestor:../../mainline/branch
    """
    prefix = "ancestor:"

    def _match_on(self, branch, revs):
        trace.mutter("matching ancestor: on: %s, %s", self.spec, branch)
        return self._find_revision_info(branch, self.spec)

    def _as_revision_id(self, context_branch):
        return self._find_revision_id(context_branch, self.spec)

    @staticmethod
    def _find_revision_info(branch, other_location):
        revision_id = RevisionSpec_ancestor._find_revision_id(branch, other_location)
        return RevisionInfo(branch, None, revision_id)

    @staticmethod
    def _find_revision_id(branch, other_location):
        from .branch import Branch

        with branch.lock_read():
            revision_a = branch.last_revision()
            if revision_a == revision.NULL_REVISION:
                raise errors.NoCommits(branch)
            if other_location == "":
                other_location = branch.get_parent()
            other_branch = Branch.open(other_location)
            with other_branch.lock_read():
                revision_b = other_branch.last_revision()
                if revision_b == revision.NULL_REVISION:
                    raise errors.NoCommits(other_branch)
                graph = branch.repository.get_graph(other_branch.repository)
                rev_id = graph.find_unique_lca(revision_a, revision_b)
            if rev_id == revision.NULL_REVISION:
                raise errors.NoCommonAncestor(revision_a, revision_b)
            return rev_id


class RevisionSpec_branch(RevisionSpec):
    """Selects the last revision of a specified branch."""

    help_txt = """Selects the last revision of a specified branch.

    Supply the path to a branch to select its last revision.

    Examples::

      branch:/path/to/branch
    """
    prefix = "branch:"
    dwim_catchable_exceptions = [errors.NotBranchError]

    def _match_on(self, branch, revs):
        from .branch import Branch

        other_branch = Branch.open(self.spec)
        revision_b = other_branch.last_revision()
        if revision_b in (None, revision.NULL_REVISION):
            raise errors.NoCommits(other_branch)
        if branch is None:
            branch = other_branch
        else:
            try:
                # pull in the remote revisions so we can diff
                branch.fetch(other_branch, revision_b)
            except errors.ReadOnlyError:
                branch = other_branch
        return RevisionInfo(branch, None, revision_b)

    def _as_revision_id(self, context_branch):
        from .branch import Branch

        other_branch = Branch.open(self.spec)
        last_revision = other_branch.last_revision()
        context_branch.fetch(other_branch, last_revision)
        if last_revision == revision.NULL_REVISION:
            raise errors.NoCommits(other_branch)
        return last_revision

    def _as_tree(self, context_branch):
        from .branch import Branch

        other_branch = Branch.open(self.spec)
        last_revision = other_branch.last_revision()
        if last_revision == revision.NULL_REVISION:
            raise errors.NoCommits(other_branch)
        return other_branch.repository.revision_tree(last_revision)

    def needs_branch(self):
        """Check if this revision spec needs a branch context to resolve.

        Returns:
            False since branch specs don't need additional context.
        """
        return False

    def get_branch(self):
        """Get the branch location specified in this revision spec.

        Returns:
            The branch location string.
        """
        return self.spec


class RevisionSpec_submit(RevisionSpec_ancestor):
    """Selects a common ancestor with a submit branch."""

    help_txt = """Selects a common ancestor with the submit branch.

    Diffing against this shows all the changes that were made in this branch,
    and is a good predictor of what merge will do.  The submit branch is
    used by the bundle and merge directive commands.  If no submit branch
    is specified, the parent branch is used instead.

    The common ancestor is the last revision that existed in both
    branches. Usually this is the branch point, but it could also be
    a revision that was merged.

    Examples::

      $ bzr diff -r submit:
    """

    prefix = "submit:"

    def _get_submit_location(self, branch):
        submit_location = branch.get_submit_branch()
        location_type = "submit branch"
        if submit_location is None:
            submit_location = branch.get_parent()
            location_type = "parent branch"
        if submit_location is None:
            raise errors.NoSubmitBranch(branch)
        trace.note(gettext("Using {0} {1}").format(location_type, submit_location))
        return submit_location

    def _match_on(self, branch, revs):
        trace.mutter("matching ancestor: on: %s, %s", self.spec, branch)
        return self._find_revision_info(branch, self._get_submit_location(branch))

    def _as_revision_id(self, context_branch):
        return self._find_revision_id(
            context_branch, self._get_submit_location(context_branch)
        )


class RevisionSpec_annotate(RevisionIDSpec):
    """Revision spec that selects the revision that last modified a specific line.

    Uses the format 'annotate:path:line_number' to identify the revision
    that last modified the specified line in the given file.
    """

    prefix = "annotate:"

    help_txt = """Select the revision that last modified the specified line.

    Select the revision that last modified the specified line.  Line is
    specified as path:number.  Path is a relative path to the file.  Numbers
    start at 1, and are relative to the current version, not the last-
    committed version of the file.
    """

    def _raise_invalid(self, numstring, context_branch):
        raise InvalidRevisionSpec(
            self.user_spec, context_branch, f"No such line: {numstring}"
        )

    def _as_revision_id(self, context_branch):
        path, numstring = self.spec.rsplit(":", 1)
        try:
            index = int(numstring) - 1
        except ValueError:
            self._raise_invalid(numstring, context_branch)
        tree, file_path = workingtree.WorkingTree.open_containing(path)
        with tree.lock_read():
            if not tree.has_filename(file_path):
                raise InvalidRevisionSpec(
                    self.user_spec,
                    context_branch,
                    f"File '{file_path}' is not versioned.",
                )
            revision_ids = [r for (r, l) in tree.annotate_iter(file_path)]
        try:
            revision_id = revision_ids[index]
        except IndexError:
            self._raise_invalid(numstring, context_branch)
        if revision_id == revision.CURRENT_REVISION:
            raise InvalidRevisionSpec(
                self.user_spec,
                context_branch,
                f"Line {numstring} has not been committed.",
            )
        return revision_id


class RevisionSpec_mainline(RevisionIDSpec):
    """Revision spec that selects the mainline revision that merged another revision.

    Finds the revision on the mainline (left-hand parent chain) that merged
    the specified revision into the mainline history.
    """

    help_txt = """Select mainline revision that merged the specified revision.

    Select the revision that merged the specified revision into mainline.
    """

    prefix = "mainline:"

    def _as_revision_id(self, context_branch):
        revspec = RevisionSpec.from_string(self.spec)
        if revspec.get_branch() is None:
            spec_branch = context_branch
        else:
            from .branch import Branch

            spec_branch = Branch.open(revspec.get_branch())
        revision_id = revspec.as_revision_id(spec_branch)
        graph = context_branch.repository.get_graph()
        result = graph.find_lefthand_merger(revision_id, context_branch.last_revision())
        if result is None:
            raise InvalidRevisionSpec(self.user_spec, context_branch)
        return result


# The order in which we want to DWIM a revision spec without any prefix.
# revno is always tried first and isn't listed here, this is used by
# RevisionSpec_dwim._match_on
RevisionSpec_dwim.append_possible_revspec(RevisionSpec_tag)
RevisionSpec_dwim.append_possible_revspec(RevisionSpec_revid)
RevisionSpec_dwim.append_possible_revspec(RevisionSpec_date)
RevisionSpec_dwim.append_possible_revspec(RevisionSpec_branch)

revspec_registry = registry.Registry[str, RevisionSpec, None]()


def _register_revspec(revspec):
    revspec_registry.register(revspec.prefix, revspec)


_register_revspec(RevisionSpec_revno)
_register_revspec(RevisionSpec_revid)
_register_revspec(RevisionSpec_last)
_register_revspec(RevisionSpec_before)
_register_revspec(RevisionSpec_tag)
_register_revspec(RevisionSpec_date)
_register_revspec(RevisionSpec_ancestor)
_register_revspec(RevisionSpec_branch)
_register_revspec(RevisionSpec_submit)
_register_revspec(RevisionSpec_annotate)
_register_revspec(RevisionSpec_mainline)
