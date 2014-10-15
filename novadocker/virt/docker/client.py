# Copyright (c) 2013 dotCloud, Inc.
# Copyright 2014 IBM Corp.
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

import functools
import inspect

import six

from docker import client


def filter_data(f):
    """Decorator that post-processes data returned by Docker.

     This will avoid any surprises with different versions of Docker.
    """
    @functools.wraps(f, assigned=[])
    def wrapper(*args, **kwds):
        out = f(*args, **kwds)

        def _filter(obj):
            if isinstance(obj, list):
                new_list = []
                for o in obj:
                    new_list.append(_filter(o))
                obj = new_list
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(k, six.string_types):
                        obj[k.lower()] = _filter(v)
            return obj
        return _filter(out)
    return wrapper


class DockerHTTPClient(client.Client):
    def __init__(self, url='unix://var/run/docker.sock'):
        super(DockerHTTPClient, self).__init__(
            base_url=url,
            version='1.7',
            timeout=10
        )
        self._setup_decorators()

    def _setup_decorators(self):
        for name, member in inspect.getmembers(self, inspect.ismethod):
            if not name.startswith('_'):
                setattr(self, name, filter_data(member))

    def pause(self, container_id):
        url = self._url("/containers/{0}/pause".format(container_id))
        res = self._post(url)
        return res.status_code == 204

    def unpause(self, container_id):
        url = self._url("/containers/{0}/unpause".format(container_id))
        res = self._post(url)
        return res.status_code == 204

    def load_repository_file(self, name, path):
        with open(path) as fh:
            self.load_image(fh)

    def get_container_logs(self, container_id):
        params = {
            'logs': 1,
            'stdout': 1,
            'stderr': 1,
            'stream': 0
        }
        return self.attach_socket(container_id, params)