#!/usr/bin/env python3
"""Test that modules can be imported and have docstrings."""

import sys
import importlib


def test_module_docstrings(module_name):
    """Test that a module can be imported and has proper docstrings."""
    try:
        module = importlib.import_module(module_name)
        print(f"✓ Successfully imported {module_name}")

        # Check some key classes
        classes_to_check = []
        if "repository" in module_name:
            classes_to_check = [
                "AllInOneRepository",
                "WeaveMetaDirRepository",
                "TextVersionedFiles",
                "RevisionTextStore",
            ]
        elif "bzrdir" in module_name:
            classes_to_check = [
                "BzrDirFormat5",
                "BzrDirFormat6",
                "ConvertBzrDir4To5",
                "BzrDirPreSplitOut",
            ]

        for class_name in classes_to_check:
            if hasattr(module, class_name):
                cls = getattr(module, class_name)
                if cls.__doc__:
                    print(f"  ✓ {class_name} has docstring")
                else:
                    print(f"  ✗ {class_name} missing docstring")

                # Check a few methods
                for method_name in ["__init__", "convert", "_convert_to_weaves"]:
                    if hasattr(cls, method_name):
                        method = getattr(cls, method_name)
                        if method.__doc__:
                            print(f"    ✓ {class_name}.{method_name} has docstring")
                        else:
                            print(f"    ✗ {class_name}.{method_name} missing docstring")

        return True
    except Exception as e:
        print(f"✗ Failed to import {module_name}: {e}")
        return False


if __name__ == "__main__":
    # Add the breezy path
    sys.path.insert(0, "/home/jelmer/breezy2")

    modules = ["breezy.plugins.weave_fmt.repository", "breezy.plugins.weave_fmt.bzrdir"]

    for module in modules:
        print(f"\nTesting {module}...")
        test_module_docstrings(module)
