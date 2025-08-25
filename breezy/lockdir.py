# Copyright (C) 2006-2011 Canonical Ltd
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

"""On-disk mutex protecting a resource.

bzr on-disk objects are locked by the existence of a directory with a
particular name within the control directory.  We use this rather than OS
internal locks (such as flock etc) because they can be seen across all
transports, including http.

Objects can be read if there is only physical read access; therefore
readers can never be required to create a lock, though they will
check whether a writer is using the lock.  Writers can't detect
whether anyone else is reading from the resource as they write.
This works because of ordering constraints that make sure readers
see a consistent view of existing data.

Waiting for a lock must be done by polling; this can be aborted after
a timeout.

Locks must always be explicitly released, typically from a try/finally
block -- they are not released from a finalizer or when Python
exits.

Locks may fail to be released if the process is abruptly terminated
(machine stop, SIGKILL) or if a remote transport becomes permanently
disconnected.  There is therefore a method to break an existing lock.
This should rarely be used, and generally only with user approval.
Locks contain some information on when the lock was taken and by who
which may guide in deciding whether it can safely be broken.  (This is
similar to the messages displayed by emacs and vim.) Note that if the
lock holder is still alive they will get no notification that the lock
has been broken and will continue their work -- so it is important to be
sure they are actually dead.

A lock is represented on disk by a directory of a particular name,
containing an information file.  Taking a lock is done by renaming a
temporary directory into place.  We use temporary directories because
for all known transports and filesystems we believe that exactly one
attempt to claim the lock will succeed and the others will fail.  (Files
won't do because some filesystems or transports only have
rename-and-overwrite, making it hard to tell who won.)

The desired characteristics are:

* Locks are not reentrant.  (That is, a client that tries to take a
  lock it already holds may deadlock or fail.)
* Stale locks can be guessed at by a heuristic
* Lost locks can be broken by any client
* Failed lock operations leave little or no mess
* Deadlocks are avoided by having a timeout always in use, clients
  desiring indefinite waits can retry or set a silly big timeout.

Storage formats use the locks, and also need to consider concurrency
issues underneath the lock.  A format may choose not to use a lock
at all for some operations.

LockDirs always operate over a Transport.  The transport may be readonly, in
which case the lock can be queried but not acquired.

Locks are identified by a path name, relative to a base transport.

Calling code will typically want to make sure there is exactly one LockDir
object per actual lock on disk.  This module does nothing to prevent aliasing
and deadlocks will likely occur if the locks are aliased.

In the future we may add a "freshen" method which can be called
by a lock holder to check that their lock has not been broken, and to
update the timestamp within it.

Example usage:

>>> from breezy.transport.memory import MemoryTransport
>>> # typically will be obtained from a BzrDir, Branch, etc
>>> t = MemoryTransport()
>>> l = LockDir(t, 'sample-lock')
>>> l.create()
>>> token = l.wait_lock()
>>> # do something here
>>> l.unlock()

Some classes of stale locks can be predicted by checking: the host name is the
same as the local host name; the user name is the same as the local user; the
process id no longer exists.  The check on user name is not strictly necessary
but helps protect against colliding host names.
"""


# TODO: We sometimes have the problem that our attempt to rename '1234' to
# 'held' fails because the transport server moves into an existing directory,
# rather than failing the rename.  If we made the info file name the same as
# the locked directory name we would avoid this problem because moving into
# the held directory would implicitly clash.  However this would not mesh with
# the existing locking code and needs a new format of the containing object.
# -- robertc, mbp 20070628

import time

from . import config, debug, errors, lock, ui, urlutils
from ._cmd_rs import LockHeldInfo
from .decorators import only_raises
from .errors import (
    DirectoryNotEmpty,
    LockBreakMismatch,
    LockBroken,
    LockContention,
    LockCorrupt,
    LockFailed,
    LockNotHeld,
    PathError,
    ResourceBusy,
    TransportError,
)
from .i18n import gettext
from .osutils import rand_chars
from .trace import mutter, note
from .transport import FileExists, NoSuchFile

# XXX: At the moment there is no consideration of thread safety on LockDir
# objects.  This should perhaps be updated - e.g. if two threads try to take a
# lock at the same time they should *both* get it.  But then that's unlikely
# to be a good idea.

# TODO: Perhaps store some kind of note like the bzr command line in the lock
# info?

# TODO: Some kind of callback run while polling a lock to show progress
# indicators.

# TODO: Make sure to pass the right file and directory mode bits to all
# files/dirs created.

_DEFAULT_TIMEOUT_SECONDS = 30
_DEFAULT_POLL_SECONDS = 1.0


class LockDir(lock.Lock):
    """Write-lock guarding access to data."""

    __INFO_NAME = "/info"

    def __init__(
        self,
        transport,
        path,
        file_modebits=0o644,
        dir_modebits=0o755,
        extra_holder_info=None,
    ):
        """Create a new LockDir object.

        The LockDir is initially unlocked - this just creates the object.

        :param transport: Transport which will contain the lock

        :param path: Path to the lock within the base directory of the
            transport.

        :param extra_holder_info: If passed, {str:str} dict of extra or
            updated information to insert into the info file when the lock is
            taken.
        """
        self.transport = transport
        self.path = path
        self._lock_held = False
        self._locked_via_token = False
        self._fake_read_lock = False
        self._held_dir = path + "/held"
        self._held_info_path = self._held_dir + self.__INFO_NAME
        self._file_modebits = file_modebits
        self._dir_modebits = dir_modebits
        self._report_function = note
        self.extra_holder_info = extra_holder_info
        self._warned_about_lock_holder = None

    def __repr__(self):
        """Return string representation of the LockDir.

        Returns:
            str: A string representation showing the class name and lock location.
        """
        return f"{self.__class__.__name__}({self.transport.base}{self.path})"

    is_held = property(lambda self: self._lock_held)

    def create(self, mode=None):
        """Create the on-disk lock.

        This is typically only called when the object/directory containing the
        directory is first created.  The lock is not held when it's created.
        """
        self._trace("create lock directory")
        try:
            self.transport.mkdir(self.path, mode=mode)
        except (TransportError, PathError) as e:
            raise LockFailed(self, e) from e

    def _attempt_lock(self):
        """Make the pending directory and attempt to rename into place.

        If the rename succeeds, we read back the info file to check that we
        really got the lock.

        If we fail to acquire the lock, this method is responsible for
        cleaning up the pending directory if possible.  (But it doesn't do
        that yet.)

        :returns: The nonce of the lock, if it was successfully acquired.

        :raises LockContention: If the lock is held by someone else.  The
            exception contains the info of the current holder of the lock.
        """
        self._trace("lock_write...")
        start_time = time.time()
        try:
            tmpname = self._create_pending_dir()
        except (errors.TransportError, PathError) as e:
            self._trace("... failed to create pending dir, %s", e)
            raise LockFailed(self, e) from e
        while True:
            try:
                self.transport.rename(tmpname, self._held_dir)
                break
            except (
                errors.TransportError,
                PathError,
                DirectoryNotEmpty,
                FileExists,
                ResourceBusy,
            ) as e:
                self._trace("... contention, %s", e)
                other_holder = self.peek()
                self._trace(f"other holder is {other_holder!r}")
                try:
                    self._handle_lock_contention(other_holder)
                except BaseException:
                    self._remove_pending_dir(tmpname)
                    raise
            except Exception as e:
                self._trace("... lock failed, %s", e)
                self._remove_pending_dir(tmpname)
                raise
        # We must check we really got the lock, because Launchpad's sftp
        # server at one time had a bug were the rename would successfully
        # move the new directory into the existing directory, which was
        # incorrect.  It's possible some other servers or filesystems will
        # have a similar bug allowing someone to think they got the lock
        # when it's already held.
        #
        # See <https://bugs.launchpad.net/bzr/+bug/498378> for one case.
        #
        # Strictly the check is unnecessary and a waste of time for most
        # people, but probably worth trapping if something is wrong.
        info = self.peek()
        self._trace("after locking, info=%r", info)
        if info is None:
            raise LockFailed(self, "lock was renamed into place, but now is missing!")
        if info.nonce != self.nonce:
            self._trace("rename succeeded, but lock is still held by someone else")
            raise LockContention(self)
        self._lock_held = True
        self._trace("... lock succeeded after %dms", (time.time() - start_time) * 1000)
        return self.nonce

    def _handle_lock_contention(self, other_holder):
        """A lock we want to take is held by someone else.

        This function can: tell the user about it; possibly detect that it's
        safe or appropriate to steal the lock, or just raise an exception.

        If this function returns (without raising an exception) the lock will
        be attempted again.

        :param other_holder: A LockHeldInfo for the current holder; note that
            it might be None if the lock can be seen to be held but the info
            can't be read.
        """
        if other_holder is not None and other_holder.is_lock_holder_known_dead():
            if self.get_config().get("locks.steal_dead"):
                ui.ui_factory.show_user_warning(
                    "locks_steal_dead",
                    lock_url=urlutils.join(self.transport.base, self.path),
                    other_holder_info=str(other_holder),
                )
                self.force_break(other_holder)
                self._trace("stole lock from dead holder")
                return
        raise LockContention(self)

    def _remove_pending_dir(self, tmpname):
        """Remove the pending directory.

        This is called if we failed to rename into place, so that the pending
        dirs don't clutter up the lockdir.
        """
        self._trace("remove %s", tmpname)
        try:
            self.transport.delete(tmpname + self.__INFO_NAME)
            self.transport.rmdir(tmpname)
        except PathError as e:
            note(gettext("error removing pending lock: %s"), e)

    def _create_pending_dir(self):
        tmpname = f"{self.path}/{rand_chars(10)}.tmp"
        try:
            self.transport.mkdir(tmpname)
        except NoSuchFile:
            # This may raise a FileExists exception
            # which is okay, it will be caught later and determined
            # to be a LockContention.
            self._trace("lock directory does not exist, creating it")
            self.create(mode=self._dir_modebits)
            # After creating the lock directory, try again
            self.transport.mkdir(tmpname)
        info = LockHeldInfo.for_this_process(self.extra_holder_info)
        self.nonce = info.nonce
        # We use put_file_non_atomic because we just created a new unique
        # directory so we don't have to worry about files existing there.
        # We'll rename the whole directory into place to get atomic
        # properties
        self.transport.put_bytes_non_atomic(tmpname + self.__INFO_NAME, info.to_bytes())
        return tmpname

    @only_raises(LockNotHeld, LockBroken)
    def unlock(self):
        """Release a held lock."""
        if self._fake_read_lock:
            self._fake_read_lock = False
            return
        if not self._lock_held:
            return lock.cant_unlock_not_held(self)
        if self._locked_via_token:
            self._locked_via_token = False
            self._lock_held = False
        else:
            old_nonce = self.nonce
            # rename before deleting, because we can't atomically remove the
            # whole tree
            start_time = time.time()
            self._trace("unlocking")
            tmpname = f"{self.path}/releasing.{rand_chars(20)}.tmp"
            # gotta own it to unlock
            self.confirm()
            self.transport.rename(self._held_dir, tmpname)
            self._lock_held = False
            self.transport.delete(tmpname + self.__INFO_NAME)
            try:
                self.transport.rmdir(tmpname)
            except DirectoryNotEmpty:
                # There might have been junk left over by a rename that moved
                # another locker within the 'held' directory.  do a slower
                # deletion where we list the directory and remove everything
                # within it.
                self._trace(
                    "doing recursive deletion of non-empty directory %s", tmpname
                )
                self.transport.delete_tree(tmpname)
            self._trace(
                "... unlock succeeded after %dms", (time.time() - start_time) * 1000
            )
            result = lock.LockResult(self.transport.abspath(self.path), old_nonce)
            for hook in self.hooks["lock_released"]:
                hook(result)

    def break_lock(self):
        """Break a lock not held by this instance of LockDir.

        This is a UI centric function: it uses the ui.ui_factory to
        prompt for input if a lock is detected and there is any doubt about
        it possibly being still active.  force_break is the non-interactive
        version.

        :returns: LockResult for the broken lock.
        """
        self._check_not_locked()
        try:
            holder_info = self.peek()
        except LockCorrupt as e:
            # The lock info is corrupt.
            if ui.ui_factory.get_boolean(f"Break (corrupt {self!r})"):
                self.force_break_corrupt(e.file_data)
            return
        if holder_info is not None and ui.ui_factory.confirm_action(
            "Break %(lock_info)s",
            "breezy.lockdir.break",
            {"lock_info": str(holder_info)},
        ):
            result = self.force_break(holder_info)
            ui.ui_factory.show_message(f"Broke lock {result.lock_url}")

    def force_break(self, dead_holder_info):
        """Release a lock held by another process.

        WARNING: This should only be used when the other process is dead; if
        it still thinks it has the lock there will be two concurrent writers.
        In general the user's approval should be sought for lock breaks.

        After the lock is broken it will not be held by any process.
        It is possible that another process may sneak in and take the
        lock before the breaking process acquires it.

        :param dead_holder_info:
            Must be the result of a previous LockDir.peek() call; this is used
            to check that it's still held by the same process that the user
            decided was dead.  If this is not the current holder,
            LockBreakMismatch is raised.

        :returns: LockResult for the broken lock.
        """
        if not isinstance(dead_holder_info, LockHeldInfo):
            raise ValueError(f"dead_holder_info: {dead_holder_info!r}")
        self._check_not_locked()
        current_info = self.peek()
        if current_info is None:
            # must have been recently released
            return
        if current_info != dead_holder_info:
            raise LockBreakMismatch(self, current_info, dead_holder_info)
        tmpname = f"{self.path}/broken.{rand_chars(20)}.tmp"
        self.transport.rename(self._held_dir, tmpname)
        # check that we actually broke the right lock, not someone else;
        # there's a small race window between checking it and doing the
        # rename.
        broken_info_path = tmpname + self.__INFO_NAME
        broken_info = self._read_info_file(broken_info_path)
        if broken_info != dead_holder_info:
            raise LockBreakMismatch(self, broken_info, dead_holder_info)
        self.transport.delete(broken_info_path)
        self.transport.rmdir(tmpname)
        result = lock.LockResult(self.transport.abspath(self.path), current_info.nonce)
        for hook in self.hooks["lock_broken"]:
            hook(result)
        return result

    def force_break_corrupt(self, corrupt_info_content):
        """Release a lock that has been corrupted.

        This is very similar to force_break, it except it doesn't assume that
        self.peek() can work.

        :param corrupt_info_content: the lines of the corrupted info file, used
            to check that the lock hasn't changed between reading the (corrupt)
            info file and calling force_break_corrupt.
        """
        # XXX: this copes with unparseable info files, but what about missing
        # info files?  Or missing lock dirs?
        self._check_not_locked()
        tmpname = f"{self.path}/broken.{rand_chars(20)}.tmp"
        self.transport.rename(self._held_dir, tmpname)
        # check that we actually broke the right lock, not someone else;
        # there's a small race window between checking it and doing the
        # rename.
        broken_info_path = tmpname + self.__INFO_NAME
        broken_content = self.transport.get_bytes(broken_info_path)
        if broken_content != corrupt_info_content:
            raise LockBreakMismatch(self, broken_content, corrupt_info_content)
        self.transport.delete(broken_info_path)
        self.transport.rmdir(tmpname)
        result = lock.LockResult(self.transport.abspath(self.path))
        for hook in self.hooks["lock_broken"]:
            hook(result)

    def _check_not_locked(self):
        """If the lock is held by this instance, raise an error."""
        if self._lock_held:
            raise AssertionError(f"can't break own lock: {self!r}")

    def confirm(self):
        """Make sure that the lock is still held by this locker.

        This should only fail if the lock was broken by user intervention,
        or if the lock has been affected by a bug.

        If the lock is not thought to be held, raises LockNotHeld.  If
        the lock is thought to be held but has been broken, raises
        LockBroken.
        """
        if not self._lock_held:
            raise LockNotHeld(self)
        info = self.peek()
        if info is None:
            # no lock there anymore!
            raise LockBroken(self)
        if info.nonce != self.nonce:
            # there is a lock, but not ours
            raise LockBroken(self)

    def _read_info_file(self, path):
        """Read one given info file.

        peek() reads the info file of the lock holder, if any.
        """
        return LockHeldInfo.from_info_file_bytes(self.transport.get_bytes(path))

    def peek(self):
        """Check if the lock is held by anyone.

        If it is held, this returns the lock info structure as a dict
        which contains some information about the current lock holder.
        Otherwise returns None.
        """
        try:
            info = self._read_info_file(self._held_info_path)
            self._trace("peek -> held")
            return info
        except NoSuchFile:
            self._trace("peek -> not held")

    def _prepare_info(self):
        """Write information about a pending lock to a temporary file."""

    def attempt_lock(self):
        """Take the lock; fail if it's already held.

        If you wish to block until the lock can be obtained, call wait_lock()
        instead.

        :return: The lock token.
        :raises LockContention: if the lock is held by someone else.
        """
        if self._fake_read_lock:
            raise LockContention(self)
        result = self._attempt_lock()
        hook_result = lock.LockResult(self.transport.abspath(self.path), self.nonce)
        for hook in self.hooks["lock_acquired"]:
            hook(hook_result)
        return result

    def lock_url_for_display(self):
        """Give a nicely-printable representation of the URL of this lock."""
        # As local lock urls are correct we display them.
        # We avoid displaying remote lock urls.
        lock_url = self.transport.abspath(self.path)
        lock_url = lock_url.split(".bzr/")[0] if lock_url.startswith("file://") else ""
        return lock_url

    def wait_lock(self, timeout=None, poll=None, max_attempts=None):
        """Wait a certain period for a lock.

        If the lock can be acquired within the bounded time, it
        is taken and this returns.  Otherwise, LockContention
        is raised.  Either way, this function should return within
        approximately `timeout` seconds.  (It may be a bit more if
        a transport operation takes a long time to complete.)

        :param timeout: Approximate maximum amount of time to wait for the
        lock, in seconds.

        :param poll: Delay in seconds between retrying the lock.

        :param max_attempts: Maximum number of times to try to lock.

        :return: The lock token.
        """
        if timeout is None:
            timeout = _DEFAULT_TIMEOUT_SECONDS
        if poll is None:
            poll = _DEFAULT_POLL_SECONDS
        # XXX: the transport interface doesn't let us guard against operations
        # there taking a long time, so the total elapsed time or poll interval
        # may be more than was requested.
        deadline = time.time() + timeout
        deadline_str = None
        last_info = None
        attempt_count = 0
        lock_url = self.lock_url_for_display()
        while True:
            attempt_count += 1
            try:
                return self.attempt_lock()
            except LockContention:
                # possibly report the blockage, then try again
                pass
            # TODO: In a few cases, we find out that there's contention by
            # reading the held info and observing that it's not ours.  In
            # those cases it's a bit redundant to read it again.  However,
            # the normal case (??) is that the rename fails and so we
            # don't know who holds the lock.  For simplicity we peek
            # always.
            new_info = self.peek()
            if new_info is not None and new_info != last_info:
                if last_info is None:
                    start = gettext("Unable to obtain")
                else:
                    start = gettext("Lock owner changed for")
                last_info = new_info
                msg = gettext("{0} lock {1} {2}.").format(start, lock_url, new_info)
                if deadline_str is None:
                    deadline_str = time.strftime("%H:%M:%S", time.localtime(deadline))
                if timeout > 0:
                    msg += (
                        "\n"
                        + gettext(
                            "Will continue to try until %s, unless you press Ctrl-C."
                        )
                        % deadline_str
                    )
                msg += "\n" + gettext('See "brz help break-lock" for more.')
                self._report_function(msg)
            if (max_attempts is not None) and (attempt_count >= max_attempts):
                self._trace("exceeded %d attempts")
                raise LockContention(self)
            if time.time() + poll < deadline:
                self._trace("waiting %ss", poll)
                time.sleep(poll)
            else:
                # As timeout is always 0 for remote locks
                # this block is applicable only for local
                # lock contention
                self._trace("timeout after waiting %ss", timeout)
                raise LockContention("(local)", lock_url)

    def leave_in_place(self):
        """Mark the lock to be left in place when this object is cleaned up.

        This is useful when the lock has been acquired via a token and should
        remain held even after this LockDir instance is done with it.
        """
        self._locked_via_token = True

    def dont_leave_in_place(self):
        """Mark the lock to be released when this object is cleaned up.

        This reverses the effect of leave_in_place(), ensuring the lock
        will be properly released.
        """
        self._locked_via_token = False

    def lock_write(self, token=None):
        """Wait for and acquire the lock.

        :param token: if this is already locked, then lock_write will fail
            unless the token matches the existing lock.
        :returns: a token if this instance supports tokens, otherwise None.
        :raises TokenLockingNotSupported: when a token is given but this
            instance doesn't support using token locks.
        :raises MismatchedToken: if the specified token doesn't match the token
            of the existing lock.

        A token should be passed in if you know that you have locked the object
        some other way, and need to synchronise this object's state with that
        fact.

        XXX: docstring duplicated from LockableFiles.lock_write.
        """
        if token is not None:
            self.validate_token(token)
            self.nonce = token
            self._lock_held = True
            self._locked_via_token = True
            return token
        else:
            return self.wait_lock()

    def lock_read(self):
        """Compatibility-mode shared lock.

        LockDir doesn't support shared read-only locks, so this
        just pretends that the lock is taken but really does nothing.
        """
        # At the moment Branches are commonly locked for read, but
        # we can't rely on that remotely.  Once this is cleaned up,
        # reenable this warning to prevent it coming back in
        # -- mbp 20060303
        # warn("LockDir.lock_read falls back to write lock")
        if self._lock_held or self._fake_read_lock:
            raise LockContention(self)
        self._fake_read_lock = True

    def validate_token(self, token):
        """Check that a token matches the lock currently held.

        Args:
            token: The token to validate against the current lock.

        Raises:
            TokenMismatch: If the provided token doesn't match the token
                of the existing lock.
        """
        if token is not None:
            info = self.peek()
            if info is None:
                # Lock isn't held
                lock_token = None
            else:
                lock_token = info.nonce
            if token != lock_token:
                raise errors.TokenMismatch(token, lock_token)
            else:
                self._trace("revalidated by token %r", token)

    def _trace(self, format, *args):
        if not debug.debug_flag_enabled("lock"):
            return
        mutter(str(self) + ": " + (format % args))

    def get_config(self):
        """Get the configuration that governs this lockdir."""
        # XXX: This really should also use the locationconfig at least, but
        # that seems a bit hard to hook up at the moment. -- mbp 20110329
        # FIXME: The above is still true ;) -- vila 20110811
        return config.GlobalStack()
