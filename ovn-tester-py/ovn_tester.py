#!/usr/bin/env python

import os
import sys
import ovn_utils
import netaddr
import time
import yaml
import ovn_workload

n_sandboxes = 4
n_lports = 4
sandboxes = [] # ovn sanbox list
farm_list = []
log = False

controller = {
}
fake_multinode_args = {
    "node_net": "192.16.0.0",
    "node_net_len": "16",
    "node_ip": "192.16.0.1",
    "ovn_cluster_db": True,
    "central_ip": "192.16.0.1-192.16.0.2-192.16.0.3",
    "sb_proto": "ssl",
    "max_timeout_s": 10,
    "cluster_cmd_path": "/root/ovn-heater/runtime/ovn-fake-multinode"
}
lnetwork_create_args = {
    "start_ext_cidr": "3.0.0.0/16",
    "gw_router_per_network": True,
    "start_gw_cidr": "2.0.0.0/16",
    "start_ext_cidr": "3.0.0.0/16",
    "cluster_cidr": "16.0.0.0/4"
}
lswitch_create_args = {
    "start_cidr" : "16.0.0.0/16",
    "nlswitch": n_sandboxes,
}
lport_bind_args = {
    "internal" : True,
    "wait_up": True,
    "wait_sync" : "ping",
}
lport_create_args = {
    "network_policy_size": 2,
    "name_space_size": 2,
    "create_acls": True
}
nbctld_config = {
    "daemon": True,
}

def usage(name):
    print("""
{} PHYSICAL_DEPLOYMENT CLUSTERED_DB
where PHYSICAL_DEPLOYMENT is the YAML file defining the deployment.
""".format(name), file=sys.stderr)

def read_physical_deployment(deployment):
    with open(deployment, 'r') as yaml_file:
        config = yaml.safe_load(yaml_file)

        for worker in config['worker-nodes']:
            farm_list.append(worker)

        central_config = config['central-node']
        controller['ip'] = central_config['name']
        controller['user'] = central_config.get('user', 'root')
        controller['password'] = central_config.get('password', '')
        controller['name'] = central_config.get('prefix', 'ovn-central')

def create_sandbox(sandbox_create_args = {}, iteration = 0):
    amount = sandbox_create_args.get("amount", 1)

    bcidr = sandbox_create_args.get("cidr", "1.0.0.0/8")
    base_cidr = netaddr.IPNetwork(bcidr)
    cidr = "{}/{}".format(str(base_cidr.ip + iteration * amount + 1),
                          base_cidr.prefixlen)
    start_cidr = netaddr.IPNetwork(cidr)
    sandbox_cidr = netaddr.IPNetwork(start_cidr)
    if not sandbox_cidr.ip + amount in sandbox_cidr:
        message = _("Network %s's size is not big enough for %d sandboxes.")
        raise exceptions.InvalidConfigException(
                message  % (start_cidr, amount))

    for i in range(amount):
        sandbox = {
                "farm": farm_list[ (i + iteration) % len(farm_list) ],
                "name" : "ovn-scale-%s" % iteration
        }
        sandboxes.append(sandbox)

def run_test():
    # create sandox list
    for i in range(n_sandboxes):
        create_sandbox(iteration = i)

    print("***** creating following sanboxes *****")
    print(yaml.dump(sandboxes))

    # start ovn-northd on ovn central
    ovn = ovn_workload.OvnWorkload(controller, sandboxes,
            fake_multinode_args.get("ovn_cluster_db", False),
            log = log)
    ovn.add_central(fake_multinode_args, nbctld_config = nbctld_config)

    # creat swith-per-node topology
    for i in range(n_sandboxes):
        ovn.add_chassis_node(fake_multinode_args, iteration = i)
        if lnetwork_create_args.get('gw_router_per_network', False):
            ovn.add_chassis_node_localnet(fake_multinode_args, iteration = i)
            ovn.add_chassis_external_host(lnetwork_create_args, iteration = i)

    for i in range(n_sandboxes):
        ovn.connect_chassis_node(fake_multinode_args, iteration = i)
        ovn.wait_chassis_node(fake_multinode_args, iteration = i)

    # create ovn topology
    ovn.create_routed_network(lswitch_create_args = lswitch_create_args,
                              lnetwork_create_args = lnetwork_create_args,
                              lport_bind_args = lport_bind_args)
    # create ovn logical ports
    for i in range(n_lports):
        ovn.create_routed_lport(lport_create_args = lport_create_args,
                                lport_bind_args = lport_bind_args,
                                iteration = i)

if __name__ == '__main__':
    if len(sys.argv) != 2:
        usage(sys.argv[0])
        sys.exit(1)

    # parse configuration
    read_physical_deployment(sys.argv[1])
    # execute the test
    sys.exit(run_test())
