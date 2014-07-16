===============================
nova-docker
===============================

Docker driver for OpenStack Nova.

Free software: Apache license

----------------------------
Installation & Configuration
----------------------------

^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
1. Install the python modules.
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

For example::

  $ python setup.py install

Note: There are better and cleaner ways of managing Python modules, such as using distribution packages or 'pip'. The setup.py file and Debian's stdeb, for instance, may be used to create Debian/Ubuntu packages.

^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2. Enable the driver in Nova's configuration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In nova.conf::

  compute_driver novadocker.virt.docker.DockerDriver

^^^^^^^^^^^^^^^^^^^^^^^^^^
3. Setup a Docker registry
^^^^^^^^^^^^^^^^^^^^^^^^^^

In a single-host development environment, the registry may live on 'localhost' using port 5042. Otherwise, it is best-advised to use a centralized registry endpoint. If running a centralized registry, it will be necessary to tune the configuration to specify its IP address and port (see step 3).

Furthermore, the registry deployed must use the Glance backend. If running multiple registries, set storage_alternative to 's3' in the registry's configuration.

For further reading and information on installing the registry for use in OpenStack: https://github.com/dmp42/docker-registry-driver-glance

^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
4. Optionally tune site-specific settings.
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In nova.conf::

  [docker]
  registry_ip=172.16.0.2
  registry_port=5000
  vif_driver=novadocker.virt.docker.vifs.DockerGenericVIFDriver

Where the registry_ip and port refer to a local Docker registry.

----------
Contact Us
----------
Join us in #nova-docker on Freenode IRC

--------
Features
--------

* TODO
