# Copyright (C) 2006 Canonical Ltd
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

"""Inter-object utility class."""

from typing import Generic, List, Type, TypeVar

from .errors import BzrError
from .lock import LogicalLockResult
from .pyutils import get_named_object


class NoCompatibleInter(BzrError):
    _fmt = (
        "No compatible object available for operations from %(source)r to %(target)r."
    )

    def __init__(self, source, target):
        self.source = source
        self.target = target


T = TypeVar("T")


class InterObject(Generic[T]):
    """This class represents operations taking place between two objects.

    Its instances have methods like join or copy_content or fetch, and contain
    references to the source and target objects these operations can be
    carried out between.

    Often we will provide convenience methods on the objects which carry out
    operations with another of similar type - they will always forward to
    a subclass of InterObject - i.e.
    InterVersionedFile.get(other).method_name(parameters).

    If the source and target objects implement the locking protocol -
    lock_read, lock_write, unlock, then the InterObject's lock_read,
    lock_write and unlock methods may be used.

    When looking for an inter, the most recently registered types are tested
    first.  So typically the most generic and slowest InterObjects should be
    registered first.
    """

    source: T
    target: T

    _optimisers: List[Type["InterObject[T]"]]

    # _optimisers = list()
    # Each concrete InterObject type should have its own optimisers list.

    def __init__(self, source: T, target: T):
        """Construct a default InterObject instance. Please use 'get'.

        Only subclasses of InterObject should call
        InterObject.__init__ - clients should call InterFOO.get where FOO
        is the base type of the objects they are interacting between. I.e.
        InterVersionedFile or InterRepository.
        get() is a convenience class method which will create an optimised
        InterFOO if possible.
        """
        self.source = source
        self.target = target

    def _double_lock(self, lock_source, lock_target):
        """Take out two locks, rolling back the first if the second throws."""
        lock_source()
        try:
            lock_target()
        except Exception:
            # we want to ensure that we don't leave source locked by mistake.
            # and any error on target should not confuse source.
            self.source.unlock()
            raise

    # TODO(jelmer): Post Python 3.11, return Self here
    @classmethod
    def get(klass, source: T, target: T):
        """Retrieve a Inter worker object for these objects.

        :param source: the object to be the 'source' member of
                       the InterObject instance.
        :param target: the object to be the 'target' member of
                       the InterObject instance.

        If an optimised worker exists it will be used otherwise
        a default Inter worker instance will be created.
        """
        for i, provider in enumerate(reversed(klass._optimisers)):
            if isinstance(provider, tuple):
                provider = get_named_object(provider[0], provider[1])
                klass._optimisers[-i] = provider
            if provider.is_compatible(source, target):
                return provider(source, target)
        raise NoCompatibleInter(source, target)

    @classmethod
    def is_compatible(cls, source, target):
        raise NotImplementedError(cls.is_compatible)

    @classmethod
    def iter_optimisers(klass):
        for provider in klass._optimisers:
            if isinstance(provider, tuple):
                yield get_named_object(provider[0], provider[1])
            else:
                yield provider

    def lock_read(self):
        """Take out a logical read lock.

        This will lock the source branch and the target branch. The source gets
        a read lock and the target a read lock.
        """
        self._double_lock(self.source.lock_read, self.target.lock_read)
        return LogicalLockResult(self.unlock)

    def lock_write(self):
        """Take out a logical write lock.

        This will lock the source branch and the target branch. The source gets
        a read lock and the target a write lock.
        """
        self._double_lock(self.source.lock_read, self.target.lock_write)
        return LogicalLockResult(self.unlock)

    @classmethod
    def register_optimiser(klass, optimiser):
        """Register an InterObject optimiser."""
        klass._optimisers.append(optimiser)

    @classmethod
    def register_lazy_optimiser(klass, module_name, member_name):
        # TODO(jelmer): Allow passing in a custom .is_compatible
        klass._optimisers.append((module_name, member_name))

    def unlock(self):
        """Release the locks on source and target."""
        try:
            self.target.unlock()
        finally:
            self.source.unlock()

    @classmethod
    def unregister_optimiser(klass, optimiser):
        """Unregister an InterObject optimiser."""
        klass._optimisers.remove(optimiser)
