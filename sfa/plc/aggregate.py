#!/usr/bin/python
from sfa.util.xrn import *
from sfa.util.plxrn import *
from sfa.rspecs.sfa_rspec import SfaRSpec
from sfa.rspecs.pg_rspec  import PGRSpec
from sfa.rspecs.rspec_version import RSpecVersion

class Aggregate:

    api = None
    sites = {}
    nodes = {}
    interfaces = {}
    links = {}
    node_tags = {}
    prepared=False

    def __init__(self, api):
        self.api = api

    def prepare_sites(self, force=False):
        if not self.sites or force:  
            for site in self.api.plshell.GetSites(self.api.plauth):
                self.sites[site['site_id']] = site
    
    def prepare_nodes(self, force=False):
        if not self.nodes or force:
            for node in self.api.plshell.GetNodes(self.api.plauth):
                self.nodes[node['node_id']] = node

    def prepare_interfaces(self, force=False):
        if not self.interfaces or force:
            for interface in self.api.plshell.GetInterfaces(self.api.plauth):
                self.interfaces[interface['interface_id']] = interface

    def prepare_links(self, force=False):
        if not self.links or force:
            pass

    def prepare_node_tags(self, force=False):
        if not self.node_tags or force:
            for node_tag in self.api.plshell.GetNodeTags(self.api.plauth):
                self.node_tags[node_tag['node_tag_id']] = node_tag

    def prepare(self, force=False):
        if not self.prepared or force:
            self.prepare_sites(force)
            self.prepare_nodes(force)
            self.prepare_interfaces(force)
            self.prepare_links(force)
            self.prepare_node_tags(force)
            # add site/interface info to nodes
            for node_id in self.nodes:
                node = self.nodes[node_id]
                site = self.sites[node['site_id']]
                interfaces = [self.interfaces[interface_id] for interface_id in node['interface_ids']]
                tags = [self.node_tags[tag_id] for tag_id in node['node_tag_ids']]
                node['network'] = self.api.hrn
                node['network_urn'] = hrn_to_urn(self.api.hrn, 'authority+sa')
                node['urn'] = hostname_to_urn(self.api.hrn, site['login_base'], node['hostname'])
                node['site_urn'] = hrn_to_urn(PlXrn.site_hrn(self.api.hrn, site['login_base']), 'authority') 
                node['site'] = site
                node['interfaces'] = interfaces
                node['tags'] = tags

        self.prepared = True  

    def get_rspec(self, slice_xrn=None, version = None, type=None):
        self.prepare()
        rspec = None
        rspec_version = RSpecVersion(version)
        if rspec_version['type'].lower() == 'protogeni':
            rspec = PGRSpec(type=type)
        elif rspec_version['type'].lower() == 'sfa':
            rspec = SfaRSpec()
        else:
            rspec = SfaRSpec()

        rspec.add_nodes(self.nodes.values())
        rspec.add_interfaces(self.interfaces.values()) 
        rspec.add_links(self.links.values())

        if slice_xrn:
            # get slice details
            slice_hrn, _ = urn_to_hrn(slice_xrn)
            slice_name = hrn_to_pl_slicename(slice_hrn)
            slices = self.api.plshell.GetSlices(self.api.plauth, slice_name)
            if slices:
                slice = slices[0]
                slivers = []
                tags = self.api.plshell.GetSliceTags(self.api.plauth, slice['slice_tag_ids'])
                for node_id in slice['node_ids']:
                    sliver = {}
                    sliver['hostname'] = self.nodes[node_id]['hostname']
                    sliver['tags'] = []
                    slivers.append(sliver)
                    for tag in tags:
                        # if tag isn't bound to a node then it applies to all slivers
                        if not tag['node_id']:
                            sliver['tags'].append(tag)
                        else:
                            tag_host = self.nodes[tag['node_id']]['hostname']
                            if tag_host == sliver['hostname']:
                                sliver.tags.append(tag)
                rspec.add_slivers(slivers)

        return rspec.toxml()          
