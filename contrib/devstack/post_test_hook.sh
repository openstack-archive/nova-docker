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

# This script is executed inside post_test_hook function in devstack gate.

# Collect docker daemon logs
sudo ls -altr /var/log/docker*
sudo ls -altr /var/log/upstart/docker*
if [ -f /var/log/docker ]; then
  sudo cp /var/log/docker $BASE/logs/docker.log
fi
if [ -f /var/log/upstart/docker.log ]; then
  sudo cp /var/log/upstart/docker.log $BASE/logs
fi