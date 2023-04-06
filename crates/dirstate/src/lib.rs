use std::cmp::Ordering;
use std::path::Path;

pub fn lt_by_dirs(path1: &Path, path2: &Path) -> bool {
    let path1_parts = path1.components();
    let path2_parts = path2.components();
    let mut path1_parts_iter = path1_parts.into_iter();
    let mut path2_parts_iter = path2_parts.into_iter();

    loop {
        match (path1_parts_iter.next(), path2_parts_iter.next()) {
            (None, None) => return false,
            (None, Some(_)) => return true,
            (Some(_), None) => return false,
            (Some(part1), Some(part2)) => {
                match part1.cmp(&part2) {
                    Ordering::Equal => continue,
                    Ordering::Less => return true,
                    Ordering::Greater => return false,
                }
            }
        }
    }
}
