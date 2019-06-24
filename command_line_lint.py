#!/usr/bin/env python
"""Command-Line Lint --- lint your command-line history.

Author: Chris Rayner (dchrisrayner@gmail.com)
Created: December 28 2018
URL: https://github.com/riscy/command_line_lint
Version: 0.0.0

This software is licensed under the conditions described here:
https://github.com/riscy/command_line_lint/blob/master/LICENSE

This script generates a simple report against your command-line history and
suggests workflow improvements.  It has the opinion that most of the commands
you type should be simple and require minimal typing.  The report will contain:

- comprehensive lists of commands you use, with and without arguments
- suggestions for ways to shorten commands (aliases, alternative syntax)
- a subset of lints from Shellcheck (if it's installed); many of these are
  useful and can warn against dangerous habits
"""
from __future__ import print_function

import re
import os
import stat
import sys
import difflib
import io
from distutils import spawn  # pylint: disable=no-name-in-module
from collections import Counter, defaultdict
from subprocess import check_output, CalledProcessError

# define the colors of the report (or none), per https://no-color.org
NO_COLOR = os.environ.get('NO_COLOR')
COLOR_DEFAULT = '' if NO_COLOR else '\033[0m'
COLOR_HEADER = '' if NO_COLOR else '\033[7m'
COLOR_WARN = '' if NO_COLOR else '\033[31m'
COLOR_INFO = '' if NO_COLOR else '\033[32m'
COLOR_TIP = '' if NO_COLOR else '\033[33m'

# shellcheck errors and warnings that are not relevant;
SC_IGNORE = [
    1036,  # https://github.com/koalaman/shellcheck/wiki/SC1036
    1078,  # https://github.com/koalaman/shellcheck/wiki/SC1078
    1079,  # https://github.com/koalaman/shellcheck/wiki/SC1079
    1088,  # https://github.com/koalaman/shellcheck/wiki/SC1088
    1089,  # https://github.com/koalaman/shellcheck/wiki/SC1089
    1090,  # https://github.com/koalaman/shellcheck/wiki/SC1090
    1091,  # https://github.com/koalaman/shellcheck/wiki/SC1091
    1117,  # https://github.com/koalaman/shellcheck/wiki/SC1117
    2034,  # https://github.com/koalaman/shellcheck/wiki/SC2034
    2103,  # https://github.com/koalaman/shellcheck/wiki/SC2103
    2148,  # https://github.com/koalaman/shellcheck/wiki/SC2148
    2154,  # https://github.com/koalaman/shellcheck/wiki/SC2154
    2164,  # https://github.com/koalaman/shellcheck/wiki/SC2164
    2224,  # https://github.com/koalaman/shellcheck/wiki/SC2224
    2230,  # https://github.com/koalaman/shellcheck/wiki/SC2230
]


def report_overview():
    """Report on some common environment settings, etc."""
    _print_header("Overview", newline=False)
    _print_history_file_stats()
    _print_environment_variable('SHELL')
    if _shell() in {'bash', 'sh'}:
        lint_bash_options()
        _print_environment_variable('HISTSIZE')
        _print_environment_variable('HISTFILESIZE')
        _print_environment_variable('HISTCONTROL')
        _print_environment_variable('HISTIGNORE')
    elif _shell() == 'zsh':
        lint_zsh_options()
        _print_environment_variable('HISTSIZE')
        _print_environment_variable('SAVEHIST')
        _print_environment_variable('HISTORY_IGNORE')


def report_top_commands(commands, top_n=3):
    """Report user's {top_n} favorite commands."""
    _print_header("Top {}".format(top_n))
    prefix_count = Counter(cmd.split()[0] for cmd in commands if ' ' in cmd)
    for prefix, count in prefix_count.most_common(top_n):
        _print_command_stats(prefix, count, len(commands))


def report_top_commands_with_args(commands, top_n=10):
    """Report user's {top_n} most common commands (with args)."""
    _print_header("Top {} with arguments".format(top_n))
    for cmd, count in Counter(commands).most_common(top_n):
        _print_command_stats(cmd, count, len(commands))
        if not _is_ignored(cmd):
            for lint in LintCommand.favorite_lints:
                lint(cmd, count, len(commands))


def report_command_line(commands):
    """Miscellaneous tips to improve command-line usage."""
    _print_header('Command-line tips')
    for num, lints in LintCommand.lints.items():
        for lint in lints:
            any(
                lint(commands[ii:ii + num])
                for ii in range(len(commands) - num + 1))


def report_shellcheck(top_n=10):
    """Report containing lints from 'Shellcheck'."""
    _print_header('Shellcheck')

    shell = _shell()
    if not _is_shellcheck_installed():
        print('Install Shellcheck at https://www.shellcheck.net'.center(79))
        return
    if shell not in {'bash', 'sh'}:
        print('<No support for {}; spoofing as bash>'.format(shell).center(79))
        shell = 'bash'
    try:
        check_output([
            'shellcheck',
            "--exclude={}".format(','.join(str(cc) for cc in SC_IGNORE)),
            "--shell={}".format(shell),
            _history_file(),
        ])
        print('Nothing to report.')
        return
    except CalledProcessError as err:
        # non-zero exit status means we may have found some warnings
        shellcheck_errors = err.output.decode('utf-8').strip().split('\n\n')
    old_errors = set()
    for error in shellcheck_errors:
        errors = (cc for cc in re.findall(r"SC([0-9]{4}):", error))
        new_errors = [cc for cc in errors if cc not in old_errors][:top_n]
        if new_errors:
            old_errors = old_errors.union(new_errors)
            print(
                re.sub(
                    r'(\^-- .*)',
                    "{}\\1{}".format(COLOR_TIP, COLOR_DEFAULT),
                    _remove_prefix(error.strip(), r'In .* line .*:\n'),
                ))


class LintVariable():
    """Register functions that lint an environment variable."""
    # pylint: disable=bad-option-value,old-style-class
    # pylint: disable=too-few-public-methods
    lints = defaultdict(list)

    def __init__(
            self,
            variable,
    ):
        self.variable = variable

    def __call__(self, lint):
        self.lints[self.variable].append(lint)
        return lint


class LintCommand():
    """Register functions that lint a command or command sequence."""
    # pylint: disable=bad-option-value,old-style-class
    # pylint: disable=too-few-public-methods
    lints = defaultdict(list)
    favorite_lints = []

    def __init__(
            self,
            num_commands_in_sequence=1,
            only_if_frequently_used=False,
    ):
        self.num_commands_in_sequence = num_commands_in_sequence
        self.only_if_frequently_used = only_if_frequently_used

    def __call__(self, lint):
        if self.only_if_frequently_used:
            self._add_lint_for_frequent_command(lint)
        else:
            self._add_lint(lint)
        return lint

    def _add_lint(self, lint):
        def lint_single(commands):
            """Convenience function to unwrap a list with one element."""
            return lint(commands[0])

        if self.num_commands_in_sequence == 1:
            self.lints[self.num_commands_in_sequence].append(lint_single)
        else:
            self.lints[self.num_commands_in_sequence].append(lint)

    def _add_lint_for_frequent_command(self, lint):
        def lint_if_frequently_used(command, count, total):
            """Only run lint if command is frequently used."""
            if count >= 2 and total / count <= 25:
                lint(command)

        self.favorite_lints.append(lint_if_frequently_used)


@LintCommand()
def cd_to_home_directory(cmd):
    """Advise dropping superfluous arguments to cd."""
    if cmd in {'cd ~', 'cd ~/', 'cd $HOME'}:
        _show_commands(cmd)
        _tip('"cd" is sufficient to move to your home directory', arrow_at=3)
        return True
    return False


@LintCommand()
def clear_has_keyboard_shortcut(cmd):
    """Advise using keyboard shortcuts when available."""
    if cmd in {'clear'}:
        _show_commands(cmd)
        _info('A common keyboard shortcut for "clear" is Ctrl-L')
        return True
    return False


@LintCommand()
def dont_pipe_wget_into_shell(cmd):
    """Advise user to avoid dangerous 'wget | sh'-style pipes."""
    if re.search(r'wget [^|]+\|\s*(bash|sh|zsh|tcsh|csh)', cmd):
        _show_commands(cmd)
        _warn("Don't pipe wget into a shell; mistakes can be costly",
              cmd.find('|'))
        return True
    return False


@LintCommand()
def reuse_common_substrings(cmd):
    """Reuse parts of the argument list within a command."""
    tokens = cmd.split()
    if len(tokens) != 3:
        return False
    prefix, arg1, arg2 = tokens
    match = difflib.SequenceMatcher(a=arg1, b=arg2)\
                   .find_longest_match(0, len(arg1), 0, len(arg2))
    if match.a == 0 and match.b == 0:
        shorter_args = "{}{{{},{}}}".format(
            arg1[match.a:match.a + match.size],
            arg1[match.a + match.size:],
            arg2[match.b + match.size:],
        )
        if float(len(prefix) + len(shorter_args) + 1) / len(cmd) <= 0.80:
            _show_commands(cmd)
            _tip(
                'Arguments have common substrings; try: "{} {}"'.format(
                    prefix, shorter_args),
                len(prefix) + 1)
            return True
    return False


@LintCommand(num_commands_in_sequence=2)
def reuse_suffix(commands):
    """Reuse the entire argument list between commands."""
    first_cmd, second_cmd = [cmd.split() for cmd in commands]
    if (first_cmd == second_cmd or not first_cmd[1:] or not second_cmd[1:]
            or first_cmd[1:] != second_cmd[1:]):
        return False
    shorter_cmd = ' '.join([second_cmd[0], '!$'])
    if len(shorter_cmd) > len(' '.join(second_cmd)) / 2:
        return False
    _show_commands(commands)
    _tip('Try reusing the first command\'s suffix: "{}"'.format(shorter_cmd),
         len(first_cmd[0]) + 1)
    return True


@LintCommand(num_commands_in_sequence=3)
def dont_mkdir_cd_mkdir(commands):
    """Suggest mkdir -p when appropriate."""
    first_cmd, second_cmd, third_cmd = [cmd.split() for cmd in commands]
    if (first_cmd[0] == 'mkdir' and second_cmd[0] == 'cd'
            and first_cmd[-1] == second_cmd[-1] and third_cmd[0] == 'mkdir'):
        _show_commands(commands)
        _tip('Create nested directories with "mkdir -p {}/{}"'.format(
            first_cmd[-1], third_cmd[1]))
        return True
    return False


@LintCommand(only_if_frequently_used=True)
def consider_an_alias(cmd):
    """Suggest an alias."""
    if len(cmd) < 5:
        return
    suggestion = ''.join(
        word[0] for word in cmd.split() if re.match(r'\w', word))
    _tip('Consider using an alias: alias {}="{}"'.format(suggestion, cmd))


@LintCommand(num_commands_in_sequence=2)
def consider_zless_or_zcat(commands):
    """Suggest mkdir -p when appropriate."""
    first_cmd, second_cmd = [cmd.split() for cmd in commands]
    if (first_cmd[0] in ['gzip', 'uncompress']
            and second_cmd[0] in ['cat', 'less']
            and second_cmd[-1] in first_cmd[-1]):
        _show_commands(commands)
        _tip('Consider zless or zcat: "zless {}"'.format(second_cmd[-1]))
        return True
    return False


@LintCommand(only_if_frequently_used=True)
def ignore_short_commands(cmd):
    """Advise ignoring frequent, short commands."""
    if len(cmd) > 4:
        return
    if _shell() in {'bash', 'sh'}:
        _tip('Add frequently used but short commands to HISTIGNORE')
    elif _shell() == 'zsh':
        _tip('Add frequently used but short commands to HISTORY_IGNORE')


@LintVariable('HISTSIZE')
def increase_histsize():
    """Advise user to try to keep more history!"""
    if 0 <= sanitize_env_var('HISTSIZE') < 5000:
        _tip('Increase/set HISTSIZE to retain history')


@LintVariable('HISTFILESIZE')
def increase_histfilesize():
    """Advise user to try to keep more history!"""
    filesize_val = sanitize_env_var('HISTFILESIZE')

    if 0 <= filesize_val < 5000:
        _tip('Increase/set HISTFILESIZE to retain more history')

    if filesize_val < sanitize_env_var('HISTSIZE'):
        _tip('Set HISTFILESIZE >= HISTSIZE')


@LintVariable('HISTCONTROL')
def dont_ignore_duplicates_in_bash():
    """Inform user about duplicates being removed."""
    histcontrol = os.environ.get('HISTCONTROL', '')
    if 'ignoredups' in histcontrol or 'erasedups' in histcontrol:
        _tip('Remove "ignoredups" and "erasedups" to retain more history')


@LintVariable('SAVEHIST')
def increase_savehist():
    """Advise user to try to keep more history!"""
    filesize_val = int(os.environ.get('SAVEHIST', '0'))

    if filesize_val < 5000:
        _tip('Increase/set SAVEHIST to retain more history')

    if filesize_val < sanitize_env_var('HISTSIZE'):
        _tip('Set SAVEHIST >= HISTSIZE')


def sanitize_env_var(env_var):
    """Sanitize the environment variable (e.g. if it is empty)"""
    env_var = os.environ.get(env_var, '0')

    # A value of -1 signifies unlimited size
    return int(env_var) if re.match(r'^\d+$', env_var) else -1


def lint_bash_options():
    """Lint bash options."""
    if _shell() not in {'bash', 'sh'}:
        return
    histappend = _shell_exec(['-i', '-c', 'shopt'])
    if re.search(r'histappend[ \t]+off', histappend):
        _tip('Run "shopt -s histappend" to retain more history')


def lint_zsh_options():
    """Lint zsh options."""
    if _shell() != 'zsh' or not spawn.find_executable('zsh'):
        return
    setopt = _shell_exec(['-i', '-c', 'setopt'])
    if 'noappendhistory' in setopt:
        _tip('Run "setopt appendhistory" to retain more history')
    if _shell() != 'zsh':
        return
    setopt = _shell_exec(['-i', '-c', 'setopt'])
    if 'histsavenodups' in setopt:
        _tip('Run "unsetopt HIST_SAVE_NO_DUPS" to retain more history')


def _show_commands(commands):
    if isinstance(commands, str):
        print(commands)
    elif isinstance(commands, list):
        print('; '.join(commands))


def _info(info, arrow_at=0):
    print(COLOR_INFO + _arrow(arrow_at) + info + COLOR_DEFAULT)


def _tip(tip, arrow_at=0):
    print(COLOR_TIP + _arrow(arrow_at) + tip + COLOR_DEFAULT)


def _warn(warn, arrow_at=0):
    print(COLOR_WARN + _arrow(arrow_at) + warn + COLOR_DEFAULT)


def _arrow(arrow_at=0):
    return ' ' * arrow_at + '^-- ' if arrow_at else '  * '


def _print_header(header, newline=True):
    if newline:
        print('')
    print(COLOR_HEADER + header.upper().center(79) + COLOR_DEFAULT)


def _print_environment_variable(var, using=''):
    value = '"' + os.environ.get(var) + '"' if var in os.environ else 'UNSET'
    if using:
        value += ' (using "{}")'.format(using)
    print("{}=> {}".format(var.ljust(20), value))
    for lint in LintVariable.lints[var]:
        lint()


def _print_command_stats(cmd, count, total):
    cmd = cmd.ljust(39)
    percent = "{}%".format(round(100 * count / total, 1)).rjust(20)
    times = "{}/{}".format(count, total).rjust(20)
    print("{}{}{}".format(cmd, percent, times))


def _print_history_file_stats():
    print('Using history in "{}":'.format(_history_file()))

    # Advise user to fix permissions on history file.
    st_mode = os.stat(_history_file()).st_mode
    if st_mode & stat.S_IROTH or st_mode & stat.S_IRGRP:
        _warn('Other users can read your history! '
              'Run "chmod 600 {}"'.format(_history_file()))

    # Inform user of mean length of commands, number of arguments.
    commands = _commands()
    cmd_length = int(sum(len(cmd) for cmd in commands) / len(commands))
    args = int(sum(len(cmd.split()) - 1 for cmd in commands) / len(commands))
    output = "{} commands read, ".format(len(commands))
    output += "averaging {} characters with ".format(cmd_length)
    output += '1 argument' if args == 1 else "{} arguments".format(args)
    _info(output)


def _history_file():
    home = os.path.expanduser('~')
    if len(sys.argv) > 1:
        history_file = sys.argv[1]
    elif os.environ.get('HISTFILE'):
        history_file = os.path.join(home, os.environ.get('HISTFILE'))
    # typical zsh:
    elif _shell() == 'zsh':
        history_file = os.path.join(home, '.zsh_history')
    elif _shell() == 'bash':
        history_file = os.path.join(home, '.bash_history')
    else:
        # typical .csh or .tcsh:
        history_file = os.path.join(home, '.history')
    if not os.path.isfile(history_file):
        _warn('History file "{}" not found.'.format(history_file))
        sys.exit(1)
    return history_file


def _commands():
    with io.open(_history_file(), errors='replace') as stream:
        return [
            _normalize(cmd) for cmd in stream.readlines() if _normalize(cmd)
        ]


def _normalize(cmd):
    # Squash extra whitespace
    cmd = ' '.join(cmd.split())

    # Remove timestamps from commands in zsh's timestamped history
    if _shell() == 'zsh':
        cmd = re.sub(r'^: \d+:\d+;', '', cmd, count=1)

    # Drop command if it was a comment.
    return '' if cmd.startswith('#') else cmd


def _shell():
    return os.path.basename(os.environ.get('SHELL'))


def _shell_exec(args):
    """Execute {args} interactively through the _shell()."""
    if not spawn.find_executable(_shell()):
        return ''
    return check_output([_shell()] + args).decode('utf-8')


def _is_shellcheck_installed():
    try:
        check_output(['shellcheck', '-V'])
        return True
    except OSError:
        return False


def _is_ignored(cmd):
    if _shell() == 'zsh':
        return cmd in re.split(r'[()|]', os.environ.get('HISTORY_IGNORE', ''))
    if _shell() in {'bash', 'sh'}:
        return cmd in os.environ.get('HISTIGNORE', '').split(':')
    return False


def _remove_prefix(text, regexp):
    match = re.search("^{}".format(regexp), text)
    if not match or not text.startswith(match.group(0)):
        return text
    return text[len(match.group(0)):]


def main():
    """Run all reports."""
    commands = _commands()
    report_overview()
    report_top_commands(commands)
    report_top_commands_with_args(commands)
    report_command_line(commands)
    report_shellcheck()


if __name__ == '__main__':
    main()
