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
    symbol_versioning,
    trace,
    )


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
_revno_regex = None


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

    def __new__(cls, spec, _internal=False):
        if _internal:
            return object.__new__(cls, spec, _internal=_internal)

        symbol_versioning.warn('Creating a RevisionSpec directly has'
                               ' been deprecated in version 0.11. Use'
                               ' RevisionSpec.from_string()'
                               ' instead.',
                               DeprecationWarning, stacklevel=2)
        return RevisionSpec.from_string(spec)

    @staticmethod
    def from_string(spec):
        """Parse a revision spec string into a RevisionSpec object.

        :param spec: A string specified by the user
        :return: A RevisionSpec object that understands how to parse the
            supplied notation.
        """
        if not isinstance(spec, (type(None), basestring)):
            raise TypeError('error')

        if spec is None:
            return RevisionSpec(None, _internal=True)

        assert isinstance(spec, basestring), \
            "You should only supply strings not %s" % (type(spec),)

        for spectype in SPEC_TYPES:
            if spec.startswith(spectype.prefix):
                trace.mutter('Returning RevisionSpec %s for %s',
                             spectype.__name__, spec)
                return spectype(spec, _internal=True)
        else:
            # RevisionSpec_revno is special cased, because it is the only
            # one that directly handles plain integers
            global _revno_regex
            if _revno_regex is None:
                _revno_regex = re.compile(r'-?\d+(:.*)?$')
            if _revno_regex.match(spec) is not None:
                return RevisionSpec_revno(spec, _internal=True)

            raise errors.NoSuchRevisionSpec(spec)

    def __init__(self, spec, _internal=False):
        """Create a RevisionSpec referring to the Null revision.

        :param spec: The original spec supplied by the user
        :param _internal: Used to ensure that RevisionSpec is not being
            called directly. Only from RevisionSpec.from_string()
        """
        if not _internal:
            # XXX: Update this after 0.10 is released
            symbol_versioning.warn('Creating a RevisionSpec directly has'
                                   ' been deprecated in version 0.11. Use'
                                   ' RevisionSpec.from_string()'
                                   ' instead.',
                                   DeprecationWarning, stacklevel=2)
        self.user_spec = spec
        if self.prefix and spec.startswith(self.prefix):
            spec = spec[len(self.prefix):]
        self.spec = spec

    def _match_on(self, branch, revs):
        trace.mutter('Returning RevisionSpec._match_on: None')
        return RevisionInfo(branch, 0, None)

    def _match_on_and_check(self, branch, revs):
        info = self._match_on(branch, revs)
        if info:
            return info
        elif info == (0, None):
            # special case - the empty tree
            return info
        elif self.prefix:
            raise errors.InvalidRevisionSpec(self.user_spec, branch)
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
        return '<%s %s>' % (self.__class__.__name__,
                              self.user_spec)
    
    def needs_branch(self):
        """Whether this revision spec needs a branch.

        Set this to False the branch argument of _match_on is not used.
        """
        return True


# private API

class RevisionSpec_revno(RevisionSpec):
    """
    This takes the a number  and return the related revision.
    Optionally can be specified a branch
    examples:
      revno:1                   -> return the first revision
      revno:3:/path/to/branch   -> return the 3rd revision of
                                   the branch '/path/to/branch'
    """
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
                raise errors.InvalidRevisionSpec(self.user_spec,
                        branch, 'cannot have an empty revno and no branch')
            revno = None
        else:
            try:
                revno = int(revno_spec)
            except ValueError, e:
                raise errors.InvalidRevisionSpec(self.user_spec,
                                                 branch, e)

        if branch_spec:
            from bzrlib.branch import Branch
            branch = Branch.open(branch_spec)
            # Need to use a new revision history
            # because we are using a specific branch
            revs = branch.revision_history()

        if revno < 0:
            if (-revno) >= len(revs):
                revno = 1
            else:
                revno = len(revs) + revno + 1
        try:
            revision_id = branch.get_rev_id(revno, revs)
        except errors.NoSuchRevision:
            raise errors.InvalidRevisionSpec(self.user_spec, branch)
        return RevisionInfo(branch, revno, revision_id)
        
    def needs_branch(self):
        return self.spec.find(':') == -1

# Old compatibility 
RevisionSpec_int = RevisionSpec_revno

SPEC_TYPES.append(RevisionSpec_revno)


class RevisionSpec_revid(RevisionSpec):
    """
    This takes the a revision-id and return the related revision.
    examples:
      revid:aaaa@bbbb-123456789
    """    
    prefix = 'revid:'

    def _match_on(self, branch, revs):
        try:
            revno = revs.index(self.spec) + 1
        except ValueError:
            revno = None
        return RevisionInfo(branch, revno, self.spec)

SPEC_TYPES.append(RevisionSpec_revid)


class RevisionSpec_last(RevisionSpec):
    """
    This takes the a namber <n> and return the <n> - 1 revision before.
    examples:
      last:1        -> return the last revision
      last3:        -> return the last - 2 revision
    """    

    prefix = 'last:'

    def _match_on(self, branch, revs):
        if self.spec == '':
            if not revs:
                raise errors.NoCommits(branch)
            return RevisionInfo(branch, len(revs), revs[-1])

        try:
            offset = int(self.spec)
        except ValueError, e:
            raise errors.InvalidRevisionSpec(self.user_spec, branch, e)

        if offset <= 0:
            raise errors.InvalidRevisionSpec(self.user_spec, branch,
                                             'you must supply a positive value')
        revno = len(revs) - offset + 1
        try:
            revision_id = branch.get_rev_id(revno, revs)
        except errors.NoSuchRevision:
            raise errors.InvalidRevisionSpec(self.user_spec, branch)
        return RevisionInfo(branch, revno, revision_id)

SPEC_TYPES.append(RevisionSpec_last)


class RevisionSpec_before(RevisionSpec):
    """
    This takes the a revision and return the revision before.
    examples:
      before:1913
      before:revid:aaaa@bbbb-1234567890
    """

    prefix = 'before:'
    
    def _match_on(self, branch, revs):
        r = RevisionSpec.from_string(self.spec)._match_on(branch, revs)
        if r.revno == 0:
            raise errors.InvalidRevisionSpec(self.user_spec, branch,
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
            except errors.NoSuchRevision:
                raise errors.InvalidRevisionSpec(self.user_spec,
                                                 branch)
        return RevisionInfo(branch, revno, revision_id)

SPEC_TYPES.append(RevisionSpec_before)


class RevisionSpec_tag(RevisionSpec):
    """
    To be implemented.
    """
    prefix = 'tag:'

    def _match_on(self, branch, revs):
        raise errors.InvalidRevisionSpec(self.user_spec, branch,
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
    """
    This takes the date and return the first revision which matches.
    date can be 'yesterday', 'today', 'tomorrow' or a YYYY-MM-DD string.
    matches the first entry after a given date (either at midnight or
    at a specified time).

    So the proper way of saying 'give me all entries for today' is:
          date:yesterday..date:today

    examples:
      date:yesterday
      date:2006-08-14,17:10:14
    """    
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
                raise errors.InvalidRevisionSpec(self.user_spec,
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
                raise errors.InvalidRevisionSpec(self.user_spec,
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
    """
    This takes the path to a branch and returns the common ancestor.
    examples:
      ancestor:/path/to/branch
    """
    prefix = 'ancestor:'

    def _match_on(self, branch, revs):
        from bzrlib.branch import Branch

        trace.mutter('matching ancestor: on: %s, %s', self.spec, branch)
        other_branch = Branch.open(self.spec)
        revision_a = branch.last_revision()
        revision_b = other_branch.last_revision()
        for r, b in ((revision_a, branch), (revision_b, other_branch)):
            if r in (None, revision.NULL_REVISION):
                raise errors.NoCommits(b)
        revision_source = revision.MultipleRevisionSources(
                branch.repository, other_branch.repository)
        rev_id = revision.common_ancestor(revision_a, revision_b,
                                          revision_source)
        try:
            revno = branch.revision_id_to_revno(rev_id)
        except errors.NoSuchRevision:
            revno = None
        return RevisionInfo(branch, revno, rev_id)
        
SPEC_TYPES.append(RevisionSpec_ancestor)


class RevisionSpec_branch(RevisionSpec):
    """
    This takes the path to a branch and returns its tip revision id.
    examples:
      branch:/path/to/branch
    """
    prefix = 'branch:'

    def _match_on(self, branch, revs):
        from bzrlib.branch import Branch
        other_branch = Branch.open(self.spec)
        revision_b = other_branch.last_revision()
        if revision_b in (None, revision.NULL_REVISION):
            raise errors.NoCommits(other_branch)
        # pull in the remote revisions so we can diff
        branch.fetch(other_branch, revision_b)
        try:
            revno = branch.revision_id_to_revno(revision_b)
        except errors.NoSuchRevision:
            revno = None
        return RevisionInfo(branch, revno, revision_b)
        
SPEC_TYPES.append(RevisionSpec_branch)
