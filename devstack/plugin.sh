#!/bin/bash
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

# Save trace setting
XTRACE=$(set +o | grep xtrace)
set +o xtrace

# main loop
if is_service_enabled kuryr; then
    if [[ "$1" == "stack" && "$2" == "install" ]]; then

    elif [[ "$1" == "stack" && "$2" == "post-config" ]]; then
        wget http://get.docker.com -O install_docker.sh
        sudo chmod 777 install_docker.sh
        sudo sh install_docker.sh
        sudo rm install_docker.sh

        # CentOS/RedHat distros don't start the services just after the package
        # is installed if it is not explicitily set. So the script fails on
        # them in this killall because there is nothing to kill.
        # TODO(devvesa): use a `is_running service` or a more elegant approach
        sudo killall docker || true
        run_process docker-engine "sudo /usr/bin/docker daemon -H tcp://0.0.0.0:2375"
    fi
    if [[ "$1" == "unstack" ]]; then
        stop_process docker-engine
    fi
fi

# Restore xtrace
$XTRACE

