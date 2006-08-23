# Copyright (C) 2005 Canonical Ltd
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


import bisect
import datetime
import re

from bzrlib import (
    errors,
    revision,
    )
from bzrlib.errors import BzrError, NoSuchRevision, NoCommits


_marker = []


class RevisionInfo(object):
    """The results of applying a revision specification to a branch.

    An instance has two useful attributes: revno, and rev_id.

    They can also be accessed as spec[0] and spec[1] respectively,
    so that you can write code like:
    revno, rev_id = RevisionSpec(branch, spec)
    although this is probably going to be deprecated later.

    This class exists mostly to be the return value of a RevisionSpec,
    so that you can access the member you're interested in (number or id)
    or treat the result as a tuple.
    """

    def __init__(self, branch, revno, rev_id=_marker):
        self.branch = branch
        self.revno = revno
        if rev_id is _marker:
            # allow caller to be lazy
            if self.revno is None:
                self.rev_id = None
            else:
                self.rev_id = branch.get_rev_id(self.revno)
        else:
            self.rev_id = rev_id

    def __nonzero__(self):
        # first the easy ones...
        if self.rev_id is None:
            return False
        if self.revno is not None:
            return True
        # TODO: otherwise, it should depend on how I was built -
        # if it's in_history(branch), then check revision_history(),
        # if it's in_store(branch), do the check below
        return self.branch.repository.has_revision(self.rev_id)

    def __len__(self):
        return 2

    def __getitem__(self, index):
        if index == 0: return self.revno
        if index == 1: return self.rev_id
        raise IndexError(index)

    def get(self):
        return self.branch.repository.get_revision(self.rev_id)

    def __eq__(self, other):
        if type(other) not in (tuple, list, type(self)):
            return False
        if type(other) is type(self) and self.branch is not other.branch:
            return False
        return tuple(self) == tuple(other)

    def __repr__(self):
        return '<bzrlib.revisionspec.RevisionInfo object %s, %s for %r>' % (
            self.revno, self.rev_id, self.branch)


# classes in this list should have a "prefix" attribute, against which
# string specs are matched
SPEC_TYPES = []


class RevisionSpec(object):
    """A parsed revision specification.

    A revision specification can be an integer, in which case it is
    assumed to be a revno (though this will translate negative values
    into positive ones); or it can be a string, in which case it is
    parsed for something like 'date:' or 'revid:' etc.

    Revision specs are an UI element, and they have been moved out
    of the branch class to leave "back-end" classes unaware of such
    details.  Code that gets a revno or rev_id from other code should
    not be using revision specs - revnos and revision ids are the
    accepted ways to refer to revisions internally.

    (Equivalent to the old Branch method get_revision_info())
    """

    prefix = None

    def __new__(cls, spec, foo=_marker):
        """Parse a revision specifier.
        """
        if spec is None:
            return object.__new__(RevisionSpec, spec)

        try:
            spec = int(spec)
        except ValueError:
            pass

        if isinstance(spec, int):
            return object.__new__(RevisionSpec_int, spec)
        elif isinstance(spec, basestring):
            for spectype in SPEC_TYPES:
                if spec.startswith(spectype.prefix):
                    return object.__new__(spectype, spec)
            else:
                raise BzrError('No namespace registered for string: %r' %
                               spec)
        else:
            raise TypeError('Unhandled revision type %s' % spec)

    def __init__(self, spec):
        if self.prefix and spec.startswith(self.prefix):
            spec = spec[len(self.prefix):]
        self.spec = spec

    def _match_on(self, branch, revs):
        return RevisionInfo(branch, 0, None)

    def _match_on_and_check(self, branch, revs):
        info = self._match_on(branch, revs)
        if info:
            return info
        elif info == (0, None):
            # special case - the empty tree
            return info
        elif self.prefix:
            raise errors.InvalidRevisionSpec(self.prefix + self.spec, branch)
        else:
            raise errors.InvalidRevisionSpec(self.spec, branch)

    def in_history(self, branch):
        if branch:
            revs = branch.revision_history()
        else:
            revs = None
        return self._match_on_and_check(branch, revs)

        # FIXME: in_history is somewhat broken,
        # it will return non-history revisions in many
        # circumstances. The expected facility is that
        # in_history only returns revision-history revs,
        # in_store returns any rev. RBC 20051010
    # aliases for now, when we fix the core logic, then they
    # will do what you expect.
    in_store = in_history
    in_branch = in_store
        
    def __repr__(self):
        # this is mostly for helping with testing
        return '<%s %s%s>' % (self.__class__.__name__,
                              self.prefix or '',
                              self.spec)
    
    def needs_branch(self):
        """Whether this revision spec needs a branch.

        Set this to False the branch argument of _match_on is not used.
        """
        return True

# private API

class RevisionSpec_int(RevisionSpec):
    """Spec is a number.  Special case."""

    def __init__(self, spec):
        self.spec = int(spec)

    def _match_on(self, branch, revs):
        if self.spec < 0:
            revno = len(revs) + self.spec + 1
        else:
            revno = self.spec
        try:
            rev_id = branch.get_rev_id(revno, revs)
        except NoSuchRevision:
            raise errors.InvalidRevisionSpec(self.spec, branch)
        return RevisionInfo(branch, revno, rev_id)


class RevisionSpec_revno(RevisionSpec):
    prefix = 'revno:'

    def _match_on(self, branch, revs):
        """Lookup a revision by revision number"""
        loc = self.spec.find(':')
        if loc == -1:
            revno_spec = self.spec
            branch_spec = None
        else:
            revno_spec = self.spec[:loc]
            branch_spec = self.spec[loc+1:]

        if revno_spec == '':
            if not branch_spec:
                raise errors.InvalidRevisionSpec(self.prefix + self.spec,
                        branch, 'cannot have an empty revno and no branch')
            revno = None
        else:
            try:
                revno = int(revno_spec)
            except ValueError, e:
                raise errors.InvalidRevisionSpec(self.prefix + self.spec,
                                                 branch, e)

            if revno < 0:
                revno = len(revs) + revno + 1

        if branch_spec:
            from bzrlib.branch import Branch
            branch = Branch.open(branch_spec)

        try:
            revid = branch.get_rev_id(revno)
        except NoSuchRevision:
            raise errors.InvalidRevisionSpec(self.prefix + self.spec, branch)

        return RevisionInfo(branch, revno)
        
    def needs_branch(self):
        return self.spec.find(':') == -1

SPEC_TYPES.append(RevisionSpec_revno)


class RevisionSpec_revid(RevisionSpec):
    prefix = 'revid:'

    def _match_on(self, branch, revs):
        try:
            revno = revs.index(self.spec) + 1
        except ValueError:
            revno = None
        return RevisionInfo(branch, revno, self.spec)

SPEC_TYPES.append(RevisionSpec_revid)


class RevisionSpec_last(RevisionSpec):

    prefix = 'last:'

    def _match_on(self, branch, revs):
        if self.spec == '':
            if not revs:
                raise NoCommits(branch)
            return RevisionInfo(branch, len(revs), revs[-1])

        try:
            offset = int(self.spec)
        except ValueError, e:
            raise errors.InvalidRevisionSpec(self.prefix + self.spec, branch, e)

        if offset <= 0:
            raise errors.InvalidRevisionSpec(self.prefix + self.spec, branch,
                                             'you must supply a positive value')
        revno = len(revs) - offset + 1
        try:
            revision_id = branch.get_rev_id(revno, revs)
        except errors.NoSuchRevision:
            raise errors.InvalidRevisionSpec(self.prefix + self.spec, branch)
        return RevisionInfo(branch, revno, revision_id)

SPEC_TYPES.append(RevisionSpec_last)


class RevisionSpec_before(RevisionSpec):

    prefix = 'before:'
    
    def _match_on(self, branch, revs):
        r = RevisionSpec(self.spec)._match_on(branch, revs)
        if r.revno == 0:
            raise errors.InvalidRevisionSpec(self.prefix + self.spec, branch,
                                         'cannot go before the null: revision')
        if r.revno is None:
            # We need to use the repository history here
            rev = branch.repository.get_revision(r.rev_id)
            if not rev.parent_ids:
                revno = 0
                revision_id = None
            else:
                revision_id = rev.parent_ids[0]
                try:
                    revno = revs.index(revision_id) + 1
                except ValueError:
                    revno = None
        else:
            revno = r.revno - 1
            try:
                revision_id = branch.get_rev_id(revno, revs)
            except NoSuchRevision:
                raise errors.InvalidRevisionSpec(self.prefix + self.spec,
                                                 branch)
        return RevisionInfo(branch, revno, revision_id)

SPEC_TYPES.append(RevisionSpec_before)


class RevisionSpec_tag(RevisionSpec):
    prefix = 'tag:'

    def _match_on(self, branch, revs):
        raise errors.InvalidRevisionSpec(self.prefix + self.spec, branch,
                                         'tag: namespace registered,'
                                         ' but not implemented')

SPEC_TYPES.append(RevisionSpec_tag)


class _RevListToTimestamps(object):
    """This takes a list of revisions, and allows you to bisect by date"""

    __slots__ = ['revs', 'branch']

    def __init__(self, revs, branch):
        self.revs = revs
        self.branch = branch

    def __getitem__(self, index):
        """Get the date of the index'd item"""
        r = self.branch.repository.get_revision(self.revs[index])
        # TODO: Handle timezone.
        return datetime.datetime.fromtimestamp(r.timestamp)

    def __len__(self):
        return len(self.revs)


class RevisionSpec_date(RevisionSpec):
    prefix = 'date:'
    _date_re = re.compile(
            r'(?P<date>(?P<year>\d\d\d\d)-(?P<month>\d\d)-(?P<day>\d\d))?'
            r'(,|T)?\s*'
            r'(?P<time>(?P<hour>\d\d):(?P<minute>\d\d)(:(?P<second>\d\d))?)?'
        )

    def _match_on(self, branch, revs):
        """
        Spec for date revisions:
          date:value
          value can be 'yesterday', 'today', 'tomorrow' or a YYYY-MM-DD string.
          matches the first entry after a given date (either at midnight or
          at a specified time).

          So the proper way of saying 'give me all entries for today' is:
              -r date:yesterday..date:today
        """
        today = datetime.datetime.fromordinal(datetime.date.today().toordinal())
        if self.spec.lower() == 'yesterday':
            dt = today - datetime.timedelta(days=1)
        elif self.spec.lower() == 'today':
            dt = today
        elif self.spec.lower() == 'tomorrow':
            dt = today + datetime.timedelta(days=1)
        else:
            m = self._date_re.match(self.spec)
            if not m or (not m.group('date') and not m.group('time')):
                raise errors.InvalidRevisionSpec(self.prefix + self.spec,
                                                 branch, 'invalid date')

            try:
                if m.group('date'):
                    year = int(m.group('year'))
                    month = int(m.group('month'))
                    day = int(m.group('day'))
                else:
                    year = today.year
                    month = today.month
                    day = today.day

                if m.group('time'):
                    hour = int(m.group('hour'))
                    minute = int(m.group('minute'))
                    if m.group('second'):
                        second = int(m.group('second'))
                    else:
                        second = 0
                else:
                    hour, minute, second = 0,0,0
            except ValueError:
                raise errors.InvalidRevisionSpec(self.prefix + self.spec,
                                                 branch, 'invalid date')

            dt = datetime.datetime(year=year, month=month, day=day,
                    hour=hour, minute=minute, second=second)
        branch.lock_read()
        try:
            rev = bisect.bisect(_RevListToTimestamps(revs, branch), dt)
        finally:
            branch.unlock()
        if rev == len(revs):
            return RevisionInfo(branch, None)
        else:
            return RevisionInfo(branch, rev + 1)

SPEC_TYPES.append(RevisionSpec_date)


class RevisionSpec_ancestor(RevisionSpec):
    prefix = 'ancestor:'

    def _match_on(self, branch, revs):
        from bzrlib.branch import Branch

        other_branch = Branch.open(self.spec)
        revision_a = branch.last_revision()
        revision_b = other_branch.last_revision()
        for r, b in ((revision_a, branch), (revision_b, other_branch)):
            if r in (None, revision.NULL_REVISION):
                raise NoCommits(b)
        revision_source = revision.MultipleRevisionSources(
                branch.repository, other_branch.repository)
        rev_id = revision.common_ancestor(revision_a, revision_b,
                                          revision_source)
        try:
            revno = branch.revision_id_to_revno(rev_id)
        except NoSuchRevision:
            revno = None
        return RevisionInfo(branch, revno, rev_id)
        
SPEC_TYPES.append(RevisionSpec_ancestor)


class RevisionSpec_branch(RevisionSpec):
    """A branch: revision specifier.

    This takes the path to a branch and returns its tip revision id.
    """
    prefix = 'branch:'

    def _match_on(self, branch, revs):
        from bzrlib.branch import Branch
        other_branch = Branch.open(self.spec)
        revision_b = other_branch.last_revision()
        if revision_b in (None, revision.NULL_REVISION):
            raise NoCommits(other_branch)
        # pull in the remote revisions so we can diff
        branch.fetch(other_branch, revision_b)
        try:
            revno = branch.revision_id_to_revno(revision_b)
        except NoSuchRevision:
            revno = None
        return RevisionInfo(branch, revno, revision_b)
        
SPEC_TYPES.append(RevisionSpec_branch)
