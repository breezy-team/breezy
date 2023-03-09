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
sys.path = [os.path.abspath('../..')] + sys.path

# Most of the configuration for Breezy docs is defined here ...
from breezy.doc_generate.conf import *

## Configuration specific to this site ##

# The locale code for this documentation set
brz_locale = 'en'

# Translations & supporting helper function
brz_titles = {
    'Table of Contents (%s)': None,
    'Breezy User Guide': None,
    'Breezy User Reference': None,
    'Breezy Release Notes': None,
    'Breezy Upgrade Guide': None,
    "Breezy System Administrator's Guide": None,
    'Breezy in five minutes': None,
    'Breezy Tutorial': None,
    'Using Breezy With Launchpad': None,
    'Centralized Workflow Tutorial': None,
    "What's New in Breezy 2.1?": None,
    }
def brz_title(s):
    return brz_titles.get(s) or s

# A shorter title for the navigation bar.  Default is the same as html_title.
html_short_title = brz_title("Table of Contents (%s)") % (release,)

# Additional templates that should be rendered to pages, maps page names to
# template names.
html_additional_pages = {'index': 'index.html'}

# Output file base name for HTML help builder.
htmlhelp_basename = 'brz-{}'.format(brz_locale)

# Grouping the document tree into files. List of tuples
# (source start file, target name, title, author, documentclass [howto/manual]).
brz_documents = [
    # Manuals
    ('user-guide/index', 'brz-{}-user-guide'.format(brz_locale),
     brz_title('Breezy User Guide'), brz_team, 'manual'),
    ('user-reference/index', 'brz-{}-user-reference'.format(brz_locale),
     brz_title('Breezy User Reference'), brz_team, 'manual'),
    ('release-notes/index', 'brz-{}-release-notes'.format(brz_locale),
     brz_title('Breezy Release Notes'), brz_team, 'manual'),
    ('upgrade-guide/index', 'brz-{}-upgrade-guide'.format(brz_locale),
     brz_title('Breezy Upgrade Guide'), brz_team, 'manual'),
    ('admin-guide/index', 'brz-{}-admin-guide'.format(brz_locale),
     brz_title("Breezy System Administrator's Guide"), brz_team, 'manual'),
    # Tutorials
    ('mini-tutorial/index', 'brz-{}-tutorial-mini'.format(brz_locale),
     brz_title('Breezy in five minutes'), brz_team, 'howto'),
    ('tutorials/tutorial', 'brz-{}-tutorial'.format(brz_locale),
     brz_title('Breezy Tutorial'), brz_team, 'howto'),
    ('tutorials/using_breezy_with_github',
     'brz-{}-tutorial-with-github'.format(brz_locale),
     brz_title('Using Breezy With GitHub'), brz_team, 'howto'),
    ('tutorials/using_breezy_with_launchpad',
     'brz-{}-tutorial-with-launchpad'.format(brz_locale),
     brz_title('Using Breezy With Launchpad'), brz_team, 'howto'),
    ('tutorials/centralized_workflow',
     'brz-{}-tutorial-centralized'.format(brz_locale),
     brz_title('Centralized Workflow Tutorial'), brz_team, 'howto'),
    ('whats-new/whats-new-in-3.1', 'brz-{}-whats-new'.format(brz_locale),
     brz_title("What's New in Breezy 3.1?"), brz_team, 'howto'),
]

latex_documents = [
    (start, target + '.tex', title, author, doc_class)
    for start, target, title, author, doc_class in brz_documents
    ]

texinfo_documents = [
    (start, target, title, author, doc_class)
    for start, target, title, author, doc_class in brz_documents
    ]

# List of documents that shouldn't be included in the build.
unused_docs = [
    # Subtopics that get included
    'upgrade-guide/overview',
    'upgrade-guide/data_migration',
    'upgrade-guide/tips_and_tricks',
    # Plain-style documentation generation stuff
    'release-notes/NEWS',
    'user-reference/brz_man',
    'user-guide/index-plain',
    'admin-guide/index-plain',
    # Templates
    'release-notes/release-template',
    'release-notes/series-template',
    # Miscellaneous
    'user-reference/readme',
]
