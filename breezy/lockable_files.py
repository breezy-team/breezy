# Copyright (C) 2005-2011 Canonical Ltd
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

from .lazy_import import lazy_import
lazy_import(globals(), """
from breezy import (
    counted_lock,
    lock,
    transactions,
    urlutils,
    )
""")

from . import (
    errors,
    )
from .decorators import (
    only_raises,
    )


class LockableFiles(object):
    """Object representing a set of related files locked within the same scope.

    This coordinates access to the lock along with providing a transaction.

    LockableFiles manage a lock count and can be locked repeatedly by
    a single caller.  (The underlying lock implementation generally does not
    support this.)

    Instances of this class are often called control_files.

    This class is now deprecated; code should move to using the Transport
    directly for file operations and using the lock or CountedLock for
    locking.

    :ivar _lock: The real underlying lock (e.g. a LockDir)
    :ivar _lock_count: If _lock_mode is true, a positive count of the number
        of times the lock has been taken (and not yet released) *by this
        process*, through this particular object instance.
    :ivar _lock_mode: None, or 'r' or 'w'
    """

    def __init__(self, transport, lock_name, lock_class):
        """Create a LockableFiles group

        :param transport: Transport pointing to the directory holding the
            control files and lock.
        :param lock_name: Name of the lock guarding these files.
        :param lock_class: Class of lock strategy to use: typically
            either LockDir or TransportLock.
        """
        self._transport = transport
        self.lock_name = lock_name
        self._transaction = None
        self._lock_mode = None
        self._lock_count = 0
        self._find_modes()
        esc_name = self._escape(lock_name)
        self._lock = lock_class(transport, esc_name,
                                file_modebits=self._file_mode,
                                dir_modebits=self._dir_mode)
        self._counted_lock = counted_lock.CountedLock(self._lock)

    def create_lock(self):
        """Create the lock.

        This should normally be called only when the LockableFiles directory
        is first created on disk.
        """
        self._lock.create(mode=self._dir_mode)

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__,
                           self._transport)

    def __str__(self):
        return 'LockableFiles(%s, %s)' % (self.lock_name, self._transport.base)

    def break_lock(self):
        """Break the lock of this lockable files group if it is held.

        The current ui factory will be used to prompt for user conformation.
        """
        self._lock.break_lock()

    def _escape(self, file_or_path):
        """DEPRECATED: Do not use outside this class"""
        if file_or_path == '':
            return u''
        return urlutils.escape(file_or_path)

    def _find_modes(self):
        """Determine the appropriate modes for files and directories.

        :deprecated: Replaced by BzrDir._find_creation_modes.
        """
        # XXX: The properties created by this can be removed or deprecated
        # once all the _get_text_store methods etc no longer use them.
        # -- mbp 20080512
        try:
            st = self._transport.stat('.')
        except errors.TransportNotPossible:
            self._dir_mode = 0o755
            self._file_mode = 0o644
        else:
            # Check the directory mode, but also make sure the created
            # directories and files are read-write for this user. This is
            # mostly a workaround for filesystems which lie about being able to
            # write to a directory (cygwin & win32)
            self._dir_mode = (st.st_mode & 0o7777) | 0o0700
            # Remove the sticky and execute bits for files
            self._file_mode = self._dir_mode & ~0o7111

    def leave_in_place(self):
        """Set this LockableFiles to not clear the physical lock on unlock."""
        self._lock.leave_in_place()

    def dont_leave_in_place(self):
        """Set this LockableFiles to clear the physical lock on unlock."""
        self._lock.dont_leave_in_place()

    def lock_write(self, token=None):
        """Lock this group of files for writing.

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
        """
        if self._lock_mode:
            if (self._lock_mode != 'w'
                    or not self.get_transaction().writeable()):
                raise errors.ReadOnlyError(self)
            self._lock.validate_token(token)
            self._lock_count += 1
            return self._token_from_lock
        else:
            token_from_lock = self._lock.lock_write(token=token)
            # traceback.print_stack()
            self._lock_mode = 'w'
            self._lock_count = 1
            self._set_write_transaction()
            self._token_from_lock = token_from_lock
            return token_from_lock

    def lock_read(self):
        if self._lock_mode:
            if self._lock_mode not in ('r', 'w'):
                raise ValueError("invalid lock mode %r" % (self._lock_mode,))
            self._lock_count += 1
        else:
            self._lock.lock_read()
            # traceback.print_stack()
            self._lock_mode = 'r'
            self._lock_count = 1
            self._set_read_transaction()

    def _set_read_transaction(self):
        """Setup a read transaction."""
        self._set_transaction(transactions.ReadOnlyTransaction())
        # 5K may be excessive, but hey, its a knob.
        self.get_transaction().set_cache_size(5000)

    def _set_write_transaction(self):
        """Setup a write transaction."""
        self._set_transaction(transactions.WriteTransaction())

    @only_raises(errors.LockNotHeld, errors.LockBroken)
    def unlock(self):
        if not self._lock_mode:
            return lock.cant_unlock_not_held(self)
        if self._lock_count > 1:
            self._lock_count -= 1
        else:
            # traceback.print_stack()
            self._finish_transaction()
            try:
                self._lock.unlock()
            finally:
                self._lock_count = 0
                self._lock_mode = None

    def is_locked(self):
        """Return true if this LockableFiles group is locked"""
        return self._lock_count >= 1

    def get_physical_lock_status(self):
        """Return physical lock status.

        Returns true if a lock is held on the transport. If no lock is held, or
        the underlying locking mechanism does not support querying lock
        status, false is returned.
        """
        try:
            return self._lock.peek() is not None
        except NotImplementedError:
            return False

    def get_transaction(self):
        """Return the current active transaction.

        If no transaction is active, this returns a passthrough object
        for which all data is immediately flushed and no caching happens.
        """
        if self._transaction is None:
            return transactions.PassThroughTransaction()
        else:
            return self._transaction

    def _set_transaction(self, new_transaction):
        """Set a new active transaction."""
        if self._transaction is not None:
            raise errors.LockError('Branch %s is in a transaction already.' %
                                   self)
        self._transaction = new_transaction

    def _finish_transaction(self):
        """Exit the current transaction."""
        if self._transaction is None:
            raise errors.LockError('Branch %s is not in a transaction' %
                                   self)
        transaction = self._transaction
        self._transaction = None
        transaction.finish()


class TransportLock(object):
    """Locking method which uses transport-dependent locks.

    On the local filesystem these transform into OS-managed locks.

    These do not guard against concurrent access via different
    transports.

    This is suitable for use only in WorkingTrees (which are at present
    always local).
    """

    def __init__(self, transport, escaped_name, file_modebits, dir_modebits):
        self._transport = transport
        self._escaped_name = escaped_name
        self._file_modebits = file_modebits
        self._dir_modebits = dir_modebits

    def break_lock(self):
        raise NotImplementedError(self.break_lock)

    def leave_in_place(self):
        raise NotImplementedError(self.leave_in_place)

    def dont_leave_in_place(self):
        raise NotImplementedError(self.dont_leave_in_place)

    def lock_write(self, token=None):
        if token is not None:
            raise errors.TokenLockingNotSupported(self)
        self._lock = self._transport.lock_write(self._escaped_name)

    def lock_read(self):
        self._lock = self._transport.lock_read(self._escaped_name)

    def unlock(self):
        self._lock.unlock()
        self._lock = None

    def peek(self):
        raise NotImplementedError()

    def create(self, mode=None):
        """Create lock mechanism"""
        # for old-style locks, create the file now
        self._transport.put_bytes(self._escaped_name, b'',
                                  mode=self._file_modebits)

    def validate_token(self, token):
        if token is not None:
            raise errors.TokenLockingNotSupported(self)
