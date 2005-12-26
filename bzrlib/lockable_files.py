import bzrlib
import bzrlib.errors as errors
from bzrlib.errors import LockError, ReadOnlyError
from bzrlib.trace import mutter
import bzrlib.transactions as transactions
from osutils import file_iterator

class LockableFiles(object):
    """Object representing a set of lockable files

    _lock_mode
        None, or 'r' or 'w'

    _lock_count
        If _lock_mode is true, a positive count of the number of times the
        lock has been taken.

    _lock
        Lock object from bzrlib.lock.
    """

    _lock_mode = None
    _lock_count = None
    _lock = None

    def __init__(self, transport, lock_name):
        object.__init__(self)
        self._transport = transport
        self.lock_name = lock_name
        self._transaction = None

    def __del__(self):
        if self._lock_mode or self._lock:
            # XXX: This should show something every time, and be suitable for
            # headless operation and embedding
            warn("file group %r was not explicitly unlocked" % self)
            self._lock.unlock()

    def _rel_controlfilename(self, file_or_path):
        if not isinstance(file_or_path, basestring):
            file_or_path = '/'.join(file_or_path)
        if file_or_path == '':
            return unicode(bzrlib.BZRDIR)
        return bzrlib.transport.urlescape(unicode(bzrlib.BZRDIR + '/' + file_or_path))

    def controlfilename(self, file_or_path):
        """Return location relative to branch."""
        return self._transport.abspath(self._rel_controlfilename(file_or_path))

    def controlfile(self, file_or_path, mode='r'):
        """Open a control file for this branch.

        There are two classes of file in the control directory: text
        and binary.  binary files are untranslated byte streams.  Text
        control files are stored with Unix newlines and in UTF-8, even
        if the platform or locale defaults are different.

        Controlfiles should almost never be opened in write mode but
        rather should be atomically copied and replaced using atomicfile.
        """
        import codecs

        relpath = self._rel_controlfilename(file_or_path)
        #TODO: codecs.open() buffers linewise, so it was overloaded with
        # a much larger buffer, do we need to do the same for getreader/getwriter?
        if mode == 'rb': 
            return self._transport.get(relpath)
        elif mode == 'wb':
            raise BzrError("Branch.controlfile(mode='wb') is not supported, use put[_utf8]")
        elif mode == 'r':
            # XXX: Do we really want errors='replace'?   Perhaps it should be
            # an error, or at least reported, if there's incorrectly-encoded
            # data inside a file.
            # <https://launchpad.net/products/bzr/+bug/3823>
            return codecs.getreader('utf-8')(self._transport.get(relpath), errors='replace')
        elif mode == 'w':
            raise BzrError("Branch.controlfile(mode='w') is not supported, use put[_utf8]")
        else:
            raise BzrError("invalid controlfile mode %r" % mode)

    def put(self, path, file):
        """Write a file.
        
        :param path: The path to put the file, relative to the .bzr control
                     directory
        :param f: A file-like or string object whose contents should be copied.
        """
        if not self._lock_mode == 'w':
            raise ReadOnlyError()
        self._transport.put(self._rel_controlfilename(path), file)

    def put_utf8(self, path, file):
        """Write a file, encoding as utf-8.

        :param path: The path to put the file, relative to the .bzr control
                     directory
        :param f: A file-like or string object whose contents should be copied.
        """
        import codecs
        from iterablefile import IterableFile
        ctrl_files = []
        if hasattr(file, 'read'):
            iterator = file_iterator(file)
        else:
            iterator = file
        # IterableFile would not be needed if Transport.put took iterables
        # instead of files.  ADHB 2005-12-25
        encoded_file = IterableFile(b.encode('utf-8', 'replace') for b in 
                                    iterator)
        self.put(path, encoded_file)

    def lock_write(self):
        mutter("lock write: %s (%s)", self, self._lock_count)
        # TODO: Upgrade locking to support using a Transport,
        # and potentially a remote locking protocol
        if self._lock_mode:
            if self._lock_mode != 'w':
                raise LockError("can't upgrade to a write lock from %r" %
                                self._lock_mode)
            self._lock_count += 1
        else:
            self._lock = self._transport.lock_write(
                    self._rel_controlfilename(self.lock_name))
            self._lock_mode = 'w'
            self._lock_count = 1
            self._set_transaction(transactions.PassThroughTransaction())

    def lock_read(self):
        mutter("lock read: %s (%s)", self, self._lock_count)
        if self._lock_mode:
            assert self._lock_mode in ('r', 'w'), \
                   "invalid lock mode %r" % self._lock_mode
            self._lock_count += 1
        else:
            self._lock = self._transport.lock_read(
                    self._rel_controlfilename(self.lock_name))
            self._lock_mode = 'r'
            self._lock_count = 1
            self._set_transaction(transactions.ReadOnlyTransaction())
            # 5K may be excessive, but hey, its a knob.
            self.get_transaction().set_cache_size(5000)
                        
    def unlock(self):
        mutter("unlock: %s (%s)", self, self._lock_count)
        if not self._lock_mode:
            raise LockError('branch %r is not locked' % (self))

        if self._lock_count > 1:
            self._lock_count -= 1
        else:
            self._finish_transaction()
            self._lock.unlock()
            self._lock = None
            self._lock_mode = self._lock_count = None

    def make_transport(self, relpath):
        return self._transport.clone(relpath)

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
