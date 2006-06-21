# Copyright (C) 2005-2006 Jelmer Vernooij <jelmer@samba.org>

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
Support for foreign branches (Subversion)
"""
import sys
import os.path
import transport
import dumpfile
import format
import branch
import submit
import workingtree

sys.path.append(os.path.dirname(__file__))

from bzrlib.transport import register_transport
register_transport('svn:', transport.SvnRaTransport)
register_transport('svn+', transport.SvnRaTransport)

from bzrlib.bzrdir import BzrDirFormat

BzrDirFormat.register_control_format(format.SvnFormat)

BzrDirFormat.register_control_format(workingtree.SvnWorkingTreeDirFormat)

BzrDirFormat.register_control_format(dumpfile.SvnDumpFileFormat)

def test_suite():
    from unittest import TestSuite, TestLoader
    import tests

    suite = TestSuite()

    suite.addTest(tests.test_suite())

    return suite

