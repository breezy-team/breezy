#! /bin/zsh -xe

weave init test.weave

weave add test.weave <<EOF
aaa
bbb
ccc
EOF

weave add test.weave 0 <<EOF
aaa
bbb
stuff from martin
ccc
ddd
EOF

weave add test.weave 0 <<EOF
aaa
bbb
stuff from john
more john stuff
ccc
EOF

weave add test.weave 1 2 <<EOF
aaa
bbb
stuff from martin
fix up merge
more john stuff
ccc
ddd
EOF

weave add test.weave 3 <<EOF
aaa
bbb
stuff from martin
fix up merge
modify john's code
ccc
ddd
add stuff here
EOF

# v5 
weave add test.weave 2 <<EOF
aaa
bbb
stuff from john
more john stuff
john replaced ccc line
EOF

# now try merging 5(2) with 4(3(2 1))