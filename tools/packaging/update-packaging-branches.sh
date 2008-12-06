#!/bin/bash
# Helper for updating all of the packaging branches

if [ -z "$UBUNTU_RELEASES" ]; then
    echo "Configure the distro platforms that you want to"
    echo "build with a line like:"
    echo '  export UBUNTU_RELEASES="dapper feisty gutsy hardy intrepid"'
    exit 1
fi

for DISTRO in $UBUNTU_RELEASES; do
    if [ -d "packaging-$DISTRO" ] ; then
        echo "Updating packaging-$DISTRO"
        bzr update packaging-$DISTRO
    else
        echo "Checking out lp:~bzr/bzr/packaging-$DISTRO"
        bzr co lp:~bzr/bzr/packaging-$DISTRO
    fi
done

