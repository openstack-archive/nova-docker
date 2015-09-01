# Copyright (c) 2014 Docker, Inc.
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


import ctypes
import datetime
import os
import time

from nova import utils


def sys_uptime():
    """Returns the host uptime."""

    if os.name == 'nt':
        tick_count64 = ctypes.windll.kernel32.GetTickCount64()
        return ("%s up %s,  0 users,  load average: 0, 0, 0" %
                (str(time.strftime("%H:%M:%S")),
                 str(datetime.timedelta(milliseconds=long(tick_count64)))))
    else:
        out, err = utils.execute('env', 'LANG=C', 'uptime')
        return out
