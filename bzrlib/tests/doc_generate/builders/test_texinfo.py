# Copyright (C) 2010, 2011 Canonical Ltd
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

"""sphinx texinfo builder tests."""

from bzrlib import tests
from bzrlib.doc_generate import (
    # FIXME: doc/en/conf.py should be used here, or rather merged into
    # bzrlib/doc_generate/conf.py -- vila 20100429
    conf,
    )
from bzrlib.tests import (
    doc_generate as test_dg, # Avoid clash with from bzrlib import doc_generate
    )


class TestBuilderDefined(tests.TestCase):

    def test_builder_defined(self):
        self.assertTrue('bzrlib.doc_generate.builders.texinfo'
                        in conf.extensions)

class TestBuilderLoaded(test_dg.TestSphinx):

    def test_builder_loaded(self):
        app, out, err = self.make_sphinx()
        self.assertTrue('texinfo' in app.builderclasses)


class TestFileProduction(test_dg.TestSphinx):

    def test_files_generated(self):
        if self.sphinx_version() >= (1, 0):
            raise tests.TestSkipped('Not compatible with sphinx >= 1.0')
        self.build_tree_contents(
            [('index.txt', """
Table of Contents
=================

.. toctree::
   :maxdepth: 1

   content
"""),
             ('content.txt', """

bzr 0.0.8
*********

Improvements
============

* Adding a file whose parent directory is not versioned will
  implicitly add the parent, and so on up to the root.
"""),
             ])
        app, out, err = self.make_sphinx()
        self.build(app)
        self.failUnlessExists('index.texi')
        self.failUnlessExists('content.texi')
