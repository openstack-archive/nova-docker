# Copyright (c) 2013 dotCloud, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import collections
import mox
import urllib
import uuid


from nova.openstack.common import jsonutils
from nova import test
import novadocker.virt.docker.client as docker_client


class FakeResponse(object):
    def __init__(self, status, data='', headers=None):
        self.status = status
        self._data = data
        self._headers = headers or {}

    def read(self, _size=None):
        return self._data

    def getheader(self, key):
        return self._headers.get(key)


class DockerHTTPClientTestCase(test.NoDBTestCase):
    VERSION = "v1.13"

    def make_request(self, *args, **kwargs):
        mock_conn = self.mox.CreateMockAnything()
        headers = {'Content-Type': 'application/json'}
        kwargs['headers'] = headers

        # args[1] == path, args[2:] == query represented as tuples
        url = "/%s/%s" % (self.VERSION, urllib.quote(args[1]))
        if len(args) > 2:
            url += "?" + urllib.urlencode(args[2:])
        encoded_args = args[0], url

        mock_conn.request(*encoded_args, **kwargs)
        return mock_conn

    def test_list_containers(self):
        mock_conn = self.make_request('GET',
                                      'containers/ps', ('all', '1'))
        response = FakeResponse(200, data='[]',
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = docker_client.DockerHTTPClient(mock_conn)
        containers = client.list_containers()
        self.assertEqual([], containers)

        self.mox.VerifyAll()

    def test_create_container(self):
        mock_conn = self.mox.CreateMockAnything()
        expected_uuid = uuid.uuid4()

        expected_body = jsonutils.dumps({
            'Hostname': '',
            'User': '',
            'Memory': 0,
            'MemorySwap': 0,
            'AttachStdin': False,
            'AttachStdout': False,
            'AttachStderr': False,
            'PortSpecs': [],
            'Tty': True,
            'OpenStdin': True,
            'StdinOnce': False,
            'Env': None,
            'Cmd': [],
            'Dns': None,
            'Image': None,
            'Volumes': {},
            'VolumesFrom': '',
        })

        mock_conn = self.make_request('POST',
                                      'containers/create',
                                      ('name', expected_uuid),
                                      body=expected_body)
        response = FakeResponse(201, data='{"id": "XXX"}',
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = docker_client.DockerHTTPClient(mock_conn)
        container_id = client.create_container({}, expected_uuid)
        self.assertEqual('XXX', container_id)

        self.mox.VerifyAll()

    def test_create_container_with_args(self):
        expected_uuid = uuid.uuid4()
        expected_body = jsonutils.dumps({
            'Hostname': 'marco',
            'User': '',
            'Memory': 512,
            'MemorySwap': 0,
            'AttachStdin': False,
            'AttachStdout': False,
            'AttachStderr': False,
            'PortSpecs': [],
            'Tty': True,
            'OpenStdin': True,
            'StdinOnce': False,
            'Env': None,
            'Cmd': [],
            'Dns': None,
            'Image': 'example',
            'Volumes': {},
            'VolumesFrom': '',
        })
        mock_conn = self.make_request('POST',
                                      'containers/create',
                                      ('name', expected_uuid),
                                      body=expected_body)
        response = FakeResponse(201, data='{"id": "XXX"}',
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = docker_client.DockerHTTPClient(mock_conn)
        args = {
            'Hostname': 'marco',
            'Memory': 512,
            'Image': 'example',
        }

        container_id = client.create_container(args, expected_uuid)
        self.assertEqual('XXX', container_id)

        self.mox.VerifyAll()

    def test_create_container_no_id_in_response(self):
        expected_uuid = uuid.uuid4()

        mock_conn = self.make_request('POST',
                                      'containers/create',
                                      ('name', expected_uuid),
                                      body=mox.IgnoreArg())
        response = FakeResponse(201, data='{"ping": "pong"}',
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = docker_client.DockerHTTPClient(mock_conn)
        container_id = client.create_container({}, expected_uuid)
        self.assertIsNone(container_id)

        self.mox.VerifyAll()

    def test_create_container_bad_return_code(self):
        expected_uuid = uuid.uuid4()

        mock_conn = self.make_request('POST',
                                      'containers/create',
                                      ('name', expected_uuid),
                                      body=mox.IgnoreArg())
        response = FakeResponse(400)
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = docker_client.DockerHTTPClient(mock_conn)
        container_id = client.create_container({}, expected_uuid)
        self.assertIsNone(container_id)

        self.mox.VerifyAll()

    def test_start_container(self):
        mock_conn = self.make_request('POST', 'containers/XXX/start',
                                      body='{}')
        response = FakeResponse(200,
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = docker_client.DockerHTTPClient(mock_conn)
        self.assertEqual(True, client.start_container('XXX'))

        self.mox.VerifyAll()

    def test_start_container_bad_return_code(self):
        mock_conn = self.make_request('POST', 'containers/XXX/start',
                                      body='{}')
        response = FakeResponse(400)
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = docker_client.DockerHTTPClient(mock_conn)
        self.assertEqual(False, client.start_container('XXX'))

        self.mox.VerifyAll()

    def test_inspect_image(self):
        mock_conn = self.make_request('GET', 'images/XXX/json')
        response = FakeResponse(200, data='{"name": "XXX"}',
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = docker_client.DockerHTTPClient(mock_conn)
        image = client.inspect_image('XXX')
        self.assertEqual({'name': 'XXX'}, image)

        self.mox.VerifyAll()

    def test_inspect_image_bad_return_code(self):
        mock_conn = self.make_request('GET', 'images/XXX/json')
        response = FakeResponse(404)
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = docker_client.DockerHTTPClient(mock_conn)
        image = client.inspect_image('XXX')
        self.assertIsNone(image)

        self.mox.VerifyAll()

    def test_inspect_container(self):
        mock_conn = self.make_request('GET', 'containers/XXX/json')
        response = FakeResponse(200, data='{"id": "XXX"}',
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = docker_client.DockerHTTPClient(mock_conn)
        container = client.inspect_container('XXX')
        self.assertEqual({'id': 'XXX'}, container)

        self.mox.VerifyAll()

    def test_inspect_container_bad_return_code(self):
        mock_conn = self.make_request('GET', 'containers/XXX/json')
        response = FakeResponse(404, data='inspect: No such container: XXX',
                                headers={'Content-Type': 'text/plain'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = docker_client.DockerHTTPClient(mock_conn)
        container = client.inspect_container('XXX')
        self.assertEqual({}, container)

        self.mox.VerifyAll()

    def test_stop_container(self):
        mock_conn = self.make_request('POST', 'containers/XXX/stop',
                                      ('t', '5'))
        response = FakeResponse(204,
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = docker_client.DockerHTTPClient(mock_conn)
        self.assertEqual(True, client.stop_container('XXX'))

        self.mox.VerifyAll()

    def test_kill_container(self):
        mock_conn = self.make_request('POST', 'containers/XXX/kill')
        response = FakeResponse(204,
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = docker_client.DockerHTTPClient(mock_conn)
        self.assertEqual(True, client.kill_container('XXX'))

        self.mox.VerifyAll()

    def test_stop_container_bad_return_code(self):
        mock_conn = self.make_request('POST', 'containers/XXX/stop',
                                      ('t', '5'))
        response = FakeResponse(400)
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = docker_client.DockerHTTPClient(mock_conn)
        self.assertEqual(False, client.stop_container('XXX'))

        self.mox.VerifyAll()

    def test_kill_container_bad_return_code(self):
        mock_conn = self.make_request('POST', 'containers/XXX/kill')
        response = FakeResponse(400)
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = docker_client.DockerHTTPClient(mock_conn)
        self.assertEqual(False, client.kill_container('XXX'))

        self.mox.VerifyAll()

    def test_destroy_container(self):
        mock_conn = self.make_request('DELETE', 'containers/XXX')
        response = FakeResponse(204,
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = docker_client.DockerHTTPClient(mock_conn)
        self.assertEqual(True, client.destroy_container('XXX'))

        self.mox.VerifyAll()

    def test_destroy_container_bad_return_code(self):
        mock_conn = self.make_request('DELETE', 'containers/XXX')
        response = FakeResponse(400)
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = docker_client.DockerHTTPClient(mock_conn)
        self.assertEqual(False, client.destroy_container('XXX'))

        self.mox.VerifyAll()

    def test_commit_container(self):
        mock_conn = self.make_request('POST',
                                      'commit',
                                      ('container', 'XXX'),
                                      ('repo', 'ping'))
        response = FakeResponse(201,
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = docker_client.DockerHTTPClient(mock_conn)
        self.assertEqual(True, client.commit_container('XXX', 'ping'))

        self.mox.VerifyAll()

    def test_commit_container_bad_return_code(self):
        mock_conn = self.make_request('POST',
                                      'commit',
                                      ('container', 'XXX'),
                                      ('repo', 'ping'))
        response = FakeResponse(400,
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = docker_client.DockerHTTPClient(mock_conn)
        self.assertEqual(False, client.commit_container('XXX', 'ping'))

        self.mox.VerifyAll()

    def test_get_container_logs(self):
        url = 'containers/XXX/attach'
        mock_conn = self.make_request('POST', url,
                                      ('logs', '1'),
                                      ('stream', '0'),
                                      ('stdout', '1'),
                                      ('stderr', '1'))
        response = FakeResponse(200, data='ping pong',
                                headers={'Content-Type': 'application/json'})
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = docker_client.DockerHTTPClient(mock_conn)
        logs = client.get_container_logs('XXX')
        self.assertEqual('ping pong', logs)

        self.mox.VerifyAll()

    def test_get_container_logs_bad_return_code(self):
        url = 'containers/XXX/attach'
        mock_conn = self.make_request('POST', url,
                                      ('logs', '1'),
                                      ('stream', '0'),
                                      ('stdout', '1'),
                                      ('stderr', '1'))
        response = FakeResponse(404)
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = docker_client.DockerHTTPClient(mock_conn)
        logs = client.get_container_logs('XXX')
        self.assertIsNone(logs)

        self.mox.VerifyAll()

    def test_get_image(self):
        image_id = 'XXX'
        data = ["hello world"]

        url = 'images/{0}/get'.format(image_id)
        headers = {'Content-Type': 'application/json'}
        mock_conn = self.make_request('GET', url, headers=headers)
        response = FakeResponse(201, data)
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = docker_client.DockerHTTPClient(mock_conn)
        image = client.get_image(image_id)
        self.assertIsInstance(image, collections.Iterable)

        # Only calling the generator will trigger the GET request.
        next(image)

        self.mox.VerifyAll()

    def test_load_repository(self):
        data = ["hello", "world"]
        url = 'images/load'
        headers = {'Content-Type': 'application/json'}
        mock_conn = self.make_request('POST', url, data=data, headers=headers)
        response = FakeResponse(200, data)
        mock_conn.getresponse().AndReturn(response)

        self.mox.ReplayAll()

        client = docker_client.DockerHTTPClient(mock_conn)
        client.load_repository('XXX', data)

        self.mox.VerifyAll()
