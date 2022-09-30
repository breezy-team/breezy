#    import_dsc.py -- Import a series of .dsc files.
#    Copyright (C) 2007 James Westby <jw+debian@jameswestby.net>
#              (C) 2008 Canonical Ltd.
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

from debian.changelog import Version

from contextlib import ExitStack
import os
import subprocess
import tempfile

from ... import osutils
from ...trace import mutter

from .util import (
    FORMAT_1_0,
    FORMAT_3_0_QUILT,
    FORMAT_3_0_NATIVE,
    component_from_orig_tarball,
    subprocess_setup,
)


class SourceExtractor(object):
    """A class to extract a source package to its constituent parts"""

    def __init__(self, dsc_path, dsc):
        self.dsc_path = dsc_path
        self.dsc = dsc
        self.extracted_upstream = None
        self.extracted_debianised = None
        self.unextracted_debian_md5 = None
        self.upstream_tarballs = []
        self.exit_stack = ExitStack()

    def extract(self):
        """Extract the package to a new temporary directory."""
        raise NotImplementedError(self.extract)

    def __enter__(self):
        self.exit_stack.__enter__()
        self.extract()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.exit_stack.__exit__(exc_type, exc_val, exc_tb)
        return False


class OneZeroSourceExtractor(SourceExtractor):
    """Source extract for the "1.0" source format."""

    def extract(self):
        """Extract the package to a new temporary directory."""
        tempdir = self.exit_stack.enter_context(tempfile.TemporaryDirectory())
        dsc_filename = os.path.abspath(self.dsc_path)
        proc = subprocess.Popen(
            "dpkg-source -su -x %s" % (dsc_filename,), shell=True,
            cwd=tempdir, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, preexec_fn=subprocess_setup)
        (stdout, _) = proc.communicate()
        assert proc.returncode == 0, "dpkg-source -x failed, output:\n%s" % \
            (stdout,)
        name = self.dsc['Source']
        version = Version(self.dsc['Version'])
        self.extracted_upstream = os.path.join(
            tempdir, "%s-%s.orig" % (name, str(version.upstream_version)))
        self.extracted_debianised = os.path.join(
            tempdir, "%s-%s" % (name, str(version.upstream_version)))
        if not os.path.exists(self.extracted_upstream):
            mutter("It's a native package")
            self.extracted_upstream = None
        for part in self.dsc['files']:
            if self.extracted_upstream is None:
                if part['name'].endswith(".tar.gz"):
                    self.unextracted_debian_md5 = part['md5sum']
            else:
                if part['name'].endswith(".orig.tar.gz"):
                    self.upstream_tarballs.append((os.path.abspath(
                            os.path.join(
                                osutils.dirname(self.dsc_path),
                                part['name'])),
                            component_from_orig_tarball(
                                part['name'], name,
                                str(version.upstream_version)),
                            str(part['md5sum'])))
                elif part['name'].endswith(".diff.gz"):
                    self.unextracted_debian_md5 = part['md5sum']


class ThreeDotZeroNativeSourceExtractor(SourceExtractor):
    """Source extractor for the "3.0 (native)" source format."""

    def extract(self):
        tempdir = self.exit_stack.enter_context(tempfile.TemporaryDirectory())
        dsc_filename = os.path.abspath(self.dsc_path)
        proc = subprocess.Popen(
            "dpkg-source -x %s" % (dsc_filename,), shell=True,
            cwd=tempdir, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, preexec_fn=subprocess_setup)
        (stdout, _) = proc.communicate()
        assert proc.returncode == 0, "dpkg-source -x failed, output:\n%s" % \
            (stdout,)
        name = self.dsc['Source']
        version = Version(self.dsc['Version'])
        self.extracted_debianised = os.path.join(
            tempdir, "%s-%s" % (name, str(version.upstream_version)))
        self.extracted_upstream = None
        for part in self.dsc['files']:
            if (part['name'].endswith(".tar.gz")
                    or part['name'].endswith(".tar.bz2")
                    or part['name'].endswith(".tar.xz")):
                self.unextracted_debian_md5 = part['md5sum']


class ThreeDotZeroQuiltSourceExtractor(SourceExtractor):
    """Source extractor for the "3.0 (quilt)" source format."""

    def extract(self):
        tempdir = self.exit_stack.enter_context(tempfile.TemporaryDirectory())
        dsc_filename = os.path.abspath(self.dsc_path)
        proc = subprocess.Popen(
            "dpkg-source --skip-debianization -x %s"
            % (dsc_filename,), shell=True,
            cwd=tempdir, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, preexec_fn=subprocess_setup)
        (stdout, _) = proc.communicate()
        assert proc.returncode == 0, "dpkg-source -x failed, output:\n%s" % \
            (stdout,)
        name = self.dsc['Source']
        version = Version(self.dsc['Version'])
        self.extracted_debianised = os.path.join(
            tempdir, "%s-%s" % (name, str(version.upstream_version)))
        self.extracted_upstream = self.extracted_debianised + ".orig"
        os.rename(self.extracted_debianised, self.extracted_upstream)
        proc = subprocess.Popen(
            "dpkg-source -x %s" % (dsc_filename,), shell=True,
            cwd=tempdir, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, preexec_fn=subprocess_setup)
        (stdout, _) = proc.communicate()
        assert proc.returncode == 0, "dpkg-source -x failed, output:\n%s" % \
            (stdout,)
        # Check that there are no unreadable files extracted.
        subprocess.call(
            ["find", self.extracted_upstream, "-perm",
             "0000", "-exec", "chmod", "644", "{}", ";"])
        subprocess.call(
            ["find", self.extracted_debianised, "-perm",
             "0000", "-exec", "chmod", "644", "{}", ";"])
        for part in self.dsc['files']:
            if (part['name'].startswith(
                    "%s_%s.orig" % (name, str(version.upstream_version)))
                    and not part['name'].endswith('.asc')):
                self.upstream_tarballs.append((
                    os.path.abspath(os.path.join(
                        osutils.dirname(self.dsc_path), part['name'])),
                    component_from_orig_tarball(
                        part['name'], name, str(version.upstream_version)),
                    str(part['md5sum'])))
            elif (part['name'].endswith(".debian.tar.gz")
                    or part['name'].endswith(".debian.tar.bz2")
                    or part['name'].endswith(".debian.tar.xz")):
                self.unextracted_debian_md5 = str(part['md5sum'])
        assert self.upstream_tarballs is not None, \
            "Can't handle non gz|bz2|xz tarballs yet"
        assert self.unextracted_debian_md5 is not None, \
            "Can't handle non gz|bz2|xz tarballs yet"


SOURCE_EXTRACTORS = {}
SOURCE_EXTRACTORS[FORMAT_1_0] = OneZeroSourceExtractor
SOURCE_EXTRACTORS[FORMAT_3_0_NATIVE] = ThreeDotZeroNativeSourceExtractor
SOURCE_EXTRACTORS[FORMAT_3_0_QUILT] = ThreeDotZeroQuiltSourceExtractor


def extract(dsc_filename, dsc):
    format = dsc.get('Format', FORMAT_1_0).strip()
    extractor_cls = SOURCE_EXTRACTORS.get(format)
    if extractor_cls is None:
        raise AssertionError(
            "Don't know how to import source format %s yet" % format)
    return extractor_cls(dsc_filename, dsc)
