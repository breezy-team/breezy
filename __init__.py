class MultiParent(object):

    def __init__(self):
        self.hunks = []

    @staticmethod
    def from_lines(text, parents=()):
        diff = MultiParent()
        diff.hunks.append(NewText(text))
        return diff

    @classmethod
    def from_texts(cls, text, parents=()):
        return cls.from_lines(text.splitlines(True),
                              [p.splitlines(True) for p in parents])


class NewText(object):

    def __init__(self, lines):
        self.lines = lines

    def __eq__(self, other):
        if self.__class__ is not other.__class__:
            return False
        return (other.lines == self.lines)
