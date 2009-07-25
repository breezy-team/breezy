set terminal png
set output 'bench-results.png'
unset key
set xlabel "number of patches"
set ylabel "elapsed time in hours"
plot 'bench-results.dat' with linespoints
