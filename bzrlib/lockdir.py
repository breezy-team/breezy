# Copyright (C) 2006, 2007 Canonical Ltd
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

"""On-disk mutex protecting a resource

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

>>> from bzrlib.transport.memory import MemoryTransport
>>> # typically will be obtained from a BzrDir, Branch, etc
>>> t = MemoryTransport()
>>> l = LockDir(t, 'sample-lock')
>>> l.create()
>>> token = l.wait_lock()
>>> # do something here
>>> l.unlock()

"""


# TODO: We sometimes have the problem that our attempt to rename '1234' to
# 'held' fails because the transport server moves into an existing directory,
# rather than failing the rename.  If we made the info file name the same as
# the locked directory name we would avoid this problem because moving into
# the held directory would implicitly clash.  However this would not mesh with
# the existing locking code and needs a new format of the containing object.
# -- robertc, mbp 20070628

import os
import time
from cStringIO import StringIO

from bzrlib import (
    debug,
    errors,
    )
import bzrlib.config
from bzrlib.errors import (
        DirectoryNotEmpty,
        FileExists,
        LockBreakMismatch,
        LockBroken,
        LockContention,
        LockNotHeld,
        NoSuchFile,
        PathError,
        ResourceBusy,
        UnlockableTransport,
        )
from bzrlib.trace import mutter, note
from bzrlib.transport import Transport
from bzrlib.osutils import rand_chars, format_delta
from bzrlib.rio import read_stanza, Stanza
import bzrlib.ui


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


_DEFAULT_TIMEOUT_SECONDS = 300
_DEFAULT_POLL_SECONDS = 1.0


class LockDir(object):
    """Write-lock guarding access to data."""

    __INFO_NAME = '/info'

    def __init__(self, transport, path, file_modebits=0644, dir_modebits=0755):
        """Create a new LockDir object.

        The LockDir is initially unlocked - this just creates the object.

        :param transport: Transport which will contain the lock

        :param path: Path to the lock within the base directory of the 
            transport.
        """
        assert isinstance(transport, Transport), \
            ("not a transport: %r" % transport)
        self.transport = transport
        self.path = path
        self._lock_held = False
        self._locked_via_token = False
        self._fake_read_lock = False
        self._held_dir = path + '/held'
        self._held_info_path = self._held_dir + self.__INFO_NAME
        self._file_modebits = file_modebits
        self._dir_modebits = dir_modebits

        self._report_function = note

    def __repr__(self):
        return '%s(%s%s)' % (self.__class__.__name__,
                             self.transport.base,
                             self.path)

    is_held = property(lambda self: self._lock_held)

    def create(self, mode=None):
        """Create the on-disk lock.

        This is typically only called when the object/directory containing the 
        directory is first created.  The lock is not held when it's created.
        """
        if self.transport.is_readonly():
            raise UnlockableTransport(self.transport)
        self._trace("create lock directory")
        self.transport.mkdir(self.path, mode=mode)

    def _attempt_lock(self):
        """Make the pending directory and attempt to rename into place.
        
        If the rename succeeds, we read back the info file to check that we
        really got the lock.

        If we fail to acquire the lock, this method is responsible for
        cleaning up the pending directory if possible.  (But it doesn't do
        that yet.)

        :returns: The nonce of the lock, if it was successfully acquired.

        :raises LockContention: If the lock is held by someone else.  The exception
            contains the info of the current holder of the lock.
        """
        self._trace("lock_write...")
        start_time = time.time()
        tmpname = self._create_pending_dir()
        try:
            self.transport.rename(tmpname, self._held_dir)
        except (PathError, DirectoryNotEmpty, FileExists, ResourceBusy), e:
            self._trace("... contention, %s", e)
            self._remove_pending_dir(tmpname)
            raise LockContention(self)
        except Exception, e:
            self._trace("... lock failed, %s", e)
            self._remove_pending_dir(tmpname)
            raise
        # We must check we really got the lock, because Launchpad's sftp
        # server at one time had a bug were the rename would successfully
        # move the new directory into the existing directory, which was
        # incorrect.  It's possible some other servers or filesystems will
        # have a similar bug allowing someone to think they got the lock
        # when it's already held.
        info = self.peek()
        self._trace("after locking, info=%r", info)
        if info['nonce'] != self.nonce:
            self._trace("rename succeeded, "
                "but lock is still held by someone else")
            raise LockContention(self)
        self._lock_held = True
        self._trace("... lock succeeded after %dms",
                (time.time() - start_time) * 1000)
        return self.nonce

    def _remove_pending_dir(self, tmpname):
        """Remove the pending directory

        This is called if we failed to rename into place, so that the pending 
        dirs don't clutter up the lockdir.
        """
        self._trace("remove %s", tmpname)
        try:
            self.transport.delete(tmpname + self.__INFO_NAME)
            self.transport.rmdir(tmpname)
        except PathError, e:
            note("error removing pending lock: %s", e)

    def _create_pending_dir(self):
        tmpname = '%s/%s.tmp' % (self.path, rand_chars(10))
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
        self.nonce = rand_chars(20)
        info_bytes = self._prepare_info()
        # We use put_file_non_atomic because we just created a new unique
        # directory so we don't have to worry about files existing there.
        # We'll rename the whole directory into place to get atomic
        # properties
        self.transport.put_bytes_non_atomic(tmpname + self.__INFO_NAME,
                                            info_bytes)
        return tmpname

    def unlock(self):
        """Release a held lock
        """
        if self._fake_read_lock:
            self._fake_read_lock = False
            return
        if not self._lock_held:
            raise LockNotHeld(self)
        if self._locked_via_token:
            self._locked_via_token = False
            self._lock_held = False
        else:
            # rename before deleting, because we can't atomically remove the
            # whole tree
            start_time = time.time()
            self._trace("unlocking")
            tmpname = '%s/releasing.%s.tmp' % (self.path, rand_chars(20))
            # gotta own it to unlock
            self.confirm()
            self.transport.rename(self._held_dir, tmpname)
            self._lock_held = False
            self.transport.delete(tmpname + self.__INFO_NAME)
            try:
                self.transport.rmdir(tmpname)
            except DirectoryNotEmpty, e:
                # There might have been junk left over by a rename that moved
                # another locker within the 'held' directory.  do a slower
                # deletion where we list the directory and remove everything
                # within it.
                #
                # Maybe this should be broader to allow for ftp servers with
                # non-specific error messages?
                self._trace("doing recursive deletion of non-empty directory "
                        "%s", tmpname)
                self.transport.delete_tree(tmpname)
            self._trace("... unlock succeeded after %dms",
                    (time.time() - start_time) * 1000)

    def break_lock(self):
        """Break a lock not held by this instance of LockDir.

        This is a UI centric function: it uses the bzrlib.ui.ui_factory to
        prompt for input if a lock is detected and there is any doubt about
        it possibly being still active.
        """
        self._check_not_locked()
        holder_info = self.peek()
        if holder_info is not None:
            lock_info = '\n'.join(self._format_lock_info(holder_info))
            if bzrlib.ui.ui_factory.get_boolean("Break %s" % lock_info):
                self.force_break(holder_info)
        
    def force_break(self, dead_holder_info):
        """Release a lock held by another process.

        WARNING: This should only be used when the other process is dead; if
        it still thinks it has the lock there will be two concurrent writers.
        In general the user's approval should be sought for lock breaks.

        dead_holder_info must be the result of a previous LockDir.peek() call;
        this is used to check that it's still held by the same process that
        the user decided was dead.  If this is not the current holder,
        LockBreakMismatch is raised.

        After the lock is broken it will not be held by any process.
        It is possible that another process may sneak in and take the 
        lock before the breaking process acquires it.
        """
        if not isinstance(dead_holder_info, dict):
            raise ValueError("dead_holder_info: %r" % dead_holder_info)
        self._check_not_locked()
        current_info = self.peek()
        if current_info is None:
            # must have been recently released
            return
        if current_info != dead_holder_info:
            raise LockBreakMismatch(self, current_info, dead_holder_info)
        tmpname = '%s/broken.%s.tmp' % (self.path, rand_chars(20))
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

    def _check_not_locked(self):
        """If the lock is held by this instance, raise an error."""
        if self._lock_held:
            raise AssertionError("can't break own lock: %r" % self)

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
        if info.get('nonce') != self.nonce:
            # there is a lock, but not ours
            raise LockBroken(self)
        
    def _read_info_file(self, path):
        """Read one given info file.

        peek() reads the info file of the lock holder, if any.
        """
        return self._parse_info(self.transport.get(path))

    def peek(self):
        """Check if the lock is held by anyone.
        
        If it is held, this returns the lock info structure as a rio Stanza,
        which contains some information about the current lock holder.
        Otherwise returns None.
        """
        try:
            info = self._read_info_file(self._held_info_path)
            self._trace("peek -> held")
            assert isinstance(info, dict), \
                    "bad parse result %r" % info
            return info
        except NoSuchFile, e:
            self._trace("peek -> not held")

    def _prepare_info(self):
        """Write information about a pending lock to a temporary file.
        """
        import socket
        # XXX: is creating this here inefficient?
        config = bzrlib.config.GlobalConfig()
        try:
            user = config.user_email()
        except errors.NoEmailInUsername:
            user = config.username()
        s = Stanza(hostname=socket.gethostname(),
                   pid=str(os.getpid()),
                   start_time=str(int(time.time())),
                   nonce=self.nonce,
                   user=user,
                   )
        return s.to_string()

    def _parse_info(self, info_file):
        return read_stanza(info_file.readlines()).as_dict()

    def attempt_lock(self):
        """Take the lock; fail if it's already held.
        
        If you wish to block until the lock can be obtained, call wait_lock()
        instead.

        :return: The lock token.
        :raises LockContention: if the lock is held by someone else.
        """
        if self._fake_read_lock:
            raise LockContention(self)
        if self.transport.is_readonly():
            raise UnlockableTransport(self.transport)
        return self._attempt_lock()

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
                    start = 'Unable to obtain'
                else:
                    start = 'Lock owner changed for'
                last_info = new_info
                formatted_info = self._format_lock_info(new_info)
                if deadline_str is None:
                    deadline_str = time.strftime('%H:%M:%S',
                                                 time.localtime(deadline))
                self._report_function('%s %s\n'
                                      '%s\n' # held by
                                      '%s\n' # locked ... ago
                                      'Will continue to try until %s\n',
                                      start,
                                      formatted_info[0],
                                      formatted_info[1],
                                      formatted_info[2],
                                      deadline_str)

            if (max_attempts is not None) and (attempt_count >= max_attempts):
                self._trace("exceeded %d attempts")
                raise LockContention(self)
            if time.time() + poll < deadline:
                self._trace("waiting %ss", poll)
                time.sleep(poll)
            else:
                self._trace("timeout after waiting %ss", timeout)
                raise LockContention(self)
    
    def leave_in_place(self):
        self._locked_via_token = True

    def dont_leave_in_place(self):
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
        ## warn("LockDir.lock_read falls back to write lock")
        if self._lock_held or self._fake_read_lock:
            raise LockContention(self)
        self._fake_read_lock = True

    def wait(self, timeout=20, poll=0.5):
        """Wait a certain period for a lock to be released."""
        # XXX: the transport interface doesn't let us guard 
        # against operations there taking a long time.
        #
        # XXX: Is this really needed?  Do people want to wait for the lock but
        # not acquire it?  As of bzr 0.17, this seems to only be called from
        # the test suite.
        deadline = time.time() + timeout
        while True:
            if self.peek():
                return
            if time.time() + poll < deadline:
                self._trace("waiting %ss", poll)
                time.sleep(poll)
            else:
                self._trace("timeout after waiting %ss", timeout)
                raise LockContention(self)

    def _format_lock_info(self, info):
        """Turn the contents of peek() into something for the user"""
        lock_url = self.transport.abspath(self.path)
        delta = time.time() - int(info['start_time'])
        return [
            'lock %s' % (lock_url,),
            'held by %(user)s on host %(hostname)s [process #%(pid)s]' % info,
            'locked %s' % (format_delta(delta),),
            ]

    def validate_token(self, token):
        if token is not None:
            info = self.peek()
            if info is None:
                # Lock isn't held
                lock_token = None
            else:
                lock_token = info.get('nonce')
            if token != lock_token:
                raise errors.TokenMismatch(token, lock_token)
            else:
                self._trace("revalidated by token %r", token)

    def _trace(self, format, *args):
        if 'lock' not in debug.debug_flags:
            return
        mutter(str(self) + ": " + (format % args))
