# docker.sh - Devstack extras script to install Docker

if [[ $VIRT_DRIVER == "docker" ]] && [[ $2 == "install" ]] ; then

  # Install docker package and images
  # * downloads a base busybox image and a glance registry image if necessary
  # * install the images in Docker's image cache


  # Keep track of the current directory
  SCRIPT_DIR=$(cd $(dirname "$0") && pwd)
  TOP_DIR=$SCRIPT_DIR

  echo $SCRIPT_DIR $TOP_DIR

  # Import common functions
  source $TOP_DIR/functions

  # Load local configuration
  source $TOP_DIR/stackrc

  FILES=$TOP_DIR/files

  # Get our defaults
  source $TOP_DIR/lib/nova_plugins/hypervisor-docker

  SERVICE_TIMEOUT=${SERVICE_TIMEOUT:-60}


  # Install Docker Service
  # ======================

  if is_fedora; then
      install_package docker-io socat dnsmasq
  else
      # Stop the auto-repo updates and do it when required here
      NO_UPDATE_REPOS=True

      # Set up home repo
      curl https://get.docker.io/gpg | sudo apt-key add -
      install_package python-software-properties && \
          sudo sh -c "echo deb $DOCKER_APT_REPO docker main > /etc/apt/sources.list.d/docker.list"
      apt_get update
      install_package --force-yes lxc-docker socat
  fi

  # Start the daemon - restart just in case the package ever auto-starts...
  restart_service docker

  echo "Waiting for docker daemon to start..."
  DOCKER_GROUP=$(groups | cut -d' ' -f1)
  CONFIGURE_CMD="while ! /bin/echo -e 'GET /v1.3/version HTTP/1.0\n\n' | socat - unix-connect:$DOCKER_UNIX_SOCKET 2>/dev/null | grep -q '200 OK'; do
      # Set the right group on docker unix socket before retrying
      sudo chgrp $DOCKER_GROUP $DOCKER_UNIX_SOCKET
      sudo chmod g+rw $DOCKER_UNIX_SOCKET
      sleep 1
  done"
  if ! timeout $SERVICE_TIMEOUT sh -c "$CONFIGURE_CMD"; then
      die $LINENO "docker did not start"
  fi

  # Get guest container image
  docker pull $DOCKER_IMAGE
  docker tag $DOCKER_IMAGE $DOCKER_IMAGE_NAME

  # Get docker-registry image
  docker pull $DOCKER_REGISTRY_IMAGE
  docker tag $DOCKER_REGISTRY_IMAGE $DOCKER_REGISTRY_IMAGE_NAME

fi


