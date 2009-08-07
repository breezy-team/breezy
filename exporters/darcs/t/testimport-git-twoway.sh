. lib.sh

create_git test

rm -rf test.darcs
mkdir test.darcs
cd test.darcs
darcs init
cd ..
gmark="$(pwd)/test.gmarks"
dmark="$(pwd)/test.dmarks"

(cd test; git fast-export --export-marks=$gmark HEAD) | (cd test.darcs; darcs-fast-import --export-marks=$dmark)
diff_importgit test || die "initial conversion differs"
upd_file_git test file2 upd_contents
(cd test; git fast-export --export-marks=$gmark --import-marks=$gmark HEAD) | (cd test.darcs; darcs-fast-import --export-marks=$dmark --import-marks=$dmark)
diff_importgit test || die "git -> darcs update #1 differs"
upd_file_darcs test.darcs file2 upd_contents2
darcs-fast-export --export-marks=$dmark --import-marks=$dmark --working test/.git/darcs test.darcs | (cd test; git fast-import --export-marks=$gmark --import-marks=$gmark)
(cd test; git checkout -f)
diff_importgit test || die "darcs -> git update #2 differs"
upd_file_git test file2 upd_contents3
upd_file_git test file2 upd_contents32
(cd test; git fast-export --export-marks=$gmark --import-marks=$gmark HEAD) | (cd test.darcs; darcs-fast-import --export-marks=$dmark --import-marks=$dmark)
diff_importgit test || die "git -> darcs update #3 differs"
upd_file_darcs test.darcs file2 upd_contents4
upd_file_darcs test.darcs file2 upd_contents42
darcs-fast-export --export-marks=$dmark --import-marks=$dmark --working test/.git/darcs test.darcs | (cd test; git fast-import --export-marks=$gmark --import-marks=$gmark)
(cd test; git checkout -f)
diff_importgit test || die "darcs -> git update #4 differs"
