# Copyright (C) 2006 Canonical Ltd

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

"""lock file protecting a resource

bzr objects are locked by the existence of a file with a particular name
within the control directory.  We use this rather than OS internal locks
(such as flock etc) because they can be seen across all transports,
including http.

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
>>> l.wait_lock()
>>> # do something here
>>> l.unlock()

"""

import os
import time
from StringIO import StringIO

import bzrlib.config
from bzrlib.errors import (
        DirectoryNotEmpty,
        FileExists,
        LockContention,
        LockError,
        LockNotHeld,
        NoSuchFile,
        UnlockableTransport,
        )
from bzrlib.transport import Transport
from bzrlib.osutils import rand_chars
from bzrlib.rio import RioWriter, read_stanza, Stanza

# XXX: At the moment there is no consideration of thread safety on LockDir
# objects.  This should perhaps be updated - e.g. if two threads try to take a
# lock at the same time they should *both* get it.  But then that's unlikely
# to be a good idea.

# TODO: After renaming the directory, check the contents are what we
# expected.  It's possible that the rename failed but the transport lost
# the failure indication.

# TODO: Transport could offer a simpler put() method that avoids the
# rename-into-place for cases like creating the lock template, where there is
# no chance that the file already exists.

# TODO: Perhaps store some kind of note like the bzr command line in the lock
# info?

# TODO: Some kind of callback run while polling a lock to show progress
# indicators.

_DEFAULT_TIMEOUT_SECONDS = 300
_DEFAULT_POLL_SECONDS = 0.5

class LockDir(object):
    """Write-lock guarding access to data.
    """

    INFO_NAME = '/info'

    def __init__(self, transport, path):
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
        self._info_path = path + self.INFO_NAME
        self.nonce = rand_chars(20)

    def __repr__(self):
        return '%s(%s%s)' % (self.__class__.__name__,
                             self.transport.base,
                             self.path)

    is_held = property(lambda self: self._lock_held)

    def attempt_lock(self):
        """Take the lock; fail if it's already held
        
        If you wish to block until the lock can be obtained, call wait_lock()
        instead.
        """
        if self.transport.is_readonly():
            raise UnlockableTransport(self.transport)
        try:
            tmpname = '%s.pending.%s.tmp' % (self.path, rand_chars(20))
            self.transport.mkdir(tmpname)
            sio = StringIO()
            self._prepare_info(sio)
            sio.seek(0)
            self.transport.put(tmpname + self.INFO_NAME, sio)
            # FIXME: this turns into os.rename on posix, but into a fancy rename 
            # on Windows that may overwrite existing directory trees.  
            # NB: posix rename will overwrite empty directories, but not 
            # non-empty directories.
            self.transport.move(tmpname, self.path)
            self._lock_held = True
            return
        except (DirectoryNotEmpty, FileExists), e:
            pass
        # fall through to here on contention
        raise LockContention(self)

    def unlock(self):
        if not self._lock_held:
            raise LockNotHeld(self)
        # rename before deleting, because we can't atomically remove the whole
        # tree
        tmpname = '%s.releasing.%s.tmp' % (self.path, rand_chars(20))
        self.transport.rename(self.path, tmpname)
        self._lock_held = False
        self.transport.delete(tmpname + self.INFO_NAME)
        self.transport.rmdir(tmpname)

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
        # info = self.peek()
        # if info['nonce'] != self._nonce:
        #     raise LockBroken(self)

    def peek(self):
        """Check if the lock is held by anyone.
        
        If it is held, this returns the lock info structure as a rio Stanza,
        which contains some information about the current lock holder.
        Otherwise returns None.
        """
        try:
            info = self._parse_info(self.transport.get(self._info_path))
            assert isinstance(info, Stanza), \
                    "bad parse result %r" % info
            return info.as_dict()
        except NoSuchFile, e:
            return None

    def _prepare_info(self, outf):
        """Write information about a pending lock to a temporary file.
        """
        import socket
        # XXX: is creating this here inefficient?
        config = bzrlib.config.GlobalConfig()
        s = Stanza(hostname=socket.gethostname(),
                   pid=str(os.getpid()),
                   start_time=str(int(time.time())),
                   nonce=self.nonce,
                   user=config.user_email(),
                   )
        RioWriter(outf).write_stanza(s)

    def _parse_info(self, info_file):
        return read_stanza(info_file.readlines())

    def wait_lock(self, timeout=_DEFAULT_TIMEOUT_SECONDS,
                  poll=_DEFAULT_POLL_SECONDS):
        """Wait a certain period for a lock.

        If the lock can be acquired within the bounded time, it
        is taken and this returns.  Otherwise, LockContention
        is raised.  Either way, this function should return within
        approximately `timeout` seconds.  (It may be a bit more if
        a transport operation takes a long time to complete.)
        """
        # XXX: the transport interface doesn't let us guard 
        # against operations there taking a long time.
        deadline = time.time() + timeout
        while True:
            try:
                self.attempt_lock()
                return
            except LockContention:
                pass
            if time.time() + poll < deadline:
                time.sleep(poll)
            else:
                raise LockContention(self)

    def wait(self, timeout=20, poll=0.5):
        """Wait a certain period for a lock to be released.
        """
        # XXX: the transport interface doesn't let us guard 
        # against operations there taking a long time.
        deadline = time.time() + timeout
        while True:
            if self.peek():
                return
            if time.time() + poll < deadline:
                time.sleep(poll)
            else:
                raise LockContention(self)
