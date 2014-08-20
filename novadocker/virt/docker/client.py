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

import functools
import socket
import urllib

from eventlet.green import httplib
import six

from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging


LOG = logging.getLogger(__name__)


def filter_data(f):
    """Decorator that post-processes data returned by Docker.

     This will avoid any surprises with different versions of Docker.
    """
    @functools.wraps(f)
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


class Response(object):
    def __init__(self, http_response, url=None):
        self.url = url
        self._response = http_response
        self.code = int(http_response.status)
        self._json = None

    def read(self, size=None):
        return self._response.read(size)

    def to_json(self, default=None):
        if not self._json:
            self._json = self._decode_json(self._response.read(), default)
        return self._json

    def _validate_content_type(self):
        # Docker does not return always the correct Content-Type.
        # Lets try to parse the response anyway since json is requested.
        if self._response.getheader('Content-Type') != 'application/json':
            LOG.debug("Content-Type of response is not application/json"
                      " (Docker bug?). Requested URL %s" % self.url)

    @filter_data
    def _decode_json(self, data, default=None):
        if not data:
            return default
        self._validate_content_type()
        # Do not catch ValueError or SyntaxError since that
        # just hides the root cause of errors.
        return jsonutils.loads(data)


class UnixHTTPConnection(httplib.HTTPConnection):
    def __init__(self):
        httplib.HTTPConnection.__init__(self, 'localhost')
        self.unix_socket = '/var/run/docker.sock'

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(self.unix_socket)
        self.sock = sock


class DockerHTTPClient(object):
    VERSION = 'v1.13'

    def __init__(self, connection=None):
        self._connection = connection

    @property
    def connection(self):
        if self._connection:
            return self._connection
        else:
            return UnixHTTPConnection()

    def make_request(self, *args, **kwargs):
        headers = {}
        if 'headers' in kwargs and kwargs['headers']:
            headers = kwargs['headers']
        if 'Content-Type' not in headers:
            headers['Content-Type'] = 'application/json'
            kwargs['headers'] = headers
        conn = self.connection

        # args[1] == path, args[2:] == query represented as tuples
        url = "/%s/%s" % (self.VERSION, urllib.quote(args[1]))
        if len(args) > 2:
            url += "?" + urllib.urlencode(args[2:])
        encoded_args = args[0], url

        conn.request(*encoded_args, **kwargs)
        return Response(conn.getresponse(), url=encoded_args[1])

    def list_containers(self, _all=True):
        resp = self.make_request(
            'GET',
            'containers/ps',
            ('all', int(_all)))
        if resp.code == 404:
            return []
        return resp.to_json(default=[])

    def create_container(self, args, name):
        data = {
            'Hostname': '',
            'User': '',
            'Memory': 0,
            'MemorySwap': 0,
            'AttachStdin': False,
            'AttachStdout': False,
            'AttachStderr': False,
            'PortSpecs': [],
            'Tty': True,
            'OpenStdin': True,
            'StdinOnce': False,
            'Env': None,
            'Cmd': [],
            'Dns': None,
            'Image': None,
            'Volumes': {},
            'VolumesFrom': '',
        }
        data.update(args)
        resp = self.make_request(
            'POST',
            'containers/create',
            ('name', unicode(name).encode('utf-8')),
            body=jsonutils.dumps(data))
        if resp.code != 201:
            return
        obj = resp.to_json()
        for k, v in obj.iteritems():
            if k.lower() == 'id':
                return v

    def start_container(self, container_id):
        resp = self.make_request(
            'POST',
            'containers/{0}/start'.format(container_id),
            body='{}')
        return (resp.code == 200 or resp.code == 204)

    def pause_container(self, container_id):
        resp = self.make_request(
            'POST',
            'containers/{0}/pause'.format(container_id),
            body='{}')
        return (resp.code == 204)

    def unpause_container(self, container_id):
        resp = self.make_request(
            'POST',
            'containers/{0}/unpause'.format(container_id),
            body='{}')
        return (resp.code == 204)

    def inspect_image(self, image_name):
        resp = self.make_request(
            'GET',
            'images/{0}/json'.format(
                unicode(image_name).encode('utf-8')))
        if resp.code != 200:
            return
        return resp.to_json()

    def inspect_container(self, container_id):
        resp = self.make_request(
            'GET',
            'containers/{0}/json'.format(container_id))
        if resp.code != 200:
            return {}
        return resp.to_json()

    def stop_container(self, container_id, timeout=5):
        resp = self.make_request(
            'POST',
            'containers/{0}/stop'.format(container_id),
            ('t', timeout))
        return (resp.code == 204)

    def kill_container(self, container_id):
        resp = self.make_request(
            'POST',
            'containers/{0}/kill'.format(container_id))
        return (resp.code == 204)

    def destroy_container(self, container_id):
        resp = self.make_request(
            'DELETE',
            'containers/{0}'.format(container_id))
        return (resp.code == 204)

    def get_image(self, name, size=4096):
        parts = unicode(name).encode('utf-8').rsplit(':', 1)
        url = 'images/{0}/get'.format(parts[0])
        resp = self.make_request('GET', url)

        while True:
            buf = resp.read(size)
            if not buf:
                break
            yield buf
        return

    def get_image_resp(self, name):
        parts = unicode(name).encode('utf-8').rsplit(':', 1)
        url = 'images/{0}/get'.format(parts[0])
        resp = self.make_request('GET', url)
        return resp

    def load_repository(self, name, data):
        url = 'images/load'
        self.make_request('POST', url, body=data)

    def load_repository_file(self, name, path):
        with open(path) as fh:
            self.load_repository(unicode(name).encode('utf-8'), fh)

    def commit_container(self, container_id, name):
        parts = unicode(name).encode('utf-8').rsplit(':', 1)
        url = 'commit'
        query = [('container', container_id),
                 ('repo', parts[0])]

        if len(parts) > 1:
            query += (('tag', parts[1]),)
        resp = self.make_request('POST', url, *query)
        return (resp.code == 201)

    def get_container_logs(self, container_id):
        resp = self.make_request(
            'POST',
            'containers/{0}/attach'.format(container_id),
            ('logs', '1'),
            ('stream', '0'),
            ('stdout', '1'),
            ('stderr', '1'))
        if resp.code != 200:
            return
        return resp.read()

    def ping(self):
        resp = self.make_request('GET', '_ping')
        return (resp.code == 200)
