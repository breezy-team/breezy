#!/usr/bin/env python3

from breezy.bzr import chk_map

# Test search_key_plain
key = [b"foo"]
print(f"search_key_plain: {chk_map._search_key_plain(key)}")

# Test a more complex key
key2 = [b"foo", b"bar"]
print(f"search_key_plain (complex): {chk_map._search_key_plain(key2)}")

print("Tests completed successfully!")
