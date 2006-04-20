# Copyright (C) 2006 by Canonical Ltd

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

from bzrlib.tests import TestCaseInTempDir, TestSkipped
from bzrlib.branch import Branch

# TODO: perhaps doc_generate should be moved into bzrlib instead?

class TestDocGenerate(TestCaseInTempDir):

    def test_generate_manpage(self):
        """Simple smoke test for doc_generate"""
        try:
            import tools.doc_generate
        except ImportError, e:
            raise TestSkipped("can't load doc_generate: %s" % e)
        infogen_mod = tools.doc_generate.get_module("man")
