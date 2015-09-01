# Copyright 2014 Docker, Inc
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

from nova import test
from novadocker.virt import hostutils


class HostUtilsTestCase(test.NoDBTestCase):
    def _test_sys_uptime(self, is_nt_os=False):
        expect_uptime = ("fake_time up 0:00:00,  0 users,  "
                         "load average: 0, 0, 0")
        fake_tick_count = 0
        fake_time = 'fake_time'

        with mock.patch.multiple(hostutils, os=mock.DEFAULT, time=mock.DEFAULT,
                                 ctypes=mock.DEFAULT, utils=mock.DEFAULT,
                                 create=True) as lib_mocks:

            lib_mocks['os'].name = 'nt' if is_nt_os else ''
            lib_mocks['time'].strftime.return_value = fake_time
            lib_mocks['utils'].execute.return_value = (expect_uptime, None)
            tick_count = lib_mocks['ctypes'].windll.kernel32.GetTickCount64
            tick_count.return_value = fake_tick_count

            uptime = hostutils.sys_uptime()

            if is_nt_os:
                tick_count.assert_called_once_with()
                lib_mocks['time'].strftime.assert_called_once_with("%H:%M:%S")
            else:
                lib_mocks['utils'].execute.assert_called_once_with(
                    'env', 'LANG=C', 'uptime')

        self.assertEqual(expect_uptime, uptime)

    def test_sys_uptime(self):
        self._test_sys_uptime()

    def test_nt_sys_uptime(self):
        self._test_sys_uptime(is_nt_os=True)
