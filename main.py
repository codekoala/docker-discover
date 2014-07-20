#!/usr/bin/env python

from collections import defaultdict
from distutils.spawn import find_executable
from subprocess import call
import os
import sys
import time

from jinja2 import Environment, PackageLoader
import etcd


env = Environment(loader=PackageLoader('haproxy', 'templates'))
POLL_TIMEOUT = 5
HAPROXY_CONFIG = '/etc/haproxy.cfg'
HAPROXY_PID = '/var/run/haproxy.pid'


def get_etcd_addr():
    """
    Determine the host and port that etcd should be available on using the
    `ETCD_HOST` environment variable..

    :returns:
        A 2-tuple with the hostname/IP and the numeric TCP port at which etcd
        can be reached.

    :raises SystemExit:
        If the `ETCD_HOST` environment variable is not defined or is empty.

    """

    etcd_host = os.environ.get("ETCD_HOST", None)
    if not etcd_host:
        print("ETCD_HOST not set")
        sys.exit(1)

    host, port = etcd_host, 4001
    if ":" in host:
        host, port = host.split(":")

    return host, int(port)


def get_haproxy_path():
    """
    Return the absolute path to the `haproxy` executable.

    :raises SystemExit:
        If haproxy cannot be found on the PATH.

    """

    path = find_executable('haproxy')
    if not path:
        print('haproxy was not found on your PATH, and it must be installed '
              'to use this script')
        sys.exit(1)

    return path


def get_services(client):
    """
    Find all services which have been published to etcd and have exposed a
    port.

    :param etcd.Client client:
        A handle to an etcd server.

    :returns:
        A dictionary of dictionaries keyed on service name. The inner
        dictionary includes the TCP port that the service uses, along with a
        list of IP:port values that refer to containers which have exposed the
        service port (thereby acting as backend services).

    """

    # TODO: handle severed connection, etc
    backends = client.read('/backends', recursive=True)
    services = defaultdict(lambda: {
        'port': None,
        'backends': []
    })

    for i in backends.children:
        if i.key[1:].count("/") < 2:
            continue

        ignore, service, container = i.key[1:].rsplit("/", 2)
        endpoints = services[service]
        if container == "port":
            endpoints["port"] = i.value
            continue

        endpoints["backends"].append(dict(name=container, addr=i.value))

    # filter out services with no "port" value in etcd
    for svc, data in tuple(services.items()):
        if data['port'] is None:
            services.pop(svc)

    return services


def generate_config(services):
    """
    Generate a configuration file for haproxy and save it to disk.

    It is expected that the results of :py:func:`get_services` will be passed
    to this function.

    :param dict services:
        A dictionary of dictionaries, keyed on service name.

    """

    template = env.get_template('haproxy.cfg.tmpl')
    with open(HAPROXY_CONFIG, "w") as f:
        f.write(template.render(services=services))


def restart_haproxy():
    """
    Restart haproxy.

    :returns:
        ``True`` when haproxy appears to have restarted successfully, ``False``
        otherwise.

    """

    path = get_haproxy_path()
    cmd = '{haproxy} -f {cfg} -p {pid} -sf $(cat {pid})'.format(
        haproxy=path,
        cfg=HAPROXY_CONFIG,
        pid=HAPROXY_PID,
    )

    # TODO: shell=True is yucky... read in PID rather than using the cat
    return call(cmd, shell=True) == 0


def main():
    """
    Periodically poll etcd for the list of available services running in docker
    containers. When a new service becomes available or a service disappears,
    update the configuration for haproxy and restart it.

    """

    # check for haproxy and etcd config before getting into the real code
    get_haproxy_path()
    host, port = get_etcd_addr()

    client = None
    current_services = {}

    while True:
        if client is None:
            # TODO: connection error handling
            client = etcd.Client(host=host, port=port)

        services = get_services(client)
        if services != current_services:
            print("config changed. reload haproxy")
            generate_config(services)

            if restart_haproxy():
                current_services = services
            else:
                print("failed to restart haproxy!")

        time.sleep(POLL_TIMEOUT)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
