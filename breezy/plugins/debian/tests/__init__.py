#    __init__.py -- Testsuite for builddeb
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

import doctest
import os
import shutil
import subprocess
import tarfile
import zipfile

from debian.changelog import Changelog, Version

from .... import tests
from ....tests import (  # noqa: F401
    TestCaseInTempDir,
    TestCaseWithTransport,
    multiply_tests,
)
from ....tests.features import (  # noqa: F401
    ExecutableFeature,
    ModuleAvailableFeature,
    UnicodeFilenameFeature,
)


def make_new_upstream_dir(source, dest):
    shutil.copytree(source, dest)


def make_new_upstream_tarball(source, dest):
    tar = tarfile.open(dest, "w:gz")
    try:
        tar.add(source)
    finally:
        tar.close()


def make_new_upstream_tarball_bz2(source, dest):
    tar = tarfile.open(dest, "w:bz2")
    try:
        tar.add(source)
    finally:
        tar.close()


def make_new_upstream_tarball_zip(source, dest):
    zip = zipfile.ZipFile(dest, "w")
    try:
        zip.writestr(source, "")
        for dirpath, dirnames, names in os.walk(source):
            for dir in dirnames:
                zip.writestr(os.path.join(dirpath, dir, ""), "")
            for name in names:
                zip.write(os.path.join(dirpath, name))
    finally:
        zip.close()


def make_new_upstream_tarball_bare(source, dest):
    tar = tarfile.open(dest, "w")
    try:
        tar.add(source)
    finally:
        tar.close()


def make_new_upstream_tarball_xz(source, dest):
    uncompressed = dest + ".temp"
    tar = tarfile.open(uncompressed, "w")
    try:
        tar.add(source)
    finally:
        tar.close()
    subprocess.check_call(["xz", "-z", uncompressed])  # noqa: S607
    os.rename(uncompressed + ".xz", dest)


def make_new_upstream_tarball_lzma(source, dest):
    import lzma

    f = lzma.LZMAFile(dest, "w", format=lzma.FORMAT_ALONE)
    try:
        tar = tarfile.open(None, "w", f)
        try:
            tar.add(source)
        finally:
            tar.close()
    finally:
        f.close()


def load_tests(loader, basic_tests, pattern):
    testmod_names = [
        "blackbox",
        "test_apt_repo",
        "test_builder",
        "test_bzrtools_import",
        "test_commit_message",
        "test_config",
        "test_dep3",
        "test_directory",
        "test_extract",
        "test_hooks",
        "test_import_dsc",
        "test_merge_changelog",
        "test_merge_package",
        "test_merge_upstream",
        "test_repack_tarball_extra",
        "test_revspec",
        "test_source_distiller",
        "test_upstream",
        "test_upstream_uscan",
        "test_util",
        "test_tagging",
    ]
    basic_tests.addTest(
        loader.loadTestsFromModuleNames([f"{__name__}.{i}" for i in testmod_names])
    )

    doctest_mod_names = ["config"]
    for mod in doctest_mod_names:
        basic_tests.addTest(doctest.DocTestSuite("breezy.plugins.debian." + mod))
    repack_tarball_tests = loader.loadTestsFromModuleNames(
        ["{}.test_repack_tarball".format(__name__)]
    )
    scenarios = [
        (
            "dir",
            {"build_tarball": make_new_upstream_dir, "old_tarball": "../package-0.2"},
        ),
        (
            ".tar.gz",
            {
                "build_tarball": make_new_upstream_tarball,
                "old_tarball": "../package-0.2.tar.gz",
            },
        ),
        (
            ".tar.bz2",
            {
                "build_tarball": make_new_upstream_tarball_bz2,
                "old_tarball": "../package-0.2.tar.bz2",
            },
        ),
        (
            ".tar.xz",
            {
                "build_tarball": make_new_upstream_tarball_xz,
                "old_tarball": "../package-0.2.tar.xz",
                "_test_needs_features": [XzFeature],
            },
        ),
        (
            ".tar.lzma",
            {
                "build_tarball": make_new_upstream_tarball_lzma,
                "old_tarball": "../package-0.2.tar.lzma",
                "_test_needs_features": [LzmaFeature],
            },
        ),
        (
            ".zip",
            {
                "build_tarball": make_new_upstream_tarball_zip,
                "old_tarball": "../package-0.2.zip",
            },
        ),
        (
            ".tar",
            {
                "build_tarball": make_new_upstream_tarball_bare,
                "old_tarball": "../package-0.2.tar",
            },
        ),
    ]
    basic_tests = multiply_tests(repack_tarball_tests, scenarios, basic_tests)
    return basic_tests


class BuilddebTestCase(tests.TestCaseWithTransport):
    package_name = "test"
    package_version = Version("0.1-1")
    upstream_version = property(lambda self: self.package_version.upstream_version)

    def make_changelog(self, version=None):
        if version is None:
            version = self.package_version
        c = Changelog()
        c.new_block()
        c.version = Version(version)
        c.package = self.package_name
        c.distributions = "unstable"
        c.urgency = "low"
        c.author = "James Westby <jw+debian@jameswestby.net>"
        c.date = "Thu,  3 Aug 2006 19:16:22 +0100"
        c.add_change("")
        c.add_change("  *  test build")
        c.add_change("")
        return c

    def write_changelog(self, changelog, filename):
        with open(filename, "w") as f:
            changelog.write_to_open_file(f)

    def check_tarball_contents(
        self, tarball, expected, basedir=None, skip_basedir=False, mode=None
    ):
        """Test that the tarball has certain contents.

        Test that the tarball has exactly expected contents. The basedir
        is checked for and prepended if it is not None. The mode is the mode
        used in tarfile.open defaults to r:gz. If skip_basedir is True and
        basedir is not None then the basedir wont be tested for itself.
        """
        if basedir is None:
            real_expected = expected[:]
        else:
            if skip_basedir:
                real_expected = []
            else:
                real_expected = [basedir]
        for item in expected:
            real_expected.append(os.path.join(basedir, item).rstrip("/"))
        extras = []
        tar = tarfile.open(tarball, "r:gz")
        try:
            for tarinfo in tar:
                if tarinfo.name in real_expected:
                    index = real_expected.index(tarinfo.name)
                    del real_expected[index : index + 1]
                else:
                    extras.append(tarinfo.name)

            if len(real_expected) > 0:
                self.fail(
                    "Files not found in {}: {}".format(
                        tarball, ", ".join(real_expected)
                    )
                )
            if len(extras) > 0:
                self.fail(
                    "Files not expected to be found in {}: {}".format(
                        tarball, ", ".join(extras)
                    )
                )
        finally:
            tar.close()


class SourcePackageBuilder:
    """An interface to ease building source packages.

    >>> builder = SourcePackageBuilder("package", Version("0.1-1"))
    >>> builder.add_upstream_file("foo")
    >>> builder.add_debian_file("debian/copyright")
    >>> builder.add_default_control()
    >>> builder.build()
    >>> builder.new_version(Version("0.2-1"))
    >>> builder.add_upstream_file("bar")
    >>> builder.remove_upstream_file("foo")
    >>> builder.build()
    >>> builder.dsc_name()
    """

    def __init__(
        self,
        name,
        version,
        native=False,
        version3=False,
        multiple_upstream_tarballs=None,
    ):
        """:param name: Package name
        :param version: Package version
        :param native: Whether to build a native source package
        :param version3: Whether to build a version 3.0 source package
        :param multiple_upstream_tarballs: A list of each top-level directory
            within the upstream tree which is to be packed as a source format
            3.0 (quilt) additional upstream tarball
        """
        self.upstream_files = {}
        self.upstream_symlinks = {}
        self.debian_files = {}
        self.name = name
        self.native = native
        self.version3 = version3
        self.multiple_upstream_tarballs = multiple_upstream_tarballs
        if multiple_upstream_tarballs and not (version3 and not native):
            raise AssertionError(
                "Multiple upstream tarballs are only "
                "possible with 3.0 (quilt) format"
            )
        self._cl = Changelog()
        self.new_version(version)

    def add_upstream_file(self, name, content=None):
        self.add_upstream_files([(name, content)])

    def add_upstream_files(self, files):
        for new_file in files:
            self.upstream_files[new_file[0]] = new_file[1]

    def add_upstream_symlink(self, name, target):
        self.upstream_symlinks[name] = target

    def remove_upstream_file(self, filename):
        del self.upstream_files[filename]

    def add_debian_file(self, name, content=None):
        self.add_debian_files([(name, content)])

    def add_debian_files(self, files):
        for new_file in files:
            self.debian_files[new_file[0]] = new_file[1]

    def remove_debian_file(self, filename):
        del self.debian_files[filename]

    def add_default_control(self):
        text = """Source: {}\nSection: misc\n""".format(self.name)
        text += "Priority: optional\n"
        text += "Maintainer: Maintainer <nobody@ubuntu.com>\n"
        text += "\n"
        text += "Package: {}\n".format(self.name)
        text += "Architecture: all\n\n"
        self.add_debian_file("debian/control", text)

    def new_version(self, version, change_text=None):
        self._cl.new_block(
            package=self.name,
            version=version,
            distributions="unstable",
            urgency="low",
            author="Maint <maint@maint.org>",
            date="Wed, 19 Mar 2008 21:27:37 +0000",
        )
        if change_text is None:
            self._cl.add_change("  * foo")
        else:
            self._cl.add_change(change_text)

    def dsc_name(self):
        return f"{self.name}_{self._cl.version!s}.dsc"

    def tar_name(self):
        if self.native:
            return f"{self.name}_{self._cl.version!s}.tar.gz"
        return f"{self.name}_{self._cl.version.upstream_version!s}.orig.tar.gz"

    def diff_name(self):
        if self.native:
            raise AssertionError("Can't have a diff with a native package")
        return f"{self.name}_{self._cl.version!s}.diff.gz"

    def changes_name(self):
        return f"{self.name}_{self._cl.version!s}_source.changes"

    def _make_files(self, files_list, basedir):
        for path, content in files_list.items():
            dirname = os.path.dirname(path)
            if dirname is not None and dirname != "":
                if not os.path.exists(os.path.join(basedir, dirname)):
                    os.makedirs(os.path.join(basedir, dirname))
            with open(os.path.join(basedir, path), "w") as f:
                if content is None:
                    content = ""
                f.write(content)

    def _make_symlinks(self, files_list, basedir):
        for path, target in files_list.items():
            dirname = os.path.dirname(path)
            if dirname is not None and dirname != "":
                if not os.path.exists(os.path.join(basedir, dirname)):
                    os.makedirs(os.path.join(basedir, dirname))
            os.symlink(target, os.path.join(basedir, path))

    def basedir(self):
        return self.name + "-" + str(self._cl.version.upstream_version)

    def write_debian_files(self, basedir):
        self._make_files(self.debian_files, basedir)
        self._make_files({"debian/changelog": str(self._cl)}, basedir)

    def _make_base(self):
        basedir = self.basedir()
        os.mkdir(basedir)
        self._make_files(self.upstream_files, basedir)
        self._make_symlinks(self.upstream_symlinks, basedir)
        return basedir

    def build(self, tar_format=None):
        if tar_format is None:
            tar_format = "gz"
        basedir = self._make_base()
        if not self.version3:
            if not self.native:
                orig_basedir = basedir + ".orig"
                shutil.copytree(basedir, orig_basedir, symlinks=True)
                cmd = ["dpkg-source", "-sa", "-b", basedir]
                if os.path.exists(
                    f"{self.name}_{self._cl.version.upstream_version}.orig.tar.gz"
                ):
                    cmd = ["dpkg-source", "-ss", "-b", basedir]
            else:
                cmd = ["dpkg-source", "-sn", "-b", basedir]
        else:
            if not self.native:
                if self.multiple_upstream_tarballs:
                    for part in self.multiple_upstream_tarballs:
                        tar_path = "{}_{}.orig-{}.tar.{}".format(
                            self.name,
                            self._cl.version.upstream_version,
                            part,
                            tar_format,
                        )
                        if os.path.exists(tar_path):
                            os.unlink(tar_path)
                        tar = tarfile.open(tar_path, "w:{}".format(tar_format))
                        part_basedir = os.path.join(basedir, part)
                        try:
                            tar.add(part_basedir, arcname=part)
                        finally:
                            tar.close()
                        shutil.rmtree(part_basedir)
                tar_path = "{}_{}.orig.tar.{}".format(
                    self.name, self._cl.version.upstream_version, tar_format
                )
                if os.path.exists(tar_path):
                    os.unlink(tar_path)
                tar = tarfile.open(tar_path, "w:{}".format(tar_format))
                try:
                    tar.add(basedir)
                finally:
                    tar.close()
                cmd = ["dpkg-source", "--format=3.0 (quilt)", "-b", basedir]
            else:
                cmd = ["dpkg-source", "--format=3.0 (native)", "-b", basedir]
        self.write_debian_files(basedir)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        ret = proc.wait()
        if ret != 0:
            raise AssertionError(f"dpkg-source failed, output:\n{proc.stdout.read()}")
        cmd = "dpkg-genchanges -S > ../{}".format(self.changes_name())
        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=basedir,
        )
        ret = proc.wait()
        if ret != 0:
            raise AssertionError(
                f"dpkg-genchanges failed, output:\n{proc.stdout.read()}"
            )
        shutil.rmtree(basedir)


XzFeature = ExecutableFeature("xz")
LzmaFeature = ModuleAvailableFeature("lzma")
