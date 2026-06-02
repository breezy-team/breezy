"""Sphinx configuration file for English Breezy documentation.

This module configures Sphinx documentation generation for the English locale
version of Breezy documentation. It sets up document structure, localization
settings, and output formats for various documentation types including user
guides, tutorials, and reference materials.

The configuration inherits base settings from breezy.doc_generate.conf and
provides locale-specific customizations for English documentation.
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
sys.path = [os.path.abspath("../..")] + sys.path

# Most of the configuration for Breezy docs is defined here ...
from breezy.doc_generate.conf import *  # noqa: F403

## Configuration specific to this site ##

# The locale code for this documentation set
brz_locale = "en"

# Translations & supporting helper function
brz_titles = {
    "Table of Contents (%s)": None,
    "Breezy User Guide": None,
    "Breezy User Reference": None,
    "Breezy Release Notes": None,
    "Breezy Upgrade Guide": None,
    "Breezy System Administrator's Guide": None,
    "Breezy in five minutes": None,
    "Breezy Tutorial": None,
    "Using Breezy With Launchpad": None,
    "Centralized Workflow Tutorial": None,
    "What's New in Breezy 2.1?": None,
}


def brz_title(s):
    """Get localized title for documentation.

    Args:
        s (str): The title string to localize.

    Returns:
        str: The localized title if available, otherwise the original string.
            For English locale, returns the original string since no translation
            is needed.
    """
    return brz_titles.get(s) or s


# A shorter title for the navigation bar.  Default is the same as html_title.
html_short_title = brz_title("Table of Contents (%s)") % (release,)

# Additional templates that should be rendered to pages, maps page names to
# template names.
html_additional_pages = {"index": "index.html"}

# Output file base name for HTML help builder.
htmlhelp_basename = f"brz-{brz_locale}"

# Grouping the document tree into files. List of tuples
# (source start file, target name, title, author, documentclass [howto/manual]).
brz_documents = [
    # Manuals
    (
        "user-guide/index",
        f"brz-{brz_locale}-user-guide",
        brz_title("Breezy User Guide"),
        brz_team,
        "manual",
    ),
    (
        "user-reference/index",
        f"brz-{brz_locale}-user-reference",
        brz_title("Breezy User Reference"),
        brz_team,
        "manual",
    ),
    (
        "release-notes/index",
        f"brz-{brz_locale}-release-notes",
        brz_title("Breezy Release Notes"),
        brz_team,
        "manual",
    ),
    (
        "upgrade-guide/index",
        f"brz-{brz_locale}-upgrade-guide",
        brz_title("Breezy Upgrade Guide"),
        brz_team,
        "manual",
    ),
    (
        "admin-guide/index",
        f"brz-{brz_locale}-admin-guide",
        brz_title("Breezy System Administrator's Guide"),
        brz_team,
        "manual",
    ),
    # Tutorials
    (
        "mini-tutorial/index",
        f"brz-{brz_locale}-tutorial-mini",
        brz_title("Breezy in five minutes"),
        brz_team,
        "howto",
    ),
    (
        "tutorials/tutorial",
        f"brz-{brz_locale}-tutorial",
        brz_title("Breezy Tutorial"),
        brz_team,
        "howto",
    ),
    (
        "tutorials/using_breezy_with_github",
        f"brz-{brz_locale}-tutorial-with-github",
        brz_title("Using Breezy With GitHub"),
        brz_team,
        "howto",
    ),
    (
        "tutorials/using_breezy_with_launchpad",
        f"brz-{brz_locale}-tutorial-with-launchpad",
        brz_title("Using Breezy With Launchpad"),
        brz_team,
        "howto",
    ),
    (
        "tutorials/centralized_workflow",
        f"brz-{brz_locale}-tutorial-centralized",
        brz_title("Centralized Workflow Tutorial"),
        brz_team,
        "howto",
    ),
    (
        "whats-new/whats-new-in-3.1",
        f"brz-{brz_locale}-whats-new",
        brz_title("What's New in Breezy 3.1?"),
        brz_team,
        "howto",
    ),
]

latex_documents = [
    (start, target + ".tex", title, author, doc_class)
    for start, target, title, author, doc_class in brz_documents
]

texinfo_documents = list(brz_documents)

# List of documents that shouldn't be included in the build.
unused_docs = [
    # Subtopics that get included
    "upgrade-guide/overview",
    "upgrade-guide/data_migration",
    "upgrade-guide/tips_and_tricks",
    # Plain-style documentation generation stuff
    "release-notes/NEWS",
    "user-reference/brz_man",
    "user-guide/index-plain",
    "admin-guide/index-plain",
    # Templates
    "release-notes/release-template",
    "release-notes/series-template",
    # Miscellaneous
    "user-reference/readme",
]
