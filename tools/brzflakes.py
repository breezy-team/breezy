#!/usr/bin/python3

"""Code quality checking tool with Breezy-specific enhancements.

This tool extends pyflakes to understand Breezy's lazy_import mechanism,
which is used throughout the codebase to defer expensive imports until
they are actually needed. Without this understanding, pyflakes would
report false positives for undefined names that are actually imported
via the lazy_import system.

The tool monkey-patches pyflakes to add support for parsing lazy_import
calls and registering the imported names as valid imports.
"""

import ast

from pyflakes.checker import Checker, ImportationFrom


# Do some monkey patching..
def CALL(self, node):
    """Handle function call nodes, with special support for lazy_import.

    This function extends pyflakes' CALL handler to recognize lazy_import
    calls and process them appropriately. It handles both direct calls to
    lazy_import() and attribute access calls like lazy_import.lazy_import().

    Args:
        self: The pyflakes Checker instance.
        node: The AST Call node being processed.

    Returns:
        The result of handling the node's children.
    """
    if isinstance(node.func, ast.Name) and node.func.id == "lazy_import":
        self.LAZY_IMPORT(node)
    elif (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "lazy_import"
        and node.func.value.id == "lazy_import"
    ):
        self.LAZY_IMPORT(node)
    return self.handleChildren(node)


Checker.CALL = CALL


def LAZY_IMPORT(self, node):
    """Process a lazy_import call and register the imported names.

    This function parses the lazy_import call to extract the import
    specifications and registers them with pyflakes as valid imports.
    This prevents false positive "undefined name" errors for symbols
    that are imported via lazy_import.

    Args:
        self: The pyflakes Checker instance.
        node: The AST Call node representing the lazy_import call.
    """
    from breezy.lazy_import import ImportProcessor

    processor = ImportProcessor()
    if not isinstance(node.args[1], ast.Str):
        # Not sure how to deal with this..
        return
    import_text = node.args[1].s
    scope = {}
    processor.lazy_import(scope, import_text)
    for name, (path, _sub, scope) in processor.imports.items():
        importation = ImportationFrom(name, node, ".".join(path), scope)
        self.addBinding(node, importation)


Checker.LAZY_IMPORT = LAZY_IMPORT


if __name__ == "__main__":
    """Main entry point that delegates to pyflakes with our enhancements.
    
    This script can be used as a drop-in replacement for pyflakes that
    understands Breezy's lazy_import mechanism.
    """
    from pyflakes import __main__

    __main__.main()
