# Copyright (C) 2010 Canonical Ltd
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

"""Test the exporter."""

import os
import tempfile
import gzip

from bzrlib import tests

from bzrlib.plugins.fastimport.exporter import (
    _get_output_stream,
    )

from bzrlib.plugins.fastimport.tests import (
    FastimportFeature,
    )


class TestOutputStream(tests.TestCase):

    _test_needs_features = [FastimportFeature]

    def test_get_output_stream_stdout(self):
        # - returns standard out
        self.assertIsNot(None, _get_output_stream("-"))

    def test_get_source_gz(self):
        fd, filename = tempfile.mkstemp(suffix=".gz")
        os.close(fd)
        stream = _get_output_stream(filename)
        stream.write("bla")
        stream.close()
        # files ending in .gz are automatically decompressed.
        f = gzip.GzipFile(filename)
        self.assertEquals("bla", f.read())
        f.close()

    def test_get_source_file(self):
        # other files are opened as regular files.
        fd, filename = tempfile.mkstemp()
        os.close(fd)
        stream = _get_output_stream(filename)
        stream.write("foo")
        stream.close()
        f = open(filename, 'r')
        self.assertEquals("foo", f.read())
        f.close()
