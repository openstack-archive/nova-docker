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

import mock
import multiprocessing

from nova import test
from novadocker.virt.docker import hostinfo
import psutil


class HostInfoTestCase(test.NoDBTestCase):

    _FAKE_DISK_INFO = {'total_size': 100000,
                       'free_size': 50000,
                       'used_size': 50000}

    def setUp(self):
        super(HostInfoTestCase, self).setUp()
        self.stubs.Set(hostinfo, 'statvfs', self.statvfs)

    def statvfs(self):
        diskinfo = psutil.namedtuple('usage', ('total', 'free', 'used'))
        return diskinfo(self._FAKE_DISK_INFO['total_size'],
                        self._FAKE_DISK_INFO['free_size'],
                        self._FAKE_DISK_INFO['used_size'])

    def test_get_disk_usage(self):
        disk_usage = hostinfo.get_disk_usage()
        self.assertEqual(disk_usage['total'],
                         self._FAKE_DISK_INFO['total_size'])
        self.assertEqual(disk_usage['available'],
                         self._FAKE_DISK_INFO['free_size'])
        self.assertEqual(disk_usage['used'],
                         self._FAKE_DISK_INFO['used_size'])

    @mock.patch.object(multiprocessing, 'cpu_count')
    def test_get_total_vcpus(self, mock_cpu_count):
        mock_cpu_count.return_value = 1

        cpu_count = hostinfo.get_total_vcpus()

        self.assertEqual(mock_cpu_count.return_value, cpu_count)

    def test_get_memory_usage(self):
        fake_total_memory = 4096
        fake_used_memory = 2048

        with mock.patch.object(psutil,
                               'virtual_memory') as mock_virtual_memory:
            mock_virtual_memory.return_value.total = fake_total_memory
            mock_virtual_memory.return_value.used = fake_used_memory

            usage = hostinfo.get_memory_usage()

            self.assertEqual(fake_total_memory, usage['total'])
            self.assertEqual(fake_used_memory, usage['used'])

    @mock.patch('novadocker.virt.docker.hostinfo.get_mounts')
    def test_find_cgroup_devices_path_centos(self, mock):
        mock.return_value = [
            'none /sys/fs/cgroup cgroup rw,relatime,perf_event,'
            'blkio,net_cls,freezer,devices,memory,cpuacct,cpu,'
            'cpuset 0 0']
        path = hostinfo.get_cgroup_devices_path()
        self.assertEqual('/sys/fs/cgroup', path)

    @mock.patch('novadocker.virt.docker.hostinfo.get_mounts')
    def test_find_cgroup_devices_path_ubuntu(self, mock):
        mock.return_value = [
            'cgroup /cgroup tmpfs rw,relatime,mode=755 0 0',
            'cgroup /cgroup/devices cgroup rw,relatime,devices,' +
            'clone_children 0 0']
        path = hostinfo.get_cgroup_devices_path()
        self.assertEqual('/cgroup/devices', path)
