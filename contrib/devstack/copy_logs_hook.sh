#!/bin/bash
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

# This script is executed inside gate_hook.sh

if is_ubuntu; then
  # Find and collect docker daemon logs
  sudo find /var/log/ -name "docker*" -print -exec sudo cp {} /opt/stack/logs/ \;
elif is_fedora; then
  # fetch the docker.service logs from the journal
  sudo journalctl _SYSTEMD_UNIT=docker.service > /opt/stack/logs/docker.log 2>&1
fi
