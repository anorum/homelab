# K3s Ansible Playbook

This Ansible playbook automates the installation of a K3s Kubernetes cluster on Raspberry Pi devices. It configures one master node and multiple worker nodes with the necessary settings for running K3s.

## Structure

```
ansible/
├── inventory/
│   └── hosts.yaml         # Inventory file defining master and worker nodes
├── playbook/
│   └── install-k3s.yaml   # Main playbook for K3s installation
└── roles/
    └── k3s/
        └── tasks/
            ├── all.yaml   # Common tasks for all nodes
            ├── master.yaml # Master node specific tasks
            └── workers.yaml # Worker nodes specific tasks
```

## Configuration

### Inventory Setup

Edit `inventory/hosts.yaml` to define your nodes:

```yaml
all:
  hosts:
    master:
      ansible_host: 192.168.1.100
      ansible_user: your_user
    worker1:
      ansible_host: 192.168.1.101
      ansible_user: your_user
    worker2:
      ansible_host: 192.168.1.102
      ansible_user: your_user
  
  children:
    workers:
      hosts:
        worker1:
        worker2:
```

## Features

- Configures cgroup settings for K3s
- Installs K3s on the master node with Traefik and ServiceLB disabled
- Retrieves the K3s token from the master
- Joins worker nodes to the cluster automatically

## Usage

1. Ensure SSH access is configured for all nodes
2. Update the inventory file with your node details
3. Ensure all Raspberry Pi nodes are running Raspberry Pi OS (formerly Raspbian)
4. Run the playbook:

```bash
cd ansible
ansible-playbook -i inventory/hosts.yaml playbook/install-k3s.yaml
```

## Verification

After installation, SSH into the master node and run:

```bash
kubectl get nodes
```

This should show all nodes in the cluster as Ready.

## Notes

- The playbook disables Traefik and ServiceLB by default as these are typically replaced with other solutions
- Make sure all nodes have Python installed as it's required by Ansible
- Ensure sudo privileges are available for the ansible_user on all nodes
- The playbook modifies /boot/firmware/cmdline.txt to enable required cgroup settings
- A reboot of all nodes is recommended after the first run of the playbook to ensure cgroup settings are applied

## Requirements

### Node Configuration
- Raspberry Pi OS (formerly Raspbian)
- Python installed for Ansible
- SSH access configured
- Sudo privileges for the ansible_user
- Internet connectivity for downloading K3s

### Hardware Requirements
- Raspberry Pi 3 or newer recommended
- At least 2GB RAM recommended
- At least 8GB SD card space
