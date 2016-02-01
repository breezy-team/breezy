# Copyright (C) 2006-2012, 2016 Canonical Ltd
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

"""Tests for the formatting and construction of errors."""

import inspect
import re
import socket
import sys

from bzrlib import (
    controldir,
    errors,
    osutils,
    urlutils,
    )
from bzrlib.tests import (
    TestCase,
    TestCaseWithTransport,
    TestSkipped,
    )


class TestErrors(TestCaseWithTransport):

    def test_no_arg_named_message(self):
        """Ensure the __init__ and _fmt in errors do not have "message" arg.

        This test fails if __init__ or _fmt in errors has an argument
        named "message" as this can cause errors in some Python versions.
        Python 2.5 uses a slot for StandardError.message.
        See bug #603461
        """
        fmt_pattern = re.compile("%\(message\)[sir]")
        subclasses_present = getattr(errors.BzrError, '__subclasses__', None)
        if not subclasses_present:
            raise TestSkipped('__subclasses__ attribute required for classes. '
                'Requires Python 2.5 or later.')
        for c in errors.BzrError.__subclasses__():
            init = getattr(c, '__init__', None)
            fmt = getattr(c, '_fmt', None)
            if init:
                args = inspect.getargspec(init)[0]
                self.assertFalse('message' in args,
                    ('Argument name "message" not allowed for '
                    '"errors.%s.__init__"' % c.__name__))
            if fmt and fmt_pattern.search(fmt):
                self.assertFalse(True, ('"message" not allowed in '
                    '"errors.%s._fmt"' % c.__name__))

    def test_bad_filename_encoding(self):
        error = errors.BadFilenameEncoding('bad/filen\xe5me', 'UTF-8')
        self.assertEqualDiff(
            "Filename 'bad/filen\\xe5me' is not valid in your current"
            " filesystem encoding UTF-8",
            str(error))

    def test_corrupt_dirstate(self):
        error = errors.CorruptDirstate('path/to/dirstate', 'the reason why')
        self.assertEqualDiff(
            "Inconsistency in dirstate file path/to/dirstate.\n"
            "Error: the reason why",
            str(error))

    def test_dirstate_corrupt(self):
        error = errors.DirstateCorrupt('.bzr/checkout/dirstate',
                                       'trailing garbage: "x"')
        self.assertEqualDiff("The dirstate file (.bzr/checkout/dirstate)"
            " appears to be corrupt: trailing garbage: \"x\"",
            str(error))

    def test_disabled_method(self):
        error = errors.DisabledMethod("class name")
        self.assertEqualDiff(
            "The smart server method 'class name' is disabled.", str(error))

    def test_duplicate_file_id(self):
        error = errors.DuplicateFileId('a_file_id', 'foo')
        self.assertEqualDiff('File id {a_file_id} already exists in inventory'
                             ' as foo', str(error))

    def test_duplicate_help_prefix(self):
        error = errors.DuplicateHelpPrefix('foo')
        self.assertEqualDiff('The prefix foo is in the help search path twice.',
            str(error))

    def test_ghost_revisions_have_no_revno(self):
        error = errors.GhostRevisionsHaveNoRevno('target', 'ghost_rev')
        self.assertEqualDiff("Could not determine revno for {target} because"
                             " its ancestry shows a ghost at {ghost_rev}",
                             str(error))

    def test_incompatibleAPI(self):
        error = errors.IncompatibleAPI("module", (1, 2, 3), (4, 5, 6), (7, 8, 9))
        self.assertEqualDiff(
            'The API for "module" is not compatible with "(1, 2, 3)". '
            'It supports versions "(4, 5, 6)" to "(7, 8, 9)".',
            str(error))

    def test_inconsistent_delta(self):
        error = errors.InconsistentDelta('path', 'file-id', 'reason for foo')
        self.assertEqualDiff(
            "An inconsistent delta was supplied involving 'path', 'file-id'\n"
            "reason: reason for foo",
            str(error))

    def test_inconsistent_delta_delta(self):
        error = errors.InconsistentDeltaDelta([], 'reason')
        self.assertEqualDiff(
            "An inconsistent delta was supplied: []\nreason: reason",
            str(error))

    def test_in_process_transport(self):
        error = errors.InProcessTransport('fpp')
        self.assertEqualDiff(
            "The transport 'fpp' is only accessible within this process.",
            str(error))

    def test_invalid_http_range(self):
        error = errors.InvalidHttpRange('path',
                                        'Content-Range: potatoes 0-00/o0oo0',
                                        'bad range')
        self.assertEqual("Invalid http range"
                         " 'Content-Range: potatoes 0-00/o0oo0'"
                         " for path: bad range",
                         str(error))

    def test_invalid_range(self):
        error = errors.InvalidRange('path', 12, 'bad range')
        self.assertEqual("Invalid range access in path at 12: bad range",
                         str(error))

    def test_inventory_modified(self):
        error = errors.InventoryModified("a tree to be repred")
        self.assertEqualDiff("The current inventory for the tree 'a tree to "
            "be repred' has been modified, so a clean inventory cannot be "
            "read without data loss.",
            str(error))

    def test_jail_break(self):
        error = errors.JailBreak("some url")
        self.assertEqualDiff("An attempt to access a url outside the server"
            " jail was made: 'some url'.",
            str(error))

    def test_lock_active(self):
        error = errors.LockActive("lock description")
        self.assertEqualDiff("The lock for 'lock description' is in use and "
            "cannot be broken.",
            str(error))

    def test_lock_corrupt(self):
        error = errors.LockCorrupt("corruption info")
        self.assertEqualDiff("Lock is apparently held, but corrupted: "
            "corruption info\n"
            "Use 'bzr break-lock' to clear it",
            str(error))

    def test_knit_data_stream_incompatible(self):
        error = errors.KnitDataStreamIncompatible(
            'stream format', 'target format')
        self.assertEqual('Cannot insert knit data stream of format '
                         '"stream format" into knit of format '
                         '"target format".', str(error))

    def test_knit_data_stream_unknown(self):
        error = errors.KnitDataStreamUnknown(
            'stream format')
        self.assertEqual('Cannot parse knit data stream of format '
                         '"stream format".', str(error))

    def test_knit_header_error(self):
        error = errors.KnitHeaderError('line foo\n', 'path/to/file')
        self.assertEqual("Knit header error: 'line foo\\n' unexpected"
                         " for file \"path/to/file\".", str(error))

    def test_knit_index_unknown_method(self):
        error = errors.KnitIndexUnknownMethod('http://host/foo.kndx',
                                              ['bad', 'no-eol'])
        self.assertEqual("Knit index http://host/foo.kndx does not have a"
                         " known method in options: ['bad', 'no-eol']",
                         str(error))

    def test_medium_not_connected(self):
        error = errors.MediumNotConnected("a medium")
        self.assertEqualDiff(
            "The medium 'a medium' is not connected.", str(error))

    def test_no_public_branch(self):
        b = self.make_branch('.')
        error = errors.NoPublicBranch(b)
        url = urlutils.unescape_for_display(b.base, 'ascii')
        self.assertEqualDiff(
            'There is no public branch set for "%s".' % url, str(error))

    def test_no_repo(self):
        dir = controldir.ControlDir.create(self.get_url())
        error = errors.NoRepositoryPresent(dir)
        self.assertNotEqual(-1, str(error).find((dir.transport.clone('..').base)))
        self.assertEqual(-1, str(error).find((dir.transport.base)))

    def test_no_smart_medium(self):
        error = errors.NoSmartMedium("a transport")
        self.assertEqualDiff("The transport 'a transport' cannot tunnel the "
            "smart protocol.",
            str(error))

    def test_no_help_topic(self):
        error = errors.NoHelpTopic("topic")
        self.assertEqualDiff("No help could be found for 'topic'. "
            "Please use 'bzr help topics' to obtain a list of topics.",
            str(error))

    def test_no_such_id(self):
        error = errors.NoSuchId("atree", "anid")
        self.assertEqualDiff("The file id \"anid\" is not present in the tree "
            "atree.",
            str(error))

    def test_no_such_revision_in_tree(self):
        error = errors.NoSuchRevisionInTree("atree", "anid")
        self.assertEqualDiff("The revision id {anid} is not present in the"
                             " tree atree.", str(error))
        self.assertIsInstance(error, errors.NoSuchRevision)

    def test_not_stacked(self):
        error = errors.NotStacked('a branch')
        self.assertEqualDiff("The branch 'a branch' is not stacked.",
            str(error))

    def test_not_write_locked(self):
        error = errors.NotWriteLocked('a thing to repr')
        self.assertEqualDiff("'a thing to repr' is not write locked but needs "
            "to be.",
            str(error))

    def test_lock_failed(self):
        error = errors.LockFailed('http://canonical.com/', 'readonly transport')
        self.assertEqualDiff("Cannot lock http://canonical.com/: readonly transport",
            str(error))
        self.assertFalse(error.internal_error)

    def test_too_many_concurrent_requests(self):
        error = errors.TooManyConcurrentRequests("a medium")
        self.assertEqualDiff("The medium 'a medium' has reached its concurrent "
            "request limit. Be sure to finish_writing and finish_reading on "
            "the currently open request.",
            str(error))

    def test_unavailable_representation(self):
        error = errors.UnavailableRepresentation(('key',), "mpdiff", "fulltext")
        self.assertEqualDiff("The encoding 'mpdiff' is not available for key "
            "('key',) which is encoded as 'fulltext'.",
            str(error))

    def test_unknown_hook(self):
        error = errors.UnknownHook("branch", "foo")
        self.assertEqualDiff("The branch hook 'foo' is unknown in this version"
            " of bzrlib.",
            str(error))
        error = errors.UnknownHook("tree", "bar")
        self.assertEqualDiff("The tree hook 'bar' is unknown in this version"
            " of bzrlib.",
            str(error))

    def test_unstackable_branch_format(self):
        format = u'foo'
        url = "/foo"
        error = errors.UnstackableBranchFormat(format, url)
        self.assertEqualDiff(
            "The branch '/foo'(foo) is not a stackable format. "
            "You will need to upgrade the branch to permit branch stacking.",
            str(error))

    def test_unstackable_location(self):
        error = errors.UnstackableLocationError('foo', 'bar')
        self.assertEqualDiff("The branch 'foo' cannot be stacked on 'bar'.",
            str(error))

    def test_unstackable_repository_format(self):
        format = u'foo'
        url = "/foo"
        error = errors.UnstackableRepositoryFormat(format, url)
        self.assertEqualDiff(
            "The repository '/foo'(foo) is not a stackable format. "
            "You will need to upgrade the repository to permit branch stacking.",
            str(error))

    def test_up_to_date(self):
        error = errors.UpToDateFormat("someformat")
        self.assertEqualDiff(
            "The branch format someformat is already at the most "
            "recent format.", str(error))

    def test_corrupt_repository(self):
        repo = self.make_repository('.')
        error = errors.CorruptRepository(repo)
        self.assertEqualDiff("An error has been detected in the repository %s.\n"
                             "Please run bzr reconcile on this repository." %
                             repo.bzrdir.root_transport.base,
                             str(error))

    def test_read_error(self):
        # a unicode path to check that %r is being used.
        path = u'a path'
        error = errors.ReadError(path)
        self.assertEqualDiff("Error reading from u'a path'.", str(error))

    def test_bad_index_format_signature(self):
        error = errors.BadIndexFormatSignature("foo", "bar")
        self.assertEqual("foo is not an index of type bar.",
            str(error))

    def test_bad_index_data(self):
        error = errors.BadIndexData("foo")
        self.assertEqual("Error in data for index foo.",
            str(error))

    def test_bad_index_duplicate_key(self):
        error = errors.BadIndexDuplicateKey("foo", "bar")
        self.assertEqual("The key 'foo' is already in index 'bar'.",
            str(error))

    def test_bad_index_key(self):
        error = errors.BadIndexKey("foo")
        self.assertEqual("The key 'foo' is not a valid key.",
            str(error))

    def test_bad_index_options(self):
        error = errors.BadIndexOptions("foo")
        self.assertEqual("Could not parse options for index foo.",
            str(error))

    def test_bad_index_value(self):
        error = errors.BadIndexValue("foo")
        self.assertEqual("The value 'foo' is not a valid value.",
            str(error))

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
        error = errors.TransportNotPossible('readonly', 'original error')
        self.assertEqualDiff('Transport operation not possible:'
                         ' readonly original error', str(error))

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

    def test_target_not_branch(self):
        """Test the formatting of TargetNotBranch."""
        error = errors.TargetNotBranch('foo')
        self.assertEqual(
            "Your branch does not have all of the revisions required in "
            "order to merge this merge directive and the target "
            "location specified in the merge directive is not a branch: "
            "foo.", str(error))

    def test_malformed_bug_identifier(self):
        """Test the formatting of MalformedBugIdentifier."""
        error = errors.MalformedBugIdentifier('bogus', 'reason for bogosity')
        self.assertEqual(
            'Did not understand bug identifier bogus: reason for bogosity. '
            'See "bzr help bugs" for more information on this feature.',
            str(error))

    def test_unknown_bug_tracker_abbreviation(self):
        """Test the formatting of UnknownBugTrackerAbbreviation."""
        branch = self.make_branch('some_branch')
        error = errors.UnknownBugTrackerAbbreviation('xxx', branch)
        self.assertEqual(
            "Cannot find registered bug tracker called xxx on %s" % branch,
            str(error))

    def test_unexpected_smart_server_response(self):
        e = errors.UnexpectedSmartServerResponse(('not yes',))
        self.assertEqual(
            "Could not understand response from smart server: ('not yes',)",
            str(e))

    def test_unknown_container_format(self):
        """Test the formatting of UnknownContainerFormatError."""
        e = errors.UnknownContainerFormatError('bad format string')
        self.assertEqual(
            "Unrecognised container format: 'bad format string'",
            str(e))

    def test_unexpected_end_of_container(self):
        """Test the formatting of UnexpectedEndOfContainerError."""
        e = errors.UnexpectedEndOfContainerError()
        self.assertEqual(
            "Unexpected end of container stream", str(e))

    def test_unknown_record_type(self):
        """Test the formatting of UnknownRecordTypeError."""
        e = errors.UnknownRecordTypeError("X")
        self.assertEqual(
            "Unknown record type: 'X'",
            str(e))

    def test_invalid_record(self):
        """Test the formatting of InvalidRecordError."""
        e = errors.InvalidRecordError("xxx")
        self.assertEqual(
            "Invalid record: xxx",
            str(e))

    def test_container_has_excess_data(self):
        """Test the formatting of ContainerHasExcessDataError."""
        e = errors.ContainerHasExcessDataError("excess bytes")
        self.assertEqual(
            "Container has data after end marker: 'excess bytes'",
            str(e))

    def test_duplicate_record_name_error(self):
        """Test the formatting of DuplicateRecordNameError."""
        e = errors.DuplicateRecordNameError(u"n\xe5me".encode('utf-8'))
        self.assertEqual(
            "Container has multiple records with the same name: n\xc3\xa5me",
            str(e))

    def test_check_error(self):
        # This has a member called 'message', which is problematic in
        # python2.5 because that is a slot on the base Exception class
        e = errors.BzrCheckError('example check failure')
        self.assertEqual(
            "Internal check failed: example check failure",
            str(e))
        self.assertTrue(e.internal_error)

    def test_repository_data_stream_error(self):
        """Test the formatting of RepositoryDataStreamError."""
        e = errors.RepositoryDataStreamError(u"my reason")
        self.assertEqual(
            "Corrupt or incompatible data stream: my reason", str(e))

    def test_immortal_pending_deletion_message(self):
        err = errors.ImmortalPendingDeletion('foo')
        self.assertEqual(
            "Unable to delete transform temporary directory foo.  "
            "Please examine foo to see if it contains any files "
            "you wish to keep, and delete it when you are done.",
            str(err))

    def test_unable_create_symlink(self):
        err = errors.UnableCreateSymlink()
        self.assertEqual(
            "Unable to create symlink on this platform",
            str(err))
        err = errors.UnableCreateSymlink(path=u'foo')
        self.assertEqual(
            "Unable to create symlink 'foo' on this platform",
            str(err))
        err = errors.UnableCreateSymlink(path=u'\xb5')
        self.assertEqual(
            "Unable to create symlink u'\\xb5' on this platform",
            str(err))

    def test_invalid_url_join(self):
        """Test the formatting of InvalidURLJoin."""
        e = errors.InvalidURLJoin('Reason', 'base path', ('args',))
        self.assertEqual(
            "Invalid URL join request: Reason: 'base path' + ('args',)",
            str(e))

    def test_incorrect_url(self):
        err = errors.InvalidBugTrackerURL('foo', 'http://bug.com/')
        self.assertEqual(
            ("The URL for bug tracker \"foo\" doesn't contain {id}: "
             "http://bug.com/"),
            str(err))

    def test_unable_encode_path(self):
        err = errors.UnableEncodePath('foo', 'executable')
        self.assertEqual("Unable to encode executable path 'foo' in "
                         "user encoding " + osutils.get_user_encoding(),
                         str(err))

    def test_unknown_format(self):
        err = errors.UnknownFormatError('bar', kind='foo')
        self.assertEqual("Unknown foo format: 'bar'", str(err))

    def test_unknown_rules(self):
        err = errors.UnknownRules(['foo', 'bar'])
        self.assertEqual("Unknown rules detected: foo, bar.", str(err))

    def test_tip_change_rejected(self):
        err = errors.TipChangeRejected(u'Unicode message\N{INTERROBANG}')
        self.assertEqual(
            u'Tip change rejected: Unicode message\N{INTERROBANG}',
            unicode(err))
        self.assertEqual(
            'Tip change rejected: Unicode message\xe2\x80\xbd',
            str(err))

    def test_error_from_smart_server(self):
        error_tuple = ('error', 'tuple')
        err = errors.ErrorFromSmartServer(error_tuple)
        self.assertEqual(
            "Error received from smart server: ('error', 'tuple')", str(err))

    def test_untranslateable_error_from_smart_server(self):
        error_tuple = ('error', 'tuple')
        orig_err = errors.ErrorFromSmartServer(error_tuple)
        err = errors.UnknownErrorFromSmartServer(orig_err)
        self.assertEqual(
            "Server sent an unexpected error: ('error', 'tuple')", str(err))

    def test_smart_message_handler_error(self):
        # Make an exc_info tuple.
        try:
            raise Exception("example error")
        except Exception:
            err = errors.SmartMessageHandlerError(sys.exc_info())
        # GZ 2010-11-08: Should not store exc_info in exception instances.
        try:
            self.assertStartsWith(
                str(err), "The message handler raised an exception:\n")
            self.assertEndsWith(str(err), "Exception: example error\n")
        finally:
            del err

    def test_must_have_working_tree(self):
        err = errors.MustHaveWorkingTree('foo', 'bar')
        self.assertEqual(str(err), "Branching 'bar'(foo) must create a"
                                   " working tree.")

    def test_no_such_view(self):
        err = errors.NoSuchView('foo')
        self.assertEqual("No such view: foo.", str(err))

    def test_views_not_supported(self):
        err = errors.ViewsNotSupported('atree')
        err_str = str(err)
        self.assertStartsWith(err_str, "Views are not supported by ")
        self.assertEndsWith(err_str, "; use 'bzr upgrade' to change your "
            "tree to a later format.")

    def test_file_outside_view(self):
        err = errors.FileOutsideView('baz', ['foo', 'bar'])
        self.assertEqual('Specified file "baz" is outside the current view: '
                         'foo, bar', str(err))

    def test_invalid_shelf_id(self):
        invalid_id = "foo"
        err = errors.InvalidShelfId(invalid_id)
        self.assertEqual('"foo" is not a valid shelf id, '
                         'try a number instead.', str(err))

    def test_unresumable_write_group(self):
        repo = "dummy repo"
        wg_tokens = ['token']
        reason = "a reason"
        err = errors.UnresumableWriteGroup(repo, wg_tokens, reason)
        self.assertEqual(
            "Repository dummy repo cannot resume write group "
            "['token']: a reason", str(err))

    def test_unsuspendable_write_group(self):
        repo = "dummy repo"
        err = errors.UnsuspendableWriteGroup(repo)
        self.assertEqual(
            'Repository dummy repo cannot suspend a write group.', str(err))

    def test_not_branch_no_args(self):
        err = errors.NotBranchError('path')
        self.assertEqual('Not a branch: "path".', str(err))

    def test_not_branch_bzrdir_with_repo(self):
        bzrdir = self.make_repository('repo').bzrdir
        err = errors.NotBranchError('path', bzrdir=bzrdir)
        self.assertEqual(
            'Not a branch: "path": location is a repository.', str(err))

    def test_not_branch_bzrdir_without_repo(self):
        bzrdir = self.make_bzrdir('bzrdir')
        err = errors.NotBranchError('path', bzrdir=bzrdir)
        self.assertEqual('Not a branch: "path".', str(err))

    def test_not_branch_bzrdir_with_recursive_not_branch_error(self):
        class FakeBzrDir(object):
            def open_repository(self):
                # str() on the NotBranchError will trigger a call to this,
                # which in turn will another, identical NotBranchError.
                raise errors.NotBranchError('path', bzrdir=FakeBzrDir())
        err = errors.NotBranchError('path', bzrdir=FakeBzrDir())
        self.assertEqual('Not a branch: "path".', str(err))

    def test_not_branch_laziness(self):
        real_bzrdir = self.make_bzrdir('path')
        class FakeBzrDir(object):
            def __init__(self):
                self.calls = []
            def open_repository(self):
                self.calls.append('open_repository')
                raise errors.NoRepositoryPresent(real_bzrdir)
        fake_bzrdir = FakeBzrDir()
        err = errors.NotBranchError('path', bzrdir=fake_bzrdir)
        self.assertEqual([], fake_bzrdir.calls)
        str(err)
        self.assertEqual(['open_repository'], fake_bzrdir.calls)
        # Stringifying twice doesn't try to open a repository twice.
        str(err)
        self.assertEqual(['open_repository'], fake_bzrdir.calls)

    def test_invalid_pattern(self):
        error = errors.InvalidPattern('Bad pattern msg.')
        self.assertEqualDiff("Invalid pattern(s) found. Bad pattern msg.",
            str(error))

    def test_recursive_bind(self):
        error = errors.RecursiveBind('foo_bar_branch')
        msg = ('Branch "foo_bar_branch" appears to be bound to itself. '
            'Please use `bzr unbind` to fix.')
        self.assertEqualDiff(msg, str(error))

    def test_retry_with_new_packs(self):
        fake_exc_info = ('{exc type}', '{exc value}', '{exc traceback}')
        error = errors.RetryWithNewPacks(
            '{context}', reload_occurred=False, exc_info=fake_exc_info)
        self.assertEqual(
            'Pack files have changed, reload and retry. context: '
            '{context} {exc value}', str(error))


class PassThroughError(errors.BzrError):

    _fmt = """Pass through %(foo)s and %(bar)s"""

    def __init__(self, foo, bar):
        errors.BzrError.__init__(self, foo=foo, bar=bar)


class ErrorWithBadFormat(errors.BzrError):

    _fmt = """One format specifier: %(thing)s"""


class ErrorWithNoFormat(errors.BzrError):
    __doc__ = """This class has a docstring but no format string."""


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
        self.assertStartsWith(str(e),
                              "Unprintable exception ErrorWithNoFormat")

    def test_mismatched_format_args(self):
        # Even though ErrorWithBadFormat's format string does not match the
        # arguments we constructing it with, we can still stringify an instance
        # of this exception. The resulting string will say its unprintable.
        e = ErrorWithBadFormat(not_thing='x')
        self.assertStartsWith(
            str(e), 'Unprintable exception ErrorWithBadFormat')

    def test_cannot_bind_address(self):
        # see <https://bugs.launchpad.net/bzr/+bug/286871>
        e = errors.CannotBindAddress('example.com', 22,
                                     socket.error(13, 'Permission denied'))
        self.assertContainsRe(
            str(e),
            r'Cannot bind address "example\.com:22":.*Permission denied')

    def test_file_timestamp_unavailable(self):
        e = errors.FileTimestampUnavailable("/path/foo")
        self.assertEqual("The filestamp for /path/foo is not available.",
                         str(e))

    def test_transform_rename_failed(self):
        e = errors.TransformRenameFailed(u"from", u"to", "readonly file", 2)
        self.assertEqual(
            u"Failed to rename from to to: readonly file",
            str(e))
