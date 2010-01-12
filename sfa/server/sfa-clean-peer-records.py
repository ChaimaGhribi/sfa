#!/usr/bin/python

import sys
import os
import traceback
from sfa.util.namespace import *
from sfa.util.table import SfaTable
from sfa.util.prefixTree import prefixTree
from sfa.plc.api import SfaAPI
from sfa.util.config import Config
from sfa.trust.certificate import Keypair
from sfa.trust.hierarchy import Hierarchy
from sfa.util.report import trace, error
from sfa.server.registry import Registries
from sfa.util.xmlrpcprotocol import *
import socket

def main():
    config = Config()
    if not config.SFA_REGISTRY_ENABLED:
        sys.exit(0)

    # Get the path to the sfa server key/cert files from 
    # the sfa hierarchy object
    sfa_hierarchy = Hierarchy()
    sfa_key_path = sfa_hierarchy.basedir
    key_file = os.path.join(sfa_key_path, "server.key")
    cert_file = os.path.join(sfa_key_path, "server.cert")
    key = Keypair(filename=key_file) 

    # get a connection to our local sfa registry
    # and a valid credential
    authority = config.SFA_INTERFACE_HRN
    url = 'http://%s:%s/' %(config.SFA_REGISTRY_HOST, config.SFA_REGISTRY_PORT)
    registry = xmlrpcprotocol.get_server(url, key_file, cert_file)
    sfa_api = SfaAPI(key_file = key_file, cert_file = cert_file, interface='registry')
    credential = sfa_api.getCredential()

    # get peer registries
    registries = Registries(sfa_api)
    tree = prefixTree()
    tree.load(registries.keys())
    
    # get local peer records
    table = SfaTable()
    peer_records = table.find({'~peer_authority': None})
    found_records = []
    hrn_dict = {}
    for record in peer_records:
        registry_hrn = tree.best_match(record['hrn'])
        if registry_hrn not in hrn_dict:
            hrn_dict[registry_hrn] = []
        hrn_dict[registry_hrn].append(record['hrn'])

    # attempt to resolve the record at the authoritative interface 
    for registry_hrn in hrn_dict:
        if registry_hrn in registries:
            records = []
            target_hrns = hrn_dict[registry_hrn]    
            try:
                records = registries[registry_hrn].resolve(credential, target_hrns)
                found_records.extend([record['hrn'] for record in records])
            except:
                traceback.print_exc()

    # remove what wasnt found 
    for peer_record in peer_records:
        if peer_record['hrn'] not in found_records:
            registries[sfa_api.hrn].remove(credential, peer_record)
                
if __name__ == '__main__':
    main()
