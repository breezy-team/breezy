# Copyright (C) 2006-2012 Aaron Bentley
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

import os
from ..sixish import StringIO
from shutil import rmtree, copy2, copytree
import tarfile
import tempfile
import warnings

from .. import (
    osutils,
    revision as _mod_revision,
    transform
    )
from ..bzr.bzrdir import BzrDir
from ..export import export
from ..upstream_import import (
    common_directory,
    get_archive_type,
    import_archive,
    import_tar,
    import_zip,
    import_dir,
    NotArchiveType,
    top_path,
    ZipFileWrapper,
)
from . import (
    TestCaseInTempDir,
    TestCaseWithTransport,
    )
from .features import UnicodeFilenameFeature


def import_tar_broken(tree, tar_input):
    """
    Import a tarfile with names that that end in //, e.g. Feisty Python 2.5
    """
    tar_file = tarfile.open('lala', 'r', tar_input)
    for member in tar_file.members:
        if member.name.endswith('/'):
            member.name += '/'
    import_archive(tree, tar_file)


class DirFileWriter(object):

    def __init__(self, fileobj, mode):
        # We may be asked to 'append'.  If so, fileobj already has a path.
        # So we copy the existing tree, and overwrite afterward.
        fileobj.seek(0)
        existing = fileobj.read()
        fileobj.seek(0)
        path = tempfile.mkdtemp(dir=os.getcwd())
        if existing != '':
            # copytree requires the directory not to exist
            os.rmdir(path)
            copytree(existing, path)
        fileobj.write(path)
        self.root = path

    def add(self, path):
        target_path = os.path.join(self.root, path)
        parent = osutils.dirname(target_path)
        if not os.path.exists(parent):
            os.makedirs(parent)
        kind = osutils.file_kind(path)
        if kind == 'file':
            copy2(path, target_path)
        if kind == 'directory':
            os.mkdir(target_path)

    def close(self):
        pass


class TestImport(TestCaseInTempDir):

    def make_tar(self, mode='w'):
        def maker(fileobj):
            return tarfile.open('project-0.1.tar', mode, fileobj)
        return self.make_archive(maker)

    def make_archive(self, maker, subdir=True):
        result = StringIO()
        archive_file = maker(result)
        try:
            os.mkdir('project-0.1')
            if subdir:
                prefix='project-0.1/'
                archive_file.add('project-0.1')
            else:
                prefix=''
                os.chdir('project-0.1')
            os.mkdir(prefix + 'junk')
            archive_file.add(prefix + 'junk')

            f = file(prefix + 'README', 'wb')
            f.write('What?')
            f.close()
            archive_file.add(prefix + 'README')

            f = file(prefix + 'FEEDME', 'wb')
            f.write('Hungry!!')
            f.close()
            archive_file.add(prefix + 'FEEDME')

            archive_file.close()
        finally:
            if not subdir:
                os.chdir('..')
            rmtree('project-0.1')
        result.seek(0)
        return result

    def make_archive2(self, builder, subdir):
        result = StringIO()
        archive_file = builder(result)
        os.mkdir('project-0.2')
        try:
            if subdir:
                prefix='project-0.2/'
                archive_file.add('project-0.2')
            else:
                prefix=''
                os.chdir('project-0.2')

            os.mkdir(prefix + 'junk')
            archive_file.add(prefix + 'junk')

            f = file(prefix + 'README', 'wb')
            f.write('Now?')
            f.close()
            archive_file.add(prefix + 'README')

            f = file(prefix + 'README', 'wb')
            f.write('Wow?')
            f.close()
            # Add a second entry for README with different contents.
            archive_file.add(prefix + 'README')
            archive_file.close()

        finally:
            if not subdir:
                os.chdir('..')
        result.seek(0)
        return result

    def make_messed_tar(self):
        result = StringIO()
        tar_file = tarfile.open('project-0.1.tar', 'w', result)
        os.mkdir('project-0.1')
        tar_file.add('project-0.1')

        os.mkdir('project-0.2')
        tar_file.add('project-0.2')

        f = file('project-0.1/README', 'wb')
        f.write('What?')
        f.close()
        tar_file.add('project-0.1/README')
        tar_file.close()
        rmtree('project-0.1')
        result.seek(0)
        return result

    def make_zip(self):
        def maker(fileobj):
            return ZipFileWrapper(fileobj, 'w')
        return self.make_archive(maker)

    def make_tar_with_bzrdir(self):
        result = StringIO()
        tar_file = tarfile.open('tar-with-bzrdir.tar', 'w', result)
        os.mkdir('toplevel-dir')
        tar_file.add('toplevel-dir')
        os.mkdir('toplevel-dir/.bzr')
        tar_file.add('toplevel-dir/.bzr')
        tar_file.close()
        rmtree('toplevel-dir')
        result.seek(0)
        return result

    def test_top_path(self):
        self.assertEqual(top_path('ab/b/c'), 'ab')
        self.assertEqual(top_path('etc'), 'etc')
        self.assertEqual(top_path('project-0.1'), 'project-0.1')

    def test_common_directory(self):
        self.assertEqual(common_directory(['ab/c/d', 'ab/c/e']), 'ab')
        self.assertIs(common_directory(['ab/c/d', 'ac/c/e']), None)
        self.assertEqual('FEEDME', common_directory(['FEEDME']))

    def test_untar(self):
        def builder(fileobj, mode='w'):
            return tarfile.open('project-0.1.tar', mode, fileobj)
        self.archive_test(builder, import_tar)

    def test_broken_tar(self):
        def builder(fileobj, mode='w'):
            return tarfile.open('project-0.1.tar', mode, fileobj)
        self.archive_test(builder, import_tar_broken, subdir=True)

    def test_unzip(self):
        def builder(fileobj, mode='w'):
            return ZipFileWrapper(fileobj, mode)
        self.archive_test(builder, import_zip)

    def test_copydir_nosub(self):
        def builder(fileobj, mode='w'):
            return DirFileWriter(fileobj, mode)
        # It would be bogus to test with the result in a subdirectory,
        # because for directories, the input root is always the output root.
        self.archive_test(builder, import_dir)

    def archive_test(self, builder, importer, subdir=False):
        archive_file = self.make_archive(builder, subdir)
        tree = BzrDir.create_standalone_workingtree('tree')
        tree.lock_write()
        try:
            importer(tree, archive_file)
            self.assertTrue(tree.is_versioned('README'))
            self.assertTrue(tree.is_versioned('FEEDME'))
            self.assertTrue(os.path.isfile(tree.abspath('README')))
            self.assertEqual(tree.stored_kind('README'), 'file')
            self.assertEqual(tree.stored_kind('FEEDME'), 'file')
            f = file(tree.abspath('junk/food'), 'wb')
            f.write('I like food\n')
            f.close()

            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                archive_file = self.make_archive2(builder, subdir)
                importer(tree, archive_file)
            self.assertTrue(tree.is_versioned('README'))
            # Ensure the second version of the file is used.
            self.assertEqual(tree.get_file_text('README'), 'Wow?')
            self.assertTrue(not os.path.exists(tree.abspath('FEEDME')))
        finally:
            tree.unlock()


    def test_untar2(self):
        tar_file = self.make_messed_tar()
        tree = BzrDir.create_standalone_workingtree('tree')
        import_tar(tree, tar_file)
        self.assertTrue(tree.is_versioned('project-0.1/README'))

    def test_untar_gzip(self):
        tar_file = self.make_tar(mode='w:gz')
        tree = BzrDir.create_standalone_workingtree('tree')
        import_tar(tree, tar_file)
        self.assertTrue(tree.is_versioned('README'))

    def test_no_crash_with_bzrdir(self):
        tar_file = self.make_tar_with_bzrdir()
        tree = BzrDir.create_standalone_workingtree('tree')
        import_tar(tree, tar_file)
        # So long as it did not crash, that should be ok

    def test_get_archive_type(self):
        self.assertEqual(('tar', None), get_archive_type('foo.tar'))
        self.assertEqual(('zip', None), get_archive_type('foo.zip'))
        self.assertRaises(NotArchiveType, get_archive_type, 'foo.gif')
        self.assertEqual(('tar', 'gz'), get_archive_type('foo.tar.gz'))
        self.assertRaises(NotArchiveType, get_archive_type,
                          'foo.zip.gz')
        self.assertEqual(('tar', 'gz'), get_archive_type('foo.tgz'))
        self.assertEqual(('tar', 'lzma'), get_archive_type('foo.tar.lzma'))
        self.assertEqual(('tar', 'lzma'), get_archive_type('foo.tar.xz'))
        self.assertEqual(('tar', 'bz2'), get_archive_type('foo.tar.bz2'))


class TestWithStuff(TestCaseWithTransport):

    def transform_to_tar(self, tt):
        stream = StringIO()
        export(tt.get_preview_tree(), root='', fileobj=stream, format='tar',
               dest=None)
        return stream

    def get_empty_tt(self):
        b = self.make_repository('foo')
        null_tree = b.revision_tree(_mod_revision.NULL_REVISION)
        tt = transform.TransformPreview(null_tree)
        root = tt.new_directory('', transform.ROOT_PARENT, 'tree-root')
        tt.fixup_new_roots()
        self.addCleanup(tt.finalize)
        return tt

    def test_nonascii_paths(self):
        self.requireFeature(UnicodeFilenameFeature)
        tt = self.get_empty_tt()
        encoded_file = tt.new_file(
            u'\u1234file', tt.root, 'contents', 'new-file')
        encoded_file = tt.new_file(
            'other', tt.root, 'contents', 'other-file')
        tarfile = self.transform_to_tar(tt)
        tarfile.seek(0)
        tree = self.make_branch_and_tree('bar')
        import_tar(tree, tarfile)
        self.assertPathExists(u'bar/\u1234file')
