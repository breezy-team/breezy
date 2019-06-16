"""Flake8 plugin for reading lazy imports."""

import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
import brzflakes


class LazyImport(object):
    """A dummy plugin that is present mainly to monkey patch pyflakes."""

    name = 'lazy-import'
    version = '0.1'

    def __init__(self, tree):
        self.tree = tree

    def run(self):
        """Do nothing."""
        return []
