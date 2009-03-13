from cStringIO import StringIO


class RenameMap(object):

    def __init__(self):
        self.edge_hashes = {}

    @staticmethod
    def iter_edge_hashes(lines):
        modulus = 1024 * 1024 * 10
        for n in range(len(lines)):
            yield hash(tuple(lines[n:n+2])) % modulus

    def add_edge_hashes(self, lines, tag):
        for my_hash in self.iter_edge_hashes(lines):
            self.edge_hashes.setdefault(my_hash, set()).add(tag)

    def add_file_edge_hashes(self, tree, file_ids):
        desired_files = [(f, f) for f in file_ids]
        for file_id, contents in tree.iter_files_bytes(desired_files):
            s = StringIO()
            s.writelines(contents)
            s.seek(0)
            self.add_edge_hashes(s.readlines(), file_id)

    def hitcounts(self, lines):
        hits = {}
        for my_hash in self.iter_edge_hashes(lines):
            tags = self.edge_hashes.get(my_hash)
            if tags is None:
                continue
            taglen = len(tags)
            for tag in tags:
                if tag not in hits:
                    hits[tag] = 0
                hits[tag] += 1.0 / taglen
        return hits

    def get_all_hits(self, tree, paths):
        ordered_hits = []
        for path in paths:
            my_file = tree.get_file(None, path=path)
            try:
                hits = self.hitcounts(my_file.readlines())
            finally:
                my_file.close()
            ordered_hits.extend((v, path, k) for k, v in hits.items())
        return ordered_hits

    def file_match(self, tree, paths):
        seen_file_ids = set()
        seen_paths = set()
        path_map = {}
        ordered_hits = self.get_all_hits(tree, paths)
        ordered_hits.sort(reverse=True)
        for count, path, file_id in ordered_hits:
            if path in seen_paths or file_id in seen_file_ids:
                continue
            path_map[path] = file_id
            seen_paths.add(path)
            seen_file_ids.add(file_id)
        return path_map
