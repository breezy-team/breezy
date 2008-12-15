#!/bin/bash
# A helper script to build packages for the various distributions

for DISTRO in $UBUNTU_RELEASES; do
    (cd "packaging-$DISTRO" && bzr builddeb -S)
done
