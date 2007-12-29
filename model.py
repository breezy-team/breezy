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

"""The model for interacting with the git process, etc."""

import os
import subprocess
import tarfile

from bzrlib.plugins.git import errors


class GitModel(object):
    """API that follows GIT model closely"""

    def __init__(self, git_dir):
        self.git_dir = git_dir

    def git_command(self, command, args):
        return ['git', command] + args

    def git_lines(self, command, args):
        cmd = self.git_command(command, args)
        env = os.environ.copy()
        env['GIT_DIR'] = self.git_dir
        p = subprocess.Popen(cmd,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             env=env)
        lines = p.stdout.readlines()
        if p.wait() != 0:
            raise errors.GitCommandError(cmd, p.returncode,
                                         p.stderr.read().strip())
        return lines

    def git_line(self, command, args):
        lines = self.git_lines(command, args)
        return lines[0]

    def cat_file(self, type, object_id, pretty=False):
        args = []
        if pretty:
            args.append('-p')
        else:
            args.append(type)
        args.append(object_id)
        return self.git_lines('cat-file', args)

    def rev_list(self, heads, max_count=None, header=False, parents=False,
                 topo_order=False, paths=None):
        args = []
        if max_count is not None:
            args.append('--max-count=%d' % max_count)
        if header:
            args.append('--header')
        if parents:
            args.append('--parents')
        if topo_order:
            args.append('--topo-order')
        if heads is None:
            args.append('--all')
        else:
            args.extend(heads)
        if paths is not None:
            args.append('--')
            args.extend(paths)
        return self.git_lines('rev-list', args)

    def rev_parse(self, git_id):
        args = ['--verify', git_id]
        return self.git_line('rev-parse', args).strip()

    def get_head(self):
        try:
            return self.rev_parse('HEAD')
        except errors.GitCommandError, e:
            # Most likely, this is a null branch, so treat it as such
            if e.stderr == 'fatal: Needed a single revision':
                return None
            raise

    def get_revision_graph(self, revisions):
        ancestors = {}
        for line in self.rev_list(revisions, parents=True):
            entries = line.split()
            ancestors[entries[0]] = entries[1:]
        return ancestors

    def get_ancestry(self, revisions):
        args = ['--topo-order', '--reverse'] + revisions
        return [line[:-1] for line in self.git_lines('rev-list', args)]

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
        for line in self.git_lines('ls-tree', ['-r', '-t', tree_id]):
            # Ideally, we would use -z so we would not have to handle escaped
            # file names. But then we could not use readlines() to split the
            # data as it is read.
            permissions, type, hash_and_path = line.split(' ', 2)
            hash, name = hash_and_path.split('\t', 1)
            name = name[:-1] # strip trailing newline
            if name.startswith('"'):
                name = name[1:-1].decode('string_escape')
            name = name.decode('utf-8')
            yield permissions, type, hash, name

    def get_tarpipe(self, tree_id):
        cmd = self.git_command('archive', [tree_id])
        env = os.environ.copy()
        env['GIT_DIR'] = self.git_dir
        p = subprocess.Popen(cmd,
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             env=env)
        p.stdin.close()
        tarpipe = TarPipe.open(mode='r|', fileobj=p.stdout)
        def close_callback():
            if p.wait() != 0:
                raise errors.GitCommandError(cmd, p.returncode,
                                             p.stderr.read().strip())
        tarpipe.set_close_callback(close_callback)
        return tarpipe


class TarPipe(tarfile.TarFile):

    def set_close_callback(self, close_callback):
        self.__close_callback = close_callback

    def close(self):
        super(TarPipe, self).close()
        self.__close_callback()
