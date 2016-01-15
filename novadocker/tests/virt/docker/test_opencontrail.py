# Copyright (C) 2014 Juniper Networks, Inc
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


class DockerOpenContrailVIFDriverTestCase(test.TestCase):
    def setUp(self):
        super(DockerOpenContrailVIFDriverTestCase, self).setUp()
        docker_driver.CONF.set_override(
            'vif_driver',
            'novadocker.virt.docker.opencontrail.OpenContrailVIFDriver',
            group='docker')

    def test_plug_vrouter(self):
        vid = '920be1f4-2b98-411e-890a-69bcabb2a5a0'
        address = '10.1.2.1'
        calls = [
            mock.call('ip', 'link', 'add', 'veth%s' % vid[:8],
                      'type', 'veth', 'peer', 'name',
                      'ns%s' % vid[:8], run_as_root=True),
            mock.call('ip', 'link', 'set', 'ns%s' % vid[:8],
                      'address', address, run_as_root=True),
        ]
        network_info = [network_model.VIF(id=vid, address=address)]
        with mock.patch('nova.utils.execute') as ex:
            driver = docker_driver.DockerDriver(object)
            driver.plug_vifs({'name': 'fake_instance'}, network_info)
            ex.assert_has_calls(calls)

    def test_plug_two_vrouters(self):
        vid1 = '921be2f4-2b98-411e-890a-69bcabb2a5a1'
        address1 = '10.1.2.2'
        vid2 = '922be3f4-2b98-411e-890a-69bcabb2a5a2'
        address2 = '10.1.2.3'
        calls = [
            mock.call('ip', 'link', 'add', 'veth%s' % vid1[:8],
                      'type', 'veth', 'peer', 'name',
                      'ns%s' % vid1[:8], run_as_root=True),
            mock.call('ip', 'link', 'set', 'ns%s' % vid1[:8],
                      'address', address1, run_as_root=True),
            mock.call('ip', 'link', 'add', 'veth%s' % vid2[:8],
                      'type', 'veth', 'peer', 'name',
                      'ns%s' % vid2[:8], run_as_root=True),
            mock.call('ip', 'link', 'set', 'ns%s' % vid2[:8],
                      'address', address2, run_as_root=True),
        ]
        network_info = [network_model.VIF(id=vid1, address=address1),
                        network_model.VIF(id=vid2, address=address2)]
        with mock.patch('nova.utils.execute') as ex:
            driver = docker_driver.DockerDriver(object)
            driver.plug_vifs({'name': 'fake_instance'}, network_info)
            ex.assert_has_calls(calls)

    @mock.patch.object(docker_driver.DockerDriver,
                       '_find_container_by_uuid',
                       return_value={'id': 'my_vm'})
    @mock.patch.object(docker_driver.DockerDriver,
                       '_find_container_pid',
                       return_value=7890)
    def test_attach_vrouter(self, mock_find_by_uuid, mock_find_pid):
        vid = '920be1f5-2b98-411e-890a-69bcabb2a5a0'
        if_remote_name = 'ns%s' % vid[:8]
        if_local_name = 'veth%s' % vid[:8]
        address = '10.1.2.1'
        gateway = '1.1.1.254'
        fixed_ip = '1.1.1.42/24'
        fixed_ip_addr = '1.1.1.42'
        vnid = 'virtual-network-1'
        network_info = [network_model.VIF(id=vid, address=address,
                                          network=network_model.Network(
                                              id=vnid,
                                              subnets=[network_model.Subnet(
                                                  cidr='1.1.1.0/24',
                                                  gateway=network_model.IP(
                                                      address=gateway,
                                                      type='gateway'),
                                                  ips=[network_model.IP(
                                                      address=fixed_ip_addr,
                                                      type='fixed',
                                                      version=4)]
                                              )]
                                          ))]
        Instance = type(
            'Instance', (dict, object),
            dict(__getattr__=lambda self, attr: self[attr]))

        instance = Instance(
            name='fake_instance', display_name='fake_vm',
            hostname='fake_vm', host='linux',
            project_id='e2d2ddc6-4e0f-4cd4-b846-3bad53093ec6',
            uuid='d4b817fb-7885-4649-bad7-89302dde12e1')

        calls = [
            mock.call('mkdir', '-p', '/var/run/netns', run_as_root=True),
            mock.call('ln', '-sf', '/proc/7890/ns/net',
                      '/var/run/netns/my_vm', run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'my_vm', 'ip', 'link',
                      'set', 'lo', 'up', run_as_root=True),
            mock.call('ip', 'link', 'set', if_remote_name, 'netns', 'my_vm',
                      run_as_root=True),
            mock.call('vrouter-port-control',
                      '--oper=add --uuid=%s --instance_uuid=%s\
                      --vn_uuid=%s --vm_project_uuid=%s\
                      --ip_address=%s --ipv6_address=None\
                      --vm_name=%s --mac=%s --tap_name=%s\
                      --port_type=NovaVMPort\
                      --tx_vlan_id=-1 --rx_vlan_id=-1' % (
                          vid, instance['uuid'], vnid,
                          instance['project_id'], fixed_ip_addr,
                          instance['name'], address, if_local_name),
                      run_as_root=True),
            mock.call('ip', 'link', 'set', if_local_name, 'up',
                      run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'my_vm', 'ip', 'link',
                      'set', if_remote_name, 'address', address,
                      run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'my_vm', 'ifconfig',
                      if_remote_name, fixed_ip, run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'my_vm', 'ip',
                      'route', 'replace', 'default', 'via', gateway,
                      'dev', if_remote_name, run_as_root=True),
            mock.call('ip', 'netns', 'exec', 'my_vm', 'ip', 'link',
                      'set', if_remote_name, 'up', run_as_root=True)
        ]
        with mock.patch('nova.utils.execute') as ex:
            driver = docker_driver.DockerDriver(object)
            driver._attach_vifs(instance, network_info)
            ex.assert_has_calls(calls)

    def test_unplug_vrouter(self):
        vid = '920be1f4-2b98-411e-890a-69bcabb2a5a0'
        address = '10.1.2.1'
        network_info = [network_model.VIF(id=vid, address=address)]
        driver = docker_driver.DockerDriver(object)
        driver.unplug_vifs({'name': 'fake_instance'}, network_info)
