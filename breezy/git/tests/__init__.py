# Copyright (C) 2007-2018 Jelmer Vernoij <jelmer@jelmer.uk>
# Copyright (C) 2006, 2007 Canonical Ltd
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

"""The basic test suite for bzr-git."""

import time
from io import BytesIO

from ... import errors as bzr_errors
from ... import tests
from ...tests.features import Feature, ModuleAvailableFeature
from .. import import_dulwich

TestCase = tests.TestCase
TestCaseInTempDir = tests.TestCaseInTempDir
TestCaseWithTransport = tests.TestCaseWithTransport
TestCaseWithMemoryTransport = tests.TestCaseWithMemoryTransport


class _DulwichFeature(Feature):
    def _probe(self):
        try:
            import_dulwich()
        except bzr_errors.DependencyNotPresent:
            return False
        return True

    def feature_name(self):
        return "dulwich"


DulwichFeature = _DulwichFeature()
FastimportFeature = ModuleAvailableFeature("fastimport")


class GitBranchBuilder:
    def __init__(self, stream=None):
        if not FastimportFeature.available():
            raise tests.UnavailableFeature(FastimportFeature)
        self.commit_info = []
        self.orig_stream = stream
        if stream is None:
            self.stream = BytesIO()
        else:
            self.stream = stream
        self._counter = 0
        self._branch = b"refs/heads/master"

    def set_branch(self, branch):
        """Set the branch we are committing."""
        self._branch = branch

    def _write(self, text):
        self.stream.write(text)

    def _writelines(self, lines):
        self.stream.writelines(lines)

    def _create_blob(self, content):
        self._counter += 1
        from fastimport.commands import BlobCommand

        blob = BlobCommand(b"%d" % self._counter, content)
        self._write(bytes(blob) + b"\n")
        return self._counter

    def set_symlink(self, path, content):
        """Create or update symlink at a given path."""
        mark = self._create_blob(self._encode_path(content))
        mode = b"120000"
        self.commit_info.append(
            b"M %s :%d %s\n" % (mode, mark, self._encode_path(path))
        )

    def set_submodule(self, path, commit_sha):
        """Create or update submodule at a given path."""
        mode = b"160000"
        self.commit_info.append(
            b"M %s %s %s\n" % (mode, commit_sha, self._encode_path(path))
        )

    def set_file(self, path, content, executable):
        """Create or update content at a given path."""
        mark = self._create_blob(content)
        mode = b"100755" if executable else b"100644"
        self.commit_info.append(
            b"M %s :%d %s\n" % (mode, mark, self._encode_path(path))
        )

    def delete_entry(self, path):
        """This will delete files or symlinks at the given location."""
        self.commit_info.append(b"D %s\n" % (self._encode_path(path),))

    @staticmethod
    def _encode_path(path):
        if isinstance(path, bytes):
            return path
        if "\n" in path or path[0] == '"':
            path = path.replace("\\", "\\\\")
            path = path.replace("\n", "\\n")
            path = path.replace('"', '\\"')
            path = '"' + path + '"'
        return path.encode("utf-8")

    # TODO: Author
    # TODO: Author timestamp+timezone
    def commit(
        self,
        committer,
        message,
        timestamp=None,
        timezone=b"+0000",
        author=None,
        merge=None,
        base=None,
    ):
        """Commit the new content.

        :param committer: The name and address for the committer
        :param message: The commit message
        :param timestamp: The timestamp for the commit
        :param timezone: The timezone of the commit, such as '+0000' or '-1000'
        :param author: The name and address of the author (if different from
            committer)
        :param merge: A list of marks if this should merge in another commit
        :param base: An id for the base revision (primary parent) if that
            is not the last commit.
        :return: A mark which can be used in the future to reference this
            commit.
        """
        self._counter += 1
        mark = b"%d" % (self._counter,)
        if timestamp is None:
            timestamp = int(time.time())
        self._write(b"commit %s\n" % (self._branch,))
        self._write(b"mark :%s\n" % (mark,))
        self._write(b"committer %s %ld %s\n" % (committer, timestamp, timezone))
        if not isinstance(message, bytes):
            message = message.encode("UTF-8")
        self._write(b"data %d\n" % (len(message),))
        self._write(message)
        self._write(b"\n")
        if base is not None:
            self._write(b"from :%s\n" % (base,))
        if merge is not None:
            for m in merge:
                self._write(b"merge :%s\n" % (m,))
        self._writelines(self.commit_info)
        self._write(b"\n")
        self.commit_info = []
        return mark

    def reset(self, ref=None, mark=None):
        """Create or recreate the named branch.

        :param ref: branch name, defaults to the current branch.
        :param mark: commit the branch will point to.
        """
        if ref is None:
            ref = self._branch
        self._write(b"reset %s\n" % (ref,))
        if mark is not None:
            self._write(b"from :%s\n" % mark)
        self._write(b"\n")

    def finish(self):
        """We are finished building, close the stream, get the id mapping."""
        self.stream.seek(0)
        if self.orig_stream is None:
            from dulwich.repo import Repo

            r = Repo(".")
            from dulwich.fastexport import GitImportProcessor

            importer = GitImportProcessor(r)
            return importer.import_stream(self.stream)


class MissingFeature(tests.TestCase):
    def test_dulwich(self):
        self.requireFeature(DulwichFeature)


def load_tests(loader, basic_tests, pattern):
    suite = loader.suiteClass()
    # add the tests for this module
    suite.addTests(basic_tests)

    prefix = __name__ + "."

    if not DulwichFeature.available():
        suite.addTests(loader.loadTestsFromTestCase(MissingFeature))
        return suite

    testmod_names = [
        "test_blackbox",
        "test_builder",
        "test_branch",
        "test_cache",
        "test_dir",
        "test_fetch",
        "test_git_remote_helper",
        "test_mapping",
        "test_memorytree",
        "test_object_store",
        "test_pristine_tar",
        "test_push",
        "test_remote",
        "test_repository",
        "test_refs",
        "test_revspec",
        "test_roundtrip",
        "test_server",
        "test_transform",
        "test_transportgit",
        "test_tree",
        "test_unpeel_map",
        "test_urls",
        "test_workingtree",
    ]

    # add the tests for the sub modules
    for module_name in testmod_names:
        suite.addTest(loader.loadTestsFromName(prefix + module_name))
    return suite
