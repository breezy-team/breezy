#!/usr/bin/python3
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
    def __init__(self, srcdir, destdir):
        self.srcdir = srcdir
        self.destdir = destdir

    # Process .txt files in sourcedir, generating output in destdir.
    def process_files(self):
        for filename in os.listdir(self.srcdir):
            # Process all text files in the current directory.
            if filename.endswith(".txt"):
                inpath = os.path.join(self.srcdir, filename)
                outpath = os.path.join(self.destdir, filename)
                self._process_file(inpath, outpath)

    def _process_file(self, inpath, outpath):
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
                return image_fixer.substitute_pdf_image(match)

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
    def __init__(self, srcdir, destdir):
        self.srcdir = srcdir
        self.destdir = destdir

    def substitute_pdf_image(self, match):
        prefix = match.string[: match.start(1)]
        newname = self.convert_image_to_pdf(match.group(1))
        suffix = match.string[match.end(1) :]
        return prefix + newname + suffix

    def replace_extension(self, path, newext):
        if path.endswith(newext):
            raise Exception(
                "File '" + path + "' already has extension '" + newext + "'"
            )
        dot = path.rfind(".")
        if dot == -1:
            return path + newext
        else:
            return path[:dot] + newext

    # Possibly use an SVG alternative to a PNG image, converting the SVG image
    # to a PDF first.  Whether or not a conversion is made, the image to use is
    # written to the destination directory and the path to use in the RST #
    # source is returned.
    def convert_image_to_pdf(self, filename):
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
