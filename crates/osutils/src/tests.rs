use crate::chunks_to_lines;

fn assert_chunks_to_lines(input: Vec<&str>, expected: Vec<&str>) {
    let iter = input.iter().map(|l| Ok::<&[u8], String>(l.as_bytes()));
    let got = chunks_to_lines(iter);
    let got = got.map(|l| String::from_utf8(l.unwrap())).collect::<Result<Vec<_>, _>>().unwrap();
    assert_eq!(got, expected);
}

#[test]
fn test_chunks_to_lines() {
    assert_chunks_to_lines(vec!["a"], vec!["a"]);
    assert_chunks_to_lines(vec!["a\n"], vec!["a\n"]);
    assert_chunks_to_lines(vec!["a\nb\n"], vec!["a\n", "b\n"]);
    assert_chunks_to_lines(vec!["a\n", "b\n"], vec!["a\n", "b\n"]);
    assert_chunks_to_lines(vec!["a", "\n", "b", "\n"], vec!["a\n", "b\n"]);
    assert_chunks_to_lines(vec!["a", "a", "\n", "b", "\n"], vec!["aa\n", "b\n"]);
    assert_chunks_to_lines(vec![""], vec![]);
}
