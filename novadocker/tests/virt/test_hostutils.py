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
    def test_sys_uptime(self):
        expect_uptime = "this is my uptime"
        with mock.patch('nova.utils.execute',
                        return_value=(expect_uptime, None)):
            uptime = hostutils.sys_uptime()
            self.assertEqual(expect_uptime, uptime)
