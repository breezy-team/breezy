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

"""Tests for LockDir"""

import os
import time

import breezy

from .. import config, errors, lock, lockdir, osutils, tests, transport
from ..errors import (
    LockBreakMismatch,
    LockBroken,
    LockContention,
    LockFailed,
    LockNotHeld,
)
from ..lockdir import LockDir, LockHeldInfo
from . import TestCaseInTempDir, TestCaseWithTransport, features

# These tests are run on the default transport provided by the test framework
# (typically a local disk transport).  That can be changed by the --transport
# option to bzr selftest.  The required properties of the transport
# implementation are tested separately.  (The main requirement is just that
# they don't allow overwriting nonempty directories.)


class TestLockDir(TestCaseWithTransport):
    """Test LockDir operations"""

    def logging_report_function(self, fmt, *args):
        self._logged_reports.append((fmt, args))

    def setup_log_reporter(self, lock_dir):
        self._logged_reports = []
        lock_dir._report_function = self.logging_report_function

    def test_00_lock_creation(self):
        """Creation of lock file on a transport"""
        t = self.get_transport()
        lf = LockDir(t, "test_lock")
        self.assertFalse(lf.is_held)

    def test_01_lock_repr(self):
        """Lock string representation"""
        lf = LockDir(self.get_transport(), "test_lock")
        r = repr(lf)
        self.assertContainsRe(r, r"^LockDir\(.*/test_lock\)$")

    def test_02_unlocked_peek(self):
        lf = LockDir(self.get_transport(), "test_lock")
        self.assertEqual(lf.peek(), None)

    def get_lock(self):
        return LockDir(self.get_transport(), "test_lock")

    def test_unlock_after_break_raises(self):
        ld = self.get_lock()
        ld2 = self.get_lock()
        ld.create()
        ld.attempt_lock()
        ld2.force_break(ld2.peek())
        self.assertRaises(LockBroken, ld.unlock)

    def test_03_readonly_peek(self):
        lf = LockDir(self.get_readonly_transport(), "test_lock")
        self.assertEqual(lf.peek(), None)

    def test_10_lock_uncontested(self):
        """Acquire and release a lock"""
        t = self.get_transport()
        lf = LockDir(t, "test_lock")
        lf.create()
        lf.attempt_lock()
        try:
            self.assertTrue(lf.is_held)
        finally:
            lf.unlock()
            self.assertFalse(lf.is_held)

    def test_11_create_readonly_transport(self):
        """Fail to create lock on readonly transport"""
        t = self.get_readonly_transport()
        lf = LockDir(t, "test_lock")
        self.assertRaises(LockFailed, lf.create)

    def test_12_lock_readonly_transport(self):
        """Fail to lock on readonly transport"""
        lf = LockDir(self.get_transport(), "test_lock")
        lf.create()
        lf = LockDir(self.get_readonly_transport(), "test_lock")
        self.assertRaises(LockFailed, lf.attempt_lock)

    def test_20_lock_contested(self):
        """Contention to get a lock"""
        t = self.get_transport()
        lf1 = LockDir(t, "test_lock")
        lf1.create()
        lf1.attempt_lock()
        lf2 = LockDir(t, "test_lock")
        try:
            # locking is between LockDir instances; aliases within
            # a single process are not detected
            lf2.attempt_lock()
            self.fail("Failed to detect lock collision")
        except LockContention as e:
            self.assertEqual(e.lock, lf2)
            self.assertContainsRe(str(e), r"^Could not acquire.*test_lock.*$")
        lf1.unlock()

    def test_20_lock_peek(self):
        """Peek at the state of a lock"""
        t = self.get_transport()
        lf1 = LockDir(t, "test_lock")
        lf1.create()
        lf1.attempt_lock()
        self.addCleanup(lf1.unlock)
        # lock is held, should get some info on it
        info1 = lf1.peek()
        self.assertEqual(
            set(info1.info_dict.keys()),
            {"user", "nonce", "hostname", "pid", "start_time"},
        )
        # should get the same info if we look at it through a different
        # instance
        info2 = LockDir(t, "test_lock").peek()
        self.assertEqual(info1, info2)
        # locks which are never used should be not-held
        self.assertEqual(LockDir(t, "other_lock").peek(), None)

    def test_21_peek_readonly(self):
        """Peek over a readonly transport"""
        t = self.get_transport()
        lf1 = LockDir(t, "test_lock")
        lf1.create()
        lf2 = LockDir(self.get_readonly_transport(), "test_lock")
        self.assertEqual(lf2.peek(), None)
        lf1.attempt_lock()
        self.addCleanup(lf1.unlock)
        info2 = lf2.peek()
        self.assertTrue(info2)
        self.assertEqual(info2.nonce, lf1.nonce)

    def test_30_lock_wait_fail(self):
        """Wait on a lock, then fail

        We ask to wait up to 400ms; this should fail within at most one
        second.  (Longer times are more realistic but we don't want the test
        suite to take too long, and this should do for now.)
        """
        t = self.get_transport()
        lf1 = LockDir(t, "test_lock")
        lf1.create()
        lf2 = LockDir(t, "test_lock")
        self.setup_log_reporter(lf2)
        lf1.attempt_lock()
        try:
            before = time.time()
            self.assertRaises(LockContention, lf2.wait_lock, timeout=0.4, poll=0.1)
            after = time.time()
            # it should only take about 0.4 seconds, but we allow more time in
            # case the machine is heavily loaded
            self.assertTrue(
                after - before <= 8.0,
                "took %f seconds to detect lock contention" % (after - before),
            )
        finally:
            lf1.unlock()
        self.assertEqual(1, len(self._logged_reports))
        self.assertContainsRe(
            self._logged_reports[0][0],
            r"Unable to obtain lock .* held by jrandom@example\.com on .*"
            r" \(process #\d+\), acquired .* ago\.\n"
            r"Will continue to try until \d{2}:\d{2}:\d{2}, unless "
            r"you press Ctrl-C.\n"
            r'See "brz help break-lock" for more.',
        )

    def test_31_lock_wait_easy(self):
        """Succeed when waiting on a lock with no contention."""
        t = self.get_transport()
        lf1 = LockDir(t, "test_lock")
        lf1.create()
        self.setup_log_reporter(lf1)
        try:
            before = time.time()
            lf1.wait_lock(timeout=0.4, poll=0.1)
            after = time.time()
            self.assertTrue(after - before <= 1.0)
        finally:
            lf1.unlock()
        self.assertEqual([], self._logged_reports)

    def test_40_confirm_easy(self):
        """Confirm a lock that's already held"""
        t = self.get_transport()
        lf1 = LockDir(t, "test_lock")
        lf1.create()
        lf1.attempt_lock()
        self.addCleanup(lf1.unlock)
        lf1.confirm()

    def test_41_confirm_not_held(self):
        """Confirm a lock that's already held"""
        t = self.get_transport()
        lf1 = LockDir(t, "test_lock")
        lf1.create()
        self.assertRaises(LockNotHeld, lf1.confirm)

    def test_42_confirm_broken_manually(self):
        """Confirm a lock broken by hand"""
        t = self.get_transport()
        lf1 = LockDir(t, "test_lock")
        lf1.create()
        lf1.attempt_lock()
        t.move("test_lock", "lock_gone_now")
        self.assertRaises(LockBroken, lf1.confirm)
        # Clean up
        t.move("lock_gone_now", "test_lock")
        lf1.unlock()

    def test_43_break(self):
        """Break a lock whose caller has forgotten it"""
        t = self.get_transport()
        lf1 = LockDir(t, "test_lock")
        lf1.create()
        lf1.attempt_lock()
        # we incorrectly discard the lock object without unlocking it
        del lf1
        # someone else sees it's still locked
        lf2 = LockDir(t, "test_lock")
        holder_info = lf2.peek()
        self.assertTrue(holder_info)
        lf2.force_break(holder_info)
        # now we should be able to take it
        lf2.attempt_lock()
        self.addCleanup(lf2.unlock)
        lf2.confirm()

    def test_44_break_already_released(self):
        """Lock break races with regular release"""
        t = self.get_transport()
        lf1 = LockDir(t, "test_lock")
        lf1.create()
        lf1.attempt_lock()
        # someone else sees it's still locked
        lf2 = LockDir(t, "test_lock")
        holder_info = lf2.peek()
        # in the interim the lock is released
        lf1.unlock()
        # break should succeed
        lf2.force_break(holder_info)
        # now we should be able to take it
        lf2.attempt_lock()
        self.addCleanup(lf2.unlock)
        lf2.confirm()

    def test_45_break_mismatch(self):
        """Lock break races with someone else acquiring it"""
        t = self.get_transport()
        lf1 = LockDir(t, "test_lock")
        lf1.create()
        lf1.attempt_lock()
        # someone else sees it's still locked
        lf2 = LockDir(t, "test_lock")
        holder_info = lf2.peek()
        # in the interim the lock is released
        lf1.unlock()
        lf3 = LockDir(t, "test_lock")
        lf3.attempt_lock()
        # break should now *fail*
        self.assertRaises(LockBreakMismatch, lf2.force_break, holder_info)
        lf3.unlock()

    def test_46_fake_read_lock(self):
        t = self.get_transport()
        lf1 = LockDir(t, "test_lock")
        lf1.create()
        lf1.lock_read()
        lf1.unlock()

    def test_50_lockdir_representation(self):
        """Check the on-disk representation of LockDirs is as expected.

        There should always be a top-level directory named by the lock.
        When the lock is held, there should be a lockname/held directory
        containing an info file.
        """
        t = self.get_transport()
        lf1 = LockDir(t, "test_lock")
        lf1.create()
        self.assertTrue(t.has("test_lock"))
        lf1.lock_write()
        self.assertTrue(t.has("test_lock/held/info"))
        lf1.unlock()
        self.assertFalse(t.has("test_lock/held/info"))

    def test_break_lock(self):
        # the ui based break_lock routine should Just Work (tm)
        ld1 = self.get_lock()
        ld2 = self.get_lock()
        ld1.create()
        ld1.lock_write()
        # do this without IO redirection to ensure it doesn't prompt.
        self.assertRaises(AssertionError, ld1.break_lock)
        orig_factory = breezy.ui.ui_factory
        breezy.ui.ui_factory = breezy.ui.CannedInputUIFactory([True])
        try:
            ld2.break_lock()
            self.assertRaises(LockBroken, ld1.unlock)
        finally:
            breezy.ui.ui_factory = orig_factory

    def test_break_lock_corrupt_info(self):
        """break_lock works even if the info file is corrupt (and tells the UI
        that it is corrupt).
        """
        ld = self.get_lock()
        ld2 = self.get_lock()
        ld.create()
        ld.lock_write()
        ld.transport.put_bytes_non_atomic("test_lock/held/info", b"\0")

        class LoggingUIFactory(breezy.ui.SilentUIFactory):
            def __init__(self):
                self.prompts = []

            def get_boolean(self, prompt):
                self.prompts.append(("boolean", prompt))
                return True

        ui = LoggingUIFactory()
        self.overrideAttr(breezy.ui, "ui_factory", ui)
        ld2.break_lock()
        self.assertLength(1, ui.prompts)
        self.assertEqual("boolean", ui.prompts[0][0])
        self.assertStartsWith(ui.prompts[0][1], "Break (corrupt LockDir")
        self.assertRaises(LockBroken, ld.unlock)

    def test_break_lock_missing_info(self):
        """break_lock works even if the info file is missing (and tells the UI
        that it is corrupt).
        """
        ld = self.get_lock()
        ld2 = self.get_lock()
        ld.create()
        ld.lock_write()
        ld.transport.delete("test_lock/held/info")

        class LoggingUIFactory(breezy.ui.SilentUIFactory):
            def __init__(self):
                self.prompts = []

            def get_boolean(self, prompt):
                self.prompts.append(("boolean", prompt))
                return True

        ui = LoggingUIFactory()
        orig_factory = breezy.ui.ui_factory
        breezy.ui.ui_factory = ui
        try:
            ld2.break_lock()
            self.assertRaises(LockBroken, ld.unlock)
            self.assertLength(0, ui.prompts)
        finally:
            breezy.ui.ui_factory = orig_factory
        # Suppress warnings due to ld not being unlocked
        # XXX: if lock_broken hook was invoked in this case, this hack would
        # not be necessary.  - Andrew Bennetts, 2010-09-06.
        del self._lock_actions[:]

    def test_create_missing_base_directory(self):
        """If LockDir.path doesn't exist, it can be created

        Some people manually remove the entire lock/ directory trying
        to unlock a stuck repository/branch/etc. Rather than failing
        after that, just create the lock directory when needed.
        """
        t = self.get_transport()
        lf1 = LockDir(t, "test_lock")

        lf1.create()
        self.assertTrue(t.has("test_lock"))

        t.rmdir("test_lock")
        self.assertFalse(t.has("test_lock"))

        # This will create 'test_lock' if it needs to
        lf1.lock_write()
        self.assertTrue(t.has("test_lock"))
        self.assertTrue(t.has("test_lock/held/info"))

        lf1.unlock()
        self.assertFalse(t.has("test_lock/held/info"))

    def test_display_form(self):
        ld1 = self.get_lock()
        ld1.create()
        ld1.lock_write()
        try:
            info_list = ld1.peek().to_readable_dict()
        finally:
            ld1.unlock()
        self.assertEqual(info_list["user"], "jrandom@example.com")
        self.assertIsInstance(info_list["pid"], int)
        self.assertContainsRe(info_list["time_ago"], "^\\d+ seconds? ago$")

    def test_lock_without_email(self):
        global_config = config.GlobalStack()
        # Intentionally has no email address
        global_config.set("email", "User Identity")
        ld1 = self.get_lock()
        ld1.create()
        ld1.lock_write()
        ld1.unlock()

    def test_lock_permission(self):
        self.requireFeature(features.not_running_as_root)
        if not osutils.supports_posix_readonly():
            raise tests.TestSkipped("Cannot induce a permission failure")
        ld1 = self.get_lock()
        lock_path = ld1.transport.local_abspath("test_lock")
        os.mkdir(lock_path)
        osutils.make_readonly(lock_path)
        self.assertRaises(errors.LockFailed, ld1.attempt_lock)

    def test_lock_by_token(self):
        ld1 = self.get_lock()
        token = ld1.lock_write()
        self.addCleanup(ld1.unlock)
        self.assertNotEqual(None, token)
        ld2 = self.get_lock()
        t2 = ld2.lock_write(token)
        self.addCleanup(ld2.unlock)
        self.assertEqual(token, t2)

    def test_lock_with_buggy_rename(self):
        # test that lock acquisition handles servers which pretend they
        # renamed correctly but that actually fail
        t = transport.get_transport_from_url("brokenrename+" + self.get_url())
        ld1 = LockDir(t, "test_lock")
        ld1.create()
        ld1.attempt_lock()
        ld2 = LockDir(t, "test_lock")
        # we should fail to lock
        e = self.assertRaises(errors.LockContention, ld2.attempt_lock)
        # now the original caller should succeed in unlocking
        ld1.unlock()
        # and there should be nothing left over
        self.assertEqual([], t.list_dir("test_lock"))

    def test_failed_lock_leaves_no_trash(self):
        # if we fail to acquire the lock, we don't leave pending directories
        # behind -- https://bugs.launchpad.net/bzr/+bug/109169
        ld1 = self.get_lock()
        ld2 = self.get_lock()
        # should be nothing before we start
        ld1.create()
        t = self.get_transport().clone("test_lock")

        def check_dir(a):
            self.assertEqual(a, t.list_dir("."))

        check_dir([])
        # when held, that's all we see
        ld1.attempt_lock()
        self.addCleanup(ld1.unlock)
        check_dir(["held"])
        # second guy should fail
        self.assertRaises(errors.LockContention, ld2.attempt_lock)
        # no kibble
        check_dir(["held"])

    def test_no_lockdir_info(self):
        """We can cope with empty info files."""
        # This seems like a fairly common failure case - see
        # <https://bugs.launchpad.net/bzr/+bug/185103> and all its dupes.
        # Processes are often interrupted after opening the file
        # before the actual contents are committed.
        t = self.get_transport()
        t.mkdir("test_lock")
        t.mkdir("test_lock/held")
        t.put_bytes("test_lock/held/info", b"")
        lf = LockDir(t, "test_lock")
        info = lf.peek()
        formatted_info = info.to_readable_dict()
        self.assertEqual(
            dict(
                user="<unknown>",
                hostname="<unknown>",
                pid="<unknown>",
                time_ago="(unknown)",
            ),
            formatted_info,
        )

    def test_corrupt_lockdir_info(self):
        """We can cope with corrupt (and thus unparseable) info files."""
        # This seems like a fairly common failure case too - see
        # <https://bugs.launchpad.net/bzr/+bug/619872> for instance.
        # In particular some systems tend to fill recently created files with
        # nul bytes after recovering from a system crash.
        t = self.get_transport()
        t.mkdir("test_lock")
        t.mkdir("test_lock/held")
        t.put_bytes("test_lock/held/info", b"\0")
        lf = LockDir(t, "test_lock")
        self.assertRaises(errors.LockCorrupt, lf.peek)
        # Currently attempt_lock gives LockContention, but LockCorrupt would be
        # a reasonable result too.
        self.assertRaises((errors.LockCorrupt, errors.LockContention), lf.attempt_lock)
        self.assertRaises(errors.LockCorrupt, lf.validate_token, "fake token")

    def test_missing_lockdir_info(self):
        """We can cope with absent info files."""
        t = self.get_transport()
        t.mkdir("test_lock")
        t.mkdir("test_lock/held")
        lf = LockDir(t, "test_lock")
        # In this case we expect the 'not held' result from peek, because peek
        # cannot be expected to notice that there is a 'held' directory with no
        # 'info' file.
        self.assertEqual(None, lf.peek())
        # And lock/unlock may work or give LockContention (but not any other
        # error).
        try:
            lf.attempt_lock()
        except LockContention:
            # LockContention is ok, and expected on Windows
            pass
        else:
            # no error is ok, and expected on POSIX (because POSIX allows
            # os.rename over an empty directory).
            lf.unlock()
        # Currently raises TokenMismatch, but LockCorrupt would be reasonable
        # too.
        self.assertRaises(
            (errors.TokenMismatch, errors.LockCorrupt), lf.validate_token, "fake token"
        )


class TestLockDirHooks(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self._calls = []

    def get_lock(self):
        return LockDir(self.get_transport(), "test_lock")

    def record_hook(self, result):
        self._calls.append(result)

    def test_LockDir_acquired_success(self):
        # the LockDir.lock_acquired hook fires when a lock is acquired.
        LockDir.hooks.install_named_hook(
            "lock_acquired", self.record_hook, "record_hook"
        )
        ld = self.get_lock()
        ld.create()
        self.assertEqual([], self._calls)
        result = ld.attempt_lock()
        lock_path = ld.transport.abspath(ld.path)
        self.assertEqual([lock.LockResult(lock_path, result)], self._calls)
        ld.unlock()
        self.assertEqual([lock.LockResult(lock_path, result)], self._calls)

    def test_LockDir_acquired_fail(self):
        # the LockDir.lock_acquired hook does not fire on failure.
        ld = self.get_lock()
        ld.create()
        ld2 = self.get_lock()
        ld2.attempt_lock()
        # install a lock hook now, when the disk lock is locked
        LockDir.hooks.install_named_hook(
            "lock_acquired", self.record_hook, "record_hook"
        )
        self.assertRaises(errors.LockContention, ld.attempt_lock)
        self.assertEqual([], self._calls)
        ld2.unlock()
        self.assertEqual([], self._calls)

    def test_LockDir_released_success(self):
        # the LockDir.lock_released hook fires when a lock is acquired.
        LockDir.hooks.install_named_hook(
            "lock_released", self.record_hook, "record_hook"
        )
        ld = self.get_lock()
        ld.create()
        self.assertEqual([], self._calls)
        result = ld.attempt_lock()
        self.assertEqual([], self._calls)
        ld.unlock()
        lock_path = ld.transport.abspath(ld.path)
        self.assertEqual([lock.LockResult(lock_path, result)], self._calls)

    def test_LockDir_released_fail(self):
        # the LockDir.lock_released hook does not fire on failure.
        ld = self.get_lock()
        ld.create()
        ld2 = self.get_lock()
        ld.attempt_lock()
        ld2.force_break(ld2.peek())
        LockDir.hooks.install_named_hook(
            "lock_released", self.record_hook, "record_hook"
        )
        self.assertRaises(LockBroken, ld.unlock)
        self.assertEqual([], self._calls)

    def test_LockDir_broken_success(self):
        # the LockDir.lock_broken hook fires when a lock is broken.
        ld = self.get_lock()
        ld.create()
        ld2 = self.get_lock()
        result = ld.attempt_lock()
        LockDir.hooks.install_named_hook("lock_broken", self.record_hook, "record_hook")
        ld2.force_break(ld2.peek())
        lock_path = ld.transport.abspath(ld.path)
        self.assertEqual([lock.LockResult(lock_path, result)], self._calls)

    def test_LockDir_broken_failure(self):
        # the LockDir.lock_broken hook does not fires when a lock is already
        # released.
        ld = self.get_lock()
        ld.create()
        ld2 = self.get_lock()
        result = ld.attempt_lock()
        holder_info = ld2.peek()
        ld.unlock()
        LockDir.hooks.install_named_hook("lock_broken", self.record_hook, "record_hook")
        ld2.force_break(holder_info)
        lock_path = ld.transport.abspath(ld.path)
        self.assertEqual([], self._calls)


class TestLockHeldInfo(TestCaseInTempDir):
    """Can get information about the lock holder, and detect whether they're
    still alive.
    """

    def test_repr(self):
        info = LockHeldInfo.for_this_process(None)
        self.assertContainsRe(repr(info), r"LockHeldInfo\(.*\)")

    def test_unicode(self):
        info = LockHeldInfo.for_this_process(None)
        self.assertContainsRe(
            str(info), r"held by .* on .* \(process #\d+\), acquired .* ago"
        )

    def test_is_locked_by_this_process(self):
        info = LockHeldInfo.for_this_process(None)
        self.assertTrue(info.is_locked_by_this_process())

    def test_is_not_locked_by_this_process(self):
        info = LockHeldInfo.for_this_process(None)
        info.info_dict["pid"] = "123123123123123"
        self.assertFalse(info.is_locked_by_this_process())

    def test_lock_holder_live_process(self):
        """Detect that the holder (this process) is still running."""
        info = LockHeldInfo.for_this_process(None)
        self.assertFalse(info.is_lock_holder_known_dead())

    def test_lock_holder_dead_process(self):
        """Detect that the holder (this process) is still running."""
        self.overrideAttr(lockdir, "get_host_name", lambda: "aproperhostname")
        info = LockHeldInfo.for_this_process(None)
        info.info_dict["pid"] = "123123123"
        self.assertTrue(info.is_lock_holder_known_dead())

    def test_lock_holder_other_machine(self):
        """The lock holder isn't here so we don't know if they're alive."""
        info = LockHeldInfo.for_this_process(None)
        info.info_dict["hostname"] = "egg.example.com"
        info.info_dict["pid"] = "123123123"
        self.assertFalse(info.is_lock_holder_known_dead())

    def test_lock_holder_other_user(self):
        """Only auto-break locks held by this user."""
        info = LockHeldInfo.for_this_process(None)
        info.info_dict["user"] = "notme@example.com"
        info.info_dict["pid"] = "123123123"
        self.assertFalse(info.is_lock_holder_known_dead())

    def test_no_good_hostname(self):
        """Correctly handle ambiguous hostnames.

        If the lock's recorded with just 'localhost' we can't really trust
        it's the same 'localhost'.  (There are quite a few of them. :-)
        So even if the process is known not to be alive, we can't say that's
        known for sure.
        """
        self.overrideAttr(lockdir, "get_host_name", lambda: "localhost")
        info = LockHeldInfo.for_this_process(None)
        info.info_dict["pid"] = "123123123"
        self.assertFalse(info.is_lock_holder_known_dead())


class TestStaleLockDir(TestCaseWithTransport):
    """Can automatically break stale locks.

    :see: https://bugs.launchpad.net/bzr/+bug/220464
    """

    def test_auto_break_stale_lock(self):
        """Locks safely known to be stale are just cleaned up.

        This generates a warning but no other user interaction.
        """
        self.overrideAttr(lockdir, "get_host_name", lambda: "aproperhostname")
        # Stealing dead locks is enabled by default.
        # Create a lock pretending to come from a different nonexistent
        # process on the same machine.
        l1 = LockDir(self.get_transport(), "a", extra_holder_info={"pid": "12312313"})
        token_1 = l1.attempt_lock()
        l2 = LockDir(self.get_transport(), "a")
        token_2 = l2.attempt_lock()
        # l1 will notice its lock was stolen.
        self.assertRaises(errors.LockBroken, l1.unlock)
        l2.unlock()

    def test_auto_break_stale_lock_configured_off(self):
        """Automatic breaking can be turned off"""
        l1 = LockDir(self.get_transport(), "a", extra_holder_info={"pid": "12312313"})
        # Stealing dead locks is enabled by default, so disable it.
        config.GlobalStack().set("locks.steal_dead", False)
        token_1 = l1.attempt_lock()
        self.addCleanup(l1.unlock)
        l2 = LockDir(self.get_transport(), "a")
        # This fails now, because dead lock breaking is disabled.
        self.assertRaises(LockContention, l2.attempt_lock)
        # and it's in fact not broken
        l1.confirm()
