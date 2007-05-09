# Copyright (C) 2007 Canonical Ltd
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

"""Pyrex extensions to knit parsing."""


def _load_data_c(kndx, fp):
    """Load the knit index file into memory."""
    cache = kndx._cache
    history = kndx._history

    kndx.check_header(fp)
    # readlines reads the whole file at once:
    # bad for transports like http, good for local disk
    # we save 60 ms doing this one change (
    # from calling readline each time to calling
    # readlines once.
    # probably what we want for nice behaviour on
    # http is a incremental readlines that yields, or
    # a check for local vs non local indexes,
    history_top = len(history) - 1
    for line in fp.readlines():
        rec = line.split()
        if len(rec) < 5 or rec[-1] != ':':
            # corrupt line.
            # FIXME: in the future we should determine if its a
            # short write - and ignore it 
            # or a different failure, and raise. RBC 20060407
            continue

        parents = []
        for value in rec[4:-1]:
            if value[0] == '.':
                # uncompressed reference
                parent_id = value[1:]
            else:
                parent_id = history[int(value)]
            parents.append(parent_id)

        version_id, options, pos, size = rec[:4]
        version_id = version_id

        # See kndx._cache_version
        # only want the _history index to reference the 1st 
        # index entry for version_id
        if version_id not in cache:
            history_top = history_top + 1
            index = history_top
            history.append(version_id)
        else:
            index = cache[version_id][5]
        cache[version_id] = (version_id,
                             options.split(','),
                             int(pos),
                             int(size),
                             parents,
                             index)
        # end kndx._cache_version 
