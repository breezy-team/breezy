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

"""Documentation generation tests."""

import os
from bzrlib import tests
from bzrlib.doc_generate import (
    # FIXME: doc/en/conf.py should be used here, or rather merged into
    # bzrlib/doc_generate/conf.py -- vila 20100429
    conf,
    )
from bzrlib.tests import features


def load_tests(basic_tests, module, loader):
    suite = loader.suiteClass()
    # add the tests for this module
    suite.addTests(basic_tests)

    testmod_names = [
        'builders',
        'writers',
        ]
    # add the tests for the sub modules
    suite.addTests(loader.loadTestsFromModuleNames(
            ['bzrlib.tests.doc_generate.' + name
             for name in testmod_names]))

    return suite


class TestSphinx(tests.TestCaseInTempDir):
    """Base class for sphinx tests.

    This is used for both the builder and the writer until a better solution is
    found to test at a lower level.
    """

    _test_needs_features = [features.sphinx]

    def sphinx_version(self):
        # Convert to a tuple to avoid traps in string comparison
        # ( '1.12' < '1.6' but (1, 12) > (1, 6) )
        return tuple(map(int, features.sphinx.module.__version__.split('.')))

    def make_sphinx(self):
        out = tests.StringIOWrapper()
        err = tests.StringIOWrapper()
        from sphinx import application
        app = application.Sphinx(
            '.', confdir=os.path.dirname(conf.__file__), outdir='.',
            doctreedir='.',
            buildername='texinfo',
            confoverrides={},
            status=out, warning=err,
            freshenv=True)
        return app, out, err

    def build(self, app, all_files=True, file_names=None):
        if file_names is None:
            file_names = []
        app.build(all_files, file_names)

    # FIXME: something smells wrong here as we can't process a single file
    # alone. On top of that, it seems the doc tree must contain an index.txt
    # file. We may need a texinfo builder ? -- vila 20100505

    def create_content(self, content):
        """Put content into a single file.

        This is appropriate for simple tests about the content of a single file.
        """
        app, out, err = self.make_sphinx()
        self.build_tree_contents([('index.txt', content),])
        self.build(app)

    def assertContent(self, expected, header=None, end=None):
        """Check the content of the file created with creste_content().

        Most texinfo constructs can be tested this way without caring for any
        boilerplate that texinfo may require at the beginning or the end of the
        file.
        """
        if header is None:
            # default boilerplate
            header = '''\
This file has been converted using a beta rst->texinfo converter. 
Most of the info links are currently bogus, don't report bugs about them,
this is currently worked on.
@node Top
@top Placeholder
'''
        if end is None:
            # By default we test constructs that are embedded into a paragraph
            # which always end with two \n (even if the input has none)
            end = '\n\n'
        self.assertFileEqual(header + expected + end, 'index.texi')


