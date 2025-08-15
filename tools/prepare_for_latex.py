#!/usr/bin/python3

"""Tool for preparing reStructuredText files for LaTeX conversion.

This tool modifies reStructuredText files to make them more suitable for
LaTeX/PDF generation by:

1. Adding width and alignment attributes to image directives to prevent
   images from being oversized in the PDF output
2. Converting PNG image references to PDF when SVG alternatives are available
3. Using Inkscape to convert SVG files to PDF for better LaTeX compatibility

Without these modifications, images in LaTeX output are often oversized and
extend beyond page boundaries.

Copyright (C) 2009 Colin D Bennett"""
#
# Modify reStructuredText 'image' directives by adding a percentage 'width'
# attribute so that the images are scaled to fit on the page when the document
# is renderd to LaTeX, and add a center alignment.
#
# Also convert references to PNG images to use PDF files generated from SVG
# files if available.
#
# Without the explicit size specification, the images are ridiculously huge and
# most extend far off the right side of the page.
#
# Copyright (C) 2009 Colin D Bennett
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
import re
import shutil
import sys
from subprocess import call
from sys import argv

verbose = False

IMAGE_DIRECTIVE_PATTERN = re.compile("^..\\s+image::\\s+(.*)\\`\\s+$")
DIRECTIVE_ELEMENT_PATTERN = re.compile("^\\s+:[^:]+:\\s+")


class Converter:
    """Converts reStructuredText files for LaTeX processing.

    This class processes .txt files in a source directory and generates
    modified versions in a destination directory with improved image handling
    for LaTeX output.

    Attributes:
        srcdir: Source directory containing .txt files to process.
        destdir: Destination directory for processed files.
    """

    def __init__(self, srcdir, destdir):
        """Initialize the converter with source and destination directories.

        Args:
            srcdir: Path to the source directory containing .txt files.
            destdir: Path to the destination directory for processed files.
        """
        self.srcdir = srcdir
        self.destdir = destdir

    def process_files(self):
        """Process all .txt files in the source directory.

        Finds all .txt files in the source directory and processes each one,
        generating modified versions in the destination directory with improved
        image handling for LaTeX output.
        """
        for filename in os.listdir(self.srcdir):
            # Process all text files in the current directory.
            if filename.endswith(".txt"):
                inpath = os.path.join(self.srcdir, filename)
                outpath = os.path.join(self.destdir, filename)
                self._process_file(inpath, outpath)

    def _process_file(self, inpath, outpath):
        """Process a single reStructuredText file.

        Args:
            inpath: Path to the input .txt file.
            outpath: Path where the processed file should be written.
        """
        infile = open(inpath)
        outfile = open(outpath, "w")
        foundimg = False
        for line in infile:
            if foundimg and DIRECTIVE_ELEMENT_PATTERN.match(line) is None:
                if verbose:
                    print("Fixing image directive")
                # The preceding image directive has no elements.
                outfile.write(" :width: 85%\n")
                outfile.write(" :align: center\n")
            foundimg = False

            image_fixer = ImageFixer(self.srcdir, self.destdir)

            def image_fixer_lambda(match):
                return image_fixer.substitute_pdf_image(match)  # noqa: B023

            line = IMAGE_DIRECTIVE_PATTERN.sub(image_fixer_lambda, line)
            directive_match = IMAGE_DIRECTIVE_PATTERN.match(line)
            if directive_match is not None:
                image_src = directive_match.group(1)
                if verbose:
                    print(
                        "Image " + image_src + " in " + filename + ": " + line.strip()
                    )

                foundimg = True
            outfile.write(line)
        outfile.close()
        infile.close()


class ImageFixer:
    """Handles image conversion and fixing for LaTeX compatibility.

    This class is responsible for converting SVG images to PDF format
    and handling image file operations needed for LaTeX processing.

    Attributes:
        srcdir: Source directory containing original images.
        destdir: Destination directory for converted images.
    """

    def __init__(self, srcdir, destdir):
        """Initialize the image fixer with source and destination directories.

        Args:
            srcdir: Path to the source directory containing images.
            destdir: Path to the destination directory for processed images.
        """
        self.srcdir = srcdir
        self.destdir = destdir

    def substitute_pdf_image(self, match):
        """Substitute an image reference with a PDF version if available.

        Args:
            match: Regular expression match object containing the image reference.

        Returns:
            str: The modified string with the new image reference.
        """
        prefix = match.string[: match.start(1)]
        newname = self.convert_image_to_pdf(match.group(1))
        suffix = match.string[match.end(1) :]
        return prefix + newname + suffix

    def replace_extension(self, path, newext):
        """Replace the file extension of a path with a new extension.

        Args:
            path: The original file path.
            newext: The new extension to use (including the dot).

        Returns:
            str: The path with the new extension.

        Raises:
            Exception: If the file already has the target extension.
        """
        if path.endswith(newext):
            raise Exception(
                "File '" + path + "' already has extension '" + newext + "'"
            )
        dot = path.rfind(".")
        if dot == -1:
            return path + newext
        else:
            return path[:dot] + newext

    def convert_image_to_pdf(self, filename):
        """Convert an image to PDF format if possible, or copy as-is.

        For PNG images, this method checks if an SVG alternative exists and
        converts it to PDF using Inkscape. If no SVG alternative exists, the
        original image is copied to the destination directory.

        Args:
            filename: The filename of the image to process.

        Returns:
            str: The filename to use in the processed RST file.

        Raises:
            Exception: If SVG to PDF conversion fails.
        """
        # Make the directory structure for the image in the destination dir.
        image_dirname = os.path.dirname(filename)
        if image_dirname:
            image_dirpath = os.path.join(self.destdir, image_dirname)
            if not os.path.exists(image_dirpath):
                os.mkdir(image_dirpath)

        # Decide how to handle this image.
        if filename.endswith(".png"):
            # See if there is a vector alternative.
            svgfile = self.replace_extension(filename, ".svg")
            svgpath = os.path.join(self.srcdir, svgfile)
            if os.path.exists(svgpath):
                if verbose:
                    print("Using SVG alternative to PNG")
                # Convert SVG to PDF with Inkscape.
                pdffile = self.replace_extension(filename, ".pdf")
                pdfpath = os.path.join(self.destdir, pdffile)
                if call(["/usr/bin/inkscape", "--export-pdf=" + pdfpath, svgpath]) != 0:
                    raise Exception("Conversion to pdf failed")
                return pdffile

        # No conversion, just copy the file.
        srcpath = os.path.join(self.srcdir, filename)
        destpath = os.path.join(self.destdir, filename)
        shutil.copyfile(srcpath, destpath)
        return filename


if __name__ == "__main__":
    IN_DIR_OPT = "--in-dir="
    OUT_DIR_OPT = "--out-dir="
    srcdir = None
    destdir = None

    if len(argv) < 2:
        print(
            "Usage: " + argv[0] + " " + IN_DIR_OPT + "INDIR " + OUT_DIR_OPT + "OUTDIR"
        )
        print()
        print("This will convert all .txt files in INDIR into file in OUTDIR")
        print("while adjusting the use of images and possibly converting SVG")
        print("images to PDF files so LaTeX can include them.")
        sys.exit(1)

    for arg in argv[1:]:
        if arg == "-v" or arg == "--verbose":
            verbose = True
        elif arg.startswith(IN_DIR_OPT):
            srcdir = arg[len(IN_DIR_OPT) :]
        elif arg.startswith(OUT_DIR_OPT):
            destdir = arg[len(OUT_DIR_OPT) :]
        else:
            print("Invalid argument " + arg)
            sys.exit(1)

    if srcdir is None or destdir is None:
        print("Please specify the " + IN_DIR_OPT + " and " + OUT_DIR_OPT + " options.")
        sys.exit(1)

    if not os.path.exists(destdir):
        os.mkdir(destdir)
    Converter(srcdir, destdir).process_files()

# vim: set ts=4 sw=4 et:
