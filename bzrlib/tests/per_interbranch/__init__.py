# Copyright (C) 2009 Canonical Ltd
# -*- coding: utf-8 -*-
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


"""InterBranch implementation tests for bzr.

These test the conformance of all the interbranch variations to the
expected API including generally applicable corner cases.
Specific tests for individual formats are in the tests for the formats
itself rather than in tests/per_interbranch/*.py.
"""


from bzrlib.branch import (
                           GenericInterBranch,
                           InterBranch,
                           )
from bzrlib.errors import (
    FileExists,
    UninitializableFormat,
    )
from bzrlib.tests import multiply_tests
from bzrlib.tests.bzrdir_implementations.test_bzrdir import TestCaseWithBzrDir
from bzrlib.transport import get_transport


def make_scenarios(test_list):
    """Transform the input test list to a list of scenarios.

    :param formats: A list of tuples:
        (interbranch_class, branch_format_from, branch_format_to).
    """
    result = []
    for interbranch_class, branch_format_from, branch_format_to in test_list:
        id = '%s,%s,%s' % (interbranch_class.__name__,
                            branch_format_from.__class__.__name__,
                            branch_format_to.__class__.__name__)
        scenario = (id,
            {
             "branch_format_from": branch_format_from,
             "interbranch_class": interbranch_class,
             "branch_format_to": branch_format_to,
             })
        result.append(scenario)
    return result


def default_test_list():
    """Generate the default list of interbranch permutations to test."""
    result = []
    # test the default InterBranch between format 6 and the current
    # default format.
    for optimiser_class in InterBranch._optimisers:
        format_from_test, format_to_test = \
            optimiser_class._get_branch_formats_to_test()
        if format_to_test is not None:
            result.append((optimiser_class,
                           format_from_test, format_to_test))
    # if there are specific combinations we want to use, we can add them
    # here.
    return result


class TestCaseWithInterBranch(TestCaseWithBzrDir):

    def setUp(self):
        super(TestCaseWithInterBranch, self).setUp()

    def make_branch(self, relpath, format=None):
        repo = self.make_repository(relpath, format=format)
        return repo.bzrdir.create_branch()

    def make_bzrdir(self, relpath, format=None):
        try:
            url = self.get_url(relpath)
            segments = url.split('/')
            if segments and segments[-1] not in ('', '.'):
                parent = '/'.join(segments[:-1])
                t = get_transport(parent)
                try:
                    t.mkdir(segments[-1])
                except FileExists:
                    pass
            if format is None:
                format = self.branch_format_from._matchingbzrdir
            return format.initialize(url)
        except UninitializableFormat:
            raise TestSkipped("Format %s is not initializable." % format)

    def make_repository(self, relpath, format=None):
        made_control = self.make_bzrdir(relpath, format=format)
        return made_control.create_repository()

    def make_to_bzrdir(self, relpath):
        return self.make_bzrdir(relpath,
            self.branch_format_to._matchingbzrdir)

    def make_to_branch(self, relpath):
        made_control = self.make_to_bzrdir(relpath)
        return self.branch_format_to.initialize(made_control)


def load_tests(standard_tests, module, loader):
    submod_tests = loader.loadTestsFromModuleNames([
        'bzrlib.tests.per_interbranch.test_update_revisions',
        ])
    scenarios = make_scenarios(default_test_list())
    return multiply_tests(submod_tests, scenarios, standard_tests)
