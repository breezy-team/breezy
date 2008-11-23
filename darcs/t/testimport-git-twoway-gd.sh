. lib.sh

create_darcs test

rm -rf test.git
mkdir test.git
cd test.git
git init
git darcs add upstream ../test
git darcs fetch upstream
git merge darcs/upstream
cd ..
diff_git test || die "initial fetch differs"
upd_file_darcs test file2 upd_contents
cd test.git
git darcs fetch upstream
git merge darcs/upstream
cd ..
diff_git test || die "fetch #1 differs"
upd_file_git test.git file2 upd_contents2
cd test.git
git darcs push upstream
cd ..
diff_git test || die "push #1 difers"
upd_file_darcs test file2 upd_contents3
upd_file_darcs test file2 upd_contents32
cd test.git
git darcs fetch upstream
git merge darcs/upstream
cd ..
diff_git test || die "fetch #2 (multiple commits) differs"
upd_file_git test.git file2 upd_contents4
upd_file_git test.git file2 upd_contents42
cd test.git
git darcs push upstream
cd ..
diff_git test || die "push #2 (multiple commits) differs"
