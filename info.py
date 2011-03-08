#!/usr/bin/python
bzr_plugin_name = 'fastimport'

bzr_commands = [
    "fast-import",
    "fast-import-filter",
    "fast-import-info",
    "fast-import-query",
    "fast-export",
    "fast-export-from-cvs",
    "fast-export-from-darcs",
    "fast-export-from-hg",
    "fast-export-from-git",
    "fast-export-from-mtn",
    "fast-export-from-p4",
    "fast-export-from-svn",
    ]

bzr_plugin_version = (0, 10, 0, 'final', 0)
bzr_minimum_version = (2, 0, 0)
bzr_maximum_version = None
