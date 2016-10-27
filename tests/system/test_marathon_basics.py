"""Marathon tests on DC/OS for negative conditions"""

import pytest
import time
import uuid

from common import *
from shakedown import *
from utils import *
from dcos import *


def test_launch_mesos_container():
    with marathon_on_marathon():
        client = marathon.create_client()
        client.add_app(app_mesos())
        deployment_wait()

        tasks = client.get_tasks('/mesos-test')
        app = client.get_app('/mesos-test')

        assert len(tasks) == 1
        assert app['container']['type'] == 'MESOS'


def test_launch_docker_container():
    with marathon_on_marathon():
        client = marathon.create_client()
        client.add_app(app_docker())
        deployment_wait()

        tasks = client.get_tasks('/docker-test')
        app = client.get_app('/docker-test')

        assert len(tasks) == 1
        assert app['container']['type'] == 'DOCKER'


def test_docker_port_mappings():
    with marathon_on_marathon():
        client = marathon.create_client()
        client.add_app(app_docker())
        deployment_wait()

        tasks = client.get_tasks('/docker-test')
        host = tasks[0]['host']
        port = tasks[0]['ports'][0]
        cmd = r'curl -s -w "%{http_code}"'
        cmd = cmd + ' {}:{}/.dockerenv'.format(host, port)
        status, output = run_command_on_agent(host, cmd)

        assert status
        assert output == "200"


def test_docker_dns_mapping():
    with marathon_on_marathon():
        client = marathon.create_client()
        app_name = uuid.uuid4().hex
        app_json = app_docker()
        app_json['id'] = app_name
        client.add_app(app_json)
        deployment_wait()

        tasks = client.get_tasks(app_name)
        host = tasks[0]['host']

        time.sleep(5)
        bad_cmd = 'ping -c 1 docker-test.marathon-user.mesos-bad'
        cmd = 'ping -c 1 {}.marathon-user.mesos'.format(app_name)
        status, output = run_command_on_agent(host, bad_cmd)
        assert not status

        status, output = run_command_on_agent(host, cmd)
        assert status

        client.remove_app(app_name)


def test_ui_registration_requirement():
    response = http.get("{}mesos/master/tasks.json".format(dcos_url()))
    tasks = response.json()['tasks']
    for task in tasks:
        if task['name'] == 'marathon-user':
            for label in task['labels']:
                if label['key'] == 'DCOS_PACKAGE_NAME':
                    assert label['value'] == 'marathon'
                if label['key'] == 'DCOS_PACKAGE_IS_FRAMEWORK':
                    assert label['value'] == 'true'
                if label['key'] == 'DCOS_SERVICE_NAME':
                    assert label['value'] == 'marathon-user'


def test_ui_available():
    response = http.get("{}service/marathon-user/ui/".format(dcos_url()))
    assert response.status_code == 200


def test_task_failure_recovers():
    app_def = app()
    app_id = app_def['id']

    with marathon_on_marathon():
        client = marathon.create_client()
        client.add_app(app_def)
        deployment_wait()
        tasks = client.get_tasks(app_id)
        host = tasks[0]['host']
        kill_process_on_host(host,'[s]leep')
        deployment_wait()
        time.sleep(1)
        new_tasks = client.get_tasks(app_id)

        assert tasks[0]['id'] != new_tasks[0]['id']


def test_good_user():
    app_def = app()
    app_id = app_def['id']
    app_def['user'] = 'core'

    with marathon_on_marathon():
        client = marathon.create_client()
        client.add_app(app_def)
        deployment_wait()
        tasks = client.get_tasks(app_id)
        deployment_wait()
        time.sleep(1)

        assert tasks[0]['id'] != app_def['id']


def test_bad_user():
    app_def = app()
    app_id = app_def['id']
    app_def['user'] = 'bad'

    with marathon_on_marathon():
        client = marathon.create_client()
        client.add_app(app_def)
        time.sleep(2)

        appl = client.get_app(app_id)
        message = appl['lastTaskFailure']['message']
        error = "Failed to get user information for 'bad'"
        assert error in message


def test_bad_uri():
    app_def = app()
    app_id = app_def['id']
    fetch = [ {
      "uri": "http://mesosphere.io/missing-artifact"
    }]

    app_def['fetch'] = fetch

    with marathon_on_marathon():
        client = marathon.create_client()
        client.add_app(app_def)
        time.sleep(2)

        appl = client.get_app(app_id)
        message = appl['lastTaskFailure']['message']
        error = "Failed to fetch all URIs for container"
        assert error in message

        client.remove_app(app_id)

def test_launch_group():
    with marathon_on_marathon():
        client = marathon.create_client()
        client.create_group(group())
        deployment_wait()

        apps = client.get_group('/test-group/sleep')
        assert len(apps) == 2


def test_scale_group():
    with marathon_on_marathon():
        client = marathon.create_client()
        try:
            client.remove_group('/test-group', True)
            deployment_wait()
        except Exception as e:
            pass

        client.create_group(group())
        deployment_wait()

        group_apps = client.get_group('/test-group/sleep')
        apps = group_apps['apps']
        assert len(apps) == 2
        tasks1 = client.get_tasks('/test-group/sleep/goodnight')
        tasks2 = client.get_tasks('/test-group/sleep/goodnight2')
        assert len(tasks1) == 1
        assert len(tasks2) == 1

        client.scale_group('/test-group/sleep', 2)
        deployment_wait()
        tasks1 = client.get_tasks('/test-group/sleep/goodnight')
        tasks2 = client.get_tasks('/test-group/sleep/goodnight2')
        assert len(tasks1) == 2
        assert len(tasks2) == 2


def test_scale_app_in_group():
    with marathon_on_marathon():
        client = marathon.create_client()
        try:
            client.remove_group('/test-group', True)
            deployment_wait()
        except Exception as e:
            pass

        client.create_group(group())
        deployment_wait()

        group_apps = client.get_group('/test-group/sleep')
        apps = group_apps['apps']
        assert len(apps) == 2
        tasks1 = client.get_tasks('/test-group/sleep/goodnight')
        tasks2 = client.get_tasks('/test-group/sleep/goodnight2')
        assert len(tasks1) == 1
        assert len(tasks2) == 1

        client.scale_app('/test-group/sleep/goodnight', 2)
        deployment_wait()
        tasks1 = client.get_tasks('/test-group/sleep/goodnight')
        tasks2 = client.get_tasks('/test-group/sleep/goodnight2')
        assert len(tasks1) == 2
        assert len(tasks2) == 1


def setup_function(function):
    with marathon_on_marathon():
        delete_all_apps_wait()

def setup_module(module):
    ensure_mom()
    cluster_info()


# def teardown_module(module):
#     with marathon_on_marathon():
#         delete_all_apps_wait()


def app_docker():

    app = {
        'id': 'docker-test',
        'cmd': 'python3 -m http.server 8080',
        'cpus': 0.5,
        'mem': 32.0,
        'container': {
            'type': 'DOCKER',
            'docker': {
                'image': 'python:3',
                'network': 'BRIDGE',
                'portMappings': [
                    { 'containerPort': 8080, 'hostPort': 0 }
                ]
            }
        }
    }
    return app


def app_mesos():

    app = {
        'id': 'mesos-test',
        'cmd': 'sleep 1000',
        'cpus': 0.5,
        'mem': 32.0,
        'container': {
            'type': 'MESOS'
        }
    }
    return app
