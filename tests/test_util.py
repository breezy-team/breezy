#    test_util.py -- Testsuite for builddeb util.py
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

import bz2
import gzip
import hashlib
import os
import shutil
import tarfile

from debian.changelog import Changelog, Version
from debmutate.changelog import strip_changelog_message

from ..config import (
    BUILD_TYPE_MERGE,
    BUILD_TYPE_NATIVE,
    BUILD_TYPE_NORMAL,
    )
from . import (
    LzmaFeature,
    SourcePackageBuilder,
    TestCaseInTempDir,
    TestCaseWithTransport,
    )
from ..util import (
    AddChangelogError,
    InconsistentSourceFormatError,
    NoPreviousUpload,
    NoSuchFile,
    changelog_find_previous_upload,
    component_from_orig_tarball,
    dget,
    dget_changes,
    extract_orig_tarballs,
    find_bugs_fixed,
    find_changelog,
    find_extra_authors,
    find_thanks,
    get_files_excluded,
    get_commit_info_from_changelog,
    guess_build_type,
    lookup_distribution,
    move_file_if_different,
    get_parent_dir,
    recursive_copy,
    safe_decode,
    suite_to_distribution,
    tarball_name,
    tree_contains_upstream_source,
    tree_get_source_format,
    write_if_different,
    MissingChangelogError,
    )

from .... import errors as bzr_errors
from six import text_type
from ....tests import (
    TestCase,
    )
from ....tests.features import (
    SymlinkFeature,
    ModuleAvailableFeature,
    )


class RecursiveCopyTests(TestCaseInTempDir):

    def test_recursive_copy(self):
        os.mkdir('a')
        os.mkdir('b')
        os.mkdir('c')
        os.mkdir('a/d')
        os.mkdir('a/d/e')
        with open('a/f', 'w') as f:
            f.write('f')
        os.mkdir('b/g')
        recursive_copy('a', 'b')
        self.assertPathExists('a')
        self.assertPathExists('b')
        self.assertPathExists('c')
        self.assertPathExists('b/d')
        self.assertPathExists('b/d/e')
        self.assertPathExists('b/f')
        self.assertPathExists('a/d')
        self.assertPathExists('a/d/e')
        self.assertPathExists('a/f')

    def test_recursive_copy_symlink(self):
        os.mkdir('a')
        os.symlink('c', 'a/link')
        os.mkdir('b')
        recursive_copy('a', 'b')
        self.assertPathExists('b')
        self.assertPathExists('b/link')
        self.assertEqual('c', os.readlink('b/link'))


class SafeDecodeTests(TestCase):

    def assertSafeDecode(self, expected, val):
        self.assertEqual(expected, safe_decode(val))

    def test_utf8(self):
        self.assertSafeDecode(u'ascii', 'ascii')
        self.assertSafeDecode(u'\xe7', b'\xc3\xa7')

    def test_iso_8859_1(self):
        self.assertSafeDecode(u'\xe7', b'\xe7')


cl_block1 = """\
bzr-builddeb (0.17) unstable; urgency=low

  [ James Westby ]
  * Pass max_blocks=1 when constructing changelogs as that is all that is
    needed currently.

 -- James Westby <jw+debian@jameswestby.net>  Sun, 17 Jun 2007 18:48:28 +0100

"""


class FindChangelogTests(TestCaseWithTransport):

    def write_changelog(self, filename):
        f = open(filename, 'w')
        try:
            f.write(cl_block1)
            f.write("""\
bzr-builddeb (0.16.2) unstable; urgency=low

  * loosen the dependency on bzr. bzr-builddeb seems to be not be broken
    by bzr version 0.17, so remove the upper bound of the dependency.

 -- Reinhard Tartler <siretart@tauware.de>  Tue, 12 Jun 2007 19:45:38 +0100
""")
        finally:
            f.close()

    def test_find_changelog_std(self):
        tree = self.make_branch_and_tree('.')
        os.mkdir('debian')
        self.write_changelog('debian/changelog')
        tree.add(['debian', 'debian/changelog'])
        (cl, lq) = find_changelog(tree, merge=False)
        self.assertEqual(str(cl), cl_block1)
        self.assertEqual(lq, False)

    def test_find_changelog_merge(self):
        tree = self.make_branch_and_tree('.')
        os.mkdir('debian')
        self.write_changelog('debian/changelog')
        tree.add(['debian', 'debian/changelog'])
        (cl, lq) = find_changelog(tree, merge=True)
        self.assertEqual(str(cl), cl_block1)
        self.assertEqual(lq, False)

    def test_find_changelog_merge_lq(self):
        tree = self.make_branch_and_tree('.')
        self.write_changelog('changelog')
        tree.add(['changelog'])
        (cl, lq) = find_changelog(tree, merge=True)
        self.assertEqual(str(cl), cl_block1)
        self.assertEqual(lq, True)

    def test_find_changelog_lq_unversioned_debian_symlink(self):
        # LarstiQ mode, but with an unversioned "debian" -> "." symlink.
        # Bug 619295
        try:
            self.requireFeature(SymlinkFeature(self.test_dir))
        except TypeError:  # brz < 3.2
            self.requireFeature(SymlinkFeature)
        tree = self.make_branch_and_tree('.')
        self.write_changelog('changelog')
        tree.add(['changelog'])
        os.symlink('.', 'debian')
        self.assertRaises(AddChangelogError, find_changelog, tree, merge=True)

    def test_find_changelog_nomerge_lq(self):
        tree = self.make_branch_and_tree('.')
        self.write_changelog('changelog')
        tree.add(['changelog'])
        self.assertRaises(
            MissingChangelogError, find_changelog, tree, merge=False)

    def test_find_changelog_nochangelog(self):
        tree = self.make_branch_and_tree('.')
        self.write_changelog('changelog')
        self.assertRaises(
            MissingChangelogError, find_changelog, tree, merge=False)

    def test_find_changelog_nochangelog_merge(self):
        tree = self.make_branch_and_tree('.')
        self.assertRaises(
            MissingChangelogError, find_changelog, tree, merge=True)

    def test_find_changelog_symlink(self):
        """When there was a symlink debian -> . then the code used to break"""
        try:
            self.requireFeature(SymlinkFeature(self.test_dir))
        except TypeError:  # brz < 3.2
            self.requireFeature(SymlinkFeature)
        tree = self.make_branch_and_tree('.')
        self.write_changelog('changelog')
        tree.add(['changelog'])
        os.symlink('.', 'debian')
        tree.add(['debian'])
        (cl, lq) = find_changelog(tree, merge=True)
        self.assertEqual(str(cl), cl_block1)
        self.assertEqual(lq, True)

    def test_find_changelog_symlink_naughty(self):
        tree = self.make_branch_and_tree('.')
        os.mkdir('debian')
        self.write_changelog('debian/changelog')
        with open('changelog', 'w') as f:
            f.write('Naughty, naughty')
        tree.add(['changelog', 'debian', 'debian/changelog'])
        (cl, lq) = find_changelog(tree, merge=True)
        self.assertEqual(str(cl), cl_block1)
        self.assertEqual(lq, False)

    def test_changelog_not_added(self):
        tree = self.make_branch_and_tree('.')
        os.mkdir('debian')
        self.write_changelog('debian/changelog')
        self.assertRaises(AddChangelogError, find_changelog, tree, merge=False)


class TarballNameTests(TestCase):

    def test_tarball_name(self):
        self.assertEqual(
            tarball_name("package", "0.1", None),
            "package_0.1.orig.tar.gz")
        self.assertEqual(
            tarball_name("package", Version("0.1"), None),
            "package_0.1.orig.tar.gz")
        self.assertEqual(
            tarball_name("package", Version("0.1"), None, format='bz2'),
            "package_0.1.orig.tar.bz2")
        self.assertEqual(
            tarball_name("package", Version("0.1"), None, format='xz'),
            "package_0.1.orig.tar.xz")
        self.assertEqual(
            tarball_name("package", Version("0.1"), "la", format='xz'),
            "package_0.1.orig-la.tar.xz")


DistroInfoFeature = ModuleAvailableFeature('distro_info')


class SuiteToDistributionTests(TestCase):

    _test_needs_features = [DistroInfoFeature]

    def _do_lookup(self, target):
        return suite_to_distribution(target)

    def lookup_ubuntu(self, target):
        self.assertEqual(self._do_lookup(target), 'ubuntu')

    def lookup_debian(self, target):
        self.assertEqual(self._do_lookup(target), 'debian')

    def lookup_kali(self, target):
        self.assertEqual(self._do_lookup(target), 'kali')

    def lookup_other(self, target):
        self.assertEqual(self._do_lookup(target), None)

    def test_lookup_ubuntu(self):
        self.lookup_ubuntu('intrepid')
        self.lookup_ubuntu('hardy-proposed')
        self.lookup_ubuntu('gutsy-updates')
        self.lookup_ubuntu('feisty-security')
        self.lookup_ubuntu('dapper-backports')

    def test_lookup_debian(self):
        self.lookup_debian('unstable')
        self.lookup_debian('stable-security')
        self.lookup_debian('testing-proposed-updates')
        self.lookup_debian('etch-backports')

    def test_lookup_kali(self):
        self.lookup_kali('kali-dev')
        self.lookup_kali('kali-rolling')
        self.lookup_kali('kali')

    def test_lookup_other(self):
        self.lookup_other('not-a-target')
        self.lookup_other("debian")
        self.lookup_other("ubuntu")


class LookupDistributionTests(SuiteToDistributionTests):

    _test_needs_features = [DistroInfoFeature]

    def _do_lookup(self, target):
        return lookup_distribution(target)

    def test_lookup_other(self):
        self.lookup_other('not-a-target')
        self.lookup_debian("debian")
        self.lookup_ubuntu("ubuntu")
        self.lookup_ubuntu("Ubuntu")


class MoveFileTests(TestCaseInTempDir):

    def test_move_file_non_extant(self):
        self.build_tree(['a'])
        move_file_if_different('a', 'b', None)
        self.assertPathDoesNotExist('a')
        self.assertPathExists('b')

    def test_move_file_samefile(self):
        self.build_tree(['a'])
        move_file_if_different('a', 'a', None)
        self.assertPathExists('a')

    def test_move_file_same_md5(self):
        self.build_tree(['a'])
        md5sum = hashlib.md5()
        with open('a', 'rb') as f:
            md5sum.update(f.read())
        shutil.copy('a', 'b')
        move_file_if_different('a', 'b', md5sum.hexdigest())
        self.assertPathExists('a')
        self.assertPathExists('b')

    def test_move_file_diff_md5(self):
        self.build_tree(['a', 'b'])
        md5sum = hashlib.md5()
        with open('a', 'rb') as f:
            md5sum.update(f.read())
        a_hexdigest = md5sum.hexdigest()
        md5sum = hashlib.md5()
        with open('b', 'rb') as f:
            md5sum.update(f.read())
        b_hexdigest = md5sum.hexdigest()
        self.assertNotEqual(a_hexdigest, b_hexdigest)
        move_file_if_different('a', 'b', a_hexdigest)
        self.assertPathDoesNotExist('a')
        self.assertPathExists('b')
        md5sum = hashlib.md5()
        with open('b', 'rb') as f:
            md5sum.update(f.read())
        self.assertEqual(md5sum.hexdigest(), a_hexdigest)


class WriteFileTests(TestCaseInTempDir):

    def test_write_non_extant(self):
        write_if_different(b"foo", 'a')
        self.assertPathExists('a')
        self.check_file_contents('a', b"foo")

    def test_write_file_same(self):
        write_if_different(b"foo", 'a')
        self.assertPathExists('a')
        self.check_file_contents('a', b"foo")
        write_if_different(b"foo", 'a')
        self.assertPathExists('a')
        self.check_file_contents('a', b"foo")

    def test_write_file_different(self):
        write_if_different(b"foo", 'a')
        self.assertPathExists('a')
        self.check_file_contents('a', b"foo")
        write_if_different(b"bar", 'a')
        self.assertPathExists('a')
        self.check_file_contents('a', b"bar")


class DgetTests(TestCaseWithTransport):

    def test_dget_local(self):
        builder = SourcePackageBuilder("package", Version("0.1-1"))
        builder.add_upstream_file("foo")
        builder.add_default_control()
        builder.build()
        self.build_tree(["target/"])
        dget(builder.dsc_name(), 'target')
        self.assertPathExists(os.path.join("target", builder.dsc_name()))
        self.assertPathExists(os.path.join("target", builder.tar_name()))
        self.assertPathExists(os.path.join("target", builder.diff_name()))

    def test_dget_transport(self):
        builder = SourcePackageBuilder("package", Version("0.1-1"))
        builder.add_upstream_file("foo")
        builder.add_default_control()
        builder.build()
        self.build_tree(["target/"])
        dget(self.get_url(builder.dsc_name()), 'target')
        self.assertPathExists(os.path.join("target", builder.dsc_name()))
        self.assertPathExists(os.path.join("target", builder.tar_name()))
        self.assertPathExists(os.path.join("target", builder.diff_name()))

    def test_dget_missing_dsc(self):
        builder = SourcePackageBuilder("package", Version("0.1-1"))
        builder.add_upstream_file("foo")
        builder.add_default_control()
        # No builder.build()
        self.build_tree(["target/"])
        self.assertRaises(
            NoSuchFile, dget,
            self.get_url(builder.dsc_name()), 'target')

    def test_dget_missing_file(self):
        builder = SourcePackageBuilder("package", Version("0.1-1"))
        builder.add_upstream_file("foo")
        builder.add_default_control()
        builder.build()
        os.unlink(builder.tar_name())
        self.build_tree(["target/"])
        self.assertRaises(
            NoSuchFile, dget,
            self.get_url(builder.dsc_name()), 'target')

    def test_dget_missing_target(self):
        builder = SourcePackageBuilder("package", Version("0.1-1"))
        builder.add_upstream_file("foo")
        builder.add_default_control()
        builder.build()
        self.assertRaises(
            bzr_errors.NotADirectory, dget,
            self.get_url(builder.dsc_name()), 'target')

    def test_dget_changes(self):
        builder = SourcePackageBuilder("package", Version("0.1-1"))
        builder.add_upstream_file("foo")
        builder.add_default_control()
        builder.build()
        self.build_tree(["target/"])
        dget_changes(builder.changes_name(), 'target')
        self.assertPathExists(os.path.join("target", builder.dsc_name()))
        self.assertPathExists(os.path.join("target", builder.tar_name()))
        self.assertPathExists(os.path.join("target", builder.diff_name()))
        self.assertPathExists(os.path.join("target", builder.changes_name()))


class ParentDirTests(TestCase):

    def test_get_parent_dir(self):
        self.assertEqual(get_parent_dir("a"), '')
        self.assertEqual(get_parent_dir("a/"), '')
        self.assertEqual(get_parent_dir("a/b"), 'a')
        self.assertEqual(get_parent_dir("a/b/"), 'a')
        self.assertEqual(get_parent_dir("a/b/c"), 'a/b')


class ChangelogInfoTests(TestCaseWithTransport):

    def test_find_extra_authors_none(self):
        changes = ["  * Do foo", "  * Do bar"]
        authors = find_extra_authors(changes)
        self.assertEqual([], authors)

    def test_find_extra_authors(self):
        changes = ["  * Do foo", "", "  [ A. Hacker ]", "  * Do bar", "",
                   "  [ B. Hacker ]", "  [ A. Hacker}"]
        authors = find_extra_authors(changes)
        self.assertEqual([u"A. Hacker", u"B. Hacker"], authors)
        self.assertEqual([text_type]*len(authors), list(map(type, authors)))

    def test_find_extra_authors_utf8(self):
        changes = [u"  * Do foo", u"", "  [ \xe1. Hacker ]", "  * Do bar", "",
                   u"  [ \xe7. Hacker ]", "  [ A. Hacker}"]
        authors = find_extra_authors(changes)
        self.assertEqual([u"\xe1. Hacker", u"\xe7. Hacker"], authors)
        self.assertEqual([text_type]*len(authors), list(map(type, authors)))

    def test_find_extra_authors_iso_8859_1(self):
        # We try to treat lines as utf-8, but if that fails to decode, we fall
        # back to iso-8859-1
        changes = ["  * Do foo", "", "  [ \xe1. Hacker ]", "  * Do bar", "",
                   "  [ \xe7. Hacker ]", "  [ A. Hacker}"]
        authors = find_extra_authors(changes)
        self.assertEqual([u"\xe1. Hacker", u"\xe7. Hacker"], authors)
        self.assertEqual([text_type]*len(authors), list(map(type, authors)))

    def test_find_extra_authors_no_changes(self):
        authors = find_extra_authors([])
        self.assertEqual([], authors)

    def assert_thanks_is(self, changes, expected_thanks):
        thanks = find_thanks(changes)
        self.assertEqual(expected_thanks, thanks)
        self.assertEqual([text_type]*len(thanks), list(map(type, thanks)))

    def test_find_thanks_no_changes(self):
        self.assert_thanks_is([], [])

    def test_find_thanks_none(self):
        changes = ["  * Do foo", "  * Do bar"]
        self.assert_thanks_is(changes, [])

    def test_find_thanks(self):
        changes = ["  * Thanks to A. Hacker"]
        self.assert_thanks_is(changes, [u"A. Hacker"])
        changes = ["  * Thanks to James A. Hacker"]
        self.assert_thanks_is(changes, [u"James A. Hacker"])
        changes = ["  * Thankyou to B. Hacker"]
        self.assert_thanks_is(changes, [u"B. Hacker"])
        changes = ["  * thanks to A. Hacker"]
        self.assert_thanks_is(changes, [u"A. Hacker"])
        changes = ["  * thankyou to B. Hacker"]
        self.assert_thanks_is(changes, [u"B. Hacker"])
        changes = ["  * Thanks A. Hacker"]
        self.assert_thanks_is(changes, [u"A. Hacker"])
        changes = ["  * Thankyou B.  Hacker"]
        self.assert_thanks_is(changes, [u"B. Hacker"])
        changes = ["  * Thanks to Mark A. Super-Hacker"]
        self.assert_thanks_is(changes, [u"Mark A. Super-Hacker"])
        changes = ["  * Thanks to A. Hacker <ahacker@example.com>"]
        self.assert_thanks_is(changes, [u"A. Hacker <ahacker@example.com>"])
        changes = [u"  * Thanks to Adeodato Sim\xc3\xb3"]
        self.assert_thanks_is(changes, [u"Adeodato Sim\xc3\xb3"])
        changes = [u"  * Thanks to \xc1deodato Sim\xc3\xb3"]
        self.assert_thanks_is(changes, [u"\xc1deodato Sim\xc3\xb3"])

    def test_find_bugs_fixed_no_changes(self):
        self.assertEqual([], find_bugs_fixed([], None, _lplib=MockLaunchpad()))

    def test_find_bugs_fixed_none(self):
        changes = ["  * Do foo", "  * Do bar"]
        bugs = find_bugs_fixed(changes, None, _lplib=MockLaunchpad())
        self.assertEqual([], bugs)

    def test_find_bugs_fixed_debian(self):
        wt = self.make_branch_and_tree(".")
        changes = ["  * Closes: #12345, 56789", "  * closes:bug45678"]
        bugs = find_bugs_fixed(changes, wt.branch, _lplib=MockLaunchpad())
        self.assertEqual(
            ["http://bugs.debian.org/12345 fixed",
             "http://bugs.debian.org/56789 fixed",
             "http://bugs.debian.org/45678 fixed"], bugs)

    def test_find_bugs_fixed_debian_with_ubuntu_links(self):
        wt = self.make_branch_and_tree(".")
        changes = ["  * Closes: #12345", "  * closes:bug45678"]
        lplib = MockLaunchpad(
            debian_bug_to_ubuntu_bugs={
                "12345": ("998877", "987654"),
                "45678": ("87654",)})
        bugs = find_bugs_fixed(changes, wt.branch, _lplib=lplib)
        self.assertEqual([], lplib.ubuntu_bug_lookups)
        self.assertEqual(["12345", "45678"], lplib.debian_bug_lookups)
        self.assertEqual(
            ["http://bugs.debian.org/12345 fixed",
             "http://bugs.debian.org/45678 fixed",
             "https://launchpad.net/bugs/87654 fixed"], bugs)

    def test_find_bugs_fixed_lp(self):
        wt = self.make_branch_and_tree(".")
        changes = ["  * LP: #12345,#56789", "  * lp:  #45678"]
        bugs = find_bugs_fixed(changes, wt.branch, _lplib=MockLaunchpad())
        self.assertEqual(
            ["https://launchpad.net/bugs/12345 fixed",
             "https://launchpad.net/bugs/56789 fixed",
             "https://launchpad.net/bugs/45678 fixed"], bugs)

    def test_find_bugs_fixed_lp_with_debian_links(self):
        wt = self.make_branch_and_tree(".")
        changes = ["  * LP: #12345", "  * lp:  #45678"]
        lplib = MockLaunchpad(
            ubuntu_bug_to_debian_bugs={
                "12345": ("998877", "987654"), "45678": ("87654",)})
        bugs = find_bugs_fixed(changes, wt.branch, _lplib=lplib)
        self.assertEqual([], lplib.debian_bug_lookups)
        self.assertEqual(["12345", "45678"], lplib.ubuntu_bug_lookups)
        self.assertEqual(
            ["https://launchpad.net/bugs/12345 fixed",
             "https://launchpad.net/bugs/45678 fixed",
             "http://bugs.debian.org/87654 fixed"], bugs)

    def test_get_commit_info_none(self):
        wt = self.make_branch_and_tree(".")
        changelog = Changelog()
        message, authors, thanks, bugs = get_commit_info_from_changelog(
            changelog, wt.branch, _lplib=MockLaunchpad())
        self.assertEqual(None, message)
        self.assertEqual([], authors)
        self.assertEqual([], thanks)
        self.assertEqual([], bugs)

    def test_get_commit_message_info(self):
        wt = self.make_branch_and_tree(".")
        changelog = Changelog()
        changes = ["  [ A. Hacker ]", "  * First change, LP: #12345",
                   "  * Second change, thanks to B. Hacker"]
        author = "J. Maintainer <maint@example.com"
        changelog.new_block(changes=changes, author=author)
        message, authors, thanks, bugs = get_commit_info_from_changelog(
            changelog, wt.branch, _lplib=MockLaunchpad())
        self.assertEqual("\n".join(strip_changelog_message(changes)), message)
        self.assertEqual([author]+find_extra_authors(changes), authors)
        self.assertEqual(text_type, type(authors[0]))
        self.assertEqual(find_thanks(changes), thanks)
        self.assertEqual(find_bugs_fixed(
            changes, wt.branch, _lplib=MockLaunchpad()), bugs)

    def assertUnicodeCommitInfo(self, changes):
        wt = self.make_branch_and_tree(".")
        changelog = Changelog()
        author = "J. Maintainer <maint@example.com>"
        changelog.new_block(changes=changes, author=author)
        message, authors, thanks, bugs = get_commit_info_from_changelog(
            changelog, wt.branch, _lplib=MockLaunchpad())
        self.assertEqual(u'[ \xc1. Hacker ]\n'
                         u'* First ch\xe1nge, LP: #12345\n'
                         u'* Second change, thanks to \xde. Hacker',
                         message)
        self.assertEqual([author, u'\xc1. Hacker'], authors)
        self.assertEqual(text_type, type(authors[0]))
        self.assertEqual([u'\xde. Hacker'], thanks)
        self.assertEqual(['https://launchpad.net/bugs/12345 fixed'], bugs)

    def test_get_commit_info_unicode(self):
        changes = [u"  [ \xc1. Hacker ]",
                   u"  * First ch\xe1nge, LP: #12345",
                   u"  * Second change, thanks to \xde. Hacker"]
        self.assertUnicodeCommitInfo(changes)


class MockLaunchpad(object):

    def __init__(self, debian_bug_to_ubuntu_bugs={},
                 ubuntu_bug_to_debian_bugs={}):
        self.debian_bug_to_ubuntu_bugs = debian_bug_to_ubuntu_bugs
        self.ubuntu_bug_to_debian_bugs = ubuntu_bug_to_debian_bugs
        self.debian_bug_lookups = []
        self.ubuntu_bug_lookups = []

    def ubuntu_bugs_for_debian_bug(self, debian_bug):
        self.debian_bug_lookups.append(debian_bug)
        try:
            return self.debian_bug_to_ubuntu_bugs[debian_bug]
        except KeyError:
            return []

    def debian_bugs_for_ubuntu_bug(self, ubuntu_bug):
        self.ubuntu_bug_lookups.append(ubuntu_bug)
        try:
            return self.ubuntu_bug_to_debian_bugs[ubuntu_bug]
        except KeyError:
            return []


class FindPreviousUploadTests(TestCase):

    def make_changelog(self, versions_and_distributions):
        cl = Changelog()
        changes = ["  [ A. Hacker ]", "  * Something"]
        author = "J. Maintainer <maint@example.com>"
        for version, distro in versions_and_distributions:
            cl.new_block(changes=changes, author=author,
                         distributions=distro, version=version)
        return cl

    def test_find_previous_upload_debian(self):
        cl = self.make_changelog(
            [("0.1-1", "unstable"),
             ("0.1-2", "unstable")])
        self.assertEqual(Version("0.1-1"), changelog_find_previous_upload(cl))
        cl = self.make_changelog(
            [("0.1-1", "unstable"),
             ("0.1-1.1", "stable-security"), ("0.1-2", "unstable")])
        self.assertEqual(Version("0.1-1"), changelog_find_previous_upload(cl))

    def test_find_previous_upload_ubuntu(self):
        cl = self.make_changelog(
            [("0.1-1", "lucid"),
             ("0.1-2", "lucid")])
        self.assertEqual(Version("0.1-1"), changelog_find_previous_upload(cl))
        cl = self.make_changelog(
            [("0.1-1", "lucid"),
             ("0.1-1.1", "unstable"), ("0.1-2", "maverick")])
        self.requireFeature(DistroInfoFeature)
        self.assertEqual(
                Version("0.1-1"), changelog_find_previous_upload(cl))

    def test_find_previous_upload_ubuntu_pocket(self):
        cl = self.make_changelog(
            [("0.1-1", "lucid-updates"),
             ("0.1-2", "lucid-updates")])
        self.assertEqual(Version("0.1-1"), changelog_find_previous_upload(cl))

    def test_find_previous_upload_unknown(self):
        cl = self.make_changelog(
            [("0.1-1", "lucid"),
             ("0.1-2", "dunno")])
        self.assertRaises(NoPreviousUpload, changelog_find_previous_upload, cl)

    def test_find_previous_upload_missing(self):
        cl = self.make_changelog(
            [("0.1-1", "unstable"),
             ("0.1-2", "lucid")])
        self.assertRaises(NoPreviousUpload, changelog_find_previous_upload, cl)
        cl = self.make_changelog([("0.1-1", "unstable")])
        self.assertRaises(NoPreviousUpload, changelog_find_previous_upload, cl)

    def test_find_previous_upload_unreleased(self):
        cl = self.make_changelog(
            [("0.1-1", "unstable"),
             ("0.1-2", "UNRELEASED")])
        self.assertEqual(Version("0.1-1"), changelog_find_previous_upload(cl))


class SourceFormatTests(TestCaseWithTransport):

    def test_no_source_format_file(self):
        tree = self.make_branch_and_tree('.')
        self.assertEquals("1.0", tree_get_source_format(tree))

    def test_source_format_newline(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree_contents(
            [("debian/", ), ("debian/source/",),
             ("debian/source/format", "3.0 (native)\n")])
        tree.add(["debian", "debian/source", "debian/source/format"])
        self.assertEquals("3.0 (native)", tree_get_source_format(tree))

    def test_source_format(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree_contents(
            [("debian/",), ("debian/source/",),
             ("debian/source/format", "3.0 (quilt)")])
        tree.add(["debian", "debian/source", "debian/source/format"])
        self.assertEquals("3.0 (quilt)", tree_get_source_format(tree))

    def test_source_format_file_unversioned(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree_contents(
            [("debian/",), ("debian/source/",),
             ("debian/source/format", "3.0 (quilt)")])
        self.assertEquals("3.0 (quilt)", tree_get_source_format(tree))


class GuessBuildTypeTests(TestCaseWithTransport):
    """Tests for guess_build_type."""

    def writeVersionFile(self, tree, format_string):
        """Write a Debian source format file.

        :param tree: Tree to write to.
        :param format_string: Format string to write.
        """
        self.build_tree_contents(
            [("debian/",), ("debian/source/",),
             ("debian/source/format", format_string)])
        tree.add(["debian", "debian/source", "debian/source/format"])

    def test_normal_source_format(self):
        # Normal source format -> NORMAL
        tree = self.make_branch_and_tree('.')
        self.writeVersionFile(tree, "3.0 (quilt)")
        self.assertEquals(
            BUILD_TYPE_NORMAL,
            guess_build_type(tree, None, contains_upstream_source=True))

    def test_normal_source_format_merge(self):
        # Normal source format without upstream source -> MERGE
        tree = self.make_branch_and_tree('.')
        self.writeVersionFile(tree, "3.0 (quilt)")
        self.assertEquals(
            BUILD_TYPE_MERGE,
            guess_build_type(tree, None, contains_upstream_source=False))

    def test_native_source_format(self):
        # Native source format -> NATIVE
        tree = self.make_branch_and_tree('.')
        self.writeVersionFile(tree, "3.0 (native)")
        self.assertEquals(
            BUILD_TYPE_NATIVE,
            guess_build_type(tree, None, contains_upstream_source=True))

    def test_prev_version_native(self):
        # Native package version -> NATIVE
        tree = self.make_branch_and_tree('.')
        self.assertEquals(
            BUILD_TYPE_NATIVE,
            guess_build_type(
                tree, Version("1.0"), contains_upstream_source=True))

    def test_empty(self):
        # Empty tree and a non-native package -> NORMAL
        tree = self.make_branch_and_tree('.')
        self.assertEquals(
            BUILD_TYPE_NORMAL,
            guess_build_type(
                tree, Version("1.0-1"), contains_upstream_source=None))

    def test_no_upstream_source(self):
        # No upstream source code and a non-native package -> MERGE
        tree = self.make_branch_and_tree('.')
        tree.mkdir("debian")
        self.assertEquals(
            BUILD_TYPE_MERGE,
            guess_build_type(
                tree, Version("1.0-1"), contains_upstream_source=False))

    def test_default(self):
        # Upstream source code and a non-native package -> NORMAL
        tree = self.make_branch_and_tree('.')
        self.assertEquals(
            BUILD_TYPE_NORMAL,
            guess_build_type(
                tree, Version("1.0-1"), contains_upstream_source=True))

    def test_inconsistent(self):
        # If version string and source format disagree on whether the package
        # is native, raise an exception.
        tree = self.make_branch_and_tree('.')
        self.writeVersionFile(tree, "3.0 (quilt)")
        e = self.assertRaises(
            InconsistentSourceFormatError, guess_build_type, tree,
            Version("1.0"), contains_upstream_source=True)
        self.assertEquals(
            "Inconsistency between source format and version: "
            "version 1.0 is native, format '3.0 (quilt)' is not native.",
            str(e))


class TestExtractOrigTarballs(TestCaseInTempDir):

    def create_tarball(self, package, version, compression, part=None):
        basedir = "%s-%s" % (package, version)
        os.mkdir(basedir)
        try:
            f = open(os.path.join(basedir, "README"), 'w')
            try:
                f.write("Hi\n")
            finally:
                f.close()
            prefix = "%s_%s.orig" % (package, version)
            if part is not None:
                prefix += "-%s" % part
            tar_path = os.path.abspath(prefix + ".tar." + compression)
            if compression == "gz":
                f = gzip.GzipFile(tar_path, "w")
            elif compression == "bz2":
                f = bz2.BZ2File(tar_path, "w")
            elif compression == "xz":
                import lzma
                f = lzma.LZMAFile(tar_path, "w")
            else:
                raise AssertionError(
                    "Unknown compressin type %r" % compression)
            try:
                tf = tarfile.open(None, 'w', f)
                try:
                    tf.add(basedir)
                finally:
                    tf.close()
            finally:
                f.close()
        finally:
            shutil.rmtree(basedir)
        return tar_path

    def test_single_orig_tar_gz(self):
        tar_path = self.create_tarball("package", "0.1", "gz")
        os.mkdir("target")
        extract_orig_tarballs(
            [(tar_path, None)], "target", strip_components=1)
        self.assertEquals(os.listdir("target"), ["README"])

    def test_single_orig_tar_bz2(self):
        tar_path = self.create_tarball("package", "0.1", "bz2")
        os.mkdir("target")
        extract_orig_tarballs(
            [(tar_path, None)], "target", strip_components=1)
        self.assertEquals(os.listdir("target"), ["README"])

    def test_single_orig_tar_xz(self):
        self.requireFeature(LzmaFeature)
        tar_path = self.create_tarball("package", "0.1", "xz")
        os.mkdir("target")
        extract_orig_tarballs(
            [(tar_path, None)], "target", strip_components=1)
        self.assertEquals(os.listdir("target"), ["README"])

    def test_multiple_tarballs(self):
        base_tar_path = self.create_tarball("package", "0.1", "bz2")
        tar_path_extra = self.create_tarball(
            "package", "0.1", "bz2", part="extra")
        os.mkdir("target")
        extract_orig_tarballs(
            [(base_tar_path, None), (tar_path_extra, "extra")], "target",
            strip_components=1)
        self.assertEquals(
            sorted(os.listdir("target")),
            sorted(["README", "extra"]))


class ComponentFromOrigTarballTests(TestCase):

    def test_base_tarball(self):
        self.assertIs(
            None,
            component_from_orig_tarball(
                "foo_0.1.orig.tar.gz", "foo", "0.1"))
        self.assertRaises(
            ValueError,
            component_from_orig_tarball, "foo_0.1.orig.tar.gz", "bar", "0.1")

    def test_invalid_extension(self):
        self.assertRaises(
            ValueError,
            component_from_orig_tarball, "foo_0.1.orig.unknown", "foo", "0.1")

    def test_component(self):
        self.assertEquals(
            "comp",
            component_from_orig_tarball(
                "foo_0.1.orig-comp.tar.gz", "foo", "0.1"))
        self.assertEquals(
            "comp-dash",
            component_from_orig_tarball(
                "foo_0.1.orig-comp-dash.tar.gz", "foo", "0.1"))

    def test_invalid_character(self):
        self.assertRaises(
            ValueError,
            component_from_orig_tarball, "foo_0.1.orig;.tar.gz", "foo", "0.1")


class TreeContainsUpstreamSourceTests(TestCaseWithTransport):

    def test_empty(self):
        tree = self.make_branch_and_tree('.')
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertIs(None, tree_contains_upstream_source(tree))

    def test_debian_dir_only(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['debian/'])
        tree.add(['debian'])
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertFalse(tree_contains_upstream_source(tree))

    def test_debian_dir_and_bzr_builddeb(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['debian/', '.bzr-builddeb/'])
        tree.add(['debian', '.bzr-builddeb'])
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertFalse(tree_contains_upstream_source(tree))

    def test_with_upstream_source(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['debian/', 'src/'])
        tree.add(['debian', 'src'])
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertTrue(tree_contains_upstream_source(tree))

    def test_with_unversioned_extra_data(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['debian/', 'x'])
        tree.add(['debian'])
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertFalse(tree_contains_upstream_source(tree))


class FilesExcludedTests(TestCaseWithTransport):

    def test_file_missing(self):
        tree = self.make_branch_and_tree('.')
        self.assertRaises(NoSuchFile, get_files_excluded, tree)

    def test_not_set(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree_contents([
            ('debian/', ),
            ('debian/copyright', """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: blah

Files: *
Copyright:
 (c) Somebody
License: MIT
""")])
        tree.add(['debian', 'debian/copyright'])
        self.assertEqual([], get_files_excluded(tree))

    def test_set(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree_contents([
            ('debian/', ),
            ('debian/copyright', """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: blah
Files-Excluded: blah/* flattr.png

Files: *
Copyright:
 (c) Somebody
License: MIT
""")])
        tree.add(['debian', 'debian/copyright'])
        self.assertEqual(['blah/*', 'flattr.png'], get_files_excluded(tree))
