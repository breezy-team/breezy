#!/bin/bash

for NAME in $UBUNTU_RELEASES; do
    (cd "packaging-$NAME" && bzr bd -S)
done
