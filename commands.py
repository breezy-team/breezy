# Copyright (C) 2008 Canonical Ltd
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

"""Import command classes."""


# Lists of command names
COMMAND_NAMES = ['blob', 'checkpoint', 'commit', 'progress', 'reset', 'tag']
FILE_COMMAND_NAMES = ['modify', 'delete', 'copy', 'rename', 'deleteall']

# Bazaar file kinds
FILE_KIND = 'file'
SYMLINK_KIND = 'symlink'


class ImportCommand(object):
    """Base class for import commands."""

    def __init__(self, name):
        self.name = name
        # List of field names not to display
        self._binary = []

    def __str__(self):
        interesting = {}
        for field,value in self.__dict__.iteritems():
            if field.startswith('_'):
                continue
            elif field in self._binary:
                if value is not None:
                    value = '(...)'
            interesting[field] = value
        return "%s: %s" % (self.__class__.__name__, interesting)


class BlobCommand(ImportCommand):

    def __init__(self, mark, data):
        ImportCommand.__init__(self, 'blob')
        self.mark = mark
        self.data = data
        self._binary = ['data']


class CheckpointCommand(ImportCommand):

    def __init__(self):
        ImportCommand.__init__(self, 'checkpoint')


class CommitCommand(ImportCommand):

    def __init__(self, ref, mark, author, committer, message, parents,
        file_iter):
        ImportCommand.__init__(self, 'commit')
        self.ref = ref
        self.mark = mark
        self.author = author
        self.committer = committer
        self.message = message
        self.parents = parents
        self.file_iter = file_iter
        self._binary = ['file_iter']

    def __str__(self):
        result = [ImportCommand.__str__(self)]
        for f in self.file_iter():
            result.append("\t%s" % f)
        return '\n'.join(result)


class ProgressCommand(ImportCommand):

    def __init__(self, message):
        ImportCommand.__init__(self, 'progress')
        self.message = message


class ResetCommand(ImportCommand):

    def __init__(self, ref, from_):
        ImportCommand.__init__(self, 'reset')
        self.ref = ref
        self.from_ = from_


class TagCommand(ImportCommand):

    def __init__(self, id, from_, tagger, message):
        ImportCommand.__init__(self, 'tag')
        self.id = id
        self.from_ = from_
        self.tagger = tagger
        self.message = message


class FileCommand(ImportCommand):
    """Base class for file commands."""
    pass


class FileModifyCommand(FileCommand):

    def __init__(self, path, kind, is_executable, dataref, data):
        # Either dataref or data should be null
        FileCommand.__init__(self, 'modify')
        self.path = path
        self.kind = kind
        self.is_executable = is_executable
        self.dataref = dataref
        self.data = data
        self._binary = ['data']


class FileDeleteCommand(FileCommand):

    def __init__(self, path):
        FileCommand.__init__(self, 'delete')
        self.path = path


class FileCopyCommand(FileCommand):

    def __init__(self, src_path, dest_path):
        FileCommand.__init__(self, 'copy')
        self.src_path = src_path
        self.dest_path = dest_path


class FileRenameCommand(FileCommand):

    def __init__(self, old_path, new_path):
        FileCommand.__init__(self, 'rename')
        self.old_path = old_path
        self.new_path = new_path


class FileDeleteAllCommand(FileCommand):

    def __init__(self):
        FileCommand.__init__(self, 'deleteall')
