use std::collections::HashSet;

static mut DEBUG_FLAGS: once_cell::sync::Lazy<HashSet<String>> =
    once_cell::sync::Lazy::new(HashSet::<String>::new);

pub fn set_debug_flag(flag: &str) {
    unsafe {
        DEBUG_FLAGS.insert(flag.to_string());
    }
}

pub fn unset_debug_flag(flag: &str) {
    unsafe {
        DEBUG_FLAGS.remove(flag);
    }
}

pub fn clear_debug_flags() {
    unsafe {
        DEBUG_FLAGS.clear();
    }
}

pub fn get_debug_flags() -> HashSet<String> {
    unsafe { DEBUG_FLAGS.iter().cloned().collect() }
}

pub fn debug_flag_enabled(flag: &str) -> bool {
    unsafe { DEBUG_FLAGS.contains(flag) }
}
