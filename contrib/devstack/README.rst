The contrib/devstack/ directory contains the files necessary to integrate Docker Nova driver with devstack.

To install::

    $ git clone https://git.openstack.org/openstack/nova-docker /opt/stack/nova-docker
    $ git clone https://git.openstack.org/openstack-dev/devstack /opt/stack/devstack

    # Note : only needed until we can make use of configure_nova_hypervisor_rootwrap
    $ git clone https://git.openstack.org/openstack/nova /opt/stack/nova

    $ cd /opt/stack/nova-docker
    $ ./contrib/devstack/prepare_devstack.sh

Run devstack as normal::

    $ ./stack.sh
