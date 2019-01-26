# pylint: disable=missing-docstring
import os
import unittest
import command_line_lint


class TestCommandLineLint(unittest.TestCase):
    def setUp(self):
        self.reset()
        os.environ['NO_COLOR'] = '1'
        # pylint: disable=protected-access
        command_line_lint._tip = self.mock_tip
        command_line_lint._info = self.mock_tip
        command_line_lint._warn = self.mock_tip

    def test_increase_savehist(self):
        self.reset()
        os.environ['SAVEHIST'] = '10'
        os.environ['HISTSIZE'] = '5'
        command_line_lint.increase_savehist()
        assert 'Increase/set SAVEHIST to retain more history' in self.tips
        assert len(self.tips) == 1

    def test_savehist_gt_histsize(self):
        self.reset()
        os.environ['SAVEHIST'] = '5'
        os.environ['HISTSIZE'] = '10'
        command_line_lint.increase_savehist()
        assert 'Increase/set SAVEHIST to retain more history' in self.tips
        assert 'Set SAVEHIST >= HISTSIZE' in self.tips
        assert len(self.tips) == 2

    def test_savehist_ok(self):
        self.reset()
        os.environ['SAVEHIST'] = '10000'
        os.environ['HISTSIZE'] = '10000'
        command_line_lint.increase_savehist()
        assert not self.tips

    def reset(self):
        self.tips = []

    def mock_tip(self, tip):
        self.tips.append(tip)
