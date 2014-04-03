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

import contextlib
import socket

import mock

from nova.compute import task_states
from nova import context
from nova import exception
from nova.openstack.common import jsonutils
from nova.openstack.common import units
from nova import test
import nova.tests.image.fake
from nova.tests import matchers
from nova.tests import utils
from nova.tests.virt.test_virt_drivers import _VirtDriverTestCase
from novadocker.tests.virt.docker import mock_client
from novadocker.tests.virt.docker import stubs
import novadocker.virt.docker
from novadocker.virt.docker import hostinfo
from novadocker.virt.docker import network


class DockerDriverTestCase(_VirtDriverTestCase, test.TestCase):

    driver_module = 'novadocker.virt.docker.DockerDriver'

    def setUp(self):
        super(DockerDriverTestCase, self).setUp()

        self.mock_client = mock_client.MockClient()
        self.stubs.Set(novadocker.virt.docker.driver.DockerDriver, 'docker',
                       self.mock_client)

        def fake_setup_network(self, instance, network_info):
            return

        self.stubs.Set(novadocker.virt.docker.driver.DockerDriver,
                       '_setup_network',
                       fake_setup_network)

        def fake_get_registry_port(self):
            return 5042

        self.stubs.Set(novadocker.virt.docker.driver.DockerDriver,
                       '_get_registry_port',
                       fake_get_registry_port)

        self.stubs.Set(novadocker.virt.docker.hostinfo,
                       'get_meminfo', stubs.get_meminfo)

        # Note: using mock.object.path on class throws
        # errors in test_virt_drivers
        def fake_teardown_network(container_id):
            return

        self.stubs.Set(network, 'teardown_network', fake_teardown_network)
        self.context = context.RequestContext('fake_user', 'fake_project')

        self.connection.init_host(None)

    def test_driver_capabilities(self):
        self.assertFalse(self.connection.capabilities['has_imagecache'])
        self.assertFalse(self.connection.capabilities['supports_recreate'])

    #NOTE(bcwaldon): This exists only because _get_running_instance on the
    # base class will not let us set a custom disk/container_format.
    def _get_running_instance(self, obj=False):
        instance_ref = utils.get_test_instance(obj=obj)
        network_info = utils.get_test_network_info()
        network_info[0]['network']['subnets'][0]['meta']['dhcp_server'] = \
            '1.1.1.1'
        image_info = utils.get_test_image_info(None, instance_ref)
        image_info['disk_format'] = 'raw'
        image_info['container_format'] = 'docker'
        self.connection.spawn(self.ctxt, jsonutils.to_primitive(instance_ref),
                image_info, [], 'herp', network_info=network_info)
        return instance_ref, network_info

    def test_get_host_stats(self):
        self.mox.StubOutWithMock(socket, 'gethostname')
        socket.gethostname().AndReturn('foo')
        socket.gethostname().AndReturn('bar')
        self.mox.ReplayAll()
        self.assertEqual('foo',
                         self.connection.get_host_stats()['host_hostname'])
        self.assertEqual('foo',
                         self.connection.get_host_stats()['host_hostname'])

    def test_get_available_resource(self):
        memory = {
            'total': 4 * units.Mi,
            'free': 3 * units.Mi,
            'used': 1 * units.Mi
        }
        disk = {
            'total': 50 * units.Gi,
            'available': 25 * units.Gi,
            'used': 25 * units.Gi
        }
        # create the mocks
        with contextlib.nested(
            mock.patch.object(hostinfo, 'get_memory_usage',
                              return_value=memory),
            mock.patch.object(hostinfo, 'get_disk_usage',
                              return_value=disk)
        ) as (
            get_memory_usage,
            get_disk_usage
        ):
            # run the code
            stats = self.connection.get_available_resource(nodename='test')
            # make our assertions
            get_memory_usage.assert_called_once_with()
            get_disk_usage.assert_called_once_with()
            expected_stats = {
                'vcpus': 1,
                'vcpus_used': 0,
                'memory_mb': 4,
                'memory_mb_used': 1,
                'local_gb': 50L,
                'local_gb_used': 25L,
                'disk_available_least': 25L,
                'hypervisor_type': 'docker',
                'hypervisor_version': 1000,
                'hypervisor_hostname': 'test',
                'cpu_info': '?',
                'supported_instances': ('[["i686", "docker", "lxc"],'
                                        ' ["x86_64", "docker", "lxc"]]')
            }
            self.assertEqual(expected_stats, stats)

    def test_plug_vifs(self):
        # Check to make sure the method raises NotImplementedError.
        self.assertRaises(NotImplementedError,
                          self.connection.plug_vifs,
                          instance=utils.get_test_instance(),
                          network_info=None)

    def test_unplug_vifs(self):
        # Check to make sure the method raises NotImplementedError.
        self.assertRaises(NotImplementedError,
                          self.connection.unplug_vifs,
                          instance=utils.get_test_instance(),
                          network_info=None)

    def test_create_container(self, image_info=None):
        instance_href = utils.get_test_instance()
        if image_info is None:
            image_info = utils.get_test_image_info(None, instance_href)
            image_info['disk_format'] = 'raw'
            image_info['container_format'] = 'docker'
        self.connection.spawn(self.context, instance_href, image_info,
                              'fake_files', 'fake_password')
        self._assert_cpu_shares(instance_href)
        self.assertEqual(self.mock_client.name, "nova-{0}".format(
            instance_href['uuid']))

    def test_create_container_vcpus_2(self, image_info=None):
        flavor = utils.get_test_flavor(options={
            'name': 'vcpu_2',
            'flavorid': 'vcpu_2',
            'vcpus': 2
        })
        instance_href = utils.get_test_instance(flavor=flavor)
        if image_info is None:
            image_info = utils.get_test_image_info(None, instance_href)
            image_info['disk_format'] = 'raw'
            image_info['container_format'] = 'docker'
        self.connection.spawn(self.context, instance_href, image_info,
                              'fake_files', 'fake_password')
        self._assert_cpu_shares(instance_href, vcpus=2)
        self.assertEqual(self.mock_client.name, "nova-{0}".format(
            instance_href['uuid']))

    def _assert_cpu_shares(self, instance_href, vcpus=4):
        container_id = self.connection._find_container_by_name(
            instance_href['name']).get('id')
        container_info = self.connection.docker.inspect_container(container_id)
        self.assertEqual(vcpus * 1024, container_info['Config']['CpuShares'])

    @mock.patch('novadocker.virt.docker.driver.DockerDriver._setup_network',
                side_effect=Exception)
    def test_create_container_net_setup_fails(self, mock_setup_network):
        self.assertRaises(exception.InstanceDeployFailure,
                          self.test_create_container)
        self.assertEqual(0, len(self.mock_client.list_containers()))

    def test_create_container_wrong_image(self):
        instance_href = utils.get_test_instance()
        image_info = utils.get_test_image_info(None, instance_href)
        image_info['disk_format'] = 'raw'
        image_info['container_format'] = 'invalid_format'
        self.assertRaises(exception.InstanceDeployFailure,
                          self.test_create_container,
                          image_info)

    @mock.patch.object(network, 'teardown_network')
    @mock.patch.object(novadocker.virt.docker.driver.DockerDriver,
                '_find_container_by_name', return_value={'id': 'fake_id'})
    def test_destroy_container(self, byname_mock, teardown_mock):
        instance = utils.get_test_instance()
        self.connection.destroy(self.context, instance, 'fake_networkinfo')
        byname_mock.assert_called_once_with(instance['name'])
        teardown_mock.assert_called_with('fake_id')

    def test_get_memory_limit_from_sys_meta_in_object(self):
        instance = utils.get_test_instance(obj=True)
        limit = self.connection._get_memory_limit_bytes(instance)
        self.assertEqual(2048 * units.Mi, limit)

    def test_get_memory_limit_from_sys_meta_in_db_instance(self):
        instance = utils.get_test_instance(obj=False)
        limit = self.connection._get_memory_limit_bytes(instance)
        self.assertEqual(2048 * units.Mi, limit)

    def test_list_instances(self):
        instance_href = utils.get_test_instance()
        image_info = utils.get_test_image_info(None, instance_href)
        image_info['disk_format'] = 'raw'
        image_info['container_format'] = 'docker'
        self.connection.spawn(self.context, instance_href, image_info,
                              'fake_files', 'fake_password')

        instances = self.connection.list_instances()
        self.assertIn(instance_href.name, instances)

    def test_list_instances_none(self):
        instances = self.connection.list_instances()
        self.assertIsInstance(instances, list)
        self.assertFalse(instances)

    def test_list_instances_no_inspect_race(self):
        """Assures containers that cannot be inspected are not listed."""
        instance_href = utils.get_test_instance()
        image_info = utils.get_test_image_info(None, instance_href)
        image_info['disk_format'] = 'raw'
        image_info['container_format'] = 'docker'
        self.connection.spawn(self.context, instance_href, image_info,
                              'fake_files', 'fake_password')

        with mock.patch('novadocker.tests.virt.docker.mock_client.'
                        'MockClient.inspect_container',
                        return_value={}):
            instances = self.connection.list_instances()
            self.assertFalse(instances)

    def test_find_container_pid(self):
        driver = novadocker.virt.docker.driver.DockerDriver(None)
        with mock.patch.object(driver.docker,
                               "inspect_container") as inspect_container:
            inspect_container.return_value = {'State': {'Pid': '12345'}}
            pid = driver._find_container_pid("fake_container_id")
            self.assertEqual(pid, '12345')

    @mock.patch.object(novadocker.tests.virt.docker.mock_client.MockClient,
                'push_repository')
    @mock.patch.object(novadocker.virt.docker.driver.DockerDriver,
                '_find_container_by_name', return_value={'id': 'fake_id'})
    def test_snapshot(self, byname_mock, repopush_mock):
        # Use mix-case to test that mixed-case image names succeed.
        snapshot_name = 'tEsT-SnAp'

        expected_calls = [
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_PENDING_UPLOAD}},
            {'args': (),
             'kwargs':
                 {'task_state': task_states.IMAGE_UPLOADING,
                  'expected_state': task_states.IMAGE_PENDING_UPLOAD}}]
        func_call_matcher = matchers.FunctionCallMatcher(expected_calls)

        instance_ref = utils.get_test_instance()
        properties = {'instance_id': instance_ref['id'],
                      'user_id': str(self.context.user_id)}
        sent_meta = {'name': snapshot_name, 'is_public': False,
                     'status': 'creating', 'properties': properties}

        # Because the docker driver doesn't push directly into Glance, we
        # cannot check that the images are correctly configured in the
        # fake image service, but we can ensuring naming and other
        # conventions are accurate.
        image_service = nova.tests.image.fake.FakeImageService()
        recv_meta = image_service.create(context, sent_meta)

        self.connection.snapshot(self.context, instance_ref, recv_meta['id'],
                      func_call_matcher.call)

        (repopush_calls, repopush_kwargs) = repopush_mock.call_args
        repo = repopush_calls[0]

        # Assure the image_href is correctly placed into the headers.
        headers_image_href = repopush_kwargs.get('headers', {}).get(
            'X-Meta-Glance-Image-Id')
        self.assertEqual(recv_meta['id'], headers_image_href)

        # Assure the repository name pushed into the docker registry is valid.
        self.assertIn(":" + str(self.connection._get_registry_port()) + "/",
                      repo)
        self.assertEqual(repo.count(":"), 1)
        self.assertEqual(repo.count("/"), 1)

        # That the lower-case snapshot name matches the name pushed
        image_name = repo.split("/")[1]
        self.assertEqual(snapshot_name.lower(), image_name)

    def test_get_image_name(self):
        instance_ref = utils.get_test_instance()
        image_info = utils.get_test_image_info(None, instance_ref)
        image_info['container_format'] = 'docker'
        image_info['name'] = 'MiXeDcAsE-image'
        repo = self.connection._get_image_name(self.context,
                                               instance_ref, image_info)

        # Assure the repository name pushed into the docker registry is valid.
        self.assertIn(":" + str(self.connection._get_registry_port()) + "/",
                      repo)
        self.assertEqual(repo.count(":"), 1)
        self.assertEqual(repo.count("/"), 1)

        # That the lower-case snapshot name matches the name pushed
        image_name = repo.split("/")[1]
        self.assertEqual(image_info['name'].lower(), image_name)


class DockerDriverNetworkTestCase(test.TestCase):

    def setUp(self):
        super(DockerDriverNetworkTestCase, self).setUp()

    @mock.patch.object(novadocker.virt.docker.driver.DockerDriver,
                '_find_container_by_name', return_value={'id': 'fake_id'})
    @mock.patch.object(novadocker.virt.docker.driver.DockerDriver,
                '_find_container_pid', return_value=1234)
    def test_setup_network(self, mock_find_by_name, mock_find_pid):
        calls = [
            mock.call('ln', '-sf', '/proc/1234/ns/net',
                      '/var/run/netns/fake_id', run_as_root=True),
            mock.call('ip', 'link', 'add', 'name', mock.ANY,
                      'type', 'veth', 'peer', 'name', mock.ANY,
                      run_as_root=True),
            mock.call('brctl', 'addif', 'br100', mock.ANY, run_as_root=True),
            mock.call('ip', 'link', 'set', mock.ANY, 'up', run_as_root=True),
            mock.call('ip', 'link', 'set', mock.ANY, 'netns', 'fake_id',
                      run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id',
                      'ifconfig', mock.ANY, '10.11.12.3/24',
                      run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id', 'ip', 'route',
                      'replace', 'default', 'via', '10.11.12.1', 'dev',
                      mock.ANY, run_as_root=True)
        ]
        network_info = [
            {'network': {'bridge': 'br100',
                         'subnets': [{'gateway': {'address': '10.11.12.1'},
                                      'cidr': '10.11.12.0/24',
                                      'ips': [{'address': '10.11.12.3',
                                               'type': 'fixed', 'version': 4}]
                                     }]}}]
        with mock.patch('nova.utils.execute') as ex:
            driver = novadocker.virt.docker.driver.DockerDriver(object)
            driver._setup_network({'name': 'fake_instance'}, network_info)
            ex.assert_has_calls(calls)
