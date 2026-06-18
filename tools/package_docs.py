#!/usr/bin/python3

# Copyright 2009 Canonical Ltd.
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

"""Package Sphinx documentation into distributable formats.

This tool processes Sphinx-built documentation from a _build directory and
packages it for distribution. It copies HTML documentation, creates downloadable
archives, and handles PDF files including quick reference cards.
"""

import os
import sys
import tarfile
from optparse import OptionParser
from shutil import copy2, copytree, rmtree

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def package_docs(section, src_build, dest_html, dest_downloads):
    """Package docs from a Sphinx _build directory into target directories.

    :param section: section in the website being built
    :param src_build: the _build directory
    :param dest_html: the directory where html should go
    :param downloads: the directory where downloads should go
    """
    # Copy across the HTML. Explicitly delete the html destination
    # directory first though because copytree insists on it not existing.
    src_html = os.path.join(src_build, "html")
    if os.path.exists(dest_html):
        rmtree(dest_html)
    copytree(src_html, dest_html)

    # Package the html as a downloadable archive
    archive_root = f"brz-{section}-html"
    archive_basename = f"{archive_root}.tar.bz2"
    archive_name = os.path.join(dest_downloads, archive_basename)
    build_archive(src_html, archive_name, archive_root, "bz2")

    # Copy across the PDF docs, if any, including the quick ref card
    pdf_files = []
    quick_ref = os.path.join(
        src_html, f"_static/{section}/brz-{section}-quick-reference.pdf"
    )
    if os.path.exists(quick_ref):
        pdf_files.append(quick_ref)
    src_pdf = os.path.join(src_build, "latex")
    if os.path.exists(src_pdf):
        for name in os.listdir(src_pdf):
            if name.endswith(".pdf"):
                pdf_files.append(os.path.join(src_pdf, name))
    if pdf_files:
        dest_pdf = os.path.join(dest_downloads, f"pdf-{section}")
        if not os.path.exists(dest_pdf):
            os.mkdir(dest_pdf)
        for pdf in pdf_files:
            copy2(pdf, dest_pdf)

    # TODO: copy across the CHM files, if any


def build_archive(src_dir, archive_name, archive_root, format):
    """Build a tar archive from a source directory.

    Args:
        src_dir: Source directory to archive.
        archive_name: Output path for the archive file.
        archive_root: Root directory name inside the archive.
        format: Compression format (e.g., 'bz2', 'gz').
    """
    print(f"creating {archive_name} ...")
    tar = tarfile.open(archive_name, f"w:{format}")
    for relpath in os.listdir(src_dir):
        src_path = os.path.join(src_dir, relpath)
        archive_path = os.path.join(archive_root, relpath)
        tar.add(src_path, arcname=archive_path)
    tar.close()


def main(argv):
    """Main entry point for the documentation packaging tool.

    Processes command line arguments and packages Sphinx documentation
    from a source directory into a website build directory.

    Args:
        argv: Command line arguments list. Expected format:
              [SOURCE-DIR, WEBSITE-BUILD-DIR]
              where SOURCE-DIR contains a _build subdirectory.
    """
    # Check usage. The first argument is the parent directory of
    # the Sphinx _build directory. It will typically be 'doc/xx'.
    # The second argument is the website build directory.
    parser = OptionParser(usage="%prog SOURCE-DIR WEBSITE-BUILD-DIR")
    (_options, args) = parser.parse_args(argv)
    if len(args) != 2:
        parser.print_help()
        sys.exit(1)

    # Get the section - locale code or 'developers'
    src_dir = args[0]
    section = os.path.basename(src_dir)
    src_build = os.path.join(src_dir, "_build")

    # Create the destination directories if they doesn't exist.
    dest_dir = args[1]
    dest_html = os.path.join(dest_dir, section)
    dest_downloads = os.path.join(dest_dir, "downloads")
    for d in [dest_dir, dest_downloads]:
        if not os.path.exists(d):
            print(f"creating directory {d} ...")
            os.mkdir(d)

    # Package and copy the files across
    package_docs(section, src_build, dest_html, dest_downloads)


if __name__ == "__main__":
    main(sys.argv[1:])
