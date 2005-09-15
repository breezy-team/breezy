# Copyright (C) 2005 by Canonical Development Ltd

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

"""
Stores are the main data-storage mechanism for Bazaar-NG.

A store is a simple write-once container indexed by a universally
unique ID.
"""

import bzrlib
from bzrlib.trace import mutter
import bzrlib.ui
import bzrlib.transport

######################################################################
# stores

class StoreError(Exception):
    pass

class Store(object):
    """This class represents the abstract storage layout for saving information.
    """
    _transport = None
    _max_buffered_requests = 10

    def __init__(self, transport):
        assert isinstance(transport, bzrlib.transport.Transport)
        self._transport = transport

    def __repr__(self):
        if self._transport is None:
            return "%s(None)" % (self.__class__.__name__)
        else:
            return "%s(%r)" % (self.__class__.__name__, self._transport.base)

    __str__ = __repr__

    def __len__(self):
        raise NotImplementedError('Children should define their length')

    def __getitem__(self, fileid):
        """Returns a file reading from a particular entry."""
        raise NotImplementedError

    def __contains__(self, fileid):
        """"""
        raise NotImplementedError

    def __iter__(self):
        raise NotImplementedError

    def add(self, f, fileid):
        """Add a file object f to the store accessible from the given fileid"""
        raise NotImplementedError('Children of Store must define their method of adding entries.')

    def add_multi(self, entries):
        """Add a series of file-like or string objects to the store with the given
        identities.
        
        :param entries: A list of tuples of file,id pairs [(file1, id1), (file2, id2), ...]
                        This could also be a generator yielding (file,id) pairs.
        """
        for f, fileid in entries:
            self.add(f, fileid)

    def has(self, fileids):
        """Return True/False for each entry in fileids.

        :param fileids: A List or generator yielding file ids.
        :return: A generator or list returning True/False for each entry.
        """
        for fileid in fileids:
            if fileid in self:
                yield True
            else:
                yield False

    def get(self, fileids, ignore_missing=False, pb=None):
        """Return a set of files, one for each requested entry.
        
        :param ignore_missing: If true, return None for entries which do not 
                               exist.
        :return: A list or generator of file-like objects, one for each id.
        """
        for fileid in fileids:
            try:
                yield self[fileid]
            except KeyError:
                if ignore_missing:
                    yield None
                else:
                    raise

    def copy_multi(self, other, ids, pb=None, permit_failure=False):
        """Copy texts for ids from other into self.

        If an id is present in self, it is skipped.  A count of copied
        ids is returned, which may be less than len(ids).

        :param other: Another Store object
        :param ids: A list of entry ids to be copied
        :param pb: A ProgressBar object, if none is given, the default will be created.
        :param permit_failure: Allow missing entries to be ignored
        :return: (n_copied, [failed]) The number of entries copied successfully,
            followed by a list of entries which could not be copied (because they
            were missing)
        """
        if pb is None:
            pb = bzrlib.ui.ui_factory.progress_bar()

        ids = list(ids) # Make sure we don't have a generator, since we iterate 2 times
        pb.update('preparing to copy')
        to_copy = []
        for file_id, has in zip(ids, self.has(ids)):
            if not has:
                to_copy.append(file_id)
        return self._do_copy(other, to_copy, pb, permit_failure=permit_failure)

    def _do_copy(self, other, to_copy, pb, permit_failure=False):
        """This is the standard copying mechanism, just get them one at
        a time from remote, and store them locally.

        :param other: Another Store object
        :param to_copy: A list of entry ids to copy
        :param pb: A ProgressBar object to display completion status.
        :param permit_failure: Allow missing entries to be ignored
        :return: (n_copied, [failed])
            The number of entries copied, and a list of failed entries.
        """
        # This should be updated to use add_multi() rather than
        # the current methods of buffering requests.
        # One question, is it faster to queue up 1-10 and then copy 1-10
        # then queue up 11-20, copy 11-20
        # or to queue up 1-10, copy 1, queue 11, copy 2, etc?
        # sort of pipeline versus batch.

        # We can't use self._transport.copy_to because we don't know
        # whether the local tree is in the same format as other
        failed = set()
        def buffer_requests():
            count = 0
            buffered_requests = []
            for fileid in to_copy:
                try:
                    f = other[fileid]
                except KeyError:
                    if permit_failure:
                        failed.add(fileid)
                        continue
                    else:
                        raise

                buffered_requests.append((f, fileid))
                if len(buffered_requests) > self._max_buffered_requests:
                    yield buffered_requests.pop(0)
                    count += 1
                    pb.update('copy', count, len(to_copy))

            for req in buffered_requests:
                yield req
                count += 1
                pb.update('copy', count, len(to_copy))

            assert count == len(to_copy)

        self.add_multi(buffer_requests())

        pb.clear()
        return len(to_copy), failed

