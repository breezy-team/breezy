#!/bin/sh

cd /home/mhr/canonical/dd/examples/ipsec-tools/ ; rm -rf tmp* debian-sid/ ubuntu-karmic/ ; tar xvpsf test-branches.tar ; cd ubuntu-karmic/ ; bzr mp file:///home/mhr/canonical/dd/examples/ipsec-tools/debian-sid/ 2>&1 | tee /tmp/mp.log
