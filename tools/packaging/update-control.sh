#!/bin/bash
# Helper to run sed on versions in dependencies in debian/control

if [ -z "$UBUNTU_RELEASES" ]; then
    echo "Configure the distro platforms that you want to"
    echo "build with a line like:"
    echo '  export UBUNTU_RELEASES="dapper feisty gutsy hardy intrepid jaunty"'
    exit 1
fi

OLD_VERSION=$1
NEW_VERSION=$2
NEXT_VERSION=$3
if [ -z "$OLD_VERSION" -o -z "$NEW_VERSION" -o -z "$NEXT_VERSION" ]; then
    echo "Missing version"
    echo "You want something like:"
    echo "  update-control.sh 1.5 1.6 1.7"
    exit
fi

if [ "$PACKAGE" = "bzr" ]; then
    continue
fi
for DISTRO in $UBUNTU_RELEASES; do
    PPAVERSION="$VERSION~${DISTRO}1"
    (
        echo "Updating control for $DISTRO"
        cd "$PACKAGE-$DISTRO" &&
            sed -i -e "s/$NEW_VERSION~/$NEXT_VERSION~/;s/$OLD_VERSION~/$NEW_VERSION~/" control &&
            bzr commit -m "New upstream release: $PPAVERSION, update control"
    )
done
