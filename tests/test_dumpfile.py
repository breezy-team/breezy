# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>

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

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.transport import Transport, get_transport
from bzrlib.workingtree import WorkingTree

import os

from tests import TestCaseWithSubversionRepository
from dumpfile import SvnDumpFile
from repository import MAPPING_VERSION

class TestDumpFile(TestCaseWithSubversionRepository):
    def test_open_empty(self):
        filename = os.path.join(self.test_dir, "dumpfile")
        open(filename, 'w').write(
"""SVN-fs-dump-format-version: 2

UUID: 6987ef2d-cd6b-461f-9991-6f1abef3bd59

Revision-number: 0
Prop-content-length: 56
Content-length: 56

K 8
svn:date
V 27
2006-07-02T13:14:51.972532Z
PROPS-END
""")
        dir = BzrDir.open(filename)
        self.assertEqual("file://%s" % filename, 
                dir.root_transport.base.rstrip("/"))

    def test_open_internal(self):
        filename = os.path.join(self.test_dir, "dumpfile")
        open(filename, 'w').write(
"""SVN-fs-dump-format-version: 2

UUID: 6987ef2d-cd6b-461f-9991-6f1abef3bd59

Revision-number: 0
Prop-content-length: 56
Content-length: 56

K 8
svn:date
V 27
2006-07-02T13:14:51.972532Z
PROPS-END

Revision-number: 1
Prop-content-length: 109
Content-length: 109

K 7
svn:log
V 9
Add trunk
K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-07-02T13:58:02.528258Z
PROPS-END

Node-path: trunk
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Node-path: trunk/bla
Node-kind: file
Node-action: add
Prop-content-length: 10
Text-content-length: 5
Text-content-md5: 6137cde4893c59f76f005a8123d8e8e6
Content-length: 15

PROPS-END
data


""")
        branch = Branch.open(filename + "/trunk")
        self.assertEqual("file://%s/trunk" % filename, branch.base)
        self.assertEqual("svn-v%d:1@6987ef2d-cd6b-461f-9991-6f1abef3bd59-trunk" % MAPPING_VERSION, branch.last_revision())
