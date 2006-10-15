# Copyright (C) 2006 by Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
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

"""Tests for the formatting and construction of errors."""

from bzrlib import (
    bzrdir,
    errors,
    )
from bzrlib.tests import TestCase, TestCaseWithTransport


# TODO: Make sure builtin exception class formats are consistent - e.g. should
# or shouldn't end with a full stop, etc.


class TestErrors(TestCaseWithTransport):

    def test_no_repo(self):
        dir = bzrdir.BzrDir.create(self.get_url())
        error = errors.NoRepositoryPresent(dir)
        self.assertNotEqual(-1, str(error).find((dir.transport.clone('..').base)))
        self.assertEqual(-1, str(error).find((dir.transport.base)))
        
    def test_no_such_id(self):
        error = errors.NoSuchId("atree", "anid")
        self.assertEqualDiff("The file id anid is not present in the tree "
            "atree.",
            str(error))

    def test_up_to_date(self):
        error = errors.UpToDateFormat(bzrdir.BzrDirFormat4())
        self.assertEqualDiff("The branch format Bazaar-NG branch, "
                             "format 0.0.4 is already at the most "
                             "recent format.",
                             str(error))

    def test_corrupt_repository(self):
        repo = self.make_repository('.')
        error = errors.CorruptRepository(repo)
        self.assertEqualDiff("An error has been detected in the repository %s.\n"
                             "Please run bzr reconcile on this repository." %
                             repo.bzrdir.root_transport.base,
                             str(error))

    def test_bzrnewerror_is_deprecated(self):
        class DeprecatedError(errors.BzrNewError):
            pass
        self.callDeprecated(['BzrNewError was deprecated in bzr 0.12; '
             'please convert DeprecatedError to use BzrError instead'],
            DeprecatedError)

    def test_bzrerror_from_literal_string(self):
        # Some code constructs BzrError from a literal string, in which case
        # no further formatting is done.  (I'm not sure raising the base class
        # is a great idea, but if the exception is not intended to be caught
        # perhaps no more is needed.)
        try:
            raise errors.BzrError('this is my errors; %d is not expanded')
        except errors.BzrError, e:
            self.assertEqual('this is my errors; %d is not expanded', str(e))


class PassThroughError(errors.BzrError):
    
    _fmt = """Pass through %(foo)s and %(bar)s"""

    def __init__(self, foo, bar):
        errors.BzrError.__init__(self, foo=foo, bar=bar)


class ErrorWithBadFormat(errors.BzrError):

    _fmt = """One format specifier: %(thing)s"""


class ErrorWithNoFormat(errors.BzrError):
    """This class has a docstring but no format string."""


class TestErrorFormatting(TestCase):
    
    def test_always_str(self):
        e = PassThroughError(u'\xb5', 'bar')
        self.assertIsInstance(e.__str__(), str)
        # In Python str(foo) *must* return a real byte string
        # not a Unicode string. The following line would raise a
        # Unicode error, because it tries to call str() on the string
        # returned from e.__str__(), and it has non ascii characters
        s = str(e)
        self.assertEqual('Pass through \xc2\xb5 and bar', s)

    def test_missing_format_string(self):
        # Code naively converted from BzrNewError might still try to 
        # use the docstring as the format string
        e = ErrorWithNoFormat(param='randomvalue')
        self.assertStartsWith(
            str(e), 'Unprintable exception ErrorWithNoFormat')

    def test_mismatched_format_args(self):
        # Even though ErrorWithBadFormat's format string does not match the
        # arguments we constructing it with, we can still stringify an instance
        # of this exception. The resulting string will say its unprintable.
        e = ErrorWithBadFormat(not_thing='x')
        self.assertStartsWith(
            str(e), 'Unprintable exception ErrorWithBadFormat')


class TestSpecificErrors(TestCase):
    
    def test_transport_not_possible(self):
        e = errors.TransportNotPossible('readonly', 'original error')
        self.assertEqual('Transport operation not possible:'
                         ' readonly original error', str(e))
