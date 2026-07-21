//! Text wrapping with East Asian character width support.
//!
//! A port of `breezy.utextwrap.UTextWrapper`, which extends CPython's
//! `textwrap.TextWrapper` to account for double-width (CJK) and ambiguous-width
//! characters. The chunk splitting, whitespace munging and wrap loop reproduce
//! CPython's behaviour byte-for-byte rather than approximating it.
//!
//! Only the behaviour breezy relies on is kept configurable via [`Options`].
//! The `TextWrapper` options breezy always leaves at their defaults
//! (`expand_tabs`, `replace_whitespace`, `drop_whitespace`, `break_on_hyphens`
//! on; `fix_sentence_endings` off; `tabsize` 8) are baked into the algorithm,
//! and the `max_lines`/`placeholder` truncation path is not implemented.
//!
//! The East Asian width *category* of a character (`F`, `W`, `A`, `H`, `Na`,
//! `N`) is supplied by the caller via [`EastAsianWidth`]. In the Python
//! extension this is backed by `unicodedata.east_asian_width` so the result
//! tracks the exact Unicode version CPython was built against.

/// How a character is measured, collapsing `unicodedata.east_asian_width`'s six
/// categories to the three cases the wrap algorithm distinguishes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EaWidth {
    /// Always two columns: fullwidth ("F") or wide ("W").
    Wide,
    /// Ambiguous ("A"): one or two columns per [`AmbiguousWidth`].
    Ambiguous,
    /// Always one column: halfwidth ("H"), narrow ("Na") or neutral ("N").
    Narrow,
}

/// Supplies the East Asian width class for a character.
pub trait EastAsianWidth {
    /// Return the East Asian width class of `c`.
    fn width_category(&self, c: char) -> EaWidth;
}

/// Treatment of ambiguous-width ("A") characters.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AmbiguousWidth {
    /// Ambiguous characters occupy a single column (`ambiguous_width=1`).
    Single,
    /// Ambiguous characters occupy two columns (`ambiguous_width=2`).
    Double,
}

/// Number of columns a tab expands to. Fixed to CPython's `TextWrapper`
/// default; breezy never varies it.
const TABSIZE: usize = 8;

/// The subset of CPython `textwrap.TextWrapper` attributes that breezy varies,
/// plus the `ambiguous_width` extension. See the module docs for the options
/// baked in at their defaults.
#[derive(Debug, Clone)]
pub struct Options {
    /// Maximum line width in display columns. May be non-positive, in which
    /// case wrapping raises [`WrapError::InvalidWidth`] (matching CPython).
    pub width: isize,
    /// String prepended to the first output line.
    pub initial_indent: String,
    /// String prepended to all output lines after the first.
    pub subsequent_indent: String,
    /// Whether words longer than `width` may be broken.
    pub break_long_words: bool,
    /// How ambiguous-width characters are measured.
    pub ambiguous_width: AmbiguousWidth,
}

impl Default for Options {
    fn default() -> Self {
        Options {
            // 70 is the CPython TextWrapper default width.
            width: 70,
            initial_indent: String::new(),
            subsequent_indent: String::new(),
            break_long_words: true,
            ambiguous_width: AmbiguousWidth::Single,
        }
    }
}

const WHITESPACE: [char; 6] = ['\t', '\n', '\x0b', '\x0c', '\r', ' '];

fn is_whitespace(c: char) -> bool {
    WHITESPACE.contains(&c)
}

/// Whether a chunk is entirely whitespace (a whitespace chunk from `split`).
fn is_blank(chunk: &str) -> bool {
    chunk.trim().is_empty()
}

/// `\w` in Python's `re` with the UNICODE flag: alphanumeric plus underscore,
/// using Unicode's notion of alphanumeric.
fn is_word_char(c: char) -> bool {
    c == '_' || c.is_alphanumeric()
}

/// `[^\d\W]` in Python's `re`: a word character that is not a decimal digit,
/// i.e. Unicode letters plus underscore. CPython's `\d` matches exactly the
/// characters with the `Nd` (Decimal_Number) general category.
fn is_letter_char(c: char) -> bool {
    is_word_char(c) && !is_decimal_digit(c)
}

/// `\d` in Python's `re` with UNICODE: characters in Unicode category `Nd`.
fn is_decimal_digit(c: char) -> bool {
    use unicode_general_category::{get_general_category, GeneralCategory};
    get_general_category(c) == GeneralCategory::DecimalNumber
}

/// The classifier is injected so the pure algorithm stays independent of any
/// particular Unicode data source.
pub struct TextWrapper<'w> {
    opts: Options,
    ea: &'w dyn EastAsianWidth,
}

impl<'w> TextWrapper<'w> {
    /// Create a wrapper with the given options and width classifier.
    pub fn new(opts: Options, ea: &'w dyn EastAsianWidth) -> Self {
        TextWrapper { opts, ea }
    }

    /// Width of a single character, honouring the ambiguous-width setting.
    fn char_width(&self, c: char) -> usize {
        let double = match self.ea.width_category(c) {
            EaWidth::Wide => true,
            EaWidth::Ambiguous => self.opts.ambiguous_width == AmbiguousWidth::Double,
            EaWidth::Narrow => false,
        };
        1 + usize::from(double)
    }

    /// Display width of a string (`UTextWrapper._width`).
    fn width_of(&self, s: &str) -> usize {
        s.chars().map(|c| self.char_width(c)).sum()
    }

    /// Split `s` into `(head, rest)` where `head` is as long as possible with
    /// `width_of(head) <= width` (`UTextWrapper._cut`). `width` may be negative,
    /// in which case `head` is empty (matching CPython).
    fn cut<'a>(&self, s: &'a str, width: isize) -> (&'a str, &'a str) {
        let mut w: isize = 0;
        for (idx, c) in s.char_indices() {
            w += self.char_width(c) as isize;
            if w > width {
                return (&s[..idx], &s[idx..]);
            }
        }
        (s, "")
    }

    /// Expand tabs to spaces (tabsize [`TABSIZE`], resetting the column count on
    /// line breaks) and translate all other whitespace to spaces
    /// (`TextWrapper._munge_whitespace` with `expand_tabs`/`replace_whitespace`
    /// both on, as breezy always uses).
    fn munge_whitespace(text: &str) -> String {
        let mut out = String::with_capacity(text.len());
        let mut col = 0usize;
        for c in text.chars() {
            match c {
                '\t' => {
                    let spaces = TABSIZE - (col % TABSIZE);
                    for _ in 0..spaces {
                        out.push(' ');
                    }
                    col += spaces;
                }
                '\n' | '\r' => {
                    out.push(' ');
                    col = 0;
                }
                other if is_whitespace(other) => {
                    out.push(' ');
                    col += 1;
                }
                other => {
                    out.push(other);
                    col += 1;
                }
            }
        }
        out
    }

    /// Equivalent of `wordsep_re` with `break_on_hyphens=True`.
    ///
    /// The chunk boundaries are:
    ///   * runs of whitespace,
    ///   * em-dashes (runs of 2+ hyphens) preceded by a word/punct char and
    ///     followed by a word char,
    ///   * words, which may be broken after an internal hyphen when the hyphen
    ///     sits between letters in a hyphenated compound.
    fn split_hyphens(&self, text: &str) -> Vec<String> {
        let chars: Vec<char> = text.chars().collect();
        let n = chars.len();
        let mut chunks: Vec<String> = Vec::new();
        let mut i = 0;

        while i < n {
            if is_whitespace(chars[i]) {
                let start = i;
                while i < n && is_whitespace(chars[i]) {
                    i += 1;
                }
                chunks.push(chars[start..i].iter().collect());
                continue;
            }

            // Try to match an em-dash at the current position: a run of >=2
            // hyphens, preceded by one of [\w!"'&.,?] and followed by \w.
            if chars[i] == '-' {
                if let Some(end) = match_em_dash(&chars, i) {
                    chunks.push(chars[i..end].iter().collect());
                    i = end;
                    continue;
                }
            }

            // Otherwise, accumulate a word. A word ends at whitespace, at an
            // em-dash boundary, or is broken after a hyphen that satisfies the
            // hyphenation rule.
            let start = i;
            loop {
                if i >= n || is_whitespace(chars[i]) {
                    break;
                }
                if chars[i] == '-' {
                    // Would an em-dash start here (given the char before it)?
                    if match_em_dash(&chars, i).is_some() {
                        break;
                    }
                    // Hyphenation break: emit the word including this hyphen.
                    if hyphen_breaks(&chars, i) {
                        i += 1;
                        break;
                    }
                }
                i += 1;
            }
            chunks.push(chars[start..i].iter().collect());
        }

        chunks
    }

    /// Split into chunks, then split off double-width characters into single
    /// chunks so CJK text can break between any two wide characters
    /// (`UTextWrapper._split`).
    fn split(&self, text: &str) -> Vec<String> {
        let chunks = self.split_hyphens(text);
        let mut out = Vec::new();
        for chunk in chunks {
            let cs: Vec<char> = chunk.chars().collect();
            let mut prev = 0usize;
            for (pos, &c) in cs.iter().enumerate() {
                if self.char_width(c) == 2 {
                    if prev < pos {
                        out.push(cs[prev..pos].iter().collect());
                    }
                    out.push(c.to_string());
                    prev = pos + 1;
                }
            }
            if prev < cs.len() {
                out.push(cs[prev..].iter().collect());
            }
        }
        out
    }

    /// `UTextWrapper._handle_long_word`.
    fn handle_long_word(
        &self,
        chunks: &mut Vec<String>,
        cur_line: &mut Vec<String>,
        cur_len: usize,
        width: isize,
    ) {
        let space_left: isize = if width < 2 {
            match chunks.last() {
                Some(last) if !last.is_empty() => {
                    // width of first character of the last chunk
                    let first = last.chars().next().unwrap();
                    self.char_width(first) as isize
                }
                _ => 1,
            }
        } else {
            width - cur_len as isize
        };

        if self.opts.break_long_words {
            let last = chunks.last().unwrap().clone();
            let (head, rest) = self.cut(&last, space_left);
            cur_line.push(head.to_string());
            if !rest.is_empty() {
                *chunks.last_mut().unwrap() = rest.to_string();
            } else {
                chunks.pop();
            }
        } else if cur_line.is_empty() {
            cur_line.push(chunks.pop().unwrap());
        }
    }

    /// `UTextWrapper._wrap_chunks`. Consumes `chunks` (reversed internally).
    fn wrap_chunks(&self, mut chunks: Vec<String>) -> Result<Vec<String>, WrapError> {
        let mut lines: Vec<String> = Vec::new();
        if self.opts.width <= 0 {
            return Err(WrapError::InvalidWidth(self.opts.width));
        }

        chunks.reverse();

        while !chunks.is_empty() {
            let mut cur_line: Vec<String> = Vec::new();
            let mut cur_len: usize = 0;

            let indent = if lines.is_empty() {
                self.opts.initial_indent.clone()
            } else {
                self.opts.subsequent_indent.clone()
            };

            // Python: width = self.width - len(indent), using code-unit length.
            let width: isize = self.opts.width - indent.chars().count() as isize;

            // Drop a leading whitespace chunk (unless this is the first line).
            if !lines.is_empty() && chunks.last().is_some_and(|c| is_blank(c)) {
                chunks.pop();
            }

            while let Some(last) = chunks.last() {
                let l = self.width_of(last);
                if cur_len as isize + l as isize <= width {
                    cur_line.push(chunks.pop().unwrap());
                    cur_len += l;
                } else {
                    break;
                }
            }

            // A chunk too wide for any line at this width is broken (or kept
            // whole) by `handle_long_word`.
            if chunks
                .last()
                .is_some_and(|c| self.width_of(c) as isize > width)
            {
                self.handle_long_word(&mut chunks, &mut cur_line, cur_len, width);
            }

            // Drop trailing whitespace chunk(s). CPython >= 3.13 drops all
            // trailing whitespace chunks; we follow that behaviour.
            while cur_line.last().is_some_and(|c| is_blank(c)) {
                cur_line.pop();
            }

            if !cur_line.is_empty() {
                lines.push(format!("{}{}", indent, cur_line.concat()));
            }
        }

        Ok(lines)
    }

    /// Wrap `text` into a list of lines (`UTextWrapper.wrap`).
    pub fn wrap(&self, text: &str) -> Result<Vec<String>, WrapError> {
        let munged = Self::munge_whitespace(text);
        let chunks = self.split(&munged);
        self.wrap_chunks(chunks)
    }

    /// Wrap `text` and join the lines with newlines (`fill`).
    pub fn fill(&self, text: &str) -> Result<String, WrapError> {
        Ok(self.wrap(text)?.join("\n"))
    }
}

/// If a run of >=2 hyphens begins at `pos` and is preceded by a char in
/// `[\w!"'&.,?]` and followed by a `\w` char, return the index just past the
/// hyphen run. `pos` must point at a `-`.
fn match_em_dash(chars: &[char], pos: usize) -> Option<usize> {
    if pos == 0 {
        return None;
    }
    let prev = chars[pos - 1];
    let allowed_prev =
        is_word_char(prev) || matches!(prev, '!' | '"' | '\'' | '&' | '.' | ',' | '?');
    if !allowed_prev {
        return None;
    }
    let mut end = pos;
    while end < chars.len() && chars[end] == '-' {
        end += 1;
    }
    if end - pos < 2 {
        return None;
    }
    if end < chars.len() && is_word_char(chars[end]) {
        Some(end)
    } else {
        None
    }
}

/// Whether the hyphen at index `hpos` is a hyphenation break point.
///
/// CPython's `wordsep_re` rule:
/// `-(?: (?<=[^\d\W]{2}-) | (?<=[^\d\W]-[^\d\W]-)) (?= [^\d\W] -? [^\d\W])`.
///
/// The `-` is consumed as part of the match, so the lookbehind ends *at* the
/// hyphen. The two variants are: the two characters immediately before the
/// hyphen are both letters, or the three characters before it are
/// letter-hyphen-letter. The lookahead requires the text after the hyphen to
/// be letter, optional-hyphen, letter. Lookbehind indices are absolute (they
/// see the real preceding text), so this does not depend on chunk boundaries.
fn hyphen_breaks(chars: &[char], hpos: usize) -> bool {
    let lb1 = hpos >= 2 && is_letter_char(chars[hpos - 2]) && is_letter_char(chars[hpos - 1]);
    let lb2 = hpos >= 3
        && is_letter_char(chars[hpos - 3])
        && chars[hpos - 2] == '-'
        && is_letter_char(chars[hpos - 1]);
    if !(lb1 || lb2) {
        return false;
    }
    let after = hpos + 1;
    if after < chars.len() && is_letter_char(chars[after]) {
        if after + 1 < chars.len() && is_letter_char(chars[after + 1]) {
            return true;
        }
        if after + 2 < chars.len() && chars[after + 1] == '-' && is_letter_char(chars[after + 2]) {
            return true;
        }
    }
    false
}

/// Errors raised while wrapping, mirroring the `ValueError`s Python raises.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WrapError {
    /// The configured width was not greater than zero.
    InvalidWidth(isize),
}

impl std::fmt::Display for WrapError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            WrapError::InvalidWidth(w) => write!(f, "invalid width {w} (must be > 0)"),
        }
    }
}

impl std::error::Error for WrapError {}

#[cfg(test)]
mod tests {
    use super::*;

    /// East Asian width classifier for the characters exercised by the tests.
    /// Fullwidth/Wide CJK are wide; the Cyrillic capital A is ambiguous; every
    /// other character is treated as neutral (single width). This mirrors the
    /// relevant subset of `unicodedata.east_asian_width`.
    struct TestEaw;

    impl EastAsianWidth for TestEaw {
        fn width_category(&self, c: char) -> EaWidth {
            match c {
                // Hiragana used throughout the tests: all Wide.
                '\u{304a}' | '\u{306f}' | '\u{3088}' | '\u{3046}' => EaWidth::Wide,
                // Cyrillic capital A: Ambiguous.
                '\u{0410}' => EaWidth::Ambiguous,
                _ => EaWidth::Narrow,
            }
        }
    }

    // Japanese "good morning": four Wide (double-width) characters.
    const STR_D: &str = "\u{304a}\u{306f}\u{3088}\u{3046}";
    const STR_S: &str = "hello";

    fn wrapper(opts: Options) -> (Options, TestEaw) {
        (opts, TestEaw)
    }

    fn wrap(opts: Options, text: &str) -> Vec<String> {
        let (opts, ea) = wrapper(opts);
        TextWrapper::new(opts, &ea).wrap(text).unwrap()
    }

    fn opts(width: isize) -> Options {
        Options {
            width,
            ..Options::default()
        }
    }

    #[test]
    fn width_of_double_and_mixed() {
        let (o, ea) = wrapper(Options::default());
        let w = TextWrapper::new(o, &ea);
        assert_eq!(w.width_of(STR_D), 8);
        assert_eq!(w.width_of(&format!("{STR_S}{STR_D}")), 13);
    }

    #[test]
    fn cut_respects_double_width() {
        let (o, ea) = wrapper(Options::default());
        let w = TextWrapper::new(o, &ea);
        let s = format!("{STR_S}{STR_D}");
        // Column widths at which the cut position (in chars) changes.
        assert_eq!(w.cut(&s, 0), ("", s.as_str()));
        assert_eq!(w.cut(&s, 5), ("hello", STR_D));
        // width 6 cannot fit the first wide char (needs 2), so still 5 chars.
        assert_eq!(w.cut(&s, 6), ("hello", STR_D));
        // width 7 fits "hello" (5) plus the first wide char (2) = 6 chars.
        let d0_len = STR_D.chars().next().unwrap().len_utf8();
        let boundary = STR_S.len() + d0_len;
        assert_eq!(w.cut(&s, 7), (&s[..boundary], &s[boundary..]));
        assert_eq!(w.cut("AAAAA", 3), ("AAA", "AA"));
    }

    #[test]
    fn split_separates_wide_chars() {
        let (o, ea) = wrapper(Options::default());
        let w = TextWrapper::new(o, &ea);
        let d: Vec<String> = STR_D.chars().map(|c| c.to_string()).collect();
        assert_eq!(w.split(STR_D), d);

        let mut sd = vec![STR_S.to_string()];
        sd.extend(d.iter().cloned());
        assert_eq!(w.split(&format!("{STR_S}{STR_D}")), sd);

        let mut ds = d.clone();
        ds.push(STR_S.to_string());
        assert_eq!(w.split(&format!("{STR_D}{STR_S}")), ds);
    }

    #[test]
    fn wrap_double_width_at_narrow_widths() {
        let d: Vec<String> = STR_D.chars().map(|c| c.to_string()).collect();
        assert_eq!(wrap(opts(1), STR_D), d);
        assert_eq!(wrap(opts(2), STR_D), d);
        assert_eq!(wrap(opts(3), STR_D), d);
        let mut o = opts(3);
        o.break_long_words = false;
        assert_eq!(wrap(o, STR_D), d);
    }

    #[test]
    fn fill_splits_double_width() {
        let (o, ea) = wrapper(opts(4));
        let w = TextWrapper::new(o, &ea);
        assert_eq!(
            w.fill(STR_D).unwrap(),
            format!("{}\n{}", &STR_D.chars().take(2).collect::<String>(), {
                STR_D.chars().skip(2).collect::<String>()
            })
        );
    }

    #[test]
    fn fill_with_breaks_mixed() {
        let text = format!("spam ham egg spamhamegg{STR_D} spam{}", STR_D.repeat(2));
        let d: Vec<char> = STR_D.chars().collect();
        let expected = [
            "spam ham".to_string(),
            "egg spam".to_string(),
            format!("hamegg{}", d[0]),
            d[1..].iter().collect(),
            format!("spam{}{}", d[0], d[1]),
            format!("{}{}{}{}", d[2], d[3], d[0], d[1]),
            format!("{}{}", d[2], d[3]),
        ]
        .join("\n");
        let (o, ea) = wrapper(opts(8));
        assert_eq!(TextWrapper::new(o, &ea).fill(&text).unwrap(), expected);
    }

    #[test]
    fn ambiguous_width_one_vs_two() {
        let cyr = '\u{0410}'.to_string();
        let s = cyr.repeat(8);

        let mut o1 = opts(4);
        o1.ambiguous_width = AmbiguousWidth::Single;
        let single = cyr.repeat(4);
        assert_eq!(wrap(o1, &s), vec![single.clone(), single]);

        let mut o2 = opts(4);
        o2.ambiguous_width = AmbiguousWidth::Double;
        let double = cyr.repeat(2);
        assert_eq!(
            wrap(o2, &s),
            vec![double.clone(), double.clone(), double.clone(), double]
        );
    }

    #[test]
    fn simple_ascii_wrapping() {
        assert_eq!(
            wrap(opts(12), "hello world this is a test"),
            vec!["hello world", "this is a", "test"]
        );
    }

    #[test]
    fn indent_applied() {
        let mut o = opts(10);
        o.initial_indent = "> ".to_string();
        o.subsequent_indent = "  ".to_string();
        assert_eq!(wrap(o, "aaa bbb ccc ddd"), vec!["> aaa bbb", "  ccc ddd"]);
    }

    #[test]
    fn invalid_width_errors() {
        let (o, ea) = wrapper(opts(0));
        assert_eq!(
            TextWrapper::new(o, &ea).wrap("x"),
            Err(WrapError::InvalidWidth(0))
        );
        let (o, ea) = wrapper(opts(-1));
        assert_eq!(
            TextWrapper::new(o, &ea).wrap("x"),
            Err(WrapError::InvalidWidth(-1))
        );
    }

    #[test]
    fn hyphenation_break_points() {
        let (o, ea) = wrapper(Options::default());
        let w = TextWrapper::new(o, &ea);
        assert_eq!(w.split("Python2.7-is-cool"), vec!["Python2.7-is-", "cool"]);
        assert_eq!(
            w.split("well-being-oriented"),
            vec!["well-", "being-", "oriented"]
        );
        assert_eq!(w.split("w-o-r-d"), vec!["w-o-", "r-d"]);
        assert_eq!(w.split("e-mail"), vec!["e-mail"]);
        assert_eq!(w.split("co-op"), vec!["co-", "op"]);
        // digits don't hyphenate
        assert_eq!(w.split("1-2-3"), vec!["1-2-3"]);
    }

    #[test]
    fn em_dash_splitting() {
        let (o, ea) = wrapper(Options::default());
        let w = TextWrapper::new(o, &ea);
        assert_eq!(w.split("a--b"), vec!["a", "--", "b"]);
        assert_eq!(w.split("a---b"), vec!["a", "---", "b"]);
        // preceded by digit (a \w char) still splits
        assert_eq!(w.split("5--6"), vec!["5", "--", "6"]);
        // preceded by a non-word/non-punct char does not
        assert_eq!(w.split("(--x"), vec!["(--x"]);
        // must be followed by a word char
        assert_eq!(w.split("a--!"), vec!["a--!"]);
    }

    #[test]
    fn expand_tabs_and_whitespace() {
        let (o, ea) = wrapper(Options::default());
        let w = TextWrapper::new(o, &ea);
        // _split does not expand tabs (that happens in munge_whitespace, only
        // reached via wrap); the raw tab is its own whitespace chunk here.
        assert_eq!(w.split("a\tb"), vec!["a", "\t", "b"]);
        // Through wrap(), the tab is expanded to spaces then collapsed.
        assert_eq!(wrap(opts(20), "a\tb"), vec!["a       b"]);
    }
}
