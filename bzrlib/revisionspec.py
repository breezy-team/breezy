# Copyright (C) 2005 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


import datetime
import re
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
        return self.rev_id in self.branch.revision_store

    def __len__(self):
        return 2

    def __getitem__(self, index):
        if index == 0: return self.revno
        if index == 1: return self.rev_id
        raise IndexError(index)

    def get(self):
        return self.branch.get_revision(self.rev_id)

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
            raise NoSuchRevision(branch, self.prefix + str(self.spec))
        else:
            raise NoSuchRevision(branch, str(self.spec))

    def in_history(self, branch):
        revs = branch.revision_history()
        return self._match_on_and_check(branch, revs)

    def __repr__(self):
        # this is mostly for helping with testing
        return '<%s %s%s>' % (self.__class__.__name__,
                              self.prefix or '',
                              self.spec)


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
        rev_id = branch.get_rev_id(revno, revs)
        return RevisionInfo(branch, revno, rev_id)


class RevisionSpec_revno(RevisionSpec):
    prefix = 'revno:'

    def _match_on(self, branch, revs):
        """Lookup a revision by revision number"""
        try:
            return RevisionInfo(branch, int(self.spec))
        except ValueError:
            return RevisionInfo(branch, None)

SPEC_TYPES.append(RevisionSpec_revno)


class RevisionSpec_revid(RevisionSpec):
    prefix = 'revid:'

    def _match_on(self, branch, revs):
        try:
            return RevisionInfo(branch, revs.index(self.spec) + 1, self.spec)
        except ValueError:
            return RevisionInfo(branch, None)

SPEC_TYPES.append(RevisionSpec_revid)


class RevisionSpec_last(RevisionSpec):
    prefix = 'last:'

    def _match_on(self, branch, revs):
        try:
            offset = int(self.spec)
        except ValueError:
            return RevisionInfo(branch, None)
        else:
            if offset <= 0:
                raise BzrError('You must supply a positive value for --revision last:XXX')
            return RevisionInfo(branch, len(revs) - offset + 1)

SPEC_TYPES.append(RevisionSpec_last)


class RevisionSpec_tag(RevisionSpec):
    prefix = 'tag:'

    def _match_on(self, branch, revs):
        raise BzrError('tag: namespace registered, but not implemented.')

SPEC_TYPES.append(RevisionSpec_tag)


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
          it can also start with a '+/-/='. '+' says match the first
          entry after the given date. '-' is match the first entry before the date
          '=' is match the first entry after, but still on the given date.

          +2005-05-12 says find the first matching entry after May 12th, 2005 at 0:00
          -2005-05-12 says find the first matching entry before May 12th, 2005 at 0:00
          =2005-05-12 says find the first match after May 12th, 2005 at 0:00 but before
              May 13th, 2005 at 0:00

          So the proper way of saying 'give me all entries for today' is:
              -r {date:+today}:{date:-tomorrow}
          The default is '=' when not supplied
        """
        match_style = '='
        if self.spec[:1] in ('+', '-', '='):
            match_style = self.spec[:1]
            self.spec = self.spec[1:]

        # XXX: this should probably be using datetime.date instead
        today = datetime.datetime.today().replace(hour=0, minute=0, second=0,
                                                  microsecond=0)
        if self.spec.lower() == 'yesterday':
            dt = today - datetime.timedelta(days=1)
        elif self.spec.lower() == 'today':
            dt = today
        elif self.spec.lower() == 'tomorrow':
            dt = today + datetime.timedelta(days=1)
        else:
            m = self._date_re.match(self.spec)
            if not m or (not m.group('date') and not m.group('time')):
                raise BzrError('Invalid revision date %r' % self.spec)

            if m.group('date'):
                year, month, day = int(m.group('year')), int(m.group('month')), int(m.group('day'))
            else:
                year, month, day = today.year, today.month, today.day
            if m.group('time'):
                hour = int(m.group('hour'))
                minute = int(m.group('minute'))
                if m.group('second'):
                    second = int(m.group('second'))
                else:
                    second = 0
            else:
                hour, minute, second = 0,0,0

            dt = datetime.datetime(year=year, month=month, day=day,
                    hour=hour, minute=minute, second=second)
        first = dt
        last = None
        reversed = False
        if match_style == '-':
            reversed = True
        elif match_style == '=':
            last = dt + datetime.timedelta(days=1)

        if reversed:
            for i in range(len(revs)-1, -1, -1):
                r = branch.get_revision(revs[i])
                # TODO: Handle timezone.
                dt = datetime.datetime.fromtimestamp(r.timestamp)
                if first >= dt and (last is None or dt >= last):
                    return RevisionInfo(branch, i+1,)
        else:
            for i in range(len(revs)):
                r = branch.get_revision(revs[i])
                # TODO: Handle timezone.
                dt = datetime.datetime.fromtimestamp(r.timestamp)
                if first <= dt and (last is None or dt <= last):
                    return RevisionInfo(branch, i+1,)

SPEC_TYPES.append(RevisionSpec_date)


class RevisionSpec_ancestor(RevisionSpec):
    prefix = 'ancestor:'

    def _match_on(self, branch, revs):
        from branch import Branch
        from revision import common_ancestor, MultipleRevisionSources
        other_branch = Branch.open_containing(self.spec)
        revision_a = branch.last_patch()
        revision_b = other_branch.last_patch()
        for r, b in ((revision_a, branch), (revision_b, other_branch)):
            if r is None:
                raise NoCommits(b)
        revision_source = MultipleRevisionSources(branch, other_branch)
        rev_id = common_ancestor(revision_a, revision_b, revision_source)
        try:
            revno = branch.revision_id_to_revno(rev_id)
        except NoSuchRevision:
            revno = None
        return RevisionInfo(branch, revno, rev_id)
        
SPEC_TYPES.append(RevisionSpec_ancestor)
