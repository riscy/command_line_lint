# pylint: disable=missing-docstring
import os
import unittest
import command_line_lint


class TestCommandLineLint(unittest.TestCase):
    def setUp(self):
        self.reset()
        os.environ['NO_COLOR'] = '1'
        # pylint: disable=protected-access
        command_line_lint._tip = self.track_tip
        command_line_lint._info = self.track_tip
        command_line_lint._warn = self.track_tip
        command_line_lint._show_commands = lambda noop: noop

    def test_increase_savehist(self):
        os.environ['SAVEHIST'] = '10'
        os.environ['HISTSIZE'] = '5'
        command_line_lint.increase_savehist()
        assert 'Increase/set SAVEHIST to retain more history' in self.tips
        assert len(self.tips) == 1

    def test_savehist_gt_histsize(self):
        os.environ['SAVEHIST'] = '5'
        os.environ['HISTSIZE'] = '10'
        command_line_lint.increase_savehist()
        assert 'Increase/set SAVEHIST to retain more history' in self.tips
        assert 'Set SAVEHIST >= HISTSIZE' in self.tips
        assert len(self.tips) == 2

    def test_savehist_ok(self):
        os.environ['SAVEHIST'] = '10000'
        os.environ['HISTSIZE'] = '10000'
        command_line_lint.increase_savehist()
        assert not self.tips

    def test_reuse_suffix(self):
        command_line_lint.reuse_suffix([
            'ls long/path/to/dir',
            'cd long/path/to/dir',
        ])
        assert self.tips

    def test_consider_zless_or_zcat(self):
        command_line_lint.consider_zless_or_zcat([
            'gzip -d some_file.txt.gzip',
            'less some_file.txt',
        ])
        assert self.tips
        self.reset()
        # command arguments don't match - no tips:
        command_line_lint.consider_zless_or_zcat([
            'gzip -d some_file.txt.gzip',
            'less some_other_file.txt',
        ])
        assert not self.tips

    def reset(self):
        self.tips = []

    def track_tip(self, tip, _arrow_at=0):
        self.tips.append(tip)
