#!/usr/bin/env python3

"""Installation script for dromedary.

Dromedary is the transport layer abstraction extracted from Breezy.
"""

from setuptools import find_packages, setup

# Import version from version module
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from version import version_string

try:
    from setuptools_rust import Binding, RustExtension
except ModuleNotFoundError:
    RustExtension = None
    rust_extensions = []
else:
    rust_extensions = [
        RustExtension(
            "dromedary._transport_rs", "_transport_rs/Cargo.toml", binding=Binding.PyO3
        ),
    ]

with open("README.md", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="dromedary",
    version=version_string,
    author="Breezy Team",
    author_email="team@breezy-vcs.org",
    description="Transport layer abstraction for version control systems",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/breezy-team/dromedary",
    packages=find_packages(),
    rust_extensions=rust_extensions,
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: GNU General Public License v2 or later (GPLv2+)",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Version Control",
    ],
    python_requires=">=3.8",
    install_requires=[
        "breezy",
    ],
    extras_require={
        "sftp": ["paramiko"],
        "gio": ["pygobject"],
    },
    zip_safe=False,
)
