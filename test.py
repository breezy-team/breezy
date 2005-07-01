from bzrlib.commands import Command

class cmd_test_plugins(Command):
    """Test every plugin that supports tests.

    """
    takes_args = []
    takes_options = []

    def run(self):
        import read_changeset
        read_changeset.test()
