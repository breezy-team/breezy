use std::cmp::Ordering;

fn lt_by_dirs(path1: &str, path2: &str) -> bool {
    let path1_parts = path1.as_bytes().split(|c| *c == b'/').filter(|&part| part != b"");
    let path2_parts = path2.as_bytes().split(|c| *c == b'/').filter(|&part| part != b"");
    let mut path1_parts_iter = path1_parts.into_iter();
    let mut path2_parts_iter = path2_parts.into_iter();

    loop {
        match (path1_parts_iter.next(), path2_parts_iter.next()) {
            (None, None) => return false,
            (None, Some(_)) => return true,
            (Some(_), None) => return false,
            (Some(part1), Some(part2)) => {
                match part1.cmp(part2) {
                    Ordering::Equal => continue,
                    Ordering::Less => return true,
                    Ordering::Greater => return false,
                }
            }
        }
    }
}
