# -*- coding: utf-8 -*-
#
# Breezy documentation build configuration file, created by
# sphinx-quickstart on Tue Jul 21 17:04:52 2009.
#
# This file is execfile()d with the current directory set to its containing dir.

import sys, os

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
    u'Table of Contents (%s)': None,
    u'Breezy User Guide': None,
    u'Breezy User Reference': None,
    u'Breezy Release Notes': None,
    u'Breezy Upgrade Guide': None,
    u"Breezy System Administrator's Guide": None,
    u'Breezy in five minutes': None,
    u'Breezy Tutorial': None,
    u'Using Breezy With Launchpad': None,
    u'Centralized Workflow Tutorial': None,
    u"What's New in Breezy 2.1?": None,
    }
def brz_title(s):
    return brz_titles.get(s) or s

# A shorter title for the navigation bar.  Default is the same as html_title.
html_short_title = brz_title(u"Table of Contents (%s)") % (release,)

# Additional templates that should be rendered to pages, maps page names to
# template names.
html_additional_pages = {'index': 'index.html'}

# Output file base name for HTML help builder.
htmlhelp_basename = 'brz-%s' % (brz_locale,)

# Grouping the document tree into files. List of tuples
# (source start file, target name, title, author, documentclass [howto/manual]).
brz_documents = [
    # Manuals
    ('user-guide/index', 'brz-%s-user-guide' % (brz_locale,),
     brz_title(u'Breezy User Guide'), brz_team, 'manual'),
    ('user-reference/index', 'brz-%s-user-reference' % (brz_locale,),
     brz_title(u'Breezy User Reference'), brz_team, 'manual'),
    ('release-notes/index', 'brz-%s-release-notes' % (brz_locale,),
     brz_title(u'Breezy Release Notes'), brz_team, 'manual'),
    ('upgrade-guide/index', 'brz-%s-upgrade-guide' % (brz_locale,),
     brz_title(u'Breezy Upgrade Guide'), brz_team, 'manual'),
    ('admin-guide/index', 'brz-%s-admin-guide' % (brz_locale,),
     brz_title(u"Breezy System Administrator's Guide"), brz_team, 'manual'),
    # Tutorials
    ('mini-tutorial/index', 'brz-%s-tutorial-mini' % (brz_locale,),
     brz_title(u'Breezy in five minutes'), brz_team, 'howto'),
    ('tutorials/tutorial', 'brz-%s-tutorial' % (brz_locale,),
     brz_title(u'Breezy Tutorial'), brz_team, 'howto'),
    ('tutorials/using_breezy_with_github',
     'brz-%s-tutorial-with-github' % (brz_locale,),
     brz_title(u'Using Breezy With GitHub'), brz_team, 'howto'),
    ('tutorials/using_breezy_with_launchpad',
     'brz-%s-tutorial-with-launchpad' % (brz_locale,),
     brz_title(u'Using Breezy With Launchpad'), brz_team, 'howto'),
    ('tutorials/centralized_workflow',
     'brz-%s-tutorial-centralized' % (brz_locale,),
     brz_title(u'Centralized Workflow Tutorial'), brz_team, 'howto'),
    ('whats-new/whats-new-in-3.1', 'brz-%s-whats-new' % (brz_locale,),
     brz_title(u"What's New in Breezy 3.1?"), brz_team, 'howto'),
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
