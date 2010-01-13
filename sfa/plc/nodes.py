### $Id$
### $URL$

import os
import time
import datetime
import sys
import traceback

from sfa.util.namespace import *
from sfa.util.rspec import *
from sfa.util.specdict import * 
from sfa.util.faults import *
from sfa.util.storage import *
from sfa.util.debug import log
from sfa.util.rspec import *
from sfa.util.specdict import * 
from sfa.util.policy import Policy
from sfa.server.aggregate import Aggregates 

class Nodes(SimpleStorage):

    def __init__(self, api, ttl = 1, origin_hrn=None):
        self.api = api
        self.ttl = ttl
        self.threshold = None
        path = self.api.config.SFA_DATA_DIR
        filename = ".".join([self.api.interface, self.api.hrn, "nodes"])
        filepath = path + os.sep + filename
        self.nodes_file = filepath
        SimpleStorage.__init__(self, self.nodes_file)
        self.policy = Policy(api)
        self.load()
        self.origin_hrn = origin_hrn


    def refresh(self):
        """
        Update the cached list of nodes
        """

        # Reload components list
        now = datetime.datetime.now()
        if not self.has_key('threshold') or not self.has_key('timestamp') or \
           now > datetime.datetime.fromtimestamp(time.mktime(time.strptime(self['threshold'], self.api.time_format))): 
            if self.api.interface in ['aggregate']:
                self.refresh_nodes_aggregate()
            elif self.api.interface in ['slicemgr']:
                self.refresh_nodes_smgr()

    def refresh_nodes_aggregate(self):
        rspec = RSpec()
        rspec.parseString(self.get_rspec())
        
        # filter nodes according to policy
        blist = self.policy['node_blacklist']
        wlist = self.policy['node_whitelist']
        rspec.filter('NodeSpec', 'name', blacklist=blist, whitelist=wlist)

        # extract ifspecs from rspec to get ips'
        ips = []
        ifspecs = rspec.getDictsByTagName('IfSpec')
        for ifspec in ifspecs:
            if ifspec.has_key('addr') and ifspec['addr']:
                ips.append(ifspec['addr'])

        # extract nodespecs from rspec to get dns names
        hostnames = []
        nodespecs = rspec.getDictsByTagName('NodeSpec')
        for nodespec in nodespecs:
            if nodespec.has_key('name') and nodespec['name']:
                hostnames.append(nodespec['name'])

        # update timestamp and threshold
        timestamp = datetime.datetime.now()
        hr_timestamp = timestamp.strftime(self.api.time_format)
        delta = datetime.timedelta(hours=self.ttl)
        threshold = timestamp + delta
        hr_threshold = threshold.strftime(self.api.time_format)

        node_details = {}
        node_details['rspec'] = rspec.toxml()
        node_details['ip'] = ips
        node_details['dns'] = hostnames
        node_details['timestamp'] = hr_timestamp
        node_details['threshold'] = hr_threshold
        # save state 
        self.update(node_details)
        self.write()       
 
    def get_rspec_smgr(self, xrn = None):
        hrn, type = urn_to_hrn(xrn)
        # convert and threshold to ints
        if self.has_key('timestamp') and self['timestamp']:
            hr_timestamp = self['timestamp']
            timestamp = datetime.datetime.fromtimestamp(time.mktime(time.strptime(hr_timestamp, self.api.time_format)))
            hr_threshold = self['threshold']
            threshold = datetime.datetime.fromtimestamp(time.mktime(time.strptime(hr_threshold, self.api.time_format)))
        else:
            timestamp = datetime.datetime.now()
            hr_timestamp = timestamp.strftime(self.api.time_format)
            delta = datetime.timedelta(hours=self.ttl)
            threshold = timestamp + delta
            hr_threshold = threshold.strftime(self.api.time_format)

        start_time = int(timestamp.strftime("%s"))
        end_time = int(threshold.strftime("%s"))
        duration = end_time - start_time

        aggregates = Aggregates(self.api)
        rspecs = {}
        networks = []
        rspec = RSpec()
        credential = self.api.getCredential()
        origin_hrn = self.origin_hrn
        for aggregate in aggregates:
          if aggregate not in [self.api.auth.client_cred.get_gid_caller().get_hrn()]:
            try:
                # get the rspec from the aggregate
                agg_rspec = aggregates[aggregate].get_resources(credential, xrn, origin_hrn)
                # extract the netspec from each aggregates rspec
                rspec.parseString(agg_rspec)
                networks.extend([{'NetSpec': rspec.getDictsByTagName('NetSpec')}])
            except:
                # XX print out to some error log
                print >> log, "Error getting resources at aggregate %s" % aggregate
                traceback.print_exc(log)
                print >> log, "%s" % (traceback.format_exc())
        # create the rspec dict
        resources = {'networks': networks, 'start_time': start_time, 'duration': duration}
        resourceDict = {'RSpec': resources}
        # convert rspec dict to xml
        rspec.parseDict(resourceDict)
        return rspec.toxml()

    def refresh_nodes_smgr(self):

        rspec = RSpec(xml=self.get_rspec_smgr())        
        # filter according to policy
        blist = self.policy['node_blacklist']
        wlist = self.policy['node_whitelist']    
        rspec.filter('NodeSpec', 'name', blacklist=blist, whitelist=wlist)

        # update timestamp and threshold
        timestamp = datetime.datetime.now()
        hr_timestamp = timestamp.strftime(self.api.time_format)
        delta = datetime.timedelta(hours=self.ttl)
        threshold = timestamp + delta
        hr_threshold = threshold.strftime(self.api.time_format)

        nodedict = {'rspec': rspec.toxml(),
                    'timestamp': hr_timestamp,
                    'threshold':  hr_threshold}

        self.update(nodedict)
        self.write()

    def get_rspec(self, xrn = None):

        if self.api.interface in ['slicemgr']:
            return self.get_rspec_smgr(xrn)
        elif self.api.interface in ['aggregate']:
            return self.get_rspec_aggregate(xrn)     

    def get_rspec_aggregate(self, xrn = None):
        """
        Get resource information from PLC
        """
        hrn, type = urn_to_hrn(xrn)
        slicename = None
        # Get the required nodes
        if not hrn:
            nodes = self.api.plshell.GetNodes(self.api.plauth, {'peer_id': None})
            try:  linkspecs = self.api.plshell.GetLinkSpecs() # if call is supported
            except:  linkspecs = []
        else:
            slicename = hrn_to_pl_slicename(hrn)
            slices = self.api.plshell.GetSlices(self.api.plauth, [slicename])
            if not slices:
                nodes = []
            else:
                slice = slices[0]
                node_ids = slice['node_ids']
                nodes = self.api.plshell.GetNodes(self.api.plauth, {'peer_id': None, 'node_id': node_ids})

        # Filter out whitelisted nodes
        public_nodes = lambda n: n.has_key('slice_ids_whitelist') and not n['slice_ids_whitelist']
            
        # ...only if they are not already assigned to this slice.
        if (not slicename):        
            nodes = filter(public_nodes, nodes)

        # Get all network interfaces
        interface_ids = []
        for node in nodes:
            # The field name has changed in plcapi 4.3
            if self.api.plshell_version in ['4.2']:
                interface_ids.extend(node['nodenetwork_ids'])
            elif self.api.plshell_version in ['4.3']:
                interface_ids.extend(node['interface_ids'])
            else:
                raise SfaAPIError, "Unsupported plcapi version ", \
                                 self.api.plshell_version

        if self.api.plshell_version in ['4.2']:
            interfaces = self.api.plshell.GetNodeNetworks(self.api.plauth, interface_ids)
        elif self.api.plshell_version in ['4.3']:
            interfaces = self.api.plshell.GetInterfaces(self.api.plauth, interface_ids)
        else:
            raise SfaAPIError, "Unsupported plcapi version ", \
                                self.api.plshell_version 
        interface_dict = {}
        for interface in interfaces:
            if self.api.plshell_version in ['4.2']:
                interface_dict[interface['nodenetwork_id']] = interface
            elif self.api.plshell_version in ['4.3']:
                interface_dict[interface['interface_id']] = interface
            else:
                raise SfaAPIError, "Unsupported plcapi version", \
                                    self.api.plshell_version 

        # join nodes with thier interfaces
        for node in nodes:
            node['interfaces'] = []
            if self.api.plshell_version in ['4.2']:
                for nodenetwork_id in node['nodenetwork_ids']:
                    node['interfaces'].append(interface_dict[nodenetwork_id])
            elif self.api.plshell_version in ['4.3']:
                for interface_id in node['interface_ids']:
                    node['interfaces'].append(interface_dict[interface_id])
            else:
                raise SfaAPIError, "Unsupported plcapi version", \
                                    self.api.plshell_version

        # convert and threshold to ints
        if self.has_key('timestamp') and self['timestamp']:
            timestamp = datetime.datetime.fromtimestamp(time.mktime(time.strptime(self['timestamp'], self.api.time_format)))
            threshold = datetime.datetime.fromtimestamp(time.mktime(time.strptime(self['threshold'], self.api.time_format)))
        else:
            timestamp = datetime.datetime.now()
            delta = datetime.timedelta(hours=self.ttl)
            threshold = timestamp + delta

        start_time = int(timestamp.strftime("%s"))
        end_time = int(threshold.strftime("%s"))
        duration = end_time - start_time

        # create the plc dict
        networks = [{'nodes': nodes,
                     'name': self.api.hrn,
                     'start_time': start_time,
                     'duration': duration}]
        if not hrn:
            networks[0]['links'] = linkspecs
        resources = {'networks': networks, 'start_time': start_time, 'duration': duration}

        # convert the plc dict to an rspec dict
        resourceDict = RSpecDict(resources)
        # convert the rspec dict to xml
        rspec = RSpec()
        rspec.parseDict(resourceDict)
        return rspec.toxml()
        
