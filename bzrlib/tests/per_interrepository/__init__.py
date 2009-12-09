# Copyright (C) 2006 Canonical Ltd
# Authors: Robert Collins <robert.collins@canonical.com>
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


"""InterRepository implementation tests for bzr.

These test the conformance of all the interrepository variations to the
expected API including generally applicable corner cases.
Specific tests for individual formats are in the tests/test_repository.py file
rather than in tests/per_interrepository/*.py.
"""


from bzrlib.errors import (
    FileExists,
    UninitializableFormat,
    )

from bzrlib.repository import (
    InterRepository,
    )
from bzrlib.tests import (
                          default_transport,
                          multiply_tests,
                          )
from bzrlib.tests.per_bzrdir.test_bzrdir import TestCaseWithBzrDir
from bzrlib.transport import get_transport


def make_scenarios(transport_server, transport_readonly_server, formats):
    """Transform the input formats to a list of scenarios.

    :param formats: A list of tuples:
        (label, repository_format, repository_format_to).
    """
    result = []
    for label, repository_format, repository_format_to in formats:
        id = '%s,%s,%s' % (label, repository_format.__class__.__name__,
                           repository_format_to.__class__.__name__)
        scenario = (id,
            {"transport_server": transport_server,
             "transport_readonly_server": transport_readonly_server,
             "repository_format": repository_format,
             "repository_format_to": repository_format_to,
             })
        result.append(scenario)
    return result


def default_test_list():
    """Generate the default list of interrepo permutations to test."""
    from bzrlib.repofmt import (
        groupcompress_repo,
        knitrepo,
        pack_repo,
        weaverepo,
        )
    result = []
    def add_combo(label, from_format, to_format):
        result.append((label, from_format, to_format))
    # test the default InterRepository between format 6 and the current
    # default format.
    # XXX: robertc 20060220 reinstate this when there are two supported
    # formats which do not have an optimal code path between them.
    #result.append((InterRepository,
    #               RepositoryFormat6(),
    #               RepositoryFormatKnit1()))
    for optimiser_class in InterRepository._optimisers:
        format_to_test = optimiser_class._get_repo_format_to_test()
        if format_to_test is not None:
            add_combo(optimiser_class.__name__, format_to_test, format_to_test)
    # if there are specific combinations we want to use, we can add them
    # here. We want to test rich root upgrading.
    # XXX: although we attach InterRepository class names to these scenarios,
    # there's nothing asserting that these labels correspond to what is
    # actually used.
    add_combo('InterRepository',
              weaverepo.RepositoryFormat5(),
              knitrepo.RepositoryFormatKnit3())
    add_combo('InterRepository',
              knitrepo.RepositoryFormatKnit1(),
              knitrepo.RepositoryFormatKnit3())
    add_combo('InterKnitRepo',
              knitrepo.RepositoryFormatKnit1(),
              pack_repo.RepositoryFormatKnitPack1())
    add_combo('InterKnitRepo',
              pack_repo.RepositoryFormatKnitPack1(),
              knitrepo.RepositoryFormatKnit1())
    add_combo('InterKnitRepo',
              knitrepo.RepositoryFormatKnit3(),
              pack_repo.RepositoryFormatKnitPack3())
    add_combo('InterKnitRepo',
              pack_repo.RepositoryFormatKnitPack3(),
              knitrepo.RepositoryFormatKnit3())
    add_combo('InterKnitRepo',
              pack_repo.RepositoryFormatKnitPack3(),
              pack_repo.RepositoryFormatKnitPack4())
    add_combo('InterDifferingSerializer',
              pack_repo.RepositoryFormatKnitPack1(),
              pack_repo.RepositoryFormatKnitPack6RichRoot())
    add_combo('InterDifferingSerializer',
              pack_repo.RepositoryFormatKnitPack6RichRoot(),
              groupcompress_repo.RepositoryFormat2a())
    add_combo('InterDifferingSerializer',
              groupcompress_repo.RepositoryFormat2a(),
              pack_repo.RepositoryFormatKnitPack6RichRoot())
    add_combo('InterRepository',
              groupcompress_repo.RepositoryFormatCHK2(),
              groupcompress_repo.RepositoryFormat2a())
    add_combo('InterDifferingSerializer',
              groupcompress_repo.RepositoryFormatCHK1(),
              groupcompress_repo.RepositoryFormat2a())
    return result


class TestCaseWithInterRepository(TestCaseWithBzrDir):

    def setUp(self):
        super(TestCaseWithInterRepository, self).setUp()

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
                format = self.repository_format._matchingbzrdir
            return format.initialize(url)
        except UninitializableFormat:
            raise TestSkipped("Format %s is not initializable." % format)

    def make_repository(self, relpath, format=None):
        made_control = self.make_bzrdir(relpath, format=format)
        return self.repository_format.initialize(made_control)

    def make_to_repository(self, relpath):
        made_control = self.make_bzrdir(relpath,
            self.repository_format_to._matchingbzrdir)
        return self.repository_format_to.initialize(made_control)


def load_tests(standard_tests, module, loader):
    submod_tests = loader.loadTestsFromModuleNames([
        'bzrlib.tests.per_interrepository.test_fetch',
        'bzrlib.tests.per_interrepository.test_interrepository',
        ])
    scenarios = make_scenarios(
        default_transport,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        default_test_list()
        )
    return multiply_tests(submod_tests, scenarios, standard_tests)
