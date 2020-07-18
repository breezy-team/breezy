# Copyright (C) 2008 Canonical Limited.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

"""Tests for bzr-fastimport."""

from .... import errors as bzr_errors
from ....tests import TestLoader
from ....tests.features import Feature
from .. import load_fastimport


class _FastimportFeature(Feature):

    def _probe(self):
        try:
            load_fastimport()
        except bzr_errors.DependencyNotPresent:
            return False
        return True

    def feature_name(self):
        return 'fastimport'


FastimportFeature = _FastimportFeature()


def test_suite():
    module_names = [__name__ + '.' + x for x in [
        'test_commands',
        'test_exporter',
        'test_branch_mapper',
        'test_generic_processor',
        'test_marks_file',
        'test_revision_store',
        ]]
    loader = TestLoader()
    return loader.loadTestsFromModuleNames(module_names)
