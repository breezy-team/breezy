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

"""Benchmarks for pack performance"""

import os

from bzrlib import (
    pack,
    )
from bzrlib.benchmarks import Benchmark


class BenchPack(Benchmark):
    """Benchmark pack performance."""

    def test_insert_one_gig_1k_chunks_no_names_disk(self):
        # test real disk writing of many small chunks. 
        # useful for testing whether buffer sizes are right 
        transport = self.get_transport()
        stream = transport.open_write_stream('pack.pack')
        writer = pack.ContainerWriter(stream.write)
        self.write_1_gig(writer)
        stream.close()

    def test_insert_one_gig_1k_chunks_no_names_null(self):
        # write to dev/null so we test the pack processing.
        transport = self.get_transport()
        dev_null = open('/dev/null', 'wb')
        writer = pack.ContainerWriter(dev_null.write)
        self.write_1_gig(writer)
        dev_null.close()

    def write_1_gig(self, writer):
        one_k = "A" * 1024
        writer.begin()
        def write_1g():
            for hunk in xrange(1024 * 1024):
                writer.add_bytes_record(one_k, [])
        self.time(write_1g)
        writer.end()
