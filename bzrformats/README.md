# bzrformats

Core Bazaar format implementations and utilities extracted from the Breezy project.

## Overview

This package contains the internal format implementations and utilities that were part of `breezy.bzr`. These modules provide the core serialization, compression, and data structure functionality for Bazaar version control formats.

## Modules Included

### Serialization Infrastructure
- `xml_serializer.py` - Base XML serialization utilities
- `xml5.py`, `xml6.py`, `xml7.py`, `xml8.py` - Version-specific XML serialization formats
- `chk_serializer.py` - CHK-based inventory serialization

### Utilities
- `tuned_gzip.py` - Optimized gzip compression for version control data
- `recordcounter.py` - Progress estimation utilities
- `_btree_serializer_py.py` - Low-level B+Tree serialization

## Purpose

These modules were extracted from Breezy to:
1. Provide reusable format implementations for other projects
2. Create cleaner separation of concerns
3. Enable independent testing and maintenance
4. Offer reference implementations of Bazaar data formats

## Usage

This package is primarily intended for use by version control systems and tools that need to work with Bazaar format data. The modules provide building blocks for implementing Bazaar-compatible storage formats.

## License

This project is licensed under the GNU General Public License v2 or later (GPLv2+), consistent with the original Bazaar project.

## History

These modules were originally part of the Breezy project (https://github.com/breezy-team/breezy) and represent internal implementation details of the Bazaar version control format.
