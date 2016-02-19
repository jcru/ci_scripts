#!/usr/bin/env python
#
# URL=https://raw.githubusercontent.com/rmyers/ci_scripts/master/run.py
# curl -s $URL | python

import json
import os
import re
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
GIT_COMMIT = os.environ.get('GIT_COMMIT')
TROVE_BIN = '/usr/share/python/trove/bin'
TROVE_PYTHON = os.path.join(TROVE_BIN, 'python')
FAB_CMD = os.path.join(TROVE_BIN, 'fab')
TROVE_FAB = '{fab} --fabfile=/Cloud-Database/fabfile.py'.format(fab=FAB_CMD)
TROVE_PIP = os.path.join(TROVE_BIN, 'pip')
PR_NUMBER = os.environ.get('PR')
REPO = os.environ.get('REPO', 'Cloud-Database')
JOB_NAME = os.environ.get('JOB_NAME', 'Unknown')
BUILD_URL = os.environ.get('BUILD_URL', 'Unknown')
BUILD_ID = os.environ.get('BUILD_ID', 'Unknown')
WORKSPACE = os.environ.get('WORKSPACE', '/tmp')
DEBUG = os.environ.get('DEBUG', 'true') == 'true'
HEADERS = {'Authorization': 'token {}'.format(TOKEN)}
PREFIX = ''
DEPENDS = re.compile('https://github.rackspace.com/[^/]+/([^/]+)/pull/(\d+)')
# Mapping of repo to path
DIRECTORIES = {
    'Cloud-Database': WORKSPACE,
    'clouddb-puppet-v2': os.path.join(WORKSPACE, 'lib/clouddb-puppet-v2'),
    'nova': os.path.join(WORKSPACE, 'lib/nova'),
    'cinder': os.path.join(WORKSPACE, 'lib/cinder'),
    'glance': os.path.join(WORKSPACE, 'lib/glance'),
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
    'lib/nova',
    'lib/cinder',
]

# Log file locations
LOGS = [
    '/var/log/trove',
    '/var/log/nova',
    '/var/log/cinder',
    '/var/log/cdbproxy',
    '/var/log/cdbproxy-endpoint',
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


def status_url(pr):
    if pr is None:
        return os.path.join(GITHUB, 'Cloud-Database', 'statuses', GIT_COMMIT)
    return pr['statuses_url']


def update_status(pr, state, job_name=JOB_NAME, build_url=BUILD_URL):
    url = status_url(pr)

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


def fetch_pr(repo=REPO, number=PR_NUMBER):
    if number is None:
        return
    url = '{github}/{repo}/pulls/{number}'.format(
        github=GITHUB, number=number, repo=repo)
    request = urllib2.Request(url, headers=HEADERS)
    resp = urllib2.urlopen(request)
    pr = json.loads(resp.read())
    if DEBUG:
        puts('\n\nPR DATA:\n')
        puts(pr)
    return pr


def parse_depends(body):
    for pull in DEPENDS.finditer(body):
        yield fetch_pr(*pull.groups())


class TestCase(object):

    template = 'test_case.xml'

    def __init__(self, name, test_cmd, xunit=True):
        self.name = name
        self.test_cmd = test_cmd
        self.pr = None
        self.xunit = xunit
        self.state = 'pending'

    def update_submodules(self):
        with cd(WORKSPACE):
            for sub in SUBMODULES:
                check_call('git submodule update --init {sub}', sub=sub)

    def checkout_pr(self, pr):
        with cd(DIRECTORIES.get(pr['base']['repo']['name'])):
            branch = 'pull/{number}/head:{number}'.format(**pr)
            check_call('git fetch origin {branch} -f'.format(branch=branch))
            check_call('git merge {number}', **pr)

    def setup(self):
        self.pr = fetch_pr()
        if self.pr is None:
            self.update_submodules()
            puts('\n\nTesting HEAD @ {sha}\n\n', sha=GIT_COMMIT)
            return

        puts('\n\nPR {number} INFO:\n', **self.pr)
        puts('URL: {html_url}', **self.pr)
        puts('SHA: {sha}', sha=self.pr['head']['sha'])
        puts('TITLE: {title}', **self.pr)
        puts('INFO: \n{body}\n', **self.pr)
        if not self.pr['mergeable']:
            puts('\n\nTHIS PR CANNOT BE MERGED!!!\n\n')
            raise Exception('Pr Not mergeable')
        self.update_submodules()
        self.checkout_pr(self.pr)
        for pull in parse_depends(self.pr['body']):
            self.checkout_pr(pull)
        update_status(self.pr, state=self.state)

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
            'mariadb_101': 'datastore=mariadb,version=10.1',
            'percona': 'datastore=percona,version=5.6',
            'redis_28': 'datastore=redis,version=2.8.22,group=rax_redis',
            'redis_30': 'datastore=redis,version=3.0.4,group=rax_redis',
            'default_groups': 'group="rax_stable|rax_replication_groups"',
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

    def archive_logs(self):
        output = '{work}/output'.format(work=WORKSPACE)
        root = "/var/lib/vz/private"
        for log_dir in LOGS:
            call('sudo su -c "cp {d}/*.log {out}"', d=log_dir, out=output)

        for ctn in os.listdir(root):
            def copy_file(src, dst):
                args = {
                    'path': os.path.join(root, ctn, src),
                    'output': output,
                    'dst': dst,
                    'ctn': ctn
                }
                call("sudo cp {path} {output}/{dst}-{ctn}.log", **args)

            copy_file("var/log/trove/trove-guestagent.log", "reffy")
            copy_file("var/log/cdbproxy-agent.log", "virgo")

        call('sudo chmod 777 {out}', out=output)

    def clean(self):
        super(VMTestCase, self).clean()
        self.archive_logs()
        with cd(WORKSPACE):
            # Call clean with trove python
            call('sudo rm -rf lib')
            call('sudo rm -rf internal')

    def setup(self):
        super(VMTestCase, self).setup()
        check_call('sudo rm -rf /Cloud-Database')
        check_call('sudo ln -s {work} /Cloud-Database', work=WORKSPACE)
        with cd(WORKSPACE):
            check_call('sudo {p} install -e internal/cdb-utils', p=TROVE_PIP)
        check_call('{fab} vm.clear vm.install', fab=TROVE_FAB)


class GlobalProxyTestCase(VMTestCase):

    def get_exisiting_global_proxy_nodes(self):
        global_proxy_nodes = []

        return global_proxy_nodes

    def remove_existing_global_proxy_nodes(self):
        global_proxy_nodes = self.get_exisiting_global_proxy_nodes()

    def setup(self):
        super(GlobalProxyTestCase, self).setup()

        # we want to check and remove  any existing global proxy nodes
        # since this job will create 2 new inova vms (requires 3 total)
        self.remove_existing_global_proxy_nodes()

        # create global proxy nodes
        self.global_proxy_nodes = []
        proxy_nodes_name = ""
        check_call('{fab} inova.boot_proxy_nodes:name={proxy_nodes_name}',
                   fab=TROVE_FAB)

    def clean(self):
        super(GlobalProxyTestCase, self).clean()
        # delete global proxy nodes


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
        'X-Usage',
        'tox -eusage -- --stop',
        xunit=False),
    VMTestCase(
        'X-MySQL-56',
        '{fab} {fab_args},{mysql_56},{default_groups}'),
    VMTestCase(
        'X-MySQL-51',
        '{fab} {fab_args},{mysql_51},group="rax_stable"'),
    VMTestCase(
        'X-Mariadb',
        '{fab} {fab_args},{mariadb},{default_groups}'),
    VMTestCase(
        'X-Mariadb-101',
        '{fab} {fab_args},{mariadb_101},{default_groups}'),
    VMTestCase(
        'X-Percona',
        '{fab} {fab_args},{percona},{default_groups}'),
    VMTestCase(
        'X-Redis-28',
        '{fab} {fab_args},{redis_28}'),
    VMTestCase(
        'X-Redis-30',
        '{fab} {fab_args},{redis_30}'),
    VMTestCase(
        'X-HA-MySQL-56',
        '{fab} {fab_args},{mysql_56},group="rax_ha_mysql"'),
    VMTestCase(
        'X-HA-Mariadb',
        '{fab} {fab_args},{mariadb},group="rax_ha_mysql"'),
    VMTestCase(
        'X-HA-Mariadb-101',
        '{fab} {fab_args},{mariadb_101},group="rax_ha_mysql"'),
    VMTestCase(
        'X-HA-Percona',
        '{fab} {fab_args},{percona},group="rax_ha_mysql"'),
    VMTestCase(
        'X-Puppet-VM',
        '{fab} {fab_args},{mysql_56},group="cdbdbaas.api.flavors"'),
    GlobalProxyTestCase(
        'X-HA-Global-Proxy-Redis',
        '{fab} {fab_args},{redis_28},group="rax_ha_globalproxy"'),
]


if __name__ == '__main__':
    # We are running in a Jenkins Job
    jobs = [PullRunner(TESTS)] + TESTS
    for test in jobs:
        if test.name == JOB_NAME:
            test.run()
