. lib.sh

create_git test

rm -rf test.darcs
mkdir test.darcs
cd test.darcs
darcs init
cd ..
gmark="$(pwd)/test.gfe-marks"
dmark="$(pwd)/test.dfi-marks"
(cd test; git fast-export --export-marks=$gmark HEAD) | (cd test.darcs; darcs-fast-import --export-marks=$dmark)
diff_importgit test || die "initial conversion differs"
upd_file_git test file2 upd_contents
(cd test; git fast-export --export-marks=$gmark --import-marks=$gmark HEAD) | (cd test.darcs; darcs-fast-import --export-marks=$dmark --import-marks=$dmark)
diff_importgit test || die "update differs"
