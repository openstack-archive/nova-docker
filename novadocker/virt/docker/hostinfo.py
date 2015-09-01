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

import multiprocessing
import os

from oslo_config import cfg
import psutil

CONF = cfg.CONF


def statvfs():
    docker_path = CONF.docker.root_directory
    if not os.path.exists(docker_path):
        docker_path = '/'
    return psutil.disk_usage(docker_path)


def get_disk_usage():
    # This is the location where Docker stores its containers. It's currently
    # hardcoded in Docker so it's not configurable yet.
    st = statvfs()
    return {
        'total': st.total,
        'available': st.free,
        'used': st.used
    }


def get_total_vcpus():
    return multiprocessing.cpu_count()


def get_vcpus_used(containers):
    total_vcpus_used = 0
    for container in containers:
        if isinstance(container, dict):
            total_vcpus_used += container.get('Config', {}).get(
                'CpuShares', 0) / 1024

    return total_vcpus_used


def get_memory_usage():
    vmem = psutil.virtual_memory()
    return {
        'total': vmem.total,
        'used': vmem.used
    }


def get_mounts():
    with open('/proc/mounts') as f:
        return f.readlines()


def get_cgroup_devices_path():
    for ln in get_mounts():
        fields = ln.split(' ')
        if fields[2] == 'cgroup' and 'devices' in fields[3].split(','):
            return fields[1]
