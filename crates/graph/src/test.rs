use crate::tsort::TopoSorter;
use crate::Error;
use std::collections::HashMap;

#[test]
fn test_tsort_empty() {
    let graph = HashMap::new();
    assert_sort_and_iterate(&graph, &[]);
}

#[test]
fn test_tsort_easy() {
    let graph = [(0, vec![])].iter().cloned().collect();
    assert_sort_and_iterate(&graph, &[0]);
}

#[test]
fn test_tsort_cycle() {
    let graph = [(0, vec![1]), (1, vec![0])].iter().cloned().collect();
    assert_sort_and_iterate_cycle(&graph);
}

#[test]
fn test_tsort_cycle_2() {
    let graph = [(0, vec![1]), (1, vec![2]), (2, vec![0])]
        .iter()
        .cloned()
        .collect();
    assert_sort_and_iterate_cycle(&graph);
}

#[test]
fn test_topo_sort_cycle_with_tail() {
    let graph = [
        (0, vec![1]),
        (1, vec![2]),
        (2, vec![3, 4]),
        (3, vec![0]),
        (4, vec![]),
    ]
    .iter()
    .cloned()
    .collect();
    assert_sort_and_iterate_cycle(&graph);
}

#[test]
fn test_tsort_1() {
    let graph = [
        (0, vec![3]),
        (1, vec![4]),
        (2, vec![1, 4]),
        (3, vec![]),
        (4, vec![0, 3]),
    ]
    .iter()
    .cloned()
    .collect();
    assert_sort_and_iterate_order(&graph);
}

#[test]
fn test_tsort_partial() {
    let graph = vec![
        (0, vec![]),
        (1, vec![0]),
        (2, vec![0]),
        (3, vec![0]),
        (4, vec![1, 2, 3]),
        (5, vec![1, 2]),
        (6, vec![1, 2]),
        (7, vec![2, 3]),
        (8, vec![0, 1, 4, 5, 6]),
    ]
    .iter()
    .cloned()
    .collect();
    assert_sort_and_iterate_order(&graph);
}

#[test]
fn test_tsort_unincluded_parent() {
    let graph = [(0, vec![1]), (1, vec![2])].iter().cloned().collect();
    assert_sort_and_iterate(&graph, &[1, 0]);
}

fn topo_sort(graph: &HashMap<usize, Vec<usize>>) -> Result<Vec<usize>, Error<usize>> {
    TopoSorter::new(graph.clone().into_iter()).sorted()
}

fn assert_sort_and_iterate_order(graph: &HashMap<usize, Vec<usize>>) {
    let sort_result = topo_sort(graph).unwrap();

    for (node, parents) in graph {
        for parent in parents {
            if sort_result.iter().position(|&n| n == *node).unwrap()
                < sort_result.iter().position(|&n| n == *parent).unwrap()
            {
                panic!(
                    "parent {} must come before child {}:\n{:?}",
                    parent, node, sort_result
                );
            }
        }
    }
}

fn assert_sort_and_iterate_cycle(graph: &HashMap<usize, Vec<usize>>) {
    let sort_result = topo_sort(graph);
    assert!(sort_result.is_err());
}

fn assert_sort_and_iterate(graph: &HashMap<usize, Vec<usize>>, expected: &[usize]) {
    let sort_result = topo_sort(graph).unwrap();
    assert_eq!(sort_result, expected);
}
