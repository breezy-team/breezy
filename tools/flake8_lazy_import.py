"""Flake8 plugin for reading lazy imports."""

import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))


class LazyImport:
    """A dummy plugin that is present mainly to monkey patch pyflakes."""

    name = "lazy-import"
    version = "0.1"

    def __init__(self, tree):
        """Initialize the LazyImport plugin.

        Args:
            tree: The AST tree to analyze (unused in this dummy implementation).
        """
        self.tree = tree

    def run(self):
        """Run the plugin analysis.

        This is a dummy implementation that performs no actual analysis.
        The plugin exists mainly to monkey patch pyflakes.

        Returns:
            list: An empty list since no issues are reported.
        """
        return []
