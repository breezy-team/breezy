#!/bin/bash
# Helper to insert a new entry in debian/changelog

if [ -z "$UBUNTU_RELEASES" ]; then
    echo "Configure the distro platforms that you want to"
    echo "build with a line like:"
    echo '  export UBUNTU_RELEASES="dapper feisty gutsy hardy intrepid jaunty"'
    exit 1
fi

if [ "x$VERSION" = "x" ]; then
    echo "Missing version"
    echo "You want something like:"
    echo "  VERSION=1.6~rc1-1~bazaar1 update-changelogs.sh"
    echo "or"
    echo "  VERSION=1.6-1~bazaar1 update-changelogs.sh"
    exit
fi

if [ -z "$1" ]; then
    MSG="New upstream release"
else
    MSG=$1
fi

for DISTRO in $UBUNTU_RELEASES; do
    PPAVERSION="$VERSION~${DISTRO}1"
    (
        echo "Updating changelog for $DISTRO"
        cd "$PACKAGE-$DISTRO" &&
            dch -v $PPAVERSION -D $DISTRO "$MSG." &&
            bzr commit -m "$MSG: $PPAVERSION"
    )
done
