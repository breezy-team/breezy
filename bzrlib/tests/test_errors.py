# Copyright (C) 2006 Canonical Ltd
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

    def test_disabled_method(self):
        error = errors.DisabledMethod("class name")
        self.assertEqualDiff(
            "The smart server method 'class name' is disabled.", str(error))

    def test_inventory_modified(self):
        error = errors.InventoryModified("a tree to be repred")
        self.assertEqualDiff("The current inventory for the tree 'a tree to "
            "be repred' has been modified, so a clean inventory cannot be "
            "read without data loss.",
            str(error))

    def test_install_failed(self):
        error = errors.InstallFailed(['rev-one'])
        self.assertEqual("Could not install revisions:\nrev-one", str(error))
        error = errors.InstallFailed(['rev-one', 'rev-two'])
        self.assertEqual("Could not install revisions:\nrev-one, rev-two",
                         str(error))
        error = errors.InstallFailed([None])
        self.assertEqual("Could not install revisions:\nNone", str(error))

    def test_knit_header_error(self):
        error = errors.KnitHeaderError('line foo\n', 'path/to/file')
        self.assertEqual("Knit header error: 'line foo\\n' unexpected"
                         " for file path/to/file", str(error))

    def test_medium_not_connected(self):
        error = errors.MediumNotConnected("a medium")
        self.assertEqualDiff(
            "The medium 'a medium' is not connected.", str(error))
        
    def test_no_repo(self):
        dir = bzrdir.BzrDir.create(self.get_url())
        error = errors.NoRepositoryPresent(dir)
        self.assertNotEqual(-1, str(error).find((dir.transport.clone('..').base)))
        self.assertEqual(-1, str(error).find((dir.transport.base)))
        
    def test_no_smart_medium(self):
        error = errors.NoSmartMedium("a transport")
        self.assertEqualDiff("The transport 'a transport' cannot tunnel the "
            "smart protocol.",
            str(error))

    def test_no_such_id(self):
        error = errors.NoSuchId("atree", "anid")
        self.assertEqualDiff("The file id anid is not present in the tree "
            "atree.",
            str(error))

    def test_not_write_locked(self):
        error = errors.NotWriteLocked('a thing to repr')
        self.assertEqualDiff("'a thing to repr' is not write locked but needs "
            "to be.",
            str(error))

    def test_too_many_concurrent_requests(self):
        error = errors.TooManyConcurrentRequests("a medium")
        self.assertEqualDiff("The medium 'a medium' has reached its concurrent "
            "request limit. Be sure to finish_writing and finish_reading on "
            "the current request that is open.",
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
        self.callDeprecated(['BzrNewError was deprecated in bzr 0.13; '
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

    def test_reading_completed(self):
        error = errors.ReadingCompleted("a request")
        self.assertEqualDiff("The MediumRequest 'a request' has already had "
            "finish_reading called upon it - the request has been completed and"
            " no more data may be read.",
            str(error))

    def test_writing_completed(self):
        error = errors.WritingCompleted("a request")
        self.assertEqualDiff("The MediumRequest 'a request' has already had "
            "finish_writing called upon it - accept bytes may not be called "
            "anymore.",
            str(error))

    def test_writing_not_completed(self):
        error = errors.WritingNotComplete("a request")
        self.assertEqualDiff("The MediumRequest 'a request' has not has "
            "finish_writing called upon it - until the write phase is complete"
            " no data may be read.",
            str(error))

    def test_transport_not_possible(self):
        e = errors.TransportNotPossible('readonly', 'original error')
        self.assertEqual('Transport operation not possible:'
                         ' readonly original error', str(e))

    def assertSocketConnectionError(self, expected, *args, **kwargs):
        """Check the formatting of a SocketConnectionError exception"""
        e = errors.SocketConnectionError(*args, **kwargs)
        self.assertEqual(expected, str(e))

    def test_socket_connection_error(self):
        """Test the formatting of SocketConnectionError"""

        # There should be a default msg about failing to connect
        # we only require a host name.
        self.assertSocketConnectionError(
            'Failed to connect to ahost',
            'ahost')

        # If port is None, we don't put :None
        self.assertSocketConnectionError(
            'Failed to connect to ahost',
            'ahost', port=None)
        # But if port is supplied we include it
        self.assertSocketConnectionError(
            'Failed to connect to ahost:22',
            'ahost', port=22)

        # We can also supply extra information about the error
        # with or without a port
        self.assertSocketConnectionError(
            'Failed to connect to ahost:22; bogus error',
            'ahost', port=22, orig_error='bogus error')
        self.assertSocketConnectionError(
            'Failed to connect to ahost; bogus error',
            'ahost', orig_error='bogus error')
        # An exception object can be passed rather than a string
        orig_error = ValueError('bad value')
        self.assertSocketConnectionError(
            'Failed to connect to ahost; %s' % (str(orig_error),),
            host='ahost', orig_error=orig_error)

        # And we can supply a custom failure message
        self.assertSocketConnectionError(
            'Unable to connect to ssh host ahost:444; my_error',
            host='ahost', port=444, msg='Unable to connect to ssh host',
            orig_error='my_error')



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
        e = ErrorWithNoFormat(param='randomvalue')
        s = self.callDeprecated(
                ['ErrorWithNoFormat uses its docstring as a format, it should use _fmt instead'],
                lambda x: str(x), e)
        ## s = str(e)
        self.assertEqual(s, 
                "This class has a docstring but no format string.")

    def test_mismatched_format_args(self):
        # Even though ErrorWithBadFormat's format string does not match the
        # arguments we constructing it with, we can still stringify an instance
        # of this exception. The resulting string will say its unprintable.
        e = ErrorWithBadFormat(not_thing='x')
        self.assertStartsWith(
            str(e), 'Unprintable exception ErrorWithBadFormat')

