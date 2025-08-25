"""Breezy developer documentation build configuration file.

This file is execfile()d with the current directory set to its containing dir.
Created by sphinx-quickstart on Tue Jul 21 17:04:52 2009.
"""
#
# Breezy documentation build configuration file, created by
# sphinx-quickstart on Tue Jul 21 17:04:52 2009.
#
# This file is execfile()d with the current directory set to its containing dir.

import os
import sys

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
sys.path = [os.path.abspath("../.."), os.path.abspath("api")] + sys.path

# Most of the configuration for Breezy docs is defined here ...
from breezy.doc_generate.conf import *  # noqa: F403

## Configuration specific to this site ##

# The locale code for this documentation set
brz_locale = "en"

# A shorter title for the navigation bar.  Default is the same as html_title.
html_short_title = f"Developer Document Catalog ({release})"

# Additional templates that should be rendered to pages, maps page names to
# template names.
# html_additional_pages = {'index': 'index.html'}

# Output file base name for HTML help builder.
htmlhelp_basename = "brz-developers"

# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title, author, documentclass [howto/manual]).
brz_documents = [
    (
        "HACKING",
        "brz-en-developer-guide",
        "Breezy Developer Guide",
        "Breezy Developers",
        "manual",
    ),
    (
        "testing",
        "brz-en-testing-guide",
        "Breezy Testing Guide",
        "Breezy Developers",
        "manual",
    ),
    (
        "overview",
        "brz-en-architecture-overview",
        "Breezy Architecture Overview",
        "Breezy Developers",
        "howto",
    ),
    (
        "integration",
        "brz-en-integration-guide",
        "Breezy Integration Guide",
        "Breezy Developers",
        "howto",
    ),
]

latex_documents = [
    (start, target + ".tex", title, author, doc_class)
    for start, target, title, author, doc_class in brz_documents
]

texinfo_documents = list(brz_documents)

# List of documents that shouldn't be included in the build.
# Note: Maybe some of them *ought* to be linked in somewhere?
unused_docs = [
    "add",
    "annotate",
    "bundle-creation",
    "bundle-format4",
    "check",
    "commit",
    "diff",
    "directory-fingerprints",
    "gc",
    "index-plain",
    "incremental-push-pull",
    "initial-push-pull",
    "merge-scaling",
    "missing",
    "performance-roadmap-rationale",
    "performance-use-case-analysis",
    "planned-change-integration",
    "planned-performance-changes",
    "revert",
    "status",
    "uncommit",
]
