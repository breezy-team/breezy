#!/bin/bash

if [ "x$1" = "x" ]; then
    echo "Missing version"
    echo "You want something like:"
    echo "  update-changelogs.sh 1.6~rc1-1~bazaar1"
    echo "or"
    echo "  update-changelogs.sh 1.6-1~bazaar1"
    exit
fi
VERSION=$1

for DISTRO in $UBUNTU_RELEASES; do
    PPAVERSION="$VERSION~${DISTRO}1"
    (
        echo "Updating changelog for $DISTRO"
	cd "packaging-$DISTRO" &&
	dch -v $PPAVERSION -D $DISTRO -c changelog 'New upstream release.' &&
	bzr commit -m "New upstream release: $PPAVERSION"
    )
done
