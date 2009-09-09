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
from bzrlib.doc_generate.sphinx_conf import *


## Configuration specific to this site ##

# The locale code for this documentation set
bzr_locale = 'en'

# A shorter title for the navigation bar.  Default is the same as html_title.
html_short_title = u"Developer Document Catalog (%s)" % (release,)

# Additional templates that should be rendered to pages, maps page names to
# template names.
#html_additional_pages = {'index': 'index.html'}

# Output file base name for HTML help builder.
htmlhelp_basename = 'bzr-developers'

# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title, author, documentclass [howto/manual]).
latex_documents = [
  ('HACKING', 'bzr-en-developer-guide.tex', u'Bazaar Developer Guide',
   u'Bazaar Developers', 'manual'),
  ('testing', 'bzr-en-testing-guide.tex', u'Bazaar Testing Guide',
   u'Bazaar Developers', 'manual'),
  ('overview', 'bzr-en-architecture-overview.tex', u'Bazaar Architecture Overview',
   u'Bazaar Developers', 'howto'),
  ('integration', 'bzr-en-integration-guide.tex', u'Bazaar Integration Guide',
   u'Bazaar Developers', 'howto'),
]

# List of documents that shouldn't be included in the build.
# Note: These are taken from the main Makefile. Maybe some of them *ought*
# to be linked in somewhere?
unused_docs = [
  'doc/developers/add',
  'doc/developers/annotate',
  'doc/developers/bundle-creation',
  'doc/developers/commit',
  'doc/developers/diff',
  'doc/developers/directory-fingerprints',
  'doc/developers/gc',
  'doc/developers/implementation-notes',
  'doc/developers/incremental-push-pull',
  'doc/developers/index',
  'doc/developers/initial-push-pull',
  'doc/developers/merge-scaling',
  'doc/developers/miscellaneous-notes',
  'doc/developers/missing',
  'doc/developers/performance-roadmap-rationale',
  'doc/developers/performance-use-case-analysis',
  'doc/developers/planned-change-integration',
  'doc/developers/planned-performance-changes',
  'doc/developers/plans',
  'doc/developers/process',
  'doc/developers/revert',
  'doc/developers/specifications',
  'doc/developers/status',
  'doc/developers/uncommit.txt',
]
