use std::collections::HashMap;
use crate::ParentMap;
use crate::invert_parent_map;

#[test]
fn test_invert_parent_map() {
    let mut pm = HashMap::new();

    pm.insert(1, vec![2, 3]);
    pm.insert(2, vec![4, 5]);
    pm.insert(3, vec![]);
    pm.insert(4, vec![]);
    pm.insert(5, vec![]);

    let rpm: ParentMap<&[u8], &[&[u8]]> = pm
        .iter()
        .map(|(k, v)| (k.as_bytes(), v.iter().map(|x| x.as_bytes()).collect::<Vec<_>>()))

    let reverse = invert_parent_map(&pm);

    let mut expected = HashMap::new();
    expected.insert(&2, vec![&1]);
    expected.insert(&3, vec![&1]);
    expected.insert(&4, vec![&2]);
    expected.insert(&5, vec![&2]);

    assert_eq!(reverse, expected);
}
