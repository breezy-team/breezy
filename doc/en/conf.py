# -*- coding: utf-8 -*-
#
# Bazaar documentation build configuration file, created by
# sphinx-quickstart on Tue Jul 21 17:04:52 2009.
#
# This file is execfile()d with the current directory set to its containing dir.

import sys, os

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
sys.path = [os.path.abspath('../..')] + sys.path

# Most of the configuration for Bazaar docs is defined here ...
from bzrlib.doc_generate.conf import *

## Configuration specific to this site ##

# The locale code for this documentation set
bzr_locale = 'en'

# Translations & supporting helper function
bzr_titles = {
        u'Table of Contents (%s)': None,
        u'Bazaar User Guide': None,
        u'Bazaar User Reference': None,
        u'Bazaar Release Notes': None,
        u'Bazaar Upgrade Guide': None,
        u"Bazaar System Administrator's Guide": None,
        u'Bazaar in five minutes': None,
        u'Bazaar Tutorial': None,
        u'Using Bazaar With Launchpad': None,
        u'Centralized Workflow Tutorial': None,
        u"What's New in Bazaar 2.1?": None,
    }
def bzr_title(s):
    return bzr_titles.get(s) or s

# A shorter title for the navigation bar.  Default is the same as html_title.
html_short_title = bzr_title(u"Table of Contents (%s)") % (release,)

# Additional templates that should be rendered to pages, maps page names to
# template names.
html_additional_pages = {'index': 'index.html'}

# Output file base name for HTML help builder.
htmlhelp_basename = 'bzr-%s' % (bzr_locale,)

# Grouping the document tree into files. List of tuples
# (source start file, target name, title, author, documentclass [howto/manual]).
bzr_documents = [
  # Manuals
  ('user-guide/index', 'bzr-%s-user-guide' % (bzr_locale,),
    bzr_title(u'Bazaar User Guide'), bzr_team, 'manual'),
  ('user-reference/index', 'bzr-%s-user-reference' % (bzr_locale,),
    bzr_title(u'Bazaar User Reference'), bzr_team, 'manual'),
  ('release-notes/index', 'bzr-%s-release-notes' % (bzr_locale,),
    bzr_title(u'Bazaar Release Notes'), bzr_team, 'manual'),
  ('upgrade-guide/index', 'bzr-%s-upgrade-guide' % (bzr_locale,),
    bzr_title(u'Bazaar Upgrade Guide'), bzr_team, 'manual'),
  ('admin-guide/index', 'bzr-%s-admin-guide' % (bzr_locale,),
    bzr_title(u"Bazaar System Administrator's Guide"), bzr_team, 'manual'),
  # Tutorials
  ('mini-tutorial/index', 'bzr-%s-tutorial-mini' % (bzr_locale,),
    bzr_title(u'Bazaar in five minutes'), bzr_team, 'howto'),
  ('tutorials/tutorial', 'bzr-%s-tutorial' % (bzr_locale,),
    bzr_title(u'Bazaar Tutorial'), bzr_team, 'howto'),
  ('tutorials/using_bazaar_with_launchpad',
    'bzr-%s-tutorial-with-launchpad' % (bzr_locale,),
    bzr_title(u'Using Bazaar With Launchpad'), bzr_team, 'howto'),
  ('tutorials/centralized_workflow',
    'bzr-%s-tutorial-centralized' % (bzr_locale,),
    bzr_title(u'Centralized Workflow Tutorial'), bzr_team, 'howto'),
  ('whats-new/whats-new-in-2.1', 'bzr-%s-whats-new' % (bzr_locale,),
    bzr_title(u"What's New in Bazaar 2.1?"), bzr_team, 'howto'),
]

latex_documents = [
    (start, target+'.tex', title, author, doc_class)
    for start, target, title, author, doc_class in bzr_documents
    ]

texinfo_documents = [
    (start, target, title, author, doc_class)
    for start, target, title, author, doc_class in bzr_documents
    ]

# List of documents that shouldn't be included in the build.
unused_docs = [
    # Subtopics that get included
    'upgrade-guide/overview',
    'upgrade-guide/data_migration',
    'upgrade-guide/tips_and_tricks',
    # Plain-style documentation generation stuff
    'release-notes/NEWS',
    'user-reference/bzr_man',
    'user-guide/index-plain',
    'admin-guide/index-plain',
    # Templates
    'release-notes/release-template',
    'release-notes/series-template',
    # Miscellaneous
    'user-reference/readme',
]

