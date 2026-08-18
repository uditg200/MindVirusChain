#!/bin/bash

iptables -I DOCKER-USER -s 172.17.0.0/16 -d 169.254.169.254 -j DROP
iptables -I DOCKER-USER -s 172.17.0.0/16 -d 172.17.0.1 -j DROP
iptables -I DOCKER-USER -s 172.17.0.0/16 -d 10.0.0.0/8 -j DROP
iptables -I DOCKER-USER -s 172.17.0.0/16 -d 192.168.0.0/16 -j DROP

echo "Rules applied. Current DOCKER-USER chain:"
iptables -L DOCKER-USER -n
