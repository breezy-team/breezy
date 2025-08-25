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

from .. import controldir, errors, osutils, tests, urlutils


class TestErrors(tests.TestCase):
    def test_no_arg_named_message(self):
        """Ensure the __init__ and _fmt in errors do not have "message" arg.

        This test fails if __init__ or _fmt in errors has an argument
        named "message" as this can cause errors in some Python versions.
        Python 2.5 uses a slot for StandardError.message.
        See bug #603461
        """
        fmt_pattern = re.compile("%\\(message\\)[sir]")
        for c in errors.BzrError.__subclasses__():
            init = getattr(c, "__init__", None)
            fmt = getattr(c, "_fmt", None)
            if init:
                args = inspect.getfullargspec(init)[0]
                self.assertNotIn(
                    "message",
                    args,
                    'Argument name "message" not allowed for '
                    f'"errors.{c.__name__}.__init__"',
                )
            if fmt and fmt_pattern.search(fmt):
                self.assertFalse(
                    True,
                    ('"message" not allowed in "errors.{}._fmt"'.format(c.__name__)),
                )

    def test_duplicate_help_prefix(self):
        error = errors.DuplicateHelpPrefix("foo")
        self.assertEqualDiff(
            "The prefix foo is in the help search path twice.", str(error)
        )

    def test_ghost_revisions_have_no_revno(self):
        error = errors.GhostRevisionsHaveNoRevno("target", "ghost_rev")
        self.assertEqualDiff(
            "Could not determine revno for {target} because"
            " its ancestry shows a ghost at {ghost_rev}",
            str(error),
        )

    def test_incompatibleVersion(self):
        error = errors.IncompatibleVersion("module", [(4, 5, 6), (7, 8, 9)], (1, 2, 3))
        self.assertEqualDiff(
            "API module is not compatible; one of versions "
            "[(4, 5, 6), (7, 8, 9)] is required, but current version is "
            "(1, 2, 3).",
            str(error),
        )

    def test_inconsistent_delta(self):
        error = errors.InconsistentDelta("path", "file-id", "reason for foo")
        self.assertEqualDiff(
            "An inconsistent delta was supplied involving 'path', 'file-id'\n"
            "reason: reason for foo",
            str(error),
        )

    def test_inconsistent_delta_delta(self):
        error = errors.InconsistentDeltaDelta([], "reason")
        self.assertEqualDiff(
            "An inconsistent delta was supplied: []\nreason: reason", str(error)
        )

    def test_in_process_transport(self):
        error = errors.InProcessTransport("fpp")
        self.assertEqualDiff(
            "The transport 'fpp' is only accessible within this process.", str(error)
        )

    def test_invalid_http_range(self):
        error = errors.InvalidHttpRange(
            "path", "Content-Range: potatoes 0-00/o0oo0", "bad range"
        )
        self.assertEqual(
            "Invalid http range"
            " 'Content-Range: potatoes 0-00/o0oo0'"
            " for path: bad range",
            str(error),
        )

    def test_invalid_range(self):
        error = errors.InvalidRange("path", 12, "bad range")
        self.assertEqual("Invalid range access in path at 12: bad range", str(error))

    def test_jail_break(self):
        error = errors.JailBreak("some url")
        self.assertEqualDiff(
            "An attempt to access a url outside the server jail was made: 'some url'.",
            str(error),
        )

    def test_lock_active(self):
        error = errors.LockActive("lock description")
        self.assertEqualDiff(
            "The lock for 'lock description' is in use and cannot be broken.",
            str(error),
        )

    def test_lock_corrupt(self):
        error = errors.LockCorrupt("corruption info")
        self.assertEqualDiff(
            "Lock is apparently held, but corrupted: "
            "corruption info\n"
            "Use 'brz break-lock' to clear it",
            str(error),
        )

    def test_medium_not_connected(self):
        error = errors.MediumNotConnected("a medium")
        self.assertEqualDiff("The medium 'a medium' is not connected.", str(error))

    def test_no_smart_medium(self):
        error = errors.NoSmartMedium("a transport")
        self.assertEqualDiff(
            "The transport 'a transport' cannot tunnel the smart protocol.",
            str(error),
        )

    def test_no_such_id(self):
        error = errors.NoSuchId("atree", "anid")
        self.assertEqualDiff(
            'The file id "anid" is not present in the tree atree.', str(error)
        )

    def test_no_such_revision_in_tree(self):
        error = errors.NoSuchRevisionInTree("atree", "anid")
        self.assertEqualDiff(
            "The revision id {anid} is not present in the tree atree.", str(error)
        )
        self.assertIsInstance(error, errors.NoSuchRevision)

    def test_not_stacked(self):
        error = errors.NotStacked("a branch")
        self.assertEqualDiff("The branch 'a branch' is not stacked.", str(error))

    def test_not_write_locked(self):
        error = errors.NotWriteLocked("a thing to repr")
        self.assertEqualDiff(
            "'a thing to repr' is not write locked but needs to be.", str(error)
        )

    def test_lock_failed(self):
        error = errors.LockFailed("http://canonical.com/", "readonly transport")
        self.assertEqualDiff(
            "Cannot lock http://canonical.com/: readonly transport", str(error)
        )
        self.assertFalse(error.internal_error)

    def test_unstackable_location(self):
        error = errors.UnstackableLocationError("foo", "bar")
        self.assertEqualDiff("The branch 'foo' cannot be stacked on 'bar'.", str(error))

    def test_unstackable_repository_format(self):
        format = "foo"
        url = "/foo"
        error = errors.UnstackableRepositoryFormat(format, url)
        self.assertEqualDiff(
            "The repository '/foo'(foo) is not a stackable format. "
            "You will need to upgrade the repository to permit branch stacking.",
            str(error),
        )

    def test_up_to_date(self):
        error = errors.UpToDateFormat("someformat")
        self.assertEqualDiff(
            "The branch format someformat is already at the most recent format.",
            str(error),
        )

    def test_read_error(self):
        # a unicode path to check that %r is being used.
        path = "a path"
        error = errors.ReadError(path)
        self.assertContainsRe(str(error), "^Error reading from 'a path'")

    def test_bzrerror_from_literal_string(self):
        # Some code constructs BzrError from a literal string, in which case
        # no further formatting is done.  (I'm not sure raising the base class
        # is a great idea, but if the exception is not intended to be caught
        # perhaps no more is needed.)
        try:
            raise errors.BzrError("this is my errors; %d is not expanded")
        except errors.BzrError as e:
            self.assertEqual("this is my errors; %d is not expanded", str(e))

    def test_reading_completed(self):
        error = errors.ReadingCompleted("a request")
        self.assertEqualDiff(
            "The MediumRequest 'a request' has already had "
            "finish_reading called upon it - the request has been completed and"
            " no more data may be read.",
            str(error),
        )

    def test_writing_completed(self):
        error = errors.WritingCompleted("a request")
        self.assertEqualDiff(
            "The MediumRequest 'a request' has already had "
            "finish_writing called upon it - accept bytes may not be called "
            "anymore.",
            str(error),
        )

    def test_writing_not_completed(self):
        error = errors.WritingNotComplete("a request")
        self.assertEqualDiff(
            "The MediumRequest 'a request' has not has "
            "finish_writing called upon it - until the write phase is complete"
            " no data may be read.",
            str(error),
        )

    def test_transport_not_possible(self):
        error = errors.TransportNotPossible("readonly", "original error")
        self.assertEqualDiff(
            "Transport operation not possible: readonly original error", str(error)
        )

    def assertSocketConnectionError(self, expected, *args, **kwargs):
        """Check the formatting of a SocketConnectionError exception."""
        e = errors.SocketConnectionError(*args, **kwargs)
        self.assertEqual(expected, str(e))

    def test_socket_connection_error(self):
        """Test the formatting of SocketConnectionError."""
        # There should be a default msg about failing to connect
        # we only require a host name.
        self.assertSocketConnectionError("Failed to connect to ahost", "ahost")

        # If port is None, we don't put :None
        self.assertSocketConnectionError(
            "Failed to connect to ahost", "ahost", port=None
        )
        # But if port is supplied we include it
        self.assertSocketConnectionError(
            "Failed to connect to ahost:22", "ahost", port=22
        )

        # We can also supply extra information about the error
        # with or without a port
        self.assertSocketConnectionError(
            "Failed to connect to ahost:22; bogus error",
            "ahost",
            port=22,
            orig_error="bogus error",
        )
        self.assertSocketConnectionError(
            "Failed to connect to ahost; bogus error", "ahost", orig_error="bogus error"
        )
        # An exception object can be passed rather than a string
        orig_error = ValueError("bad value")
        self.assertSocketConnectionError(
            f"Failed to connect to ahost; {orig_error!s}",
            host="ahost",
            orig_error=orig_error,
        )

        # And we can supply a custom failure message
        self.assertSocketConnectionError(
            "Unable to connect to ssh host ahost:444; my_error",
            host="ahost",
            port=444,
            msg="Unable to connect to ssh host",
            orig_error="my_error",
        )

    def test_target_not_branch(self):
        """Test the formatting of TargetNotBranch."""
        error = errors.TargetNotBranch("foo")
        self.assertEqual(
            "Your branch does not have all of the revisions required in "
            "order to merge this merge directive and the target "
            "location specified in the merge directive is not a branch: "
            "foo.",
            str(error),
        )

    def test_unexpected_smart_server_response(self):
        e = errors.UnexpectedSmartServerResponse(("not yes",))
        self.assertEqual(
            "Could not understand response from smart server: ('not yes',)", str(e)
        )

    def test_check_error(self):
        e = errors.BzrCheckError("example check failure")
        self.assertEqual("Internal check failed: example check failure", str(e))
        self.assertTrue(e.internal_error)

    def test_repository_data_stream_error(self):
        """Test the formatting of RepositoryDataStreamError."""
        e = errors.RepositoryDataStreamError("my reason")
        self.assertEqual("Corrupt or incompatible data stream: my reason", str(e))

    def test_immortal_pending_deletion_message(self):
        err = errors.ImmortalPendingDeletion("foo")
        self.assertEqual(
            "Unable to delete transform temporary directory foo.  "
            "Please examine foo to see if it contains any files "
            "you wish to keep, and delete it when you are done.",
            str(err),
        )

    def test_invalid_url_join(self):
        """Test the formatting of InvalidURLJoin."""
        e = urlutils.InvalidURLJoin("Reason", "base path", ("args",))
        self.assertEqual(
            "Invalid URL join request: Reason: 'base path' + ('args',)", str(e)
        )

    def test_unable_encode_path(self):
        err = errors.UnableEncodePath("foo", "executable")
        self.assertEqual(
            "Unable to encode executable path 'foo' in "
            "user encoding " + osutils.get_user_encoding(),
            str(err),
        )

    def test_unknown_format(self):
        err = errors.UnknownFormatError("bar", kind="foo")
        self.assertEqual("Unknown foo format: 'bar'", str(err))

    def test_tip_change_rejected(self):
        err = errors.TipChangeRejected("Unicode message\N{INTERROBANG}")
        self.assertEqual(
            "Tip change rejected: Unicode message\N{INTERROBANG}", str(err)
        )

    def test_error_from_smart_server(self):
        error_tuple = ("error", "tuple")
        err = errors.ErrorFromSmartServer(error_tuple)
        self.assertEqual(
            "Error received from smart server: ('error', 'tuple')", str(err)
        )

    def test_unresumable_write_group(self):
        repo = "dummy repo"
        wg_tokens = ["token"]
        reason = "a reason"
        err = errors.UnresumableWriteGroup(repo, wg_tokens, reason)
        self.assertEqual(
            "Repository dummy repo cannot resume write group ['token']: a reason",
            str(err),
        )

    def test_unsuspendable_write_group(self):
        repo = "dummy repo"
        err = errors.UnsuspendableWriteGroup(repo)
        self.assertEqual(
            "Repository dummy repo cannot suspend a write group.", str(err)
        )

    def test_not_branch_no_args(self):
        err = errors.NotBranchError("path")
        self.assertEqual('Not a branch: "path".', str(err))

    def test_not_branch_bzrdir_with_recursive_not_branch_error(self):
        class FakeBzrDir:
            def open_repository(self):
                # str() on the NotBranchError will trigger a call to this,
                # which in turn will another, identical NotBranchError.
                raise errors.NotBranchError("path", controldir=FakeBzrDir())

        err = errors.NotBranchError("path", controldir=FakeBzrDir())
        self.assertEqual('Not a branch: "path": NotBranchError.', str(err))

    def test_recursive_bind(self):
        error = errors.RecursiveBind("foo_bar_branch")
        msg = (
            'Branch "foo_bar_branch" appears to be bound to itself. '
            "Please use `brz unbind` to fix."
        )
        self.assertEqualDiff(msg, str(error))


class PassThroughError(errors.BzrError):
    _fmt = """Pass through %(foo)s and %(bar)s"""

    def __init__(self, foo, bar):
        errors.BzrError.__init__(self, foo=foo, bar=bar)


class ErrorWithBadFormat(errors.BzrError):
    _fmt = """One format specifier: %(thing)s"""


class ErrorWithNoFormat(errors.BzrError):
    __doc__ = """This class has a docstring but no format string."""


class TestErrorFormatting(tests.TestCase):
    def test_always_str(self):
        e = PassThroughError("\xb5", "bar")
        self.assertIsInstance(e.__str__(), str)
        # In Python 2 str(foo) *must* return a real byte string
        # not a Unicode string. The following line would raise a
        # Unicode error, because it tries to call str() on the string
        # returned from e.__str__(), and it has non ascii characters
        s = str(e)
        self.assertEqual("Pass through \xb5 and bar", s)

    def test_missing_format_string(self):
        e = ErrorWithNoFormat(param="randomvalue")
        self.assertStartsWith(str(e), "Unprintable exception ErrorWithNoFormat")

    def test_mismatched_format_args(self):
        # Even though ErrorWithBadFormat's format string does not match the
        # arguments we constructing it with, we can still stringify an instance
        # of this exception. The resulting string will say its unprintable.
        e = ErrorWithBadFormat(not_thing="x")
        self.assertStartsWith(str(e), "Unprintable exception ErrorWithBadFormat")

    def test_cannot_bind_address(self):
        # see <https://bugs.launchpad.net/bzr/+bug/286871>
        e = errors.CannotBindAddress(
            "example.com", 22, OSError(13, "Permission denied")
        )
        self.assertContainsRe(
            str(e), r'Cannot bind address "example\.com:22":.*Permission denied'
        )


class TestErrorsUsingTransport(tests.TestCaseWithMemoryTransport):
    """Tests for errors that need to use a branch or repo."""

    def test_no_public_branch(self):
        b = self.make_branch(".")
        error = errors.NoPublicBranch(b)
        url = urlutils.unescape_for_display(b.base, "ascii")
        self.assertEqualDiff(f'There is no public branch set for "{url}".', str(error))

    def test_no_repo(self):
        dir = controldir.ControlDir.create(self.get_url())
        error = errors.NoRepositoryPresent(dir)
        self.assertNotEqual(-1, str(error).find(dir.transport.clone("..").base))
        self.assertEqual(-1, str(error).find(dir.transport.base))

    def test_corrupt_repository(self):
        repo = self.make_repository(".")
        error = errors.CorruptRepository(repo)
        self.assertEqualDiff(
            "An error has been detected in the repository {}.\n"
            "Please run brz reconcile on this repository.".format(
                repo.controldir.root_transport.base
            ),
            str(error),
        )

    def test_not_branch_bzrdir_with_repo(self):
        controldir = self.make_repository("repo").controldir
        err = errors.NotBranchError("path", controldir=controldir)
        self.assertEqual('Not a branch: "path": location is a repository.', str(err))

    def test_not_branch_bzrdir_without_repo(self):
        controldir = self.make_controldir("bzrdir")
        err = errors.NotBranchError("path", controldir=controldir)
        self.assertEqual('Not a branch: "path".', str(err))

    def test_not_branch_laziness(self):
        real_bzrdir = self.make_controldir("path")

        class FakeBzrDir:
            def __init__(self):
                self.calls = []

            def open_repository(self):
                self.calls.append("open_repository")
                raise errors.NoRepositoryPresent(real_bzrdir)

        fake_bzrdir = FakeBzrDir()
        err = errors.NotBranchError("path", controldir=fake_bzrdir)
        self.assertEqual([], fake_bzrdir.calls)
        str(err)
        self.assertEqual(["open_repository"], fake_bzrdir.calls)
        # Stringifying twice doesn't try to open a repository twice.
        str(err)
        self.assertEqual(["open_repository"], fake_bzrdir.calls)
