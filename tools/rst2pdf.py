#!/usr/bin/env python3
# $Id: rst2pdf.py 5560 2008-05-20 13:00:31Z milde $

# rst2pdf.py
# ==========
# ::

"""A front end to the Docutils Publisher, producing PDF.

Produces a latex file with the "latex" writer and converts
it to PDF with the "rubber" building system for LaTeX documents.
"""

# ``rst2pdf.py`` is a PDF front-end for docutils that is compatible
# with the ``rst2*.py`` front ends of the docutils_ suite.
# It enables the generation of PDF documents from a reStructuredText source in
# one step.
#
# It is implemented as a combination of docutils' ``rst2latex.py``
# by David Goodger and rubber_ by Emmanuel Beffara.
#
# Copyright: © 2008 Günter Milde
#            Licensed under the `Apache License, Version 2.0`_
#            Provided WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND
#
# Changelog
# ---------
#
# =====  ==========  =======================================================
# 0.1    2008-05-20  first attempt
# =====  ==========  =======================================================
#
# ::

_version = 0.1


# Imports
# =======
# ::

# from pprint import pprint # for debugging
import os

# Docutils::

try:
    import locale

    locale.setlocale(locale.LC_ALL, "")
except BaseException:
    pass

import sys

from docutils.core import Publisher, default_description, default_usage

# Rubber (rubber is not installed in the PYTHONPATH)::

sys.path.append("/usr/share/rubber")

try:
    import rubber.cmd_pipe
    import rubber.cmdline
except ModuleNotFoundError:
    print("Cannot find the rubber modules, rubber not installed correctly.")
    sys.exit(1)

# Generate the latex file
# =======================
#
# We need to replace the <destination> by a intermediate latex file path.
# The most reliable way to get the value of <destination> is to
# call the Publisher "by hand", and query its settings.
#
# Modeled on the publish_cmdline() function of docutils.core
#
# Default values::

reader = None
reader_name = "standalone"
parser = None
parser_name = "restructuredtext"
writer = None
writer_name = "pseudoxml"
settings = None
settings_spec = None
settings_overrides = None
config_section = None
enable_exit_status = 1
argv = None
usage = default_usage
description = default_description

# Argument values given to publish_cmdline() in rst2latex.py::

description = (
    "Generates PDF documents from standalone reStructuredText "
    'sources using the "latex" Writer and the "rubber" '
    "building system for LaTeX documents.  " + default_description
)
writer_name = "latex"

# Set up the publisher::

pub = Publisher(reader, parser, writer, settings=settings)
pub.set_components(reader_name, parser_name, writer_name)

# Parse the command line args
# (Publisher.publish does this in a try statement)::

pub.process_command_line(
    argv,
    usage,
    description,
    settings_spec,
    config_section,
    **(settings_overrides or {}),
)
# pprint(pub.settings.__dict__)

# Get source and destination path::

source = pub.settings._source
destination = pub.settings._destination
# print source, destination

# Generate names for the temporary files and set ``destination`` to temporary
# latex file:
#
# make_name() from rubber.cmd_pipe checks that no existing file is
# overwritten. If we are going to support rubbers ``--inplace`` and ``--into``
# options, the chdir() must occure before this point to have the check in the
# right directory. ::

tmppath = rubber.cmd_pipe.make_name()
texpath = tmppath + ".tex"
pdfpath = tmppath + ".pdf"

pub.settings._destination = texpath

# Now do the rst -> latex conversion::

pub.publish(
    argv,
    usage,
    description,
    settings_spec,
    settings_overrides,
    config_section=config_section,
    enable_exit_status=enable_exit_status,
)


# Generating the PDF document with rubber
# =======================================
#
#
# rubber_ has no documentet API for programmatic use. We simualate a command
# line call and pass command line arguments (see man: rubber-pipe) in an array::

rubber_argv = [
    "--pdf",  # use pdflatex to produce PDF
    "--short",  # Display LaTeX’s error messages one error per line.
    texpath,
]

# Get a TeX processing class instance and do the latex->pdf conversion::

tex_processor = rubber.cmdline.Main()
tex_processor(rubber_argv)

# Rename output to _destination or print to stdout::

if destination is None:
    with open(pdfpath) as pdffile:
        print(pdffile.read())
else:
    os.rename(pdfpath, destination)

# Clean up (remove intermediate files)
#
# ::

tex_processor(["--clean"] + rubber_argv)
os.remove(texpath)


# .. References
#
# .. _docutils: http://docutils.sourceforge.net/
# .. _rubber: http://www.pps.jussieu.fr/~beffara/soft/rubber/
# .. _Apache License, Version 2.0: http://www.apache.org/licenses/LICENSE-2.0
#
