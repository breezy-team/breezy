//! Annotation helpers.
//!
//! Provides the core algorithms used by the annotator: merging two
//! pre-sorted, de-duplicated sequences into a single sorted, de-duplicated
//! sequence, and validating that matching-block ranges fit inside their
//! containers.

/// Merge two pre-sorted, de-duplicated slices into a single sorted, de-duplicated
/// `Vec`.
///
/// Both inputs must already be sorted ascending and contain no duplicates.
/// The output preserves that invariant.
pub fn combine_sorted<T>(left: &[T], right: &[T]) -> Vec<T>
where
    T: Ord + Clone,
{
    let mut out = Vec::with_capacity(left.len() + right.len());
    let mut i = 0;
    let mut j = 0;
    while i < left.len() && j < right.len() {
        match left[i].cmp(&right[j]) {
            std::cmp::Ordering::Less => {
                out.push(left[i].clone());
                i += 1;
            }
            std::cmp::Ordering::Greater => {
                out.push(right[j].clone());
                j += 1;
            }
            std::cmp::Ordering::Equal => {
                out.push(left[i].clone());
                i += 1;
                j += 1;
            }
        }
    }
    out.extend_from_slice(&left[i..]);
    out.extend_from_slice(&right[j..]);
    out
}

/// Error returned when a matching block exceeds the bounds of one of the
/// sequences it refers to.
#[derive(Debug, PartialEq, Eq)]
pub struct MatchOutOfRange {
    pub which: &'static str,
    pub end: usize,
    pub len: usize,
}

impl std::fmt::Display for MatchOutOfRange {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "Match length exceeds len of {} {} > {}",
            self.which, self.end, self.len
        )
    }
}

impl std::error::Error for MatchOutOfRange {}

/// Verify that the matching block at (`parent_idx`, `lines_idx`, `match_len`)
/// fits inside both `parent_len` and `lines_len`.
pub fn check_match_ranges(
    parent_len: usize,
    lines_len: usize,
    parent_idx: usize,
    lines_idx: usize,
    match_len: usize,
) -> Result<(), MatchOutOfRange> {
    if parent_idx + match_len > parent_len {
        return Err(MatchOutOfRange {
            which: "parent_annotations",
            end: parent_idx + match_len,
            len: parent_len,
        });
    }
    if lines_idx + match_len > lines_len {
        return Err(MatchOutOfRange {
            which: "annotations",
            end: lines_idx + match_len,
            len: lines_len,
        });
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn combine_sorted_disjoint() {
        let a = [1, 3, 5];
        let b = [2, 4, 6];
        assert_eq!(combine_sorted(&a, &b), vec![1, 2, 3, 4, 5, 6]);
    }

    #[test]
    fn combine_sorted_overlapping() {
        let a = [1, 2, 3];
        let b = [2, 3, 4];
        assert_eq!(combine_sorted(&a, &b), vec![1, 2, 3, 4]);
    }

    #[test]
    fn combine_sorted_empty_left() {
        let a: [i32; 0] = [];
        let b = [1, 2, 3];
        assert_eq!(combine_sorted(&a, &b), vec![1, 2, 3]);
    }

    #[test]
    fn combine_sorted_empty_right() {
        let a = [1, 2, 3];
        let b: [i32; 0] = [];
        assert_eq!(combine_sorted(&a, &b), vec![1, 2, 3]);
    }

    #[test]
    fn check_ranges_ok() {
        assert!(check_match_ranges(10, 8, 2, 1, 5).is_ok());
        assert!(check_match_ranges(5, 5, 0, 0, 5).is_ok());
    }

    #[test]
    fn check_ranges_parent_oob() {
        let err = check_match_ranges(5, 8, 3, 0, 5).unwrap_err();
        assert_eq!(err.which, "parent_annotations");
        assert_eq!(err.end, 8);
        assert_eq!(err.len, 5);
    }

    #[test]
    fn check_ranges_lines_oob() {
        let err = check_match_ranges(10, 5, 0, 3, 5).unwrap_err();
        assert_eq!(err.which, "annotations");
    }
}
