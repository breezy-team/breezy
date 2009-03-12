from cStringIO import StringIO


class RenameMap(object):

    def __init__(self):
        self.edge_hashes = {}

    def iter_edge_hashes(self, lines):
        for n in range(len(lines)):
            yield hash(tuple(lines[n:n+2]))

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
            for tag in tags:
                if tag not in hits:
                    hits[tag] = 0
                hits[tag] += 1
        return hits

    def file_match(self, tree, paths):
        seen = set()
        path_map = {}
        for path in paths:
            my_file = tree.get_file(None, path=path)
            try:
                hits = self.hitcounts(my_file.readlines())
            finally:
                my_file.close()
            ordered_hits = sorted([(v,k) for k, v in hits.items()
                                   if k not in seen], reverse=True)
            if len(ordered_hits) > 0:
                file_id = ordered_hits[0][1]
                path_map[path] = file_id
        return path_map
