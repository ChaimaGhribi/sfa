
import os
import socket
import base64
import string
import random    
from collections import defaultdict
from nova.exception import ImageNotFound
from nova.api.ec2.cloud import CloudController
from sfa.util.faults import SfaAPIError
from sfa.rspecs.rspec import RSpec
from sfa.rspecs.elements.hardware_type import HardwareType
from sfa.rspecs.elements.node import Node
from sfa.rspecs.elements.sliver import Sliver
from sfa.rspecs.elements.login import Login
from sfa.rspecs.elements.disk_image import DiskImage
from sfa.rspecs.elements.services import Services
from sfa.rspecs.elements.interface import Interface
from sfa.util.xrn import Xrn
from sfa.planetlab.plxrn import PlXrn 
from sfa.openstack.osxrn import OSXrn, hrn_to_os_slicename
from sfa.rspecs.version_manager import VersionManager
from sfa.openstack.security_group import SecurityGroup
from sfa.util.sfalogging import logger

def pubkeys_to_user_data(pubkeys):
    user_data = "#!/bin/bash\n\n"
    for pubkey in pubkeys:
        pubkey = pubkey.replace('\n', '')
        user_data += "echo %s >> /root/.ssh/authorized_keys" % pubkey
        user_data += "\n"
        user_data += "echo >> /root/.ssh/authorized_keys"
        user_data += "\n"
    return user_data

def instance_to_sliver(instance, slice_xrn=None):
    sliver_id = None
    if slice_xrn:
        xrn = Xrn(slice_xrn, 'slice')
        sliver_id = xrn.get_sliver_id(instance.project_id, instance.hostname, instance.id)

    sliver = Sliver({'slice_id': sliver_id,
                     'name': instance.name,
                     'type': instance.name,
                     'cpus': str(instance.vcpus),
                     'memory': str(instance.ram),
                     'storage':  str(instance.disk)})
    return sliver

def image_to_rspec_disk_image(image):
    img = DiskImage()
    img['name'] = image['name']
    img['description'] = image['name']
    img['os'] = image['name']
    img['version'] = image['name']    
    return img
    
class OSAggregate:

    def __init__(self, driver):
        self.driver = driver

    def get_rspec(self, slice_xrn=None, version=None, options={}):
        version_manager = VersionManager()
        version = version_manager.get_version(version)
        if not slice_xrn:
            rspec_version = version_manager._get_version(version.type, version.version, 'ad')
            nodes = self.get_aggregate_nodes()
        else:
            rspec_version = version_manager._get_version(version.type, version.version, 'manifest')
            nodes = self.get_slice_nodes(slice_xrn)
        rspec = RSpec(version=rspec_version, user_options=options)
        rspec.version.add_nodes(nodes)
        return rspec.toxml()

    def get_availability_zones(self):
        # essex release
        zones = self.driver.shell.nova_manager.dns_domains.domains()

        if not zones:
            zones = ['cloud']
        else:
            zones = [zone.name for zone in zones]
        return zones

    def get_slice_nodes(self, slice_xrn):
        zones = self.get_availability_zones()
        name = hrn_to_os_slicename(slice_xrn)
        instances = self.driver.shell.nova_manager.servers.findall(name=name)
        rspec_nodes = []
        for instance in instances:
            rspec_node = Node()
            
            #TODO: find a way to look up an instances availability zone in essex
            #if instance.availability_zone:
            #    node_xrn = OSXrn(instance.availability_zone, 'node')
            #else:
            #    node_xrn = OSXrn('cloud', 'node')
            node_xrn = instance.metatata.get('component_id')
            if not node_xrn:
                node_xrn = OSXrn('cloud', 'node') 

            rspec_node['component_id'] = node_xrn.urn
            rspec_node['component_name'] = node_xrn.name
            rspec_node['component_manager_id'] = Xrn(self.driver.hrn, 'authority+cm').get_urn()
            flavor = self.driver.shell.nova_manager.flavors.find(id=instance.flavor['id'])
            sliver = instance_to_sliver(flavor)
            rspec_node['slivers'] = [sliver]
            image = self.driver.shell.image_manager.get_images(id=instance.image['id'])
            if isinstance(image, list) and len(image) > 0:
                image = image[0]
            disk_image = image_to_rspec_disk_image(image)
            sliver['disk_image'] = [disk_image]

            # build interfaces            
            interfaces = []
            addresses = instance.addresses
            for private_ip in addresses.get('private', []):
                if_xrn = PlXrn(auth=self.driver.hrn, 
                               interface='node%s:eth0' % (instance.hostId)) 
                interface = Interface({'component_id': if_xrn.urn})
                interface['ips'] =  [{'address': private_ip['addr'],
                                     #'netmask': private_ip['network'],
                                     'type': private_ip['version']}]
                interfaces.append(interface)
            rspec_node['interfaces'] = interfaces 
            
            # slivers always provide the ssh service
            rspec_node['services'] = []
            for public_ip in addresses.get('public', []):
                login = Login({'authentication': 'ssh-keys', 
                               'hostname': public_ip['addr'], 
                               'port':'22', 'username': 'root'})
                service = Services({'login': login})
                rspec_node['services'].append(service)
            rspec_nodes.append(rspec_node)
        return rspec_nodes

    def get_aggregate_nodes(self):
        zones = self.get_availability_zones()
        # available sliver/instance/vm types
        instances = self.driver.shell.nova_manager.flavors.list()
        if isinstance(instances, dict):
            instances = instances.values()
        # available images
        images = self.driver.shell.image_manager.get_images_detailed()
        disk_images  = [image_to_rspec_disk_image(img) for img in images if img['container_format'] in ['ami', 'ovf']]
        rspec_nodes = []
        for zone in zones:
            rspec_node = Node()
            xrn = OSXrn(zone, type='node')
            rspec_node['component_id'] = xrn.urn
            rspec_node['component_name'] = xrn.name
            rspec_node['component_manager_id'] = Xrn(self.driver.hrn, 'authority+cm').get_urn()
            rspec_node['exclusive'] = 'false'
            rspec_node['hardware_types'] = [HardwareType({'name': 'plos-pc'}),
                                                HardwareType({'name': 'pc'})]
            slivers = []
            for instance in instances:
                sliver = instance_to_sliver(instance)
                sliver['disk_image'] = disk_images
                slivers.append(sliver)
        
            rspec_node['slivers'] = slivers
            rspec_nodes.append(rspec_node) 

        return rspec_nodes 


    def create_instance_key(self, slice_hrn, user):
        key_name = "%s:%s" (slice_name, Xrn(user['urn']).get_hrn())
        pubkey = user['keys'][0]
        key_found = False
        existing_keys = self.driver.shell.nova_manager.keypairs.findall(name=key_name)
        for existing_key in existing_keys:
            if existing_key.public_key != pubkey:
                self.driver.shell.nova_manager.keypairs.delete(existing_key)
            elif existing_key.public_key == pubkey:
                key_found = True

        if not key_found:
            self.driver.shll.nova_manager.keypairs.create(key_name, pubkey)
        return key_name       
        

    def create_security_group(self, slicename, fw_rules=[]):
        # use default group by default
        group_name = 'default' 
        if isinstance(fw_rules, list) and fw_rules:
            # Each sliver get's its own security group.
            # Keep security group names unique by appending some random
            # characters on end.
            random_name = "".join([random.choice(string.letters+string.digits)
                                           for i in xrange(6)])
            group_name = slicename + random_name 
            security_group = SecurityGroup(self.driver)
            security_group.create_security_group(group_name)
            for rule in fw_rules:
                security_group.add_rule_to_group(group_name, 
                                             protocol = rule.get('protocol'), 
                                             cidr_ip = rule.get('cidr_ip'), 
                                             port_range = rule.get('port_range'), 
                                             icmp_type_code = rule.get('icmp_type_code'))
        return group_name

    def add_rule_to_security_group(self, group_name, **kwds):
        security_group = SecurityGroup(self.driver)
        security_group.add_rule_to_group(group_name=group_name, 
                                         protocol=kwds.get('protocol'), 
                                         cidr_ip =kwds.get('cidr_ip'), 
                                         icmp_type_code = kwds.get('icmp_type_code'))

 

    def run_instances(self, slicename, rspec, key_name, pubkeys):
        #logger.debug('Reserving an instance: image: %s, flavor: ' \
        #            '%s, key: %s, name: %s' % \
        #            (image_id, flavor_id, key_name, slicename))

        authorized_keys = "\n".join(pubkeys)
        files = {'/root/.ssh/authorized_keys': authorized_keys}
        rspec = RSpec(rspec)
        requested_instances = defaultdict(list)
        # iterate over clouds/zones/nodes
        for node in rspec.version.get_nodes_with_slivers():
            instances = node.get('slivers', [])
            if not instances:
                continue
            for instance in instances:
                metadata = {}
                flavor_id = self.driver.shell.nova_manager.flavors.find(name=instance['name'])
                image = instance.get('disk_image')
                if image and isinstance(image, list):
                    image = image[0]
                image_id = self.driver.shell.nova_manager.images.find(name=image['name'])
                fw_rules = instance.get('fw_rules', [])
                group_name = self.create_security_group(slicename, fw_rules)
                metadata['security_groups'] = group_name
                metadata['component_id'] = node['component_id']
                try: 
                    self.driver.shell.nova_manager.servers.create(flavor=flavor_id,
                                                            image=image_id,
                                                            key_name = key_name,
                                                            security_group = group_name,
                                                            files=files,
                                                            meta=metadata, 
                                                            name=slicename)
                except Exception, err:    
                    logger.log_exc(err)                                
                           


    def delete_instances(self, instance_name):
        instances = self.driver.shell.nova_manager.servers.findall(name=instance_name)
        security_group_manager = SecurityGroup(self.driver)
        for instance in instances:
            # deleate this instance's security groups
            for security_group in instance.metadata.get('security_groups', []):
                # dont delete the default security group
                if security_group != 'default': 
                    security_group_manager.delete_security_group(security_group)
            # destroy instance
            self.driver.shell.nova_manager.servers.delete(instance)
        return 1

    def stop_instances(self, instance_name):
        instances = self.driver.shell.nova_manager.servers.findall(name=instance_name)
        for instance in instances:
            self.driver.shell.nova_manager.servers.pause(instance)
        return 1

    def update_instances(self, project_name):
        pass
