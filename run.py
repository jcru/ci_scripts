#!/usr/bin/env python
#
# curl -s https://raw.githubusercontent.com/rmyers/ci_scripts/master/run.py | python

import json
import os
import sys
import urllib2
import pprint
import subprocess


def puts(line, **kwargs):
    if isinstance(line, basestring):
        print(line.format(**kwargs))
    else:
        pprint.pprint(line)
    sys.stdout.flush()


puts('\n\nENVIRONMENT:')
puts(dict(os.environ))

TOKEN = os.environ.get('GITHUB_TOKEN', 'Unknown')
GITHUB = 'https://github.rackspace.com/api/v3/repos/Cloud-Database'
# the clean script on the web
CLEAN = 'https://raw.githubusercontent.com/rmyers/ci_scripts/master/clean.py'
TROVE_BIN = '/usr/share/python/trove/bin'
TROVE_PYTHON = os.path.join(TROVE_BIN, 'python')
FAB_CMD = os.path.join(TROVE_BIN, 'fab')
TROVE_FAB = '{fab} --fabfile=/Cloud-Database/fabfile.py'.format(fab=FAB_CMD)
TROVE_PIP = os.path.join(TROVE_BIN, 'pip')
PR_NUMBER = os.environ.get('PR', 'Unknown')
REPO = os.environ.get('REPO', 'Cloud-Database')
JOB_NAME = os.environ.get('JOB_NAME', 'Unknown')
BUILD_URL = os.environ.get('BUILD_URL', 'Unknown')
BUILD_ID = os.environ.get('BUILD_ID', 'Unknown')
WORKSPACE = os.environ.get('WORKSPACE', '/tmp')
DEBUG = os.environ.get('DEBUG', 'true') == 'true'
COMMAND = os.environ.get('COMMAND', 'test')
HEADERS = {'Authorization': 'token {}'.format(TOKEN)}
PREFIX = ''
# Mapping of repo to path
DIRECTORIES = {
    'Cloud-Database': WORKSPACE,
    'clouddb-puppet-v2': os.path.join(WORKSPACE, 'lib/clouddb-puppet-v2'),
}

# Submodules to update
SUBMODULES = [
    'lib/clouddb-puppet-v2',
    'lib/rackspace-monitoring',
    'lib/python-cloudlb',
    'lib/python-cinderclient',
    'lib/python-swiftclient',
    'lib/python-keystoneclient',
    'lib/python-glanceclient',
    'lib/private/python-novaclient',
    'lib/private/secrets',
]


class cd(object):
    """Run commands in a different directory."""

    def __init__(self, path):
        global PREFIX
        self.original = PREFIX
        self.path = path

    def __enter__(self, *args, **kwargs):
        global PREFIX
        PREFIX = 'cd {path} && '.format(path=self.path)

    def __exit__(self, *args, **kwargs):
        global PREFIX
        PREFIX = self.original


def call(command, **kwargs):
    command = command.format(**kwargs)
    cmd = '{prefix}{command}'.format(prefix=PREFIX, command=command)
    puts(cmd)
    return subprocess.call(cmd, shell=True)


def check_call(command, **kwargs):
    command = command.format(**kwargs)
    cmd = '{prefix}{command}'.format(prefix=PREFIX, command=command)
    puts(cmd)
    return subprocess.check_call(cmd, shell=True)


def update_status(pr, state, job_name=JOB_NAME, build_url=BUILD_URL):
    url = pr['statuses_url']

    if state == 'pending':
        description = "Stashy says check back later..."
    elif state == 'success':
        description = "Stashy says you are golden!"
    elif state == 'failure':
        description = "Stashy says better luck next time :("

    data = {
        'state': state,
        'description': description,
        'context': job_name,
        'target_url': build_url,
    }
    if DEBUG:
        puts(data)

    puts('\nSetting test state to: {state}\n', state=state)
    request = urllib2.Request(url, headers=HEADERS)
    request.add_data(json.dumps(data))
    resp = urllib2.urlopen(request)


class TestCase(object):

    template = 'test_case.xml'

    def __init__(self, name, test_cmd):
        self.name = name
        self.test_cmd = test_cmd
        self.pr = None
        self.state = 'pending'

    def fetch_pr(self, repo=REPO, number=PR_NUMBER):
        url = '{github}/{repo}/pulls/{number}'.format(
            github=GITHUB, number=number, repo=repo)
        request = urllib2.Request(url, headers=HEADERS)
        resp = urllib2.urlopen(request)
        pr = json.loads(resp.read())
        if DEBUG:
            puts('\n\nPR DATA:\n')
            puts(pr)
        return pr

    def update_submodules(self):
        with cd(WORKSPACE):
            for sub in SUBMODULES:
                check_call('git submodule update --init {sub}', sub=sub)

    def checkout_pr(self, pr):
        with cd(DIRECTORIES.get(pr['base']['repo']['name'])):
            branch = 'pull/{number}/head:{number}'.format(**pr)
            check_call('git fetch origin {branch} -f'.format(branch=branch))
            check_call('git checkout {number}', **pr)

    def setup(self):
        self.pr = self.fetch_pr()
        puts('\n\nPR {number} INFO:\n', **self.pr)
        puts('URL: {html_url}', **self.pr)
        puts('SHA: {sha}', sha=self.pr['head']['sha'])
        puts('TITLE: {title}', **self.pr)
        puts('INFO: \n{body}\n', **self.pr)
        if not self.pr['mergeable']:
            puts('\n\nTHIS PR CANNOT BE MERGED!!!\n\n')
            raise Exception('Pr Not mergeable')
        # TODO(rmyers): search body for 'DEPENDS ON:' and handle it too
        self.update_submodules()
        self.checkout_pr(self.pr)

    def clean(self):
        puts('\nCLEANING UP:\n')

    def run_tests(self):
        args = {
            'fab': TROVE_FAB,
            'pip': TROVE_PIP,
            'python': TROVE_PYTHON,
            'bin': TROVE_BIN,
            'workspace': WORKSPACE,
            'fab_args': 'tests:stop=True,white_box=True,with_xunit=True',
            'mysql_56': 'datastore=mysql,version=5.6',
            'mysql_51': 'datastore=mysql,version=5.1',
            'mariadb': 'datastore=mariadb,version=10',
            'percona': 'datastore=percona,version=5.6',
        }
        check_call(self.test_cmd, **args)

    def run(self):
        """Actually run the tests."""
        try:
            self.setup()
            self.run_tests()
            self.state = 'success'
        except:
            self.state = 'failure'
            raise
        finally:
            update_status(self.pr, state=self.state)
            self.clean()


class VMTestCase(TestCase):

    template = 'vm_test_case.xml'

    def clean(self):
        super(VMTestCase, self).clean()
        cmd = 'curl -s {clean}?build={build} | {python}'
        call(cmd, clean=CLEAN, build=BUILD_ID, python=TROVE_PYTHON)
        with cd(WORKSPACE):
            # Call clean with trove python
            call('sudo rm -rf lib')
            call('sudo rm -rf internal')

    def setup(self):
        super(VMTestCase, self).setup()
        check_call('sudo rm -rf /Cloud-database')
        check_call('sudo ln -s {work} /Cloud-database', work=WORKSPACE)
        with cd(WORKSPACE):
            check_call('sudo {p} install -e internal/cdb-utils', p=TROVE_PIP)
        check_call('/usr/local/bin/refresh-puppet')


class PullRunner(TestCase):

    template = 'pull_runner.xml'

    def __init__(self, tests):
        self.name = 'PR_Run'
        self.tests = tests
        self.test_cmd = ''
        self.pr = None
        self.state = 'pending'

    def run_tests(self):
        # Mark all the jobs as pending with no url
        for test in self.tests:
            update_status(self.pr,
                          state='pending',
                          job_name=test.name,
                          build_url=None)


TESTS = [
    TestCase(
        'X-QuickTests',
        'tox -ecover -- --xunit-file={workspace}/output/tests.xml'),
    TestCase(
        'X-Docs',
        'tox -edocs -- --xunit-file={workspace}/output/tests.xml'),
    TestCase(
        'X-Pep8',
        'tox -epep8'),
    TestCase(
        'X-Usage',
        'tox -eusage -- --xunit-file={workspace}/output/tests.xml'),
    VMTestCase(
        'X-MySQL-56',
        '{fab} {fab_args},{mysql_56},group=rax_stable'),
    VMTestCase(
        'X-MySQL-51',
        '{fab} {fab_args},{mysql_51},group=rax_stable'),
    VMTestCase(
        'X-Mariadb',
        '{fab} {fab_args},{mariadb},group=rax_stable'),
    VMTestCase(
        'X-Percona',
        '{fab} {fab_args},{percona},group=rax_stable'),
]


if __name__ == '__main__':
    # We are running in a Jenkins Job
    jobs = [PullRunner(TESTS)] + TESTS
    for test in jobs:
        if test.name == JOB_NAME:
            test.run()
