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
from novadocker.virt.docker import driver as docker_driver
from novadocker.virt.docker import vifs


class DockerGenericVIFDriverTestCase(test.TestCase):

    REQUIRES_LOCKING = True
    gateway_bridge_4 = network_model.IP(address='10.11.12.1', type='gateway')
    dns_bridge_4 = network_model.IP(address='8.8.8.8', type=None)
    ips_bridge_4 = [network_model.IP(address='101.168.1.9', type='fixed',
                                     version=4)]

    subnet_bridge_4 = network_model.Subnet(cidr='10.11.1.0/24',
                                           dns=[dns_bridge_4],
                                           gateway=gateway_bridge_4,
                                           ips=ips_bridge_4,
                                           routes=None)

    network_bridge = network_model.Network(id='network-id-xxx-yyy-zzz',
                                           bridge='br100',
                                           label=None,
                                           subnets=[subnet_bridge_4],
                                           bridge_interface='eth0')

    vif_bridge = network_model.VIF(id='920be2f4-2b98-411e-890a-69bcabb2a5a0',
                                   address='00:11:22:33:44:55',
                                   network=network_bridge,
                                   type=network_model.VIF_TYPE_BRIDGE)

    network_iovisor = network_model.Network(id='network-id-xxx-yyy-zzz',
                                            bridge='br100',
                                            label='net1',
                                            subnets=[subnet_bridge_4],
                                            bridge_interface='eth0')

    vif_iovisor = network_model.VIF(id='920be2f4-2b98-411e-890a-69bcabb2a5a0',
                                    address='00:11:22:33:44:55',
                                    network=network_iovisor,
                                    type=network_model.VIF_TYPE_IOVISOR)

    def setUp(self):
        super(DockerGenericVIFDriverTestCase, self).setUp()

        def fake_fe_random_mac(self):
            return 'fe:16:3e:ff:ff:ff'

        self.stubs.Set(vifs.DockerGenericVIFDriver,
                       '_fe_random_mac',
                       fake_fe_random_mac)

    def test_plug_vifs_bridge(self):
        calls = [
            mock.call('ip', 'link', 'add', 'name', 'tap920be2f4-2b',
                      'type', 'veth', 'peer', 'name', 'ns920be2f4-2b',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'tap920be2f4-2b', 'address',
                      'fe:16:3e:ff:ff:ff', run_as_root=True),
            mock.call('brctl', 'addif', 'br100', 'tap920be2f4-2b',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'tap920be2f4-2b', 'up',
                      run_as_root=True)
        ]
        network_info = [self.vif_bridge]
        with mock.patch('nova.utils.execute') as ex:
            driver = docker_driver.DockerDriver(object)
            driver.plug_vifs({'name': 'fake_instance'}, network_info)
            ex.assert_has_calls(calls)

    def test_plug_vifs_bridge_two_interfaces(self):
        calls = [
            # interface 1
            mock.call('ip', 'link', 'add', 'name', 'tap920be2f4-2b',
                      'type', 'veth', 'peer', 'name', 'ns920be2f4-2b',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'tap920be2f4-2b', 'address',
                      'fe:16:3e:ff:ff:ff', run_as_root=True),
            mock.call('brctl', 'addif', 'br100', 'tap920be2f4-2b',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'tap920be2f4-2b', 'up',
                      run_as_root=True),
            # interface 2
            mock.call('ip', 'link', 'add', 'name', 'tap920be2f4-2b',
                      'type', 'veth', 'peer', 'name', 'ns920be2f4-2b',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'tap920be2f4-2b', 'address',
                      'fe:16:3e:ff:ff:ff', run_as_root=True),
            mock.call('brctl', 'addif', 'br100', 'tap920be2f4-2b',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'tap920be2f4-2b', 'up',
                      run_as_root=True),
        ]
        network_info = [self.vif_bridge, self.vif_bridge]
        with mock.patch('nova.utils.execute') as ex:
            driver = docker_driver.DockerDriver(object)
            driver.plug_vifs({'name': 'fake_instance'}, network_info)
            ex.assert_has_calls(calls)

    def test_plug_vifs_ovs(self):
        iface_id = '920be2f4-2b98-411e-890a-69bcabb2a5a0'
        calls = [
            mock.call('ip', 'link', 'add', 'name', 'tap920be2f4-2b',
                      'type', 'veth', 'peer', 'name', 'ns920be2f4-2b',
                      run_as_root=True),

            mock.call('ovs-vsctl', '--timeout=120', '--', '--if-exists',
                      'del-port', 'tap920be2f4-2b', '--', 'add-port',
                      'br-int', 'tap920be2f4-2b',
                      '--', 'set', 'Interface', 'tap920be2f4-2b',
                      'external-ids:iface-id=%s' % iface_id,
                      'external-ids:iface-status=active',
                      'external-ids:attached-mac=00:11:22:33:44:55',
                      'external-ids:vm-uuid=instance_uuid',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'tap920be2f4-2b', 'up',
                      run_as_root=True),
        ]
        network_info = [
            {'network': {'bridge': 'br-int',
                         'subnets': [{'gateway': {'address': '10.11.12.1'},
                                      'cidr': '10.11.12.0/24',
                                      'ips': [{'address': '10.11.12.3',
                                               'type': 'fixed', 'version': 4}]
                                      }]},
             'address': '00:11:22:33:44:55',
             'id': iface_id,
             'type': network_model.VIF_TYPE_OVS}]
        with mock.patch('nova.utils.execute') as ex:
            driver = docker_driver.DockerDriver(object)
            driver.plug_vifs({'name': 'fake_instance',
                              'uuid': 'instance_uuid'}, network_info)
            ex.assert_has_calls(calls)

    def test_plug_vifs_ovs_hybrid(self):
        iface_id = '920be2f4-2b98-411e-890a-69bcabb2a5a0'
        calls = [
            mock.call('brctl', 'addbr', 'qbr920be2f4-2b', run_as_root=True),

            mock.call('brctl', 'setfd', 'qbr920be2f4-2b', 0, run_as_root=True),
            mock.call('brctl', 'stp', 'qbr920be2f4-2b', 'off',
                      run_as_root=True),
            mock.call('tee', "/sys/class/net/qbr920be2f4-2b/bridge/multicast_"
                      "snooping", run_as_root=True, process_input='0',
                      check_exit_code=[0, 1]),
            mock.call('ip', 'link', 'add', 'qvb920be2f4-2b', 'type',
                      'veth', 'peer', 'name', 'qvo920be2f4-2b',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'qvb920be2f4-2b', 'up',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'qvb920be2f4-2b', 'promisc', 'on',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'qvo920be2f4-2b', 'up',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'qvo920be2f4-2b', 'promisc', 'on',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'qbr920be2f4-2b', 'up',
                      run_as_root=True),
            mock.call('brctl', 'addif', 'qbr920be2f4-2b', 'qvb920be2f4-2b',
                      run_as_root=True),
            mock.call('ovs-vsctl', '--timeout=120', '--', '--if-exists',
                      'del-port', 'qvo920be2f4-2b', '--', 'add-port',
                      'br-int', 'qvo920be2f4-2b', '--', 'set', 'Interface',
                      'qvo920be2f4-2b', "external-ids:iface-id=920be2f4-2b98-"
                      "411e-890a-69bcabb2a5a0",
                      'external-ids:iface-status=active',
                      'external-ids:attached-mac=00:11:22:33:44:55',
                      'external-ids:vm-uuid=instance_uuid', run_as_root=True),
            mock.call('ip', 'link', 'add', 'name', 'tap920be2f4-2b', 'type',
                      'veth', 'peer', 'name', 'ns920be2f4-2b',
                      run_as_root=True),
            mock.call('brctl', 'addif', 'qbr920be2f4-2b', 'tap920be2f4-2b',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'tap920be2f4-2b', 'up',
                      run_as_root=True),
        ]
        network_info = [
            {'network': {'bridge': 'br-int',
                         'subnets': [{'gateway': {'address': '10.11.12.1'},
                                      'cidr': '10.11.12.0/24',
                                      'ips': [{'address': '10.11.12.3',
                                               'type': 'fixed', 'version': 4}]
                                      }]},
             'address': '00:11:22:33:44:55',
             'id': iface_id,
             'details': {'port_filter': True, 'ovs_hybrid_plug': True},
             'type': network_model.VIF_TYPE_OVS}]
        with mock.patch('nova.utils.execute') as ex:
            driver = docker_driver.DockerDriver(object)
            driver.plug_vifs({'name': 'fake_instance',
                              'uuid': 'instance_uuid'}, network_info)
            ex.assert_has_calls(calls)

    def test_unplug_vifs_ovs(self):
        iface_id = '920be2f4-2b98-411e-890a-69bcabb2a5a0'
        calls = [
            mock.call('ovs-vsctl', '--timeout=120', '--', '--if-exists',
                      'del-port', 'br-int', 'tap920be2f4-2b',
                      run_as_root=True)
        ]
        network_info = [
            {'network': {'bridge': 'br-int',
                         'subnets': [{'gateway': {'address': '10.11.12.1'},
                                      'cidr': '10.11.12.0/24',
                                      'ips': [{'address': '10.11.12.3',
                                               'type': 'fixed', 'version': 4}]
                                      }]},
             'devname': 'tap920be2f4-2b',
             'address': '00:11:22:33:44:55',
             'id': iface_id,
             'type': network_model.VIF_TYPE_OVS}]
        with mock.patch('nova.utils.execute') as ex:
            driver = docker_driver.DockerDriver(object)
            driver.unplug_vifs({'name': 'fake_instance',
                                'uuid': 'instance_uuid'}, network_info)
            ex.assert_has_calls(calls)

    def test_plug_vifs_midonet(self):
        iface_id = '920be2f4-2b98-411e-890a-69bcabb2a5a0'
        host_side_veth = 'tap920be2f4-2b'
        calls = [
            mock.call('ip', 'link', 'add', 'name', host_side_veth,
                      'type', 'veth', 'peer', 'name', 'ns920be2f4-2b',
                      run_as_root=True),

            mock.call('ip', 'link', 'set', host_side_veth, 'up',
                      run_as_root=True),

            mock.call('mm-ctl', '--bind-port', iface_id, host_side_veth,
                      run_as_root=True),
        ]

        network_info = [{'id': iface_id,
                         'type': network_model.VIF_TYPE_MIDONET}]

        with mock.patch('nova.utils.execute') as ex:
            driver = docker_driver.DockerDriver(object)
            driver.plug_vifs({'name': 'fake_instance',
                              'uuid': 'instance_uuid'}, network_info)
            ex.assert_has_calls(calls)

    def test_unplug_vifs_midonet(self):
        iface_id = '920be2f4-2b98-411e-890a-69bcabb2a5a0'
        calls = [
            mock.call('mm-ctl', '--unbind-port', iface_id, run_as_root=True)
        ]
        network_info = [{'id': iface_id,
                         'type': network_model.VIF_TYPE_MIDONET}]
        with mock.patch('nova.utils.execute') as ex:
            driver = docker_driver.DockerDriver(object)
            driver.unplug_vifs({'name': 'fake_instance',
                                'uuid': 'instance_uuid'}, network_info)
            ex.assert_has_calls(calls)

    def test_plug_vifs_iovisor(self):
        iface_id = '920be2f4-2b98-411e-890a-69bcabb2a5a0'
        tenant_id = 'tenant1'
        calls = [
            mock.call('ip', 'link', 'add', 'name', 'tap920be2f4-2b', 'type',
                      'veth', 'peer', 'name', 'ns920be2f4-2b',
                      run_as_root=True),

            mock.call('ifc_ctl', 'gateway', 'add_port', 'tap920be2f4-2b',
                      run_as_root=True),

            mock.call('ifc_ctl', 'gateway', 'ifup', 'tap920be2f4-2b',
                      'access_vm', "net1_" + iface_id, '00:11:22:33:44:55',
                      'pgtag2=network-id-xxx-yyy-zzz',
                      'pgtag1=%s' % tenant_id, run_as_root=True),

            mock.call('ip', 'link', 'set', 'tap920be2f4-2b', 'up',
                      run_as_root=True),
        ]

        network_info = [self.vif_iovisor]

        with mock.patch('nova.utils.execute') as ex:
            driver = docker_driver.DockerDriver(object)
            driver.plug_vifs({'name': 'fake_instance',
                              'uuid': 'instance_uuid',
                              'project_id': tenant_id}, network_info)
            ex.assert_has_calls(calls)

    def test_unplug_vifs_iovisor(self):
        iface_id = '920be2f4-2b98-411e-890a-69bcabb2a5a0'
        tenant_id = 'tenant1'
        calls = [
            mock.call('ifc_ctl', 'gateway', 'ifdown', 'tap920be2f4-2b',
                      'access_vm', 'net1_' + iface_id, '00:11:22:33:44:55',
                      run_as_root=True),
            mock.call('ifc_ctl', 'gateway', 'del_port', 'tap920be2f4-2b',
                      run_as_root=True)
        ]
        network_info = [self.vif_iovisor]
        with mock.patch('nova.utils.execute') as ex:
            driver = docker_driver.DockerDriver(object)
            driver.unplug_vifs({'name': 'fake_instance',
                                'uuid': 'instance_uuid',
                                'project_id': tenant_id}, network_info)
            ex.assert_has_calls(calls)

    def test_plug_vifs_windows(self):
        network_info = [{'type': 'hyperv'}]
        fake_instance = mock.sentinel.instance
        with mock.patch.object(vifs.DockerGenericVIFDriver,
                               'plug_windows') as mock_plug_windows:
            driver = docker_driver.DockerDriver(object)
            driver.plug_vifs(fake_instance, network_info)
            mock_plug_windows.assert_called_once_with(
                fake_instance, {'type': 'hyperv'})

    def test_unplug_vifs_windows(self):
        network_info = [{'type': 'hyperv'}]
        fake_instance = mock.sentinel.instance
        with mock.patch.object(vifs.DockerGenericVIFDriver,
                               'unplug_windows') as mock_unplug_windows:
            driver = docker_driver.DockerDriver(object)
            driver.unplug_vifs(fake_instance, network_info)
            mock_unplug_windows.assert_called_once_with(
                fake_instance, {'type': 'hyperv'})

    def test_unplug_vifs_ovs_hybrid(self):
        iface_id = '920be2f4-2b98-411e-890a-69bcabb2a5a0'
        calls = [
            mock.call('ovs-vsctl', '--timeout=120', '--', '--if-exists',
                      'del-port', 'br-int', 'qvo920be2f4-2b',
                      run_as_root=True)
        ]
        network_info = [
            {'network': {'bridge': 'br-int',
                         'subnets': [{'gateway': {'address': '10.11.12.1'},
                                      'cidr': '10.11.12.0/24',
                                      'ips': [{'address': '10.11.12.3',
                                               'type': 'fixed', 'version': 4}]
                                      }]},
             'devname': 'tap920be2f4-2b',
             'address': '00:11:22:33:44:55',
             'id': iface_id,
             'details': {'port_filter': True, 'ovs_hybrid_plug': True},
             'type': network_model.VIF_TYPE_OVS}]
        with mock.patch('nova.utils.execute') as ex:
            driver = docker_driver.DockerDriver(object)
            driver.unplug_vifs({'name': 'fake_instance',
                                'uuid': 'instance_uuid'}, network_info)
            ex.assert_has_calls(calls)

    @mock.patch.object(docker_driver.DockerDriver,
                       '_find_container_by_uuid',
                       return_value={'id': 'fake_id'})
    @mock.patch.object(docker_driver.DockerDriver,
                       '_find_container_pid',
                       return_value=1234)
    def test_attach_vifs(self, mock_find_by_uuid, mock_find_pid):
        calls = [
            mock.call('ln', '-sf', '/proc/1234/ns/net',
                      '/var/run/netns/fake_id', run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id', 'ip', 'link',
                      'set', 'lo', 'up', run_as_root=True),
            mock.call('ip', 'link', 'set', 'ns920be2f4-2b', 'netns',
                      'fake_id', run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id', 'ip', 'link',
                      'set', 'ns920be2f4-2b', 'address', '00:11:22:33:44:55',
                      run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id',
                      'ip', 'addr', 'add', '10.11.12.3/24', 'dev',
                      'ns920be2f4-2b', run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id',
                      'ip', 'link', 'set',
                      'ns920be2f4-2b', 'up', run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id', 'ip', 'route',
                      'replace', 'default', 'via', '10.11.12.1', 'dev',
                      'ns920be2f4-2b', run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id', 'ethtool', '--offload',
                      'ns920be2f4-2b', 'tso', 'off', run_as_root=True)
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
            driver = docker_driver.DockerDriver(object)
            driver._attach_vifs({'uuid': 'fake_uuid'}, network_info)
            ex.assert_has_calls(calls)

    @mock.patch.object(docker_driver.DockerDriver,
                       '_find_container_by_uuid',
                       return_value={'id': 'fake_id'})
    @mock.patch.object(docker_driver.DockerDriver,
                       '_find_container_pid',
                       return_value=1234)
    def test_attach_vifs_two_interfaces(self, mock_find_by_uuid,
                                        mock_find_pid):
        calls = [
            mock.call('ln', '-sf', '/proc/1234/ns/net',
                      '/var/run/netns/fake_id', run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id', 'ip', 'link',
                      'set', 'lo', 'up', run_as_root=True),
            # interface 1
            mock.call('ip', 'link', 'set', 'ns920be2f4-2b', 'netns', 'fake_id',
                      run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id', 'ip', 'link',
                      'set', 'ns920be2f4-2b', 'address', '00:11:22:33:44:55',
                      run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id',
                      'ip', 'addr', 'add', '10.11.12.3/24', 'dev',
                      'ns920be2f4-2b', run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id',
                      'ip', 'link', 'set',
                      'ns920be2f4-2b', 'up', run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id', 'ip', 'route',
                      'replace', 'default', 'via', '10.11.12.1', 'dev',
                      'ns920be2f4-2b', run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id', 'ethtool', '--offload',
                      'ns920be2f4-2b', 'tso', 'off', run_as_root=True),
            # interface 2
            mock.call('ip', 'link', 'set', 'ns920be2f4-2b', 'netns', 'fake_id',
                      run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id', 'ip', 'link',
                      'set', 'ns920be2f4-2b', 'address', '00:11:22:33:44:66',
                      run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id',
                      'ip', 'addr', 'add', '10.13.12.3/24', 'dev',
                      'ns920be2f4-2b', run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id',
                      'ip', 'link', 'set',
                      'ns920be2f4-2b', 'up', run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id', 'ip', 'route',
                      'replace', 'default', 'via', '10.13.12.1', 'dev',
                      'ns920be2f4-2b', run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'fake_id', 'ethtool', '--offload',
                      'ns920be2f4-2b', 'tso', 'off', run_as_root=True)
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
            driver = docker_driver.DockerDriver(object)
            driver._attach_vifs({'uuid': 'fake_uuid'}, network_info)
            ex.assert_has_calls(calls)

    @mock.patch.object(docker_driver, 'os')
    def test_attach_vifs_hyperv(self, mock_os):
        mock_os.name = 'nt'
        with mock.patch.object(docker_driver.DockerDriver,
                               '_get_container_id') as mock_get_container_id:
            driver = docker_driver.DockerDriver(object)
            driver._attach_vifs(mock.sentinel.instance,
                                mock.sentinel.network_info)
            self.assertFalse(mock_get_container_id.called)
