#!/bin/bash
# Helper to build packages for the various distributions

if [ -z "$UBUNTU_RELEASES" ]; then
    echo "Configure the distro platforms that you want to"
    echo "build with a line like:"
    echo '  export UBUNTU_RELEASES="dapper feisty gutsy hardy intrepid jaunty"'
    exit 1
fi

for DISTRO in $UBUNTU_RELEASES; do
    (cd "$PACKAGE-$DISTRO" && bzr builddeb -S)
done
