#!/usr/bin/python3

import ast

from pyflakes.checker import Checker, ImportationFrom


# Do some monkey patching..
def CALL(self, node):
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
    from pyflakes import __main__

    __main__.main()
