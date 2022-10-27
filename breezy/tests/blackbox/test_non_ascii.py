# Copyright (C) 2006-2011 Canonical Ltd
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

"""Black-box tests for brz handling non-ascii characters."""

import os
import sys

from breezy import (
    osutils,
    tests,
    urlutils,
    )
from breezy.tests import EncodingAdapter
from breezy.tests.scenarios import load_tests_apply_scenarios


load_tests = load_tests_apply_scenarios


class TestNonAscii(tests.TestCaseWithTransport):
    """Test that brz handles files/committers/etc which are non-ascii."""

    scenarios = EncodingAdapter.encoding_scenarios

    def setUp(self):
        super(TestNonAscii, self).setUp()
        self._check_can_encode_paths()

        self.overrideAttr(osutils, '_cached_user_encoding', self.encoding)
        email = self.info['committer'] + ' <joe@foo.com>'
        self.overrideEnv('BRZ_EMAIL', email)
        self.create_base()

    def run_bzr_decode(self, args, encoding=None, fail=False, retcode=None,
                       working_dir=None):
        """Run brz and decode the output into a particular encoding.

        Returns a string containing the stdout output from bzr.

        :param fail: If true, the operation is expected to fail with
            a UnicodeError.
        """
        if encoding is None:
            encoding = osutils.get_user_encoding()
        try:
            out = self.run_bzr_raw(args, encoding=encoding,
                                   retcode=retcode, working_dir=working_dir)[0]
            return out.decode(encoding)
        except UnicodeError as e:
            if not fail:
                raise
        else:
            # This command, run from the regular command line, will give a
            # traceback to the user.  That's not really good for a situation
            # that can be provoked just by the interaction of their input data
            # and locale, as some of these are.  What would be better?
            if fail:
                self.fail("Expected UnicodeError not raised")

    def _check_OSX_can_roundtrip(self, path, fs_enc=None):
        """Stop the test if it's about to fail or errors out.

        Until we get proper support on OSX for accented paths (in fact, any
        path whose NFD decomposition is different than the NFC one), this is
        the best way to keep test active (as opposed to disabling them
        completely). This is a stop gap. The tests should at least be rewritten
        so that the failing ones are clearly separated from the passing ones.
        """
        if fs_enc is None:
            fs_enc = sys.getfilesystemencoding()
        if sys.platform == 'darwin':
            encoded = path.encode(fs_enc)
            import unicodedata
            normal_thing = unicodedata.normalize('NFD', path)
            mac_encoded = normal_thing.encode(fs_enc)
            if mac_encoded != encoded:
                self.knownFailure(
                    'Unable to roundtrip path %r on OSX filesystem'
                    ' using encoding "%s"'
                    % (path, fs_enc))

    def _check_can_encode_paths(self):
        fs_enc = sys.getfilesystemencoding()
        terminal_enc = osutils.get_terminal_encoding()
        fname = self.info['filename']
        dir_name = self.info['directory']
        for thing in [fname, dir_name]:
            try:
                thing.encode(fs_enc)
            except UnicodeEncodeError:
                raise tests.TestSkipped(
                    'Unable to represent path %r in filesystem encoding "%s"'
                    % (thing, fs_enc))
            try:
                thing.encode(terminal_enc)
            except UnicodeEncodeError:
                raise tests.TestSkipped(
                    'Unable to represent path %r in terminal encoding "%s"'
                    ' (even though it is valid in filesystem encoding "%s")'
                    % (thing, terminal_enc, fs_enc))

    def create_base(self):
        wt = self.make_branch_and_tree('.')
        self.build_tree_contents([('a', b'foo\n')])
        wt.add('a')
        wt.commit('adding a')

        self.build_tree_contents(
            [('b', b'non-ascii \xFF\xFF\xFC\xFB\x00 in b\n')])
        wt.add('b')
        wt.commit(self.info['message'])

        fname = self.info['filename']
        self.build_tree_contents([(fname, b'unicode filename\n')])
        wt.add(fname)
        wt.commit(u'And a unicode file\n')
        self.wt = wt
        # FIXME: We don't check that the add went well, in fact, it doesn't on
        # OSX (when LC_ALL is set correctly) because the added path doesn't
        # match the one used on OSX. But checking here will require more
        # invasive changes than adding the _check_OSX_can_roundtrip(), so I
        # punt for now -- vila 20090702

    def test_status(self):
        self.build_tree_contents(
            [(self.info['filename'], b'changed something\n')])
        txt = self.run_bzr_decode('status')
        self._check_OSX_can_roundtrip(self.info['filename'])
        self.assertEqual(u'modified:\n  %s\n' % (self.info['filename'],), txt)

        txt = self.run_bzr_decode('status', encoding='ascii')
        expected = u'modified:\n  %s\n' % (
            self.info['filename'].encode('ascii', 'replace').decode('ascii'),)
        self.assertEqual(expected, txt)

    def test_cat(self):
        # brz cat shouldn't change the contents
        # using run_brz since that doesn't decode
        txt = self.run_bzr_raw('cat b')[0]
        self.assertEqual(b'non-ascii \xFF\xFF\xFC\xFB\x00 in b\n', txt)

        self._check_OSX_can_roundtrip(self.info['filename'])
        txt = self.run_bzr_raw(['cat', self.info['filename']])[0]
        self.assertEqual(b'unicode filename\n', txt)

    def test_cat_revision(self):
        committer = self.info['committer']
        txt = self.run_bzr_decode('cat-revision -r 1')
        self.assertTrue(committer in txt,
                        'failed to find %r in %r' % (committer, txt))

        msg = self.info['message']
        txt = self.run_bzr_decode('cat-revision -r 2')
        self.assertTrue(msg in txt, 'failed to find %r in %r' % (msg, txt))

    def test_mkdir(self):
        txt = self.run_bzr_decode(['mkdir', self.info['directory']])
        self.assertEqual(u'added %s\n' % self.info['directory'], txt)

        # The text should be garbled, but the command should succeed
        txt = self.run_bzr_raw(['mkdir', self.info['directory'] + '2'],
                               encoding='ascii')[0]
        expected = u'added %s2\n' % (self.info['directory'],)
        expected = expected.encode('ascii', 'replace')
        self.assertEqual(expected, txt)

    def test_relpath(self):
        txt = self.run_bzr_decode(['relpath', self.info['filename']])
        self.assertEqual(self.info['filename'] + '\n', txt)

        self.run_bzr_decode(['relpath', self.info['filename']],
                            encoding='ascii', fail=True)

    def test_inventory(self):
        txt = self.run_bzr_decode('inventory')
        self._check_OSX_can_roundtrip(self.info['filename'])
        self.assertEqual(['a', 'b', self.info['filename']],
                         txt.splitlines())

        # inventory should fail if unable to encode
        self.run_bzr_decode('inventory', encoding='ascii', fail=True)

        # We don't really care about the ids themselves,
        # but the command shouldn't fail
        txt = self.run_bzr_decode('inventory --show-ids')

    def test_revno(self):
        # There isn't a lot to test here, since revno should always
        # be an integer
        self.assertEqual('3\n', self.run_bzr_decode('revno'))
        self.assertEqual('3\n', self.run_bzr_decode('revno', encoding='ascii'))

    def test_revision_info(self):
        self.run_bzr_decode('revision-info -r 1')

        # TODO: jam 20060105 If we support revisions with non-ascii characters,
        # this should be strict and fail.
        self.run_bzr_decode('revision-info -r 1', encoding='ascii')

    def test_mv(self):
        fname1 = self.info['filename']
        fname2 = self.info['filename'] + '2'
        dirname = self.info['directory']

        # fname1 already exists
        self.run_bzr_decode(['mv', 'a', fname1], fail=True)

        txt = self.run_bzr_decode(['mv', 'a', fname2])
        self.assertEqual(u'a => %s\n' % fname2, txt)
        self.assertPathDoesNotExist('a')
        self.assertPathExists(fname2)

        # After 'mv' we need to re-open the working tree
        self.wt = self.wt.controldir.open_workingtree()
        self.wt.commit('renamed to non-ascii')

        os.mkdir(dirname)
        self.wt.add(dirname)
        txt = self.run_bzr_decode(['mv', fname1, fname2, dirname])
        self._check_OSX_can_roundtrip(self.info['filename'])
        self.assertEqual([u'%s => %s/%s' % (fname1, dirname, fname1),
                          u'%s => %s/%s' % (fname2, dirname, fname2)], txt.splitlines())

        # The rename should still succeed
        newpath = u'%s/%s' % (dirname, fname2)
        txt = self.run_bzr_raw(['mv', newpath, 'a'], encoding='ascii')[0]
        self.assertPathExists('a')
        self.assertEqual(newpath.encode('ascii', 'replace') + b' => a\n', txt)

    def test_branch(self):
        # We should be able to branch into a directory that
        # has a unicode name, even if we can't display the name
        self.run_bzr_decode(['branch', u'.', self.info['directory']])
        self.run_bzr_decode(['branch', u'.', self.info['directory'] + '2'],
                            encoding='ascii')

    def test_pull(self):
        # Make sure we can pull from paths that can't be encoded
        dirname1 = self.info['directory']
        dirname2 = self.info['directory'] + '2'
        url1 = urlutils.local_path_to_url(dirname1)
        url2 = urlutils.local_path_to_url(dirname2)
        out_bzrdir = self.wt.controldir.sprout(url1)
        out_bzrdir.sprout(url2)

        self.build_tree_contents(
            [(osutils.pathjoin(dirname1, "a"), b'different text\n')])
        self.wt.commit('mod a')

        txt = self.run_bzr_decode('pull', working_dir=dirname2)

        expected = osutils.pathjoin(osutils.getcwd(), dirname1)
        self.assertEqual(u'Using saved parent location: %s/\n'
                         'No revisions or tags to pull.\n' % (expected,), txt)

        self.build_tree_contents(
            [(osutils.pathjoin(dirname1, 'a'), b'and yet more\n')])
        self.wt.commit(u'modifying a by ' + self.info['committer'])

        # We should be able to pull, even if our encoding is bad
        self.run_bzr_decode('pull --verbose', encoding='ascii',
                            working_dir=dirname2)

    def test_push(self):
        # TODO: Test push to an SFTP location
        # Make sure we can pull from paths that can't be encoded
        # TODO: jam 20060427 For drastically improving performance, we probably
        #       could create a local repository, so it wouldn't have to copy
        #       the files around as much.
        # Note that the tests don't actually fail, but if we don't set this
        # flag, we end up getting "Lock was not Unlocked" warnings

        dirname = self.info['directory']
        self.run_bzr_decode(['push', dirname])

        self.build_tree_contents([('a', b'adding more text\n')])
        self.wt.commit('added some stuff')

        # TODO: check the output text is properly encoded
        self.run_bzr_decode('push')

        self.build_tree_contents(
            [('a', b'and a bit more: \n%s\n' % (dirname.encode('utf-8'),))])

        self.wt.commit('Added some ' + dirname)
        self.run_bzr_decode('push --verbose', encoding='ascii')

        self.run_bzr_decode(['push', '--verbose', dirname + '2'])

        self.run_bzr_decode(['push', '--verbose', dirname + '3'],
                            encoding='ascii')

        self.run_bzr_decode(['push', '--verbose', '--create-prefix',
                             dirname + '4/' + dirname + '5'])
        self.run_bzr_decode(['push', '--verbose', '--create-prefix',
                             dirname + '6/' + dirname + '7'], encoding='ascii')

    def test_renames(self):
        fname = self.info['filename'] + '2'
        self.wt.rename_one('a', fname)
        txt = self.run_bzr_decode('renames')
        self.assertEqual(u'a => %s\n' % fname, txt)

        self.run_bzr_decode('renames', fail=True, encoding='ascii')

    def test_remove(self):
        fname = self.info['filename']
        txt = self.run_bzr_decode(['remove', fname], encoding='ascii')

    def test_remove_verbose(self):
        fname = self.info['filename']
        txt = self.run_bzr_decode(['remove', '--verbose', fname],
                                  encoding='ascii')

    def test_file_id(self):
        fname = self.info['filename']
        txt = self.run_bzr_decode(['file-id', fname])

        # TODO: jam 20060106 We don't support non-ascii file ids yet,
        #       so there is nothing which would fail in ascii encoding
        #       This *should* be retcode=3
        txt = self.run_bzr_decode(['file-id', fname], encoding='ascii')

    def test_file_path(self):
        # Create a directory structure
        fname = self.info['filename']
        dirname = self.info['directory']
        self.build_tree_contents([
            ('base/', ),
            (osutils.pathjoin('base', '%s/' % (dirname,)), )])
        self.wt.add('base')
        self.wt.add('base/' + dirname)
        path = osutils.pathjoin('base', dirname, fname)
        self._check_OSX_can_roundtrip(self.info['filename'])
        self.wt.rename_one(fname, path)
        self.wt.commit('moving things around')

        txt = self.run_bzr_decode(['file-path', path])

        # TODO: jam 20060106 We don't support non-ascii file ids yet,
        #       so there is nothing which would fail in ascii encoding
        #       This *should* be retcode=3
        txt = self.run_bzr_decode(['file-path', path], encoding='ascii')

    def test_revision_history(self):
        # TODO: jam 20060106 We don't support non-ascii revision ids yet,
        #       so there is nothing which would fail in ascii encoding
        txt = self.run_bzr_decode('revision-history')

    def test_ancestry(self):
        # TODO: jam 20060106 We don't support non-ascii revision ids yet,
        #       so there is nothing which would fail in ascii encoding
        txt = self.run_bzr_decode('ancestry')

    def test_diff(self):
        self._check_OSX_can_roundtrip(self.info['filename'])
        # TODO: jam 20060106 diff is a difficult one to test, because it
        #       shouldn't encode the file contents, but it needs some sort
        #       of encoding for the paths, etc which are displayed.
        self.build_tree_contents([(self.info['filename'], b'newline\n')])
        txt = self.run_bzr('diff', retcode=1)[0]

    def test_deleted(self):
        self._check_OSX_can_roundtrip(self.info['filename'])
        fname = self.info['filename']
        os.remove(fname)
        self.wt.remove(fname)

        txt = self.run_bzr_decode('deleted')
        self.assertEqual(fname + '\n', txt)

        txt = self.run_bzr_decode('deleted --show-ids')
        self.assertTrue(txt.startswith(fname))

        # Deleted should fail if cannot decode
        # Because it is giving the exact paths
        # which might be used by a front end
        self.run_bzr_decode('deleted', encoding='ascii', fail=True)

    def test_modified(self):
        fname = self.info['filename']
        self.build_tree_contents([(fname, b'modified\n')])

        txt = self.run_bzr_decode('modified')
        self._check_OSX_can_roundtrip(self.info['filename'])
        self.assertEqual('"' + fname + '"' + '\n', txt)

        self.run_bzr_decode('modified', encoding='ascii', fail=True)

    def test_added(self):
        fname = self.info['filename'] + '2'
        self.build_tree_contents([(fname, b'added\n')])
        self.wt.add(fname)

        txt = self.run_bzr_decode('added')
        self.assertEqual('"' + fname + '"' + '\n', txt)

        self.run_bzr_decode('added', encoding='ascii', fail=True)

    def test_root(self):
        dirname = self.info['directory']
        url = urlutils.local_path_to_url(dirname)
        self.run_bzr_decode('root')

        self.wt.controldir.sprout(url)

        txt = self.run_bzr_decode('root', working_dir=dirname)
        self.assertTrue(txt.endswith(dirname + '\n'))

        txt = self.run_bzr_decode('root', encoding='ascii', fail=True,
                                  working_dir=dirname)

    def test_log(self):
        fname = self.info['filename']

        txt = self.run_bzr_decode('log')
        self.assertNotEqual(-1, txt.find(self.info['committer']))
        self.assertNotEqual(-1, txt.find(self.info['message']))

        txt = self.run_bzr_decode('log --verbose')
        # FIXME: iso-8859-2 test shouldn't be skipped here --vila 20090702
        self._check_OSX_can_roundtrip(self.info['filename'])
        self.assertNotEqual(-1, txt.find(fname))

        # Make sure log doesn't fail even if we can't write out
        txt = self.run_bzr_raw('log --verbose', encoding='ascii')[0]
        self.assertNotEqual(-1, txt.find(fname.encode('ascii', 'replace')))

    def test_touching_revisions(self):
        fname = self.info['filename']
        txt = self.run_bzr_decode(['touching-revisions', fname])
        self._check_OSX_can_roundtrip(self.info['filename'])
        self.assertEqual(u'     3 added %s\n' % (fname,), txt)

        fname2 = self.info['filename'] + '2'
        self.wt.rename_one(fname, fname2)
        self.wt.commit(u'Renamed %s => %s' % (fname, fname2))

        txt = self.run_bzr_decode(['touching-revisions', fname2])
        expected_txt = (u'     3 added %s\n'
                        u'     4 renamed %s => %s\n'
                        % (fname, fname, fname2))
        self.assertEqual(expected_txt, txt)

        self.run_bzr_decode(['touching-revisions', fname2], encoding='ascii',
                            fail=True)

    def test_ls(self):
        txt = self.run_bzr_decode('ls')
        self.assertEqual(sorted(['a', 'b', self.info['filename']]),
                         sorted(txt.splitlines()))
        txt = self.run_bzr_decode('ls --null')
        self.assertEqual(sorted(['', 'a', 'b', self.info['filename']]),
                         sorted(txt.split('\0')))

        txt = self.run_bzr_decode('ls', encoding='ascii', fail=True)
        txt = self.run_bzr_decode('ls --null', encoding='ascii', fail=True)

    def test_unknowns(self):
        fname = self.info['filename'] + '2'
        self.build_tree_contents([(fname, b'unknown\n')])

        # TODO: jam 20060112 brz unknowns is the only one which
        #       quotes paths do we really want it to?
        #       awilkins 20080521 added and modified do it now as well
        txt = self.run_bzr_decode('unknowns')
        self._check_OSX_can_roundtrip(self.info['filename'])
        self.assertEqual(u'"%s"\n' % (fname,), txt)

        self.run_bzr_decode('unknowns', encoding='ascii', fail=True)

    def test_ignore(self):
        fname2 = self.info['filename'] + '2.txt'
        self.build_tree_contents([(fname2, b'ignored\n')])

        def check_unknowns(expected):
            self.assertEqual(expected, list(self.wt.unknowns()))

        self._check_OSX_can_roundtrip(self.info['filename'])
        check_unknowns([fname2])

        self.run_bzr_decode(['ignore', './' + fname2])
        check_unknowns([])

        fname3 = self.info['filename'] + '3.txt'
        self.build_tree_contents([(fname3, b'unknown 3\n')])
        check_unknowns([fname3])

        # Ignore should not care what the encoding is
        # (right now it doesn't print anything)
        self.run_bzr_decode(['ignore', fname3], encoding='ascii')
        check_unknowns([])

        # Now try a wildcard match
        fname4 = self.info['filename'] + '4.txt'
        self.build_tree_contents([(fname4, b'unknown 4\n')])
        self.run_bzr_decode('ignore *.txt')
        check_unknowns([])

        # and a different wildcard that matches everything
        os.remove('.bzrignore')
        self.run_bzr_decode(['ignore', self.info['filename'] + '*'])
        check_unknowns([])

    def test_missing(self):
        # create empty tree as reference for missing
        self.make_branch_and_tree('empty-tree')

        msg = self.info['message']

        txt = self.run_bzr_decode('missing empty-tree')
        self.assertNotEqual(-1, txt.find(self.info['committer']))
        self.assertNotEqual(-1, txt.find(msg))

        # Make sure missing doesn't fail even if we can't write out
        txt = self.run_bzr_raw('missing empty-tree', encoding='ascii',
                               retcode=1)[0]
        self.assertNotEqual(-1, txt.find(msg.encode('ascii', 'replace')))

    def test_info(self):
        self.run_bzr_decode(['branch', u'.', self.info['directory']])
        self.run_bzr_decode(['info', self.info['directory']])
        self.run_bzr_decode(['info', self.info['directory']],
                            encoding='ascii')

    def test_ignored(self):
        fname = self.info['filename'] + '1.txt'
        self.build_tree_contents([(fname, b'ignored\n')])
        self.run_bzr(['ignore', fname])
        txt = self.run_bzr_decode(['ignored'])
        self.assertEqual(txt, '%-50s %s\n' % (fname, fname))
        txt = self.run_bzr_decode(['ignored'], encoding='ascii')
        fname = fname.encode('ascii', 'replace').decode('ascii')
        self.assertEqual(txt, '%-50s %s\n' % (fname, fname))
