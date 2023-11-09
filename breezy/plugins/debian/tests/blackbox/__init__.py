#    __init__.py -- blackbox test suite for builddeb.
#    Copyright (C) 2007 James Westby <jw+debian@jameswestby.net>
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#


def load_tests(loader, basic_tests, pattern):
    testmod_names = [
        "test_builddeb",
        "test_debrelease",
        "test_dep3",
        "test_do",
        "test_get_tar",
        "test_import_dsc",
        "test_import_upstream",
        "test_merge_package",
        "test_merge_upstream",
    ]
    basic_tests.addTest(
        loader.loadTestsFromModuleNames([f"{__name__}.{i}" for i in testmod_names])
    )
    return basic_tests
