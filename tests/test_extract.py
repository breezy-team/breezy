#    test_import_dsc.py -- Test importing .dsc files.
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

from debian import deb822
from debian.changelog import Version
import os

from ..extract import (
    OneZeroSourceExtractor,
    SOURCE_EXTRACTORS,
    ThreeDotZeroNativeSourceExtractor,
    ThreeDotZeroQuiltSourceExtractor,
    )

from .... import (
    tests,
    )

from . import (
    SourcePackageBuilder,
    )


class OneZeroSourceExtractorTests(tests.TestCaseInTempDir):

    def test_extract_format1(self):
        version = Version("0.1-1")
        name = "package"
        builder = SourcePackageBuilder(name, version)
        builder.add_upstream_file("README", "Hi\n")
        builder.add_upstream_file("BUGS")
        builder.add_default_control()
        builder.build()
        dsc = deb822.Dsc(open(builder.dsc_name()).read())
        self.assertEqual(
            OneZeroSourceExtractor, SOURCE_EXTRACTORS[dsc['Format']])
        with OneZeroSourceExtractor(builder.dsc_name(), dsc) as extractor:
            unpacked_dir = extractor.extracted_debianised
            orig_dir = extractor.extracted_upstream
            self.assertTrue(os.path.exists(unpacked_dir))
            self.assertTrue(os.path.exists(orig_dir))
            self.assertTrue(os.path.exists(os.path.join(unpacked_dir,
                            "README")))
            self.assertTrue(os.path.exists(os.path.join(unpacked_dir,
                            "debian", "control")))
            self.assertTrue(os.path.exists(os.path.join(orig_dir,
                            "README")))
            self.assertFalse(os.path.exists(os.path.join(orig_dir,
                             "debian", "control")))
            self.assertEquals(1, len(extractor.upstream_tarballs))
            self.assertEquals(3, len(extractor.upstream_tarballs[0]))
            self.assertTrue(os.path.exists(extractor.upstream_tarballs[0][0]))
            self.assertIs(None, extractor.upstream_tarballs[0][1])
            self.assertIsInstance(
                extractor.upstream_tarballs[0][2], str)  # md5sum

    def test_extract_format1_native(self):
        version = Version("0.1-1")
        name = "package"
        builder = SourcePackageBuilder(name, version, native=True)
        builder.add_upstream_file("README", "Hi\n")
        builder.add_upstream_file("BUGS")
        builder.add_default_control()
        builder.build()
        dsc = deb822.Dsc(open(builder.dsc_name()).read())
        self.assertEqual(
            OneZeroSourceExtractor, SOURCE_EXTRACTORS[dsc['Format']])
        with OneZeroSourceExtractor(builder.dsc_name(), dsc) as extractor:
            unpacked_dir = extractor.extracted_debianised
            orig_dir = extractor.extracted_upstream
            self.assertTrue(os.path.exists(unpacked_dir))
            self.assertEqual(None, orig_dir)
            self.assertTrue(os.path.exists(os.path.join(unpacked_dir,
                            "README")))
            self.assertTrue(os.path.exists(os.path.join(unpacked_dir,
                            "debian", "control")))

    def test_extract_format3_native(self):
        version = Version("0.1")
        name = "package"
        builder = SourcePackageBuilder(
            name, version, native=True, version3=True)
        builder.add_upstream_file("README", "Hi\n")
        builder.add_upstream_file("BUGS")
        builder.add_default_control()
        builder.build()
        dsc = deb822.Dsc(open(builder.dsc_name()).read())
        self.assertEqual(
            ThreeDotZeroNativeSourceExtractor,
            SOURCE_EXTRACTORS[dsc['Format']])
        with ThreeDotZeroNativeSourceExtractor(
                builder.dsc_name(), dsc) as extractor:
            unpacked_dir = extractor.extracted_debianised
            orig_dir = extractor.extracted_upstream
            self.assertTrue(os.path.exists(unpacked_dir))
            self.assertEqual(None, orig_dir)
            self.assertTrue(os.path.exists(os.path.join(unpacked_dir,
                            "README")))
            self.assertTrue(os.path.exists(os.path.join(unpacked_dir,
                            "debian", "control")))

    def test_extract_format3_quilt(self):
        version = Version("0.1-1")
        name = "package"
        builder = SourcePackageBuilder(name, version, version3=True)
        builder.add_upstream_file("README", "Hi\n")
        builder.add_upstream_file("BUGS")
        builder.add_default_control()
        builder.build()
        dsc = deb822.Dsc(open(builder.dsc_name()).read())
        self.assertEqual(
            ThreeDotZeroQuiltSourceExtractor,
            SOURCE_EXTRACTORS[dsc['Format']])
        with ThreeDotZeroQuiltSourceExtractor(
                builder.dsc_name(), dsc) as extractor:
            unpacked_dir = extractor.extracted_debianised
            orig_dir = extractor.extracted_upstream
            self.assertTrue(os.path.exists(unpacked_dir))
            self.assertTrue(os.path.exists(orig_dir))
            self.assertTrue(os.path.exists(os.path.join(unpacked_dir,
                            "README")))
            self.assertTrue(os.path.exists(os.path.join(unpacked_dir,
                            "debian", "control")))
            self.assertTrue(os.path.exists(os.path.join(orig_dir,
                            "README")))
            self.assertFalse(os.path.exists(os.path.join(orig_dir,
                             "debian", "control")))
            self.assertEquals(1, len(extractor.upstream_tarballs))
            self.assertEquals(3, len(extractor.upstream_tarballs[0]))
            self.assertTrue(os.path.exists(extractor.upstream_tarballs[0][0]))
            self.assertIs(None, extractor.upstream_tarballs[0][1])
            self.assertIsInstance(
                extractor.upstream_tarballs[0][2], str)  # md5sum

    def test_extract_format3_quilt_bz2(self):
        version = Version("0.1-1")
        name = "package"
        builder = SourcePackageBuilder(name, version, version3=True)
        builder.add_upstream_file("README", "Hi\n")
        builder.add_upstream_file("BUGS")
        builder.add_default_control()
        builder.build(tar_format='bz2')
        dsc = deb822.Dsc(open(builder.dsc_name()).read())
        self.assertEqual(
            ThreeDotZeroQuiltSourceExtractor,
            SOURCE_EXTRACTORS[dsc['Format']])
        with ThreeDotZeroQuiltSourceExtractor(
                builder.dsc_name(), dsc) as extractor:
            unpacked_dir = extractor.extracted_debianised
            orig_dir = extractor.extracted_upstream
            self.assertTrue(os.path.exists(unpacked_dir))
            self.assertTrue(os.path.exists(orig_dir))
            self.assertTrue(os.path.exists(os.path.join(unpacked_dir,
                            "README")))
            self.assertTrue(os.path.exists(os.path.join(unpacked_dir,
                            "debian", "control")))
            self.assertTrue(os.path.exists(os.path.join(orig_dir,
                            "README")))
            self.assertFalse(os.path.exists(os.path.join(orig_dir,
                             "debian", "control")))
            self.assertTrue(os.path.exists(extractor.upstream_tarballs[0][0]))

    def test_extract_format3_quilt_multiple_upstream_tarballs(self):
        version = Version("0.1-1")
        name = "package"
        builder = SourcePackageBuilder(
            name, version, version3=True,
            multiple_upstream_tarballs=("foo", "bar"))
        builder.add_upstream_file("README", "Hi\n")
        builder.add_upstream_file("BUGS")
        builder.add_upstream_file("foo/wibble")
        builder.add_upstream_file("bar/xyzzy")
        builder.add_default_control()
        builder.build(tar_format='bz2')
        dsc = deb822.Dsc(open(builder.dsc_name()).read())
        self.assertEqual(
            ThreeDotZeroQuiltSourceExtractor,
            SOURCE_EXTRACTORS[dsc['Format']])
        extractor = ThreeDotZeroQuiltSourceExtractor(builder.dsc_name(), dsc)
        self.assertEquals([], extractor.upstream_tarballs)
        with extractor:
            pass  # trigger cleanup
