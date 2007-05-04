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

"""Tests for the compiled extensions."""

from bzrlib import tests


# TODO: jam 20070503 This seems like a good feature to have, but right now it
#       seems like we need to test individually compiled modules
# class _CompiledFeature(tests.Feature):
#     def _probe(self):
#         try:
#             import bzrlib.compiled.???
#         except ImportError:
#             return False
#         return True
#
#     def feature_name(self):
#         return 'bzrlib.compiled.???'
#
# CompiledFeature =_CompiledFeature()


def test_suite():
    testmod_names = [
        'bzrlib.tests.compiled.test_dirstate_helpers',
    ]

    loader = tests.TestLoader()
    suite = loader.loadTestsFromModuleNames(testmod_names)
    return suite
