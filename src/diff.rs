//! Unified diff generation.
//!
//! Ports the text-diff core of `breezy/diff.py` (`unified_diff_bytes` and the
//! byte fixups in `internal_diff`). The line-matching is delegated to
//! `patiencediff::SequenceMatcher`; the byte formatting is done here so the
//! output matches breezy's historical format exactly (in particular the `@@`
//! header always carries an explicit length, unlike patchkit's serializer).

use patiencediff::{Opcode, SequenceMatcher};

/// Number of context lines shown around a change by default.
pub const DEFAULT_CONTEXT_AMOUNT: usize = 3;

fn header_range(start: usize, length: usize) -> Vec<u8> {
    format!("{},{}", start, length).into_bytes()
}

/// Compare two sequences of lines and yield a unified diff.
///
/// Each returned entry is one output line, keeping the caller free to write
/// them out or post-process (as `internal_diff` does for the `/dev/null`
/// fixups). Returns an empty vector when the inputs are identical.
///
/// `a` and `b` are the old and new line lists. Lines keep their trailing
/// newline, matching `file.readlines()` semantics. `n` is the number of
/// context lines.
#[allow(clippy::too_many_arguments)]
pub fn unified_diff_bytes(
    a: &[&[u8]],
    b: &[&[u8]],
    fromfile: &[u8],
    tofile: &[u8],
    fromfiledate: &[u8],
    tofiledate: &[u8],
    n: usize,
    lineterm: &[u8],
) -> Vec<Vec<u8>> {
    let mut out = Vec::new();
    let mut matcher = SequenceMatcher::new(a, b);
    let mut started = false;
    for group in matcher.get_grouped_opcodes(n) {
        if group.is_empty() {
            continue;
        }
        if !started {
            let mut from_line = Vec::new();
            from_line.extend_from_slice(b"--- ");
            from_line.extend_from_slice(fromfile);
            if !fromfiledate.is_empty() {
                from_line.push(b'\t');
                from_line.extend_from_slice(fromfiledate);
            }
            from_line.extend_from_slice(lineterm);
            out.push(from_line);

            let mut to_line = Vec::new();
            to_line.extend_from_slice(b"+++ ");
            to_line.extend_from_slice(tofile);
            if !tofiledate.is_empty() {
                to_line.push(b'\t');
                to_line.extend_from_slice(tofiledate);
            }
            to_line.extend_from_slice(lineterm);
            out.push(to_line);
            started = true;
        }

        let first = &group[0];
        let last = &group[group.len() - 1];
        let (i1, j1) = (first.a_start(), first.b_start());
        let (i2, j2) = (last.a_end(), last.b_end());

        let mut header = Vec::new();
        header.extend_from_slice(b"@@ -");
        header.extend_from_slice(&header_range(i1 + 1, i2 - i1));
        header.extend_from_slice(b" +");
        header.extend_from_slice(&header_range(j1 + 1, j2 - j1));
        header.extend_from_slice(b" @@");
        header.extend_from_slice(lineterm);
        out.push(header);

        for opcode in &group {
            match opcode {
                Opcode::Equal(a1, a2, _, _) => {
                    for line in &a[*a1..*a2] {
                        let mut ctx = Vec::with_capacity(line.len() + 1);
                        ctx.push(b' ');
                        ctx.extend_from_slice(line);
                        out.push(ctx);
                    }
                }
                Opcode::Replace(a1, a2, b1, b2) => {
                    push_prefixed(&mut out, b'-', &a[*a1..*a2]);
                    push_prefixed(&mut out, b'+', &b[*b1..*b2]);
                }
                Opcode::Delete(a1, a2, _, _) => {
                    push_prefixed(&mut out, b'-', &a[*a1..*a2]);
                }
                Opcode::Insert(_, _, b1, b2) => {
                    push_prefixed(&mut out, b'+', &b[*b1..*b2]);
                }
            }
        }
    }
    out
}

fn push_prefixed(out: &mut Vec<Vec<u8>>, prefix: u8, lines: &[&[u8]]) {
    for line in lines {
        let mut buf = Vec::with_capacity(line.len() + 1);
        buf.push(prefix);
        buf.extend_from_slice(line);
        out.push(buf);
    }
}

/// Generate a unified diff between two line lists, ready to be written out.
///
/// This is the byte-producing core of `breezy.diff.internal_diff`: it applies
/// the `/dev/null` header workaround (patch does not recognise `-1,0` /
/// `+1,0`), appends the `\ No newline at end of file` marker after any line
/// lacking a trailing newline, and terminates the diff with a blank line.
///
/// Returns `None` when the inputs are identical (no diff to write).
pub fn internal_diff(
    old_label: &[u8],
    oldlines: &[&[u8]],
    new_label: &[u8],
    newlines: &[&[u8]],
    context_lines: usize,
) -> Option<Vec<u8>> {
    let mut ud = unified_diff_bytes(
        oldlines,
        newlines,
        old_label,
        new_label,
        b"",
        b"",
        context_lines,
        b"\n",
    );
    if ud.is_empty() {
        return None;
    }

    // work-around for difflib being too smart for its own good: if /dev/null is
    // "1,0", patch won't recognize it as /dev/null.
    if oldlines.is_empty() {
        replace_first(&mut ud[2], b"-1,0", b"-0,0");
    } else if newlines.is_empty() {
        replace_first(&mut ud[2], b"+1,0", b"+0,0");
    }

    let mut result = Vec::new();
    for line in &ud {
        result.extend_from_slice(line);
        if !line.ends_with(b"\n") {
            result.extend_from_slice(b"\n\\ No newline at end of file\n");
        }
    }
    result.extend_from_slice(b"\n");
    Some(result)
}

fn replace_first(buf: &mut Vec<u8>, needle: &[u8], replacement: &[u8]) {
    if let Some(pos) = buf
        .windows(needle.len())
        .position(|window| window == needle)
    {
        buf.splice(pos..pos + needle.len(), replacement.iter().copied());
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn lines(data: &[&[u8]]) -> Vec<Vec<u8>> {
        data.iter().map(|l| l.to_vec()).collect()
    }

    fn as_slices(data: &[Vec<u8>]) -> Vec<&[u8]> {
        data.iter().map(|l| l.as_slice()).collect()
    }

    #[test]
    fn identical_is_none() {
        let old = lines(&[b"text\n", b"contents\n"]);
        let new = lines(&[b"text\n", b"contents\n"]);
        assert_eq!(
            internal_diff(b"old", &as_slices(&old), b"new", &as_slices(&new), 3),
            None
        );
    }

    #[test]
    fn empty_is_none() {
        assert_eq!(internal_diff(b"old", &[], b"new", &[], 3), None);
    }

    #[test]
    fn single_line_change() {
        let old = lines(&[b"old_text\n"]);
        let new = lines(&[b"new_text\n"]);
        let out = internal_diff(b"old", &as_slices(&old), b"new", &as_slices(&new), 3).unwrap();
        assert_eq!(
            out,
            b"--- old\n+++ new\n@@ -1,1 +1,1 @@\n-old_text\n+new_text\n\n".to_vec()
        );
    }

    #[test]
    fn default_context_trims() {
        let old = lines(&[
            b"same_text\n",
            b"same_text\n",
            b"same_text\n",
            b"same_text\n",
            b"same_text\n",
            b"old_text\n",
        ]);
        let new = lines(&[
            b"same_text\n",
            b"same_text\n",
            b"same_text\n",
            b"same_text\n",
            b"same_text\n",
            b"new_text\n",
        ]);
        let out = internal_diff(b"old", &as_slices(&old), b"new", &as_slices(&new), 3).unwrap();
        assert_eq!(
            out,
            b"--- old\n+++ new\n@@ -3,4 +3,4 @@\n same_text\n same_text\n same_text\n-old_text\n+new_text\n\n".to_vec()
        );
    }

    #[test]
    fn no_context() {
        let old = lines(&[
            b"same_text\n",
            b"same_text\n",
            b"same_text\n",
            b"same_text\n",
            b"same_text\n",
            b"old_text\n",
        ]);
        let new = lines(&[
            b"same_text\n",
            b"same_text\n",
            b"same_text\n",
            b"same_text\n",
            b"same_text\n",
            b"new_text\n",
        ]);
        let out = internal_diff(b"old", &as_slices(&old), b"new", &as_slices(&new), 0).unwrap();
        assert_eq!(
            out,
            b"--- old\n+++ new\n@@ -6,1 +6,1 @@\n-old_text\n+new_text\n\n".to_vec()
        );
    }

    #[test]
    fn added_file_dev_null_fixup() {
        let new = lines(&[b"new_text\n"]);
        let out = internal_diff(b"old", &[], b"new", &as_slices(&new), 3).unwrap();
        assert_eq!(
            out,
            b"--- old\n+++ new\n@@ -0,0 +1,1 @@\n+new_text\n\n".to_vec()
        );
    }

    #[test]
    fn removed_file_dev_null_fixup() {
        let old = lines(&[b"old_text\n"]);
        let out = internal_diff(b"old", &as_slices(&old), b"new", &[], 3).unwrap();
        assert_eq!(
            out,
            b"--- old\n+++ new\n@@ -1,1 +0,0 @@\n-old_text\n\n".to_vec()
        );
    }

    #[test]
    fn no_newline_marker() {
        let old = lines(&[b"old_text"]);
        let new = lines(&[b"new_text"]);
        let out = internal_diff(b"old", &as_slices(&old), b"new", &as_slices(&new), 3).unwrap();
        assert_eq!(
            out,
            b"--- old\n+++ new\n@@ -1,1 +1,1 @@\n-old_text\n\\ No newline at end of file\n+new_text\n\\ No newline at end of file\n\n".to_vec()
        );
    }
}
