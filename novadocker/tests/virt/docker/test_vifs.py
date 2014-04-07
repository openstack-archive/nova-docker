# Copyright (c) 2013 VMware, Inc.
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

import mock

from nova.network import model as network_model
from nova import test
import novadocker.virt.docker


class DockerGenericVIFDriverTestCase(test.TestCase):

    def setUp(self):
        super(DockerGenericVIFDriverTestCase, self).setUp()

    @mock.patch.object(novadocker.virt.docker.driver.DockerDriver,
                '_find_container_by_name', return_value={'id': 'fake_id'})
    @mock.patch.object(novadocker.virt.docker.driver.DockerDriver,
                '_find_container_pid', return_value=1234)
    def test_plug_vifs_bridge(self, mock_find_by_name, mock_find_pid):
        calls = [
            mock.call('ln', '-sf', '/proc/1234/ns/net',
                      '/var/run/netns/fake_id', run_as_root=True),
            mock.call('ip', 'link', 'add', 'name', 'tap920be2f4-2b',
                      'type', 'veth', 'peer', 'name', 'ns920be2f4-2b',
                      run_as_root=True),
            mock.call('brctl', 'addif', 'br100', 'tap920be2f4-2b',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'tap920be2f4-2b', 'up',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'ns920be2f4-2b', 'netns',
                      'fake_id', run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id', 'ip', 'link',
                      'set', 'ns920be2f4-2b', 'address', '00:11:22:33:44:55',
                      run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id',
                      'ifconfig', 'ns920be2f4-2b', '10.11.12.3/24',
                      run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id', 'ip', 'route',
                      'replace', 'default', 'via', '10.11.12.1', 'dev',
                      'ns920be2f4-2b', run_as_root=True)
        ]
        network_info = [
            {'network': {'bridge': 'br100',
                         'subnets': [{'gateway': {'address': '10.11.12.1'},
                                      'cidr': '10.11.12.0/24',
                                      'ips': [{'address': '10.11.12.3',
                                               'type': 'fixed', 'version': 4}]
                                     }]},
             'address': '00:11:22:33:44:55',
             'id': '920be2f4-2b98-411e-890a-69bcabb2a5a0',
             'type': network_model.VIF_TYPE_BRIDGE}]
        with mock.patch('nova.utils.execute') as ex:
            driver = novadocker.virt.docker.driver.DockerDriver(object)
            driver.plug_vifs({'name': 'fake_instance'}, network_info)
            ex.assert_has_calls(calls)

    @mock.patch.object(novadocker.virt.docker.driver.DockerDriver,
                '_find_container_by_name', return_value={'id': 'fake_id'})
    @mock.patch.object(novadocker.virt.docker.driver.DockerDriver,
                '_find_container_pid', return_value=1234)
    def test_plug_vifs_bridge_two_interfaces(self, mock_find_by_name,
                                             mock_find_pid):
        calls = [
            mock.call('ln', '-sf', '/proc/1234/ns/net',
                      '/var/run/netns/fake_id', run_as_root=True),
            # interface 1
            mock.call('ip', 'link', 'add', 'name', 'tap920be2f4-2b',
                      'type', 'veth', 'peer', 'name', 'ns920be2f4-2b',
                      run_as_root=True),
            mock.call('brctl', 'addif', 'br100', 'tap920be2f4-2b',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'tap920be2f4-2b', 'up',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'ns920be2f4-2b', 'netns', 'fake_id',
                      run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id', 'ip', 'link',
                      'set', 'ns920be2f4-2b', 'address', '00:11:22:33:44:55',
                      run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id',
                      'ifconfig', 'ns920be2f4-2b', '10.11.12.3/24',
                      run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id', 'ip', 'route',
                      'replace', 'default', 'via', '10.11.12.1', 'dev',
                      'ns920be2f4-2b', run_as_root=True),
            # interface 2
            mock.call('ip', 'link', 'add', 'name', 'tap920be2f4-2b',
                      'type', 'veth', 'peer', 'name', 'ns920be2f4-2b',
                      run_as_root=True),
            mock.call('brctl', 'addif', 'br100', 'tap920be2f4-2b',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'tap920be2f4-2b', 'up',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'ns920be2f4-2b', 'netns', 'fake_id',
                      run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id', 'ip', 'link',
                      'set', 'ns920be2f4-2b', 'address', '00:11:22:33:44:66',
                      run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id',
                      'ifconfig', 'ns920be2f4-2b', '10.13.12.3/24',
                      run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id', 'ip', 'route',
                      'replace', 'default', 'via', '10.13.12.1', 'dev',
                      'ns920be2f4-2b', run_as_root=True)
        ]
        network_info = [
            {'network': {'bridge': 'br100',
                         'subnets': [{'gateway': {'address': '10.11.12.1'},
                                      'cidr': '10.11.12.0/24',
                                      'ips': [{'address': '10.11.12.3',
                                               'type': 'fixed', 'version': 4}],
                                    }]},
             'address': '00:11:22:33:44:55',
             'type': network_model.VIF_TYPE_BRIDGE,
             'id': '920be2f4-2b98-411e-890a-69bcabb2a5a0'},
            {'network': {'bridge': 'br100',
                         'subnets': [{'gateway': {'address': '10.13.12.1'},
                                      'cidr': '10.13.12.0/24',
                                      'ips': [{'address': '10.13.12.3',
                                               'type': 'fixed', 'version': 4}]
                                    }]},
             'address': '00:11:22:33:44:66',
             'type': network_model.VIF_TYPE_BRIDGE,
             'id': '920be2f4-2b98-411e-890a-69bcabb2a5a0'}]
        with mock.patch('nova.utils.execute') as ex:
            driver = novadocker.virt.docker.driver.DockerDriver(object)
            driver.plug_vifs({'name': 'fake_instance'}, network_info)
            ex.assert_has_calls(calls)
