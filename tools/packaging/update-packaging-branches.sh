#!/bin/bash
# Helper for updating all of the packaging branches

if [ -z "$UBUNTU_RELEASES" ]; then
    echo "Configure the distro platforms that you want to"
    echo "build with a line like:"
    echo '  export UBUNTU_RELEASES="dapper feisty gutsy hardy intrepid jaunty"'
    exit 1
fi

for DISTRO in $UBUNTU_RELEASES; do
    if [ -d "$PACKAGE-$DISTRO" ] ; then
        echo "Updating $PACKAGE-$DISTRO"
        bzr update $PACKAGE-$DISTRO
        if [ "$PACKAGE" = "bzr-svn" ] ; then
            cd $PACKAGE-$DISTRO
            bzr merge http://bzr.debian.org/pkg-bazaar/bzr-svn/unstable/
            cd ..
        fi
    else
        SRC="lp:~bzr/ubuntu/$DISTRO/$PACKAGE/bzr-ppa"
        echo "Checking out $SRC"
        bzr co $SRC $PACKAGE-$DISTRO
    fi
done
