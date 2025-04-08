use once_cell::sync::Lazy;
use std::collections::HashSet;
use std::sync::RwLock;

static DEBUG_FLAGS: Lazy<RwLock<HashSet<String>>> = Lazy::new(|| {
    let initial_set = HashSet::new();
    RwLock::new(initial_set)
});

pub fn set_debug_flag(flag: &str) {
    let mut lock = DEBUG_FLAGS.write().unwrap();
    lock.insert(flag.to_string());
}

pub fn unset_debug_flag(flag: &str) {
    let mut lock = DEBUG_FLAGS.write().unwrap();
    lock.remove(flag);
}

pub fn clear_debug_flags() {
    let mut lock = DEBUG_FLAGS.write().unwrap();
    lock.clear();
}

pub fn get_debug_flags() -> HashSet<String> {
    let lock = DEBUG_FLAGS.read().unwrap();
    lock.clone()
}

pub fn debug_flag_enabled(flag: &str) -> bool {
    let lock = DEBUG_FLAGS.read().unwrap();
    lock.contains(flag)
}
