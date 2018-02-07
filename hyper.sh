#!/bin/sh -x

IP=192.168.122.177
CENTRAL=192.168.122.214
ID=f26-cnt0
VM_IP="192.168.0.2/24"

HV0_IFACE=sw0-p1
HV0_MAC="02:ac:10:ff:00:11"

VMNAME=f26-cnt0
NMNAME=f26-cnt0

# OVN configuration
ip netns del $NMNAME
ovs-vsctl destroy open_vswitch .
systemctl restart openvswitch.service
systemctl restart ovn-controller

sudo ovs-vsctl set open_vswitch . system-type=$ID
sudo ovs-vsctl set open_vswitch . external-ids:system-id=$ID
sudo ovs-vsctl set open_vswitch . external-ids:hostname=$ID
sudo ovs-vsctl set open_vswitch . external-ids:ovn-bridge="br-int"
sudo ovs-vsctl set open_vswitch . external-ids:ovn-encap-ip=$IP
sudo ovs-vsctl set open_vswitch . external-ids:ovn-encap-type="geneve"
sudo ovs-vsctl set open . external-ids:ovn-remote=tcp:$CENTRAL:6642

# create virtual interface
ip netns add $NMNAME
ovs-vsctl add-port br-int $NMNAME -- set interface $NMNAME type=internal
ip link set $VMNAME netns $NMNAME
ip -n $NMNAME link set $VMNAME address $HV0_MAC
ip -n $NMNAME addr add $VM_IP dev $VMNAME
ip -n $NMNAME link set $VMNAME up
ovs-vsctl set Interface $VMNAME external_ids:iface-id=$HV0_IFACE
