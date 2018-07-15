#!/usr/bin/env python
import os
import re
import requests
import subprocess
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from collections import defaultdict

HEADERS = [
    'Major changes',
    'Backwards compatibility breaks',
    'Minor changes'
]
PREFIX = '* '
SUFFIX = ' ([#{pr_number}](../pull/{pr_number}))\n'

def request_https_get(url):
    """
    Make HTTPS GET request and return response
    """
    s = requests.Session()
    retry = Retry(total=5, read=5, connect=5, backoff_factor=0.1,
        status_forcelist=(500, 502, 503, 504))
    adapter = HTTPAdapter(max_retries=retry)
    s.mount('https://', adapter)
    r = s.get(url)
    r.raise_for_status()
    return r

def get_changelog(pr_desc):
    """
    Parse changelogs from a string

    pr_desc should be a string or list or lines of the pull request
    description.

    Returns a tuple (status, message, changelogs), where:

    - status is a boolean indicating if the changelog entry is valid or not
    - message is a string with a message to be reported changelogs is a dict
    - mapping headers to changelog messages

    """
    status = True
    message_list = []
    changelogs = defaultdict(list)
    current = None
    header = None
    if isinstance(pr_desc, (str, bytes)):
        pr_desc = pr_desc.splitlines()
    lines = iter(pr_desc)

    # First find the release notes header
    for line in lines:
        if line.strip() == "<!- BEGIN RELEASE NOTES ->":
            break
    else:
        return (False, "The `<!- BEGIN RELEASE NOTES ->` block was not found",
                changelogs)

    for line in lines:
        if line.strip() == "<!- END RELEASE NOTES ->":
            break
        if 'Add entry(ies)' in line:
            _, answer = line.split('?', 1)
            answer = re.sub('[^a-zA-Z]+', '', answer).lower()
            if answer in ['no', 'n', 'false', 'f']:
                message_list += ['Skipping changelog']
                status = False
            break
        elif line.startswith('*'):
            _, header = line.split('*', 1)
            header = header.strip()
        else:
            if not header:
                message_list += [
                    'No subheader found. Please add a header for',
                    'the module, for example,',
                    '',
                    '```',
                    '* solvers',
                    '  * improve solving of trig equations',
                    '```',
                ]
                status = False
                break
            changelogs[header].append(line)
    else:
        if not changelogs:
            message_list += ['No changelog was detected. If there is no',
                             'changelog entry, please write `NO ENTRY` in the',
                             'PR description under `<!- BEGIN RELEASE NOTES ->`.']
        status = False

    count = sum(len(changelogs[t]) for t in changelogs)
    if count == 0:
        message_list += ['Changelog not found! Please add a changelog.']
        status = False
    message_list += ['%s changelog entr%s found!' % (count, 'y' if count == 1 else 'ies')]
    return status, '\n'.join(message_list), changelogs

def get_release_notes_filename():
    """
    Return filename of release notes for current development version
    """
    import sympy
    v = re.match(r'\d+(?:(?:\.\d+)*(?:\.[1-9]\d*)|\.0)', sympy.__version__).group()
    return 'Release-Notes-for-' + v + '.md'

def update_release_notes(rel_notes_path, changelogs, pr_number):
    """
    Update release notes
    """
    rel_notes = open(rel_notes_path, 'r+')
    contents = rel_notes.readlines()

    current = None
    for i in range(len(contents)):
        line = contents[i].strip()
        is_empty = (not line or line == '*')
        if line.startswith('## '):
            # last heading is assumed to be not a changelog header
            if changelogs[current]:
                suffix = SUFFIX.format(pr_number=pr_number)
                entry = (PREFIX + (suffix + PREFIX).join(changelogs[current]) +
                    suffix + '\n')
                if not is_prev_empty:
                    contents[i] = contents[i] + entry
                else:
                    contents[n] = entry
            for header in HEADERS:
                if header in line:
                    current = header
                    break
        elif current and not is_prev_empty and is_empty:
            n = i
        is_prev_empty = is_empty

    rel_notes.seek(0)
    rel_notes.writelines(contents)
    rel_notes.truncate()
    rel_notes.close()

if __name__ == '__main__':
    ON_TRAVIS = os.environ.get('TRAVIS', 'false') == 'true'

    if ON_TRAVIS:
        pr_number = get_build_information()
    else:
        while True:
            test_repo = input("Enter GitHub repository name: ")
            if test_repo.count("/") == 1:
                os.environ['TRAVIS_REPO_SLUG'] = test_repo
                break
        while True:
            pr_number = input("Enter PR number: ")
            if pr_number.isdigit():
                break

    pr_desc = get_pr_desc(pr_number)
    changelogs = get_changelog(pr_desc)

    rel_notes_name = get_release_notes_filename()
    rel_notes_path = os.path.abspath(rel_notes_name)

    if not ON_TRAVIS:
        print(green('Parsed changelogs:'))
        print(str(changelogs))
        print(green('Downloading %s' % rel_notes_name))
        r = request_https_get('https://raw.githubusercontent.com/wiki/' +
            os.environ['TRAVIS_REPO_SLUG'] + '/' + rel_notes_name)
        with open(rel_notes_path, 'w') as f:
            f.write(r.text)

    print(green('Updating %s' % rel_notes_path))
    update_release_notes(rel_notes_path, changelogs, pr_number)

    if ON_TRAVIS:
        print(green('Staging updated release notes'))
        command = ['git', 'add', rel_notes_path]
        print(blue(' '.join(command)))
        subprocess.run(command, check=True)