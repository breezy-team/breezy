# Copyright (C) 2006 Canonical Ltd
# Authors: Robert Collins <robert.collins@canonical.com>
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


"""A GIT branch and repository format implementation for bzr."""


from StringIO import StringIO

import stgit
import stgit.git as git

from bzrlib import (
    commands,
    config,
    deprecated_graph,
    iterablefile,
    osutils,
    urlutils,
    )
from bzrlib.decorators import *
import bzrlib.branch
import bzrlib.bzrdir
import bzrlib.errors as errors
import bzrlib.repository
from bzrlib.revision import Revision


class GitInventory(object):

    def __init__(self, revision_id):
        self.entries = {}
        self.root = GitEntry('', 'directory', revision_id)
        self.entries[''] = self.root

    def __getitem__(self, key):
        return self.entries[key]

    def iter_entries(self):
        return iter(sorted(self.entries.items()))

    def iter_entries_by_dir(self):
        return self.iter_entries()

    def __len__(self):
        return len(self.entries)


class GitEntry(object):

    def __init__(self, path, kind, revision, text_sha1=None, executable=False,
                 text_size=None):
        self.path = path
        self.file_id = path
        self.kind = kind
        self.executable = executable
        self.name = osutils.basename(path)
        if path == '':
            self.parent_id = None
        else:
            self.parent_id = osutils.dirname(path)
        self.revision = revision
        self.symlink_target = None
        self.text_sha1 = text_sha1
        self.text_size = None

    def __repr__(self):
        return "GitEntry(%r, %r, %r, %r)" % (self.path, self.kind, 
                                             self.revision, self.parent_id)


class GitModel(object):
    """API that follows GIT model closely"""

    def __init__(self, git_dir):
        self.git_dir = git_dir

    def git_command(self, command, args):
        args = ' '.join("'%s'" % arg for arg in args)
        return 'git --git-dir=%s %s %s' % (self.git_dir, command, args) 

    def git_lines(self, command, args):
        return stgit.git._output_lines(self.git_command(command, args))

    def git_line(self, command, args):
        return stgit.git._output_one_line(self.git_command(command, args))

    def cat_file(self, type, object_id, pretty=False):
        args = []
        if pretty:
            args.append('-p')
        else:
            args.append(type)
        args.append(object_id)
        return self.git_lines('cat-file', args)

    def rev_list(self, heads, max_count=None, header=False):
        args = []
        if max_count is not None:
            args.append('--max-count=%d' % max_count)
        if header is not False:
            args.append('--header')
        if heads is None:
            args.append('--all')
        else:
            args.extend(heads)
        return self.git_lines('rev-list', args)

    def rev_parse(self, git_id):
        args = ['--verify', git_id]
        return self.git_line('rev-parse', args)

    def get_head(self):
        return self.rev_parse('HEAD')

    def ancestor_lines(self, revisions):
        revision_lines = []
        for line in self.rev_list(revisions, header=True):
            if line.startswith('\x00'):
                yield revision_lines
                revision_lines = [line[1:].decode('latin-1')]
            else:
                revision_lines.append(line.decode('latin-1'))
        assert revision_lines == ['']

    def get_inventory(self, tree_id):
        for line in self.cat_file('tree', tree_id, True):
            sections = line.split(' ', 2)
            obj_id, name = sections[2].split('\t', 1)
            name = name.rstrip('\n')
            if name.startswith('"'):
                name = name[1:-1].decode('string_escape').decode('utf-8')
            yield (sections[0], sections[1], obj_id, name)


class cmd_test_git(commands.Command):

    def run(self):
        from bzrlib.tests import selftest
        selftest
def test_suite():
    from bzrlib.plugins.git import tests
    return tests.test_suite()
