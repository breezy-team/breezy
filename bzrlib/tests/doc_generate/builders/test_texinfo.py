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


class TestBuilderLoaded(tests.TestCaseInTempDir):

    _test_needs_features = [features.sphinx]

    def test_builder_loaded(self):
        out = tests.StringIOWrapper()
        err = tests.StringIOWrapper()
        app = application.Sphinx(
            '.', confdir=os.path.dirname(conf.__file__), outdir='.',
            doctreedir='.',
            buildername='texinfo',
            confoverrides={},
            status=out, warning=err,
            freshenv=False, warningiserror=False,
            tags=[])
        self.assertTrue('texinfo' in app.builderclasses)
