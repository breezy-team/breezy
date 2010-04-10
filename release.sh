#!/bin/bash

set -e

python setup.py sdist upload --sign
for ABI in 2.4 2.5 2.6; do
    python$ABI setup.py bdist_egg upload --sign
done
