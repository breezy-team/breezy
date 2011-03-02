#!/usr/bin/python
bzr_plugin_name = 'rewrite'

bzr_plugin_version = (0, 6, 2, 'final', 0)

bzr_compatible_versions = [
    (1, 14, 0), (1, 15, 0), (1, 16, 0), (1, 17, 0), (1, 18, 0),
    (2, 0, 0), (2, 1, 0), (2, 2, 0), (2, 3, 0), (2, 4, 0)]

bzr_minimum_version = bzr_compatible_versions[0]

bzr_maximum_version = bzr_compatible_versions[-1]

bzr_commands = [
    "pseudonyms",
    "replay",
    "rebase",
    "rebase_abort",
    "rebase_continue",
    "rebase_foreign",
    "rebase_todo",
    ]


