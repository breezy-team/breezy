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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""sphinx texinfo builder tests."""

import os
from sphinx import application

from bzrlib import tests
from bzrlib.doc_generate import (
    # FIXME: doc/en/conf.py should be used here, or rather merged into
    # bzrlib/doc_generate/conf.py -- vila 20100429
    conf,
    )
from bzrlib.tests import features


class TestBuilderDefined(tests.TestCase):

    def test_builder_defined(self):
        self.assertTrue('bzrlib.doc_generate.builders.texinfo'
                        in conf.extensions)

class TestSphinx(tests.TestCaseInTempDir):

    def make_sphinx(self):
        out = tests.StringIOWrapper()
        err = tests.StringIOWrapper()
        app = application.Sphinx(
            '.', confdir=os.path.dirname(conf.__file__), outdir='.',
            doctreedir='.',
            buildername='texinfo',
            confoverrides={},
            status=out, warning=err,
            freshenv=True)
        return app, out, err

class TestBuilderLoaded(TestSphinx):

    def test_builder_loaded(self):
        app, out, err = self.make_sphinx()
        self.assertTrue('texinfo' in app.builderclasses)


class TestTexinfoFileGeneration(TestSphinx):

    def test_files_generated(self):
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
        app.build(True, [])
        self.failUnlessExists('index.texi')
        self.failUnlessExists('content.texi')
        # FIXME: When the content of the files becomes clearer replace the
        # assertion above by the ones below -- vila 20100504
#         self.assertFileEqual("""\
# """,
#                               'content.texi')
#         self.assertFileEqual("""\
# """,
#                               'index.texi')
# 
