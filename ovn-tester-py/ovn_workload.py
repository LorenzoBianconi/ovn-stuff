import ovn_utils
import time
import netaddr
import random
import string
from randmac import RandMac

class OvnWorkload:
    def __init__(self, controller = None, sandboxes = None):
        self.controller = controller
        self.sandboxes = sandboxes
        self.nbctl = ovn_utils.OvnNbctl(controller, container = controller["name"])
        self.lswitches = []
        self.lports = []

    def add_central(self, fake_multinode_args = {}):
        print("***** creating central node *****")
    
        node_net = fake_multinode_args.get("node_net")
        node_net_len = fake_multinode_args.get("node_net_len")
        node_ip = fake_multinode_args.get("node_ip")
        ovn_fake_path = fake_multinode_args.get("cluster_cmd_path")
        
        if fake_multinode_args.get("ovn_monitor_all"):
            monitor_cmd = "OVN_MONITOR_ALL=yes"
        else:
            monitor_cmd = "OVN_MONITOR_ALL=no"
    
        if fake_multinode_args.get("ovn_cluster_db"):
            cluster_db_cmd = "OVN_DB_CLUSTER=yes"
        else:
            cluster_db_cmd = "OVN_DB_CLUSTER=no"
    
        cmd = "cd {} && CHASSIS_COUNT=0 GW_COUNT=0 IP_HOST={} IP_CIDR={} IP_START={} {} {} CREATE_FAKE_VMS=no ./ovn_cluster.sh start".format(
                ovn_fake_path, node_net, node_net_len, node_ip, monitor_cmd, cluster_db_cmd
            )
        client = ovn_utils.SSH(self.controller)
        client.run(cmd = cmd)
    
        time.sleep(5)

    def add_chassis_node_localnet(self, fake_multinode_args = {}, iteration = 0):
        sandbox = self.sandboxes[iteration % len(self.sandboxes)]
    
        print("***** creating localnet on %s controller *****" % sandbox["name"])
    
        cmd = "ovs-vsctl -- set open_vswitch . external-ids:ovn-bridge-mappings={}:br-ex".format(
            fake_multinode_args.get("physnet", "providernet")
        )
        node = {
            "ip": sandbox["farm"],
        }
        client = ovn_utils.SSH(node, container = sandbox["name"])
        client.run(cmd = cmd)
    
    def add_chassis_external_host(self, lnetwork_create_args = {}, iteration = 0):
        sandbox = self.sandboxes[iteration % len(self.sandboxes)]
        cidr = netaddr.IPNetwork(lnetwork_create_args.get('start_ext_cidr'))
        ext_cidr = cidr.next(iteration)
    
        gw_ip = netaddr.IPAddress(ext_cidr.last - 1)
        host_ip = netaddr.IPAddress(ext_cidr.last - 2)
    
        node = {
            "ip": sandbox["farm"],
        }
        client = ovn_utils.SSH(node, container = sandbox["name"])
        client.run(cmd = "ip link add veth0 type veth peer name veth1")
        client.run(cmd = "ip link add veth0 type veth peer name veth1")
        client.run(cmd = "ip netns add ext-ns")
        client.run(cmd = "ip link set netns ext-ns dev veth0")
        client.run(cmd = "ip netns exec ext-ns ip link set dev veth0 up")
        client.run(cmd = "ip netns exec ext-ns ip addr add {}/{} dev veth0".format(
                   host_ip, ext_cidr.prefixlen))
        client.run(cmd = "ip netns exec ext-ns ip route add default via {}".format(
                   gw_ip))
        client.run(cmd = "ip link set dev veth1 up")
        client.run(cmd = "ovs-vsctl add-port br-ex veth1")
    
    def add_chassis_node(self, fake_multinode_args = {}, iteration = 0):
        node_net = fake_multinode_args.get("node_net")
        node_net_len = fake_multinode_args.get("node_net_len")
        node_cidr = netaddr.IPNetwork("{}/{}".format(node_net, node_net_len))
        node_ip = str(node_cidr.ip + iteration + 1)
    
        ovn_fake_path = fake_multinode_args.get("cluster_cmd_path")
    
        sandbox = self.sandboxes[iteration % len(self.sandboxes)]
    
        print("***** adding %s controller *****" % sandbox["name"])
    
        if fake_multinode_args.get("ovn_monitor_all"):
            monitor_cmd = "OVN_MONITOR_ALL=yes"
        else:
            monitor_cmd = "OVN_MONITOR_ALL=no"
    
        if fake_multinode_args.get("ovn_cluster_db"):
            cluster_db_cmd = "OVN_DB_CLUSTER=yes"
        else:
            cluster_db_cmd = "OVN_DB_CLUSTER=no"
    
        cmd = "cd {} && IP_HOST={} IP_CIDR={} IP_START={} {} {} ./ovn_cluster.sh add-chassis {} {}".format(
            ovn_fake_path, node_net, node_net_len, node_ip, monitor_cmd, cluster_db_cmd,
            sandbox["name"], "tcp:0.0.0.1:6642"
        )
        node = {
            "ip": sandbox["farm"],
        }
        client = ovn_utils.SSH(node)
        client.run(cmd)

    def connect_chassis_node(self, fake_multinode_args = {}, iteration = 0):
        sandbox = self.sandboxes[iteration % len(self.sandboxes)]
        node_prefix = fake_multinode_args.get("node_prefix", "")
    
        print("***** connecting %s controller *****" % sandbox["name"])
    
        central_ip = fake_multinode_args.get("central_ip")
        sb_proto = fake_multinode_args.get("sb_proto", "ssl")
        ovn_fake_path = fake_multinode_args.get("cluster_cmd_path")
    
        central_ips = [ip.strip() for ip in central_ip.split('-')]
        remote = ",".join(["{}:{}:6642".format(sb_proto, r) for r in central_ips])
    
        cmd = "cd {} && ./ovn_cluster.sh set-chassis-ovn-remote {} {}".format(
            ovn_fake_path, sandbox["name"], remote
        )
        node = {
            "ip": sandbox["farm"],
        }
        client = ovn_utils.SSH(node)
        client.run(cmd = cmd)

    def wait_chassis_node(self, fake_multinode_args = {}, iteration = 0,
                          controller = {}):
        sandbox = self.sandboxes[iteration % len(self.sandboxes)]
        max_timeout_s = fake_multinode_args.get("max_timeout_s")
        for i in range(0, max_timeout_s * 10):
            sbctl = ovn_utils.OvnSbctl(self.controller,
                                       container = self.controller["name"])
            if sbctl.chassis_bound(chassis = sandbox["name"]):
                break
            time.sleep(0.1)

    def bind_and_wait_port(self, lport = None, lport_bind_args = {},
                           sandbox = None):
        node = {
            "ip": sandbox["farm"],
        }
        internal = lport_bind_args.get("internal", False)
        internal_vm = lport_bind_args.get("internal_vm", True)
        vsctl = ovn_utils.OvsVsctl(node = node, container = sandbox["name"])
        # add ovs port
        vsctl.add_port(lport["name"], "br-int", internal = internal,
                       ifaceid = lport["name"])
        if internal and internal_vm:
            vsctl.bind_vm_port(lport)


    def create_lswitch_port(self, lswitch = None, lport_create_args = {},
                            iteration = 0):
        cidr = lswitch.get("cidr", None)
        if cidr:
            ip = str(next(netaddr.iter_iprange(cidr.ip + iteration + 1,
                                               cidr.last)))
            ip_mask = '{}/{}'.format(ip, cidr.prefixlen)
            gw = str(netaddr.IPAddress(cidr.last - 1))
            name = "lp_{}".format(ip)
        else:
            name = "lp_".join(random.choice(string.ascii_letters) for i in range(10))
            ip_mask = ""
            ip = ""
            gw = ""

        print("***** creating lport {} *****".format(name))
        lswitch_port = self.nbctl.ls_port_add(lswitch["name"], name,
                                              mac = str(RandMac()),
                                              ip = ip_mask, gw = gw)
        return lswitch_port

    def create_lswitch(self, lswitch_create_args = {}, iteration = 0):
        start_cidr = lswitch_create_args.get("start_cidr", "")
        if start_cidr:
            start_cidr = netaddr.IPNetwork(start_cidr)
            cidr = start_cidr.next(iteration)
            name = "lswitch_%s" % cidr
        else:
            name = 'lswitch_'.join(random.choice(string.ascii_letters) for i in range(10))

        print("***** creating lswitch {} *****".format(name))
        lswitch = self.nbctl.ls_add(name)
        if start_cidr:
            lswitch["cidr"] = cidr

        return lswitch

    def connect_lswitch_to_router(self, lrouter = None, lswitch = None):
        gw = netaddr.IPAddress(lswitch["cidr"].last - 1)
        lrouter_port_ip = '{}/{}'.format(gw, lswitch["cidr"].prefixlen)
        mac = RandMac()
        lrouter_port = self.nbctl.lr_port_add(lrouter["name"], lswitch["name"],
                                              mac, lrouter_port_ip)
        lswitch_port = self.nbctl.ls_port_add(lswitch["name"],
                                              "rp-" + lswitch["name"],
                                              lswitch["name"])

    def create_routed_network(self, lswitch_create_args = {},
                              lport_bind_args = {}):
        # create logical router
        name = ''.join(random.choice(string.ascii_letters) for i in range(10))
        router = self.nbctl.lr_add("lrouter_" + name)

        # create logical switches
        for i in range(lswitch_create_args.get("nlswitch", 10)):
            lswitch = self.create_lswitch(lswitch_create_args, i)
            self.lswitches.append(lswitch)
            self.connect_lswitch_to_router(router, lswitch)
            lport = self.create_lswitch_port(lswitch, iteration = 0)
            self.lports.append(lport)
            sandbox = self.sandboxes[i % len(self.sandboxes)]
            self.bind_and_wait_port(lport, lport_bind_args = lport_bind_args,
                                    sandbox = sandbox)

    def create_acl(self, lswitch = None, lport = None, acl_create_args = {}):
        print("***** creating acl on {} *****".format(lport["name"]))

        direction = acl_create_args.get("direction", "to-lport")
        priority = acl_create_args.get("priority", 1000)
        verdict = acl_create_args.get("action", "allow")
        address_set = acl_create_args.get("address_set", "")
        acl_type = acl_create_args.get("type", "switch")

        '''
        match template: {
            "direction" : "<inport/outport>",
            "lport" : "<switch port or port-group>",
            "address_set" : "<address_set id>"
            "l4_port" : "<l4 port number>",
        }
        '''
        match_template = acl_create_args.get("match",
                                             "%(direction)s == %(lport)s && \
                                             ip4 && udp && udp.src == %(l4_port)s")
        p = "inport" if direction == "from-lport" else "outport"
        match = match_template % {
            "direction" : p,
            "lport" : lport["name"],
            "address_set" : address_set,
            "l4_port" : 100
        }
        self.nbctl.acl_add(lswitch["name"], direction, priority, acl_type,
                           match, verdict)

    def create_port_group_acls(self, name):
        port_group_acl = { "name" : "@%s" % name }
        port_group = { "name" : name }
        """
        create two acl for each ingress/egress of the Network Policy (NP)
        to allow ingress and egress traffic selected by the NP
        """
        # ingress
        match = "%(direction)s == %(lport)s && ip4.src == $%(address_set)s"
        acl_create_args = {
            "match" : match,
            "address_set" : "%s_ingress_as" % name,
            "priority": 1010, "direction": "from-lport",
            "type": "port-group"
        }
        self.create_acl(port_group, port_group_acl, acl_create_args)
        acl_create_args = {
            "priority" : 1009,
            "match" : "%(direction)s == %(lport)s && ip4",
            "type": "port-group", "direction":"from-lport",
            "action": "allow-related"
        }
        self.create_acl(port_group, port_group_acl, acl_create_args)
        # egress
        match = "%(direction)s == %(lport)s && ip4.dst == $%(address_set)s"
        acl_create_args = {
            "match" : match,
            "address_set" : "%s_egress_as" % name,
            "priority": 1010, "type": "port-group"
        }
        self.create_acl(port_group, port_group_acl, acl_create_args)
        acl_create_args = {
            "priority" : 1009,
            "match" : "%(direction)s == %(lport)s && ip4",
            "type": "port-group"," action": "allow-related"
        }
        self.create_acl(port_group, port_group_acl, acl_create_args)

    def create_update_deny_port_group(self, lport = None, create = True):
        self.nbctl.port_group_add("portGroupDefDeny", lport, create)
        if create:
            # create defualt acl for ingress and egress traffic: only allow ARP traffic
            port_group_acl = {
                "name" : "@portGroupDefDeny"
            }
            port_group = {
                "name" : "portGroupDefDeny"
            }
            # ingress
            acl_create_args = {
                "match" : "%(direction)s == %(lport)s && arp",
                "priority": 1001, "direction": "from-lport",
                "type": "port-group"
            }
            self.create_acl(port_group, port_group_acl, acl_create_args)
            acl_create_args = {
                "match" : "%(direction)s == %(lport)s",
                "direction": "from-lport", "action": "drop",
                "type": "port-group"
            }
            self.create_acl(port_group, port_group_acl, acl_create_args)
            # egress
            acl_create_args = {
                "match" : "%(direction)s == %(lport)s && arp",
                "priority": 1001,
                "type": "port-group"
            }
            self.create_acl(port_group, port_group_acl, acl_create_args)
            acl_create_args = {
                "match" : "%(direction)s == %(lport)s",
                "action": "drop",
                "type": "port-group"
            }
            self.create_acl(port_group, port_group_acl, acl_create_args)

    def create_update_deny_multicast_port_group(self, lport = None,
                                                create = True):
        self.nbctl.port_group_add("portGroupMultiDefDeny", lport, create)
        if create:
            # create defualt acl for ingress and egress multicast traffic: drop all multicast
            port_group_acl = {
                "name" : "@portGroupMultiDefDeny"
            }
            port_group = {
                "name" : "portGroupMultiDefDeny"
            }
            # ingress
            acl_create_args = {
                "match" : "%(direction)s == %(lport)s && ip4.mcast",
                "priority": 1011, "direction": "from-lport",
                "type": "port-group", "action": "drop"
            }
            self.create_acl(port_group, port_group_acl, acl_create_args)
            # egress
            acl_create_args = {
                "match" : "%(direction)s == %(lport)s && ip4.mcast",
                "priority": 1011, "type": "port-group",
                "action": "drop"
            }
            self.create_acl(port_group, port_group_acl, acl_create_args)

    def create_update_network_policy(self, lport = None, ip = "",
                                     lport_create_args = {},
                                     iteration = 0):

        network_policy_size = lport_create_args.get("network_policy_size", 1)
        network_policy_index = iteration / network_policy_size
        create = (iteration % network_policy_size) == 0
        name = "networkPolicy%d" % network_policy_index

        self.nbctl.port_group_add(name, lport, create)
        self.nbctl.address_set_add("%s_ingress_as" % name, ip, create)
        self.nbctl.address_set_add("%s_egress_as" % name, ip, create)
        if (create):
            self.create_port_group_acls(name)

        self.create_update_deny_port_group(lport, iteration == 0)
        self.create_update_deny_multicast_port_group(lport, iteration == 0)

    def create_update_name_space(self, lport = None, ip = "",
                                 lport_create_args = {},
                                 iteration = 0):
        name_space_size = lport_create_args.get("name_space_size", 1)
        name_space_index = iteration / name_space_size
        create = (iteration % name_space_size) == 0
        name = "nameSpace%d" % name_space_index
        port_group_name = "mcastPortGroup_%s" % name
        port_group_acl = {
            "name" : "@" + port_group_name
        }
        port_group = {
            "name" : port_group_name
        }

        self.nbctl.port_group_add(port_group_name, lport, create)
        self.nbctl.address_set_add(name, ip, create)

        if (create):
            # create multicast ACL
            match = "%(direction)s == %(lport)s && ip4.mcast"
            acl_create_args = {
                "match" : match, "priority": 1012,
                "direction": "from-lport",
                "type": "port-group"
            }
            self.create_acl(port_group, port_group_acl, acl_create_args)
            acl_create_args = {
                "match" : match, "priority": 1012,
                "type": "port-group"
            }
            self.create_acl(port_group, port_group_acl, acl_create_args)

    def configure_routed_lport(self, sandbox = None, lswitch = None,
                               lport_create_args = {}, lport_bind_args = {},
                               iteration = 0):
        lport = self.create_lswitch_port(lswitch, iteration = iteration + 2)
        self.bind_and_wait_port(lport, lport_bind_args = lport_bind_args,
                                sandbox = sandbox)
        if lport_create_args.get("create_acls", False):
            cidr = lswitch.get("cidr", None)
            if cidr:
                ip = str(next(netaddr.IPNetwork(cidr.ip + 2).iter_hosts()))
            else:
                ip = ""

            # create or update network policy
            self.create_update_network_policy(lport, ip,
                    lport_create_args = lport_create_args,
                    iteration = iteration)

            # create/update namespace
            self.create_update_name_space(lport, ip,
                    lport_create_args = lport_create_args,
                    iteration = iteration)

    def create_routed_lport(self, lport_create_args = {},
                            lport_bind_args = {}, iteration = 0):
        lswitch = self.lswitches[iteration % len(self.lswitches)]
        sandbox = self.sandboxes[iteration % len(self.sandboxes)]
        self.configure_routed_lport(sandbox, lswitch,
                                    lport_create_args = lport_create_args,
                                    lport_bind_args = lport_bind_args,
                                    iteration = iteration)
