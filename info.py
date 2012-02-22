#!/usr/bin/python
bzr_plugin_name = 'rewrite'

bzr_plugin_version = (0, 6, 3, 'dev', 0)

bzr_compatible_versions = [(2, 5, 0)]

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


