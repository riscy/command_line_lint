"""Command-Line Lint --- lint your command-line history.

Author: Chris Rayner (dchrisrayner@gmail.com)
Created: December 28 2018
URL: https://github.com/riscy/command_line_lint
Version: 0.0.0

This software is licensed under the permissive MIT License.

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
from collections import Counter
from subprocess import check_output, CalledProcessError

# parametrize the length and format of the report
NUM_COMMANDS = 5
NUM_WITH_ARGUMENTS = 5
NUM_SHELLCHECK = 10
ENV_WIDTH = 20

# define the colors of the report (or none), per https://no-color.org
NO_COLOR = os.environ.get('NO_COLOR')
COLOR_DEFAULT = '' if NO_COLOR else '\033[0m'
COLOR_HEADER = '' if NO_COLOR else '\033[7m'
COLOR_WARN = '' if NO_COLOR else '\033[31m'
COLOR_INFO = '' if NO_COLOR else '\033[32m'
COLOR_TIP = '' if NO_COLOR else '\033[33m'

# shellcheck errors and warnings that are not relevant;
SC_IGNORE = [
    1089,  # https://github.com/koalaman/shellcheck/wiki/SC1089
    1090,  # https://github.com/koalaman/shellcheck/wiki/SC1090
    1091,  # https://github.com/koalaman/shellcheck/wiki/SC1091
    1117,  # https://github.com/koalaman/shellcheck/wiki/SC1091
    2103,  # https://github.com/koalaman/shellcheck/wiki/SC2103
    2148,  # https://github.com/koalaman/shellcheck/wiki/SC2148
    2154,  # https://github.com/koalaman/shellcheck/wiki/SC2154
    2164,  # https://github.com/koalaman/shellcheck/wiki/SC2164
    2224,  # https://github.com/koalaman/shellcheck/wiki/SC2224
    2230,  # https://github.com/koalaman/shellcheck/wiki/SC2230
]


def report_overview(commands):
    """Report on some common environment settings, etc."""
    _print_header("Overview", newline=False)
    _print_environment_variable('SHELL')
    _print_environment_variable('HISTFILE', using=_history_file())
    _lint_lengths_of_commands(commands)
    _lint_histfile()
    _print_environment_variable('HISTSIZE')
    _lint_histsize()
    if _shell() in {'bash', 'sh'}:
        _print_environment_variable('HISTFILESIZE')
        _lint_bash_histfilesize()
        _print_environment_variable('HISTIGNORE')
        _print_environment_variable('HISTCONTROL')
        _lint_bash_histcontrol()
        _lint_bash_histappend()
    elif _shell() == 'zsh':
        _print_environment_variable('SAVEHIST')
        _lint_zsh_savehist()
        _print_environment_variable('HISTORY_IGNORE')
        _lint_zsh_dupes()
        _lint_zsh_histappend()


def report_top_commands(commands, top_n=NUM_COMMANDS):
    """Report user's {top_n} favorite commands."""
    _print_header("Top {}".format(top_n))
    prefix_count = Counter(cmd.split()[0] for cmd in commands if ' ' in cmd)
    for prefix, count in prefix_count.most_common(top_n):
        _print_command_stats(prefix, count, len(commands))


def report_top_commands_with_args(commands, top_n=NUM_WITH_ARGUMENTS):
    """Report user's {top_n} most common commands (with args)."""
    _print_header("Top {} with arguments".format(top_n))
    for cmd, count in Counter(commands).most_common(top_n):
        _print_command_stats(cmd, count, len(commands))
        if not _is_in_histignore(cmd):
            sum(
                lint(cmd, count, len(commands)) for lint in [
                    _lint_command_alias,
                    _lint_command_ignore,
                ])


def report_miscellaneous(commands):
    """Report for some miscellaneous issues."""
    _print_header('Miscellaneous')
    for lint in [
            _lint_command_rename,
            _lint_command_cd_home,
    ]:
        any(lint(cmd) for cmd in set(commands))


def report_shellcheck(top_n=NUM_SHELLCHECK):
    """Report containing lints from 'Shellcheck'."""
    _print_header('Shellcheck')
    if not _is_shellcheck_installed():
        print('Shellcheck not installed - see https://www.shellcheck.net')
        return
    try:
        check_output([
            'shellcheck',
            "--exclude={}".format(','.join(str(cc) for cc in SC_IGNORE)),
            "--shell={}".format(_shell()),
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


def _info(info, arrow_at=0):
    print(COLOR_INFO + _arrow(arrow_at) + info + COLOR_DEFAULT)


def _tip(tip, arrow_at=0):
    print(COLOR_TIP + _arrow(arrow_at) + tip + COLOR_DEFAULT)


def _warn(warn, arrow_at=0):
    print(COLOR_WARN + _arrow(arrow_at) + warn + COLOR_DEFAULT)


def _arrow(arrow_at=0):
    return ' ' * arrow_at + '^-- '


def _print_header(header, newline=True):
    if newline:
        print('')
    print(COLOR_HEADER + header.center(79) + COLOR_DEFAULT)


def _print_environment_variable(var, using=''):
    value = '"' + os.environ.get(var) + '"' if var in os.environ else 'UNSET'
    if using:
        value += ' -- using "{}"'.format(using)
    print("{}=> {}".format(var.ljust(ENV_WIDTH), value))


def _print_command_stats(cmd, count, total):
    cmd = cmd.ljust(39)
    percent = "{}%".format(round(100 * count / total, 1)).rjust(20)
    times = "{}/{}".format(count, total).rjust(20)
    print("{}{}{}".format(cmd, percent, times))


def _lint_command_alias(cmd, count, total):
    if (cmd in str(check_output([_shell(), '-i', '-c', 'alias'])) or count < 2
            or total / count > 20 or ' ' not in cmd):
        return False
    suggestion = ''.join(
        word[0] for word in cmd.split() if re.match(r'\w', word))
    _tip('Consider using an alias: alias {}="{}"'.format(suggestion, cmd))
    return True


def _lint_command_cd_home(cmd):
    if _standardize(cmd) in {'cd ~', 'cd ~/', 'cd $HOME'}:
        print(cmd)
        _tip('"cd" is sufficient to move to your home directory', arrow_at=3)
        return True
    return False


def _lint_command_ignore(cmd, count, total):
    if len(cmd) >= 4 or count < 2 or total / count > 20:
        return False
    if _shell() in {'bash', 'sh'}:
        _tip('Consider adding frequent but short commands to HISTIGNORE')
        return True
    if _shell() == 'zsh':
        _tip('Consider adding frequent but short commands to HISTORY_IGNORE')
        return True
    return False


def _lint_command_rename(cmd):
    short_enough = 0.80
    tokens = cmd.split()
    if len(tokens) != 3 or tokens[0] not in {'mv', 'cp'}:
        return False
    prefix, arg1, arg2 = tokens
    match = difflib.SequenceMatcher(a=arg1, b=arg2)\
                   .find_longest_match(0, len(arg1), 0, len(arg2))
    if match.a == 0 and match.b == 0:
        new_cmd = "{}{{{},{}}}".format(
            arg1[match.a:match.a + match.size],
            arg1[match.a + match.size:],
            arg2[match.b + match.size:],
        )
        if float(len(new_cmd)) / len(cmd) <= short_enough:
            print(' '.join(tokens))
            _info('It can be shorter to write "{} {}"'.format(prefix, new_cmd),
                  len(prefix) + 1)
            return True
    return False


def _lint_lengths_of_commands(commands):
    output = "Commands average {} characters with ".format(
        int(sum(len(cmd) for cmd in commands) / len(commands)))
    args = int(sum(len(cmd.split()) - 1 for cmd in commands) / len(commands))
    output += '1 argument' if args == 1 else "{} arguments".format(args)
    _info(output, ENV_WIDTH + 3)


def _lint_bash_histappend():
    if _shell() not in {'bash', 'sh'}:
        return
    histappend = check_output([_shell(), '-i', '-c', 'shopt']).decode('utf-8')
    if re.search(r'histappend[ \t]+off', histappend):
        _tip('Run "shopt -s histappend" to retain more history')


def _lint_bash_histcontrol():
    if _shell() not in {'bash', 'sh'}:
        return
    histcontrol = os.environ.get('HISTCONTROL', '')
    if 'ignoredups' in histcontrol or 'erasedups' in histcontrol:
        _tip(
            'Remove "ignoredups" and "erasedups" to retain more history',
            arrow_at=ENV_WIDTH + 3)


def _lint_bash_histfilesize():
    if _shell() not in {'bash', 'sh'}:
        return
    indent = ENV_WIDTH + 3
    filesize_val = int(os.environ.get('HISTFILESIZE', '0'))
    if filesize_val < 5000:
        _tip('Increase/set HISTFILESIZE to retain more history', indent)
    if filesize_val < int(os.environ.get('HISTSIZE', '0')):
        _tip('Set HISTFILESIZE >= HISTSIZE', indent)


def _lint_zsh_histappend():
    if _shell() != 'zsh':
        return
    setopt = check_output([_shell(), '-i', '-c', 'setopt']).decode('utf-8')
    if 'noappendhistory' in setopt:
        _tip('Run "setopt appendhistory" to retain more history')


def _lint_zsh_savehist():
    if _shell() != 'zsh':
        return
    indent = ENV_WIDTH + 3
    filesize_val = int(os.environ.get('SAVEHIST', '0'))
    if filesize_val < 5000:
        _tip('Increase/set SAVEHIST to retain more history', indent)
    if filesize_val < int(os.environ.get('HISTSIZE', '0')):
        _tip('Set SAVEHIST >= HISTSIZE', indent)


def _lint_zsh_dupes():
    if _shell() != 'zsh':
        return
    setopt = str(check_output([_shell(), '-i', '-c', 'setopt']))
    if 'histignorealldups' not in setopt:
        _tip('Run "unsetopt histignorerealdups" to retain more history')


def _lint_histfile():
    history_file = _history_file()
    st_mode = os.stat(history_file).st_mode
    if st_mode & stat.S_IROTH or st_mode & stat.S_IRGRP:
        _warn(
            'Other users can read this file! '
            'Run "chmod 600 {}"'.format(history_file),
            ENV_WIDTH + 3,
        )


def _lint_histsize():
    histsize_val = int(os.environ.get('HISTSIZE', '0'))
    if histsize_val < 5000:
        _tip('Increase/set HISTSIZE to retain history', ENV_WIDTH + 3)


def _history_file():
    home = os.path.expanduser('~')
    if len(sys.argv) > 1:
        history_file = sys.argv[1]
    elif os.environ.get('HISTFILE'):
        # typical zsh:
        history_file = os.path.join(home, os.environ.get('HISTFILE'))
    elif _shell() == 'bash':
        history_file = os.path.join(home, '.bash_history')
    else:
        # typical .csh or .tcsh:
        history_file = os.path.join(home, '.history')
    if not os.path.isfile(history_file):
        _warn('History file "{}" not found.'.format(history_file))
        sys.exit(1)
    return history_file


def _shell():
    return os.path.basename(os.environ.get('SHELL'))


def _is_shellcheck_installed():
    try:
        check_output(['shellcheck', '-V'])
        return True
    except CalledProcessError:
        return False


def _is_in_histignore(cmd):
    return _standardize(cmd) in os.environ.get('HISTIGNORE', '').split(':')


def _remove_prefix(text, regexp):
    match = re.search("^{}".format(regexp), text)
    if not match or not text.startswith(match.group(0)):
        return text
    return text[len(match.group(0)):]


def _standardize(cmd):
    return ' '.join(cmd.split())


def main():
    """Run all reports."""
    with open(_history_file()) as stream:
        commands = [
            cmd.strip() for cmd in stream.readlines()
            if cmd.strip() and not cmd.startswith('#')
        ]
    report_overview(commands)
    report_top_commands(commands)
    report_top_commands_with_args(commands)
    report_miscellaneous(commands)
    report_shellcheck()


if __name__ == '__main__':
    main()
