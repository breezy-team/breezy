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
from bzrlib.errors import BzrError, NoSuchRevision

# Map some sort of prefix into a namespace
# stuff like "revno:10", "revid:", etc.
# This should match a prefix with a function which accepts it
REVISION_NAMESPACES = {}

class RevisionSpec(object):
    """Equivalent to the old get_revision_info().
    An instance has two useful attributes: revno, and rev_id.

    They can also be accessed as spec[0] and spec[1] respectively,
    so that you can write code like:
    revno, rev_id = RevisionSpec(branch, spec)
    although this is probably going to be deprecated later.

    Revision specs are an UI element, and they have been moved out
    of the branch class to leave "back-end" classes unaware of such
    details.  Code that gets a revno or rev_id from other code should
    not be using revision specs - revnos and revision ids are the
    accepted ways to refer to revisions internally.
    """
    def __init__(self, branch, spec):
        """Parse a revision specifier.

        spec can be an integer, in which case it is assumed to be revno
        (though this will translate negative values into positive ones)
        spec can also be a string, in which case it is parsed for something
        like 'date:' or 'revid:' etc.
        """
        self.branch = branch

        if spec is None:
            self.revno = 0
            self.rev_id = None
            return
        self.revno = None
        try:# Convert to int if possible
            spec = int(spec)
        except ValueError:
            pass
        revs = branch.revision_history()
        if isinstance(spec, int):
            if spec < 0:
                self.revno = len(revs) + spec + 1
            else:
                self.revno = spec
            self.rev_id = branch.get_rev_id(self.revno, revs)
        elif isinstance(spec, basestring):
            for prefix, func in REVISION_NAMESPACES.iteritems():
                if spec.startswith(prefix):
                    result = func(branch, revs, spec)
                    if len(result) > 1:
                        self.revno, self.rev_id = result
                    else:
                        self.revno = result[0]
                        self.rev_id = branch.get_rev_id(self.revno, revs)
                    break
            else:
                raise BzrError('No namespace registered for string: %r' %
                               spec)
        else:
            raise TypeError('Unhandled revision type %s' % spec)

        if self.revno is None or self.rev_id is None:
            raise NoSuchRevision(branch, spec)

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
        print 'comparing', tuple(self), tuple(other)
        return tuple(self) == tuple(other)

    def __repr__(self):
        return '<bzrlib.revisionspec.RevisionSpec object %s, %s for %r>' % (
            self.revno, self.rev_id, self.branch)


# private API

def _namespace_revno(branch, revs, spec):
    """Lookup a revision by revision number"""
    assert spec.startswith('revno:')
    try:
        return (int(spec[len('revno:'):]),)
    except ValueError:
        return (None,)
REVISION_NAMESPACES['revno:'] = _namespace_revno


def _namespace_revid(branch, revs, spec):
    assert spec.startswith('revid:')
    rev_id = spec[len('revid:'):]
    try:
        return revs.index(rev_id) + 1, rev_id
    except ValueError:
        return (None,)
REVISION_NAMESPACES['revid:'] = _namespace_revid


def _namespace_last(branch, revs, spec):
    assert spec.startswith('last:')
    try:
        offset = int(spec[5:])
    except ValueError:
        return (None,)
    else:
        if offset <= 0:
            raise BzrError('You must supply a positive value for --revision last:XXX')
        return (len(revs) - offset + 1,)
REVISION_NAMESPACES['last:'] = _namespace_last


def _namespace_tag(branch, revs, spec):
    assert spec.startswith('tag:')
    raise BzrError('tag: namespace registered, but not implemented.')
REVISION_NAMESPACES['tag:'] = _namespace_tag


_date_re = re.compile(
        r'(?P<date>(?P<year>\d\d\d\d)-(?P<month>\d\d)-(?P<day>\d\d))?'
        r'(,|T)?\s*'
        r'(?P<time>(?P<hour>\d\d):(?P<minute>\d\d)(:(?P<second>\d\d))?)?'
    )

def _namespace_date(branch, revs, spec):
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
    assert spec.startswith('date:')
    val = spec[5:]
    match_style = '='
    if val[:1] in ('+', '-', '='):
        match_style = val[:1]
        val = val[1:]

    # XXX: this should probably be using datetime.date instead
    today = datetime.datetime.today().replace(hour=0, minute=0, second=0,
                                              microsecond=0)
    if val.lower() == 'yesterday':
        dt = today - datetime.timedelta(days=1)
    elif val.lower() == 'today':
        dt = today
    elif val.lower() == 'tomorrow':
        dt = today + datetime.timedelta(days=1)
    else:
        m = _date_re.match(val)
        if not m or (not m.group('date') and not m.group('time')):
            raise BzrError('Invalid revision date %r' % spec)

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
                return (i+1,)
    else:
        for i in range(len(revs)):
            r = branch.get_revision(revs[i])
            # TODO: Handle timezone.
            dt = datetime.datetime.fromtimestamp(r.timestamp)
            if first <= dt and (last is None or dt <= last):
                return (i+1,)
REVISION_NAMESPACES['date:'] = _namespace_date
