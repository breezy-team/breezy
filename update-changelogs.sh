#!/bin/bash

if [ "x$1" = "x" ]; then
    echo "Missing version"
    exit
fi
VERSION=$1

for NAME in $UBUNTU_RELEASES; do
    PPAVERSION="$VERSION~${NAME}1"
    (
	cd "packaging-$NAME" &&
	dch -v $PPAVERSION -D $NAME -c changelog 'New upstream release.' &&
	bzr ci -m "New upstream release: $PPAVERSION"
    )
done
