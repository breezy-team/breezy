//! Unicode-compatible command-line splitter for all platforms.
//!
//! Ported from `breezy/cmdline.py`. The splitter walks the input character by
//! character through a small state machine that tracks quoting and backslash
//! escaping, yielding `(quoted, token)` pairs. The user-visible behaviour is
//! described in `configuring_bazaar.txt`.

/// Whether a character counts as whitespace for token separation.
///
/// This mirrors Python's `re` `\s` with the `UNICODE` flag, which matches the
/// Unicode `White_Space` set plus the four ASCII information separators
/// (`0x1c`-`0x1f`). Rust's [`char::is_whitespace`] covers the former but not the
/// latter, so the separators are added explicitly.
fn is_whitespace(c: char) -> bool {
    c.is_whitespace() || matches!(c, '\u{1c}'..='\u{1f}')
}

/// A character source that supports pushing a single character back so the
/// next state can reprocess it.
struct PushbackSequence {
    chars: std::vec::IntoIter<char>,
    pushback: Vec<char>,
}

impl PushbackSequence {
    fn new(s: &str) -> Self {
        PushbackSequence {
            chars: s.chars().collect::<Vec<_>>().into_iter(),
            pushback: Vec::new(),
        }
    }

    fn pushback(&mut self, c: char) {
        self.pushback.push(c);
    }
}

impl Iterator for PushbackSequence {
    type Item = char;

    fn next(&mut self) -> Option<char> {
        if let Some(c) = self.pushback.pop() {
            Some(c)
        } else {
            self.chars.next()
        }
    }
}

/// The states the splitter can be in while consuming a single token.
enum State {
    Whitespace,
    Word,
    Quotes { quote_char: char, in_word: bool },
    Backslash { count: usize, exit: Box<State> },
}

/// The outcome of feeding one character to a state.
enum Step {
    /// Continue with this state.
    Continue(State),
    /// The token is complete.
    Done,
}

/// Mutable context shared across state transitions while building one token.
struct Context<'a> {
    seq: &'a mut PushbackSequence,
    allowed_quote_chars: &'a str,
    quoted: bool,
    token: String,
}

impl<'a> Context<'a> {
    fn is_quote(&self, c: char) -> bool {
        self.allowed_quote_chars.contains(c)
    }
}

impl State {
    fn process(self, c: char, ctx: &mut Context<'_>) -> Step {
        match self {
            State::Whitespace => {
                if is_whitespace(c) {
                    // A token that has been started - including an empty one
                    // closed off by a quote pair - is terminated by whitespace.
                    if ctx.quoted || !ctx.token.is_empty() {
                        Step::Done
                    } else {
                        Step::Continue(State::Whitespace)
                    }
                } else if ctx.is_quote(c) {
                    ctx.quoted = true;
                    Step::Continue(State::Quotes {
                        quote_char: c,
                        in_word: false,
                    })
                } else if c == '\\' {
                    Step::Continue(State::Backslash {
                        count: 1,
                        exit: Box::new(State::Whitespace),
                    })
                } else {
                    ctx.token.push(c);
                    Step::Continue(State::Word)
                }
            }
            State::Word => {
                if is_whitespace(c) {
                    Step::Done
                } else if ctx.is_quote(c) {
                    Step::Continue(State::Quotes {
                        quote_char: c,
                        in_word: true,
                    })
                } else if c == '\\' {
                    Step::Continue(State::Backslash {
                        count: 1,
                        exit: Box::new(State::Word),
                    })
                } else {
                    ctx.token.push(c);
                    Step::Continue(State::Word)
                }
            }
            State::Quotes {
                quote_char,
                in_word,
            } => {
                if c == '\\' {
                    Step::Continue(State::Backslash {
                        count: 1,
                        exit: Box::new(State::Quotes {
                            quote_char,
                            in_word,
                        }),
                    })
                } else if c == quote_char {
                    // The closing quote contributes nothing to the token but
                    // leaves it marked as (possibly empty and) quoted.
                    Step::Continue(if in_word {
                        State::Word
                    } else {
                        State::Whitespace
                    })
                } else {
                    ctx.token.push(c);
                    Step::Continue(State::Quotes {
                        quote_char,
                        in_word,
                    })
                }
            }
            State::Backslash { mut count, exit } => {
                // See http://msdn.microsoft.com/en-us/library/bb776391(VS.85).aspx
                if c == '\\' {
                    count += 1;
                    Step::Continue(State::Backslash { count, exit })
                } else if ctx.is_quote(c) {
                    // 2N backslashes followed by a quote are N backslashes.
                    for _ in 0..count / 2 {
                        ctx.token.push('\\');
                    }
                    if count % 2 == 1 {
                        // 2N+1 backslashes followed by a quote are N backslashes
                        // followed by the quote, which is escaped and so is not
                        // treated as the start or end of a quoted arg.
                        ctx.token.push(c);
                    } else {
                        // Let the exit state handle the quote.
                        ctx.seq.pushback(c);
                    }
                    Step::Continue(*exit)
                } else {
                    // N backslashes not followed by a quote are just N
                    // backslashes.
                    for _ in 0..count {
                        ctx.token.push('\\');
                    }
                    ctx.seq.pushback(c);
                    Step::Continue(*exit)
                }
            }
        }
    }

    /// Flush any trailing state once the input is exhausted mid-token.
    fn finish(self, ctx: &mut Context<'_>) {
        if let State::Backslash { count, .. } = self {
            for _ in 0..count {
                ctx.token.push('\\');
            }
        }
    }
}

/// Splits a command line into `(quoted, token)` pairs.
pub struct Splitter {
    seq: PushbackSequence,
    allowed_quote_chars: String,
}

impl Splitter {
    /// Create a splitter over `command_line`.
    ///
    /// When `single_quotes_allowed` is true, single quotes may delimit tokens
    /// in addition to double quotes.
    pub fn new(command_line: &str, single_quotes_allowed: bool) -> Self {
        let mut allowed_quote_chars = String::from("\"");
        if single_quotes_allowed {
            allowed_quote_chars.push('\'');
        }
        Splitter {
            seq: PushbackSequence::new(command_line),
            allowed_quote_chars,
        }
    }

    fn get_token(&mut self) -> (bool, Option<String>) {
        let mut ctx = Context {
            seq: &mut self.seq,
            allowed_quote_chars: &self.allowed_quote_chars,
            quoted: false,
            token: String::new(),
        };
        let mut state = Some(State::Whitespace);
        while let Some(c) = ctx.seq.next() {
            match state.take().unwrap().process(c, &mut ctx) {
                Step::Continue(next) => state = Some(next),
                Step::Done => break,
            }
        }
        // A `None` here means the loop broke on `Done`; otherwise the input was
        // exhausted mid-token and any pending state must be flushed.
        if let Some(state) = state {
            state.finish(&mut ctx);
        }
        let quoted = ctx.quoted;
        let result = if !quoted && ctx.token.is_empty() {
            None
        } else {
            Some(ctx.token)
        };
        (quoted, result)
    }
}

impl Iterator for Splitter {
    type Item = (bool, String);

    fn next(&mut self) -> Option<(bool, String)> {
        let (quoted, token) = self.get_token();
        token.map(|t| (quoted, t))
    }
}

/// Split a command line string into a list of arguments.
pub fn split(unsplit: &str, single_quotes_allowed: bool) -> Vec<String> {
    Splitter::new(unsplit, single_quotes_allowed)
        .map(|(_quoted, arg)| arg)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn as_tokens(line: &str, single_quotes_allowed: bool) -> Vec<(bool, String)> {
        Splitter::new(line, single_quotes_allowed).collect()
    }

    fn t(quoted: bool, s: &str) -> (bool, String) {
        (quoted, s.to_string())
    }

    #[test]
    fn simple() {
        assert_eq!(
            as_tokens("foo bar baz", false),
            vec![t(false, "foo"), t(false, "bar"), t(false, "baz")]
        );
    }

    #[test]
    fn ignore_multiple_spaces() {
        assert_eq!(
            as_tokens("foo  bar", false),
            vec![t(false, "foo"), t(false, "bar")]
        );
    }

    #[test]
    fn ignore_leading_space() {
        assert_eq!(
            as_tokens("  foo bar", false),
            vec![t(false, "foo"), t(false, "bar")]
        );
    }

    #[test]
    fn ignore_trailing_space() {
        assert_eq!(
            as_tokens("foo bar  ", false),
            vec![t(false, "foo"), t(false, "bar")]
        );
    }

    #[test]
    fn posix_quotations() {
        assert_eq!(as_tokens("'foo bar'", true), vec![t(true, "foo bar")]);
        assert_eq!(as_tokens("'fo''o b''ar'", true), vec![t(true, "foo bar")]);
        assert_eq!(
            as_tokens("\"fo\"\"o b\"\"ar\"", true),
            vec![t(true, "foo bar")]
        );
        assert_eq!(
            as_tokens("\"fo\"'o b'\"ar\"", true),
            vec![t(true, "foo bar")]
        );
    }

    #[test]
    fn nested_quotations() {
        assert_eq!(
            as_tokens("\"foo\\\"\\\" bar\"", false),
            vec![t(true, "foo\"\" bar")]
        );
        assert_eq!(
            as_tokens("\"foo'' bar\"", false),
            vec![t(true, "foo'' bar")]
        );
        assert_eq!(as_tokens("\"foo'' bar\"", true), vec![t(true, "foo'' bar")]);
        assert_eq!(
            as_tokens("'foo\"\" bar'", true),
            vec![t(true, "foo\"\" bar")]
        );
    }

    #[test]
    fn empty_result() {
        assert_eq!(as_tokens("", false), Vec::<(bool, String)>::new());
        assert_eq!(as_tokens("    ", false), Vec::<(bool, String)>::new());
    }

    #[test]
    fn quoted_empty() {
        assert_eq!(as_tokens("\"\"", false), vec![t(true, "")]);
        assert_eq!(as_tokens("''", false), vec![t(false, "''")]);
        assert_eq!(as_tokens("''", true), vec![t(true, "")]);
        assert_eq!(
            as_tokens("a \"\" c", false),
            vec![t(false, "a"), t(true, ""), t(false, "c")]
        );
        assert_eq!(
            as_tokens("a '' c", true),
            vec![t(false, "a"), t(true, ""), t(false, "c")]
        );
    }

    #[test]
    fn unicode_chars() {
        assert_eq!(
            as_tokens("f\u{b5}\u{ee} \u{1234}\u{3456}", false),
            vec![t(false, "f\u{b5}\u{ee}"), t(false, "\u{1234}\u{3456}")]
        );
    }

    #[test]
    fn newline_in_quoted_section() {
        assert_eq!(
            as_tokens("\"foo\nbar\nbaz\n\"", false),
            vec![t(true, "foo\nbar\nbaz\n")]
        );
        assert_eq!(
            as_tokens("'foo\nbar\nbaz\n'", true),
            vec![t(true, "foo\nbar\nbaz\n")]
        );
    }

    #[test]
    fn escape_chars() {
        assert_eq!(as_tokens("foo\\bar", false), vec![t(false, "foo\\bar")]);
    }

    #[test]
    fn escape_quote() {
        assert_eq!(
            as_tokens("\"foo\\\"bar\"", false),
            vec![t(true, "foo\"bar")]
        );
        assert_eq!(
            as_tokens("\"foo\\\\\\\"bar\"", false),
            vec![t(true, "foo\\\"bar")]
        );
        assert_eq!(
            as_tokens("\"foo\\\\\"bar\"", false),
            vec![t(true, "foo\\bar")]
        );
    }

    #[test]
    fn double_escape() {
        assert_eq!(
            as_tokens("\"foo\\\\bar\"", false),
            vec![t(true, "foo\\\\bar")]
        );
        assert_eq!(as_tokens("foo\\\\bar", false), vec![t(false, "foo\\\\bar")]);
    }

    #[test]
    fn multiple_quoted_args() {
        assert_eq!(
            as_tokens("\"x x\" \"y y\"", false),
            vec![t(true, "x x"), t(true, "y y")]
        );
        assert_eq!(
            as_tokens("\"x x\" 'y y'", true),
            vec![t(true, "x x"), t(true, "y y")]
        );
    }

    #[test]
    fn n_backslashes_handling() {
        assert_eq!(
            as_tokens(r#""\\host\path""#, false),
            vec![t(true, r"\\host\path")]
        );
        assert_eq!(
            as_tokens(r"\\host\path", false),
            vec![t(false, r"\\host\path")]
        );
        assert_eq!(
            as_tokens(r#""\\\\" *.py"#, false),
            vec![t(true, r"\\"), t(false, "*.py")]
        );
        assert_eq!(
            as_tokens(r#""\\\\\" *.py""#, false),
            vec![t(true, r#"\\" *.py"#)]
        );
        assert_eq!(
            as_tokens(r#"\\\\" *.py""#, false),
            vec![t(true, r"\\ *.py")]
        );
        assert_eq!(
            as_tokens(r#"\\\\\" *.py"#, false),
            vec![t(false, r#"\\""#), t(false, "*.py")]
        );
        assert_eq!(as_tokens("\"\\\\", false), vec![t(true, "\\\\")]);
    }

    #[test]
    fn split_helper() {
        assert_eq!(split("foo bar baz", false), vec!["foo", "bar", "baz"]);
    }
}
