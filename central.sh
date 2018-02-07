#!/bin/sh

IP=192.168.122.214
CENTRAL=127.0.0.1
ID=f26-central
VM_IP="192.168.0.1/24"

SWITCH_NAME=sw0
CENTRAL_IFACE=sw0-p0
HV0_IFACE=sw0-p1
CENTRAL_MAC="02:ac:10:ff:00:01"
HV0_MAC="02:ac:10:ff:00:11"

VMNAME=f26-central
NMNAME=f26-central

# OVN configuration
ip netns del $NMNAME
ovs-vsctl destroy open_vswitch .
systemctl restart openvswitch.service
systemctl restart ovn-northd
systemctl restart ovn-controller

sudo ovn-nbctl ls-del $SWITCH_NAME
ovn-nbctl ls-add $SWITCH_NAME
ovn-nbctl lsp-add $SWITCH_NAME $CENTRAL_IFACE
ovn-nbctl lsp-set-addresses $CENTRAL_IFACE $CENTRAL_MAC
ovn-nbctl lsp-set-port-security $CENTRAL_IFACE $CENTRAL_MAC
ovn-nbctl lsp-add $SWITCH_NAME $HV0_IFACE
ovn-nbctl lsp-set-addresses $HV0_IFACE $HV0_MAC
ovn-nbctl lsp-set-port-security $HV0_IFACE $HV0_MAC

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
ip -n $NMNAME link set $VMNAME address $CENTRAL_MAC
ip -n $NMNAME addr add $VM_IP dev $VMNAME
ip -n $NMNAME link set $VMNAME up
ovs-vsctl set Interface $VMNAME external_ids:iface-id=$CENTRAL_IFACE
