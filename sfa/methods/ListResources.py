from sfa.util.faults import *
from sfa.util.namespace import *
from sfa.util.method import Method
from sfa.util.parameter import Parameter, Mixed
from sfa.trust.credential import Credential
from sfa.util.sfatablesRuntime import run_sfatables
import sys
import zlib

class ListResources(Method):
    """
    Returns information about available resources or resources allocated to this slice
    @param credential list
    @param options dictionary
    @return string
    """
    interfaces = ['aggregate', 'slicemgr', 'geni_am']
    accepts = [
        Mixed(Parameter(str, "Credential string"), 
              Parameter(type([str]), "List of credentials")),
        Parameter(dict, "Options")
        ]
    returns = Parameter(str, "List of resources")

    def call(self, creds, options):
        self.api.logger.info("interface: %s\tmethod-name: %s" % (self.api.interface, self.name))
        
        # get slice's hrn from options    
        xrn = options.get('geni_slice_urn', None)
        hrn, _ = urn_to_hrn(xrn)

        # Find the valid credentials
        valid_creds = self.api.auth.checkCredentials(creds, 'listnodes', hrn)

        # get hrn of the original caller 
        origin_hrn = options.get('origin_hrn', None)
        if not origin_hrn:
            origin_hrn = Credential(string=valid_creds[0]).get_gid_caller().get_hrn()
            
        manager = self.api.get_interface_manager()
        rspec = manager.get_rspec(self.api, valid_creds, options)

        # filter rspec through sfatables 
        if self.api.interface in ['aggregate', 'geni_am']:
            chain_name = 'OUTGOING'
        elif self.api.interface in ['slicemgr']: 
            chain_name = 'FORWARD-OUTGOING'

        filtered_rspec = run_sfatables(chain_name, hrn, origin_hrn, rspec) 
 
        if options.has_key('geni_compressed') and options['geni_compressed'] == True:
            filtered_rspec = zlib.compress(rspec).encode('base64')

        return filtered_rspec  
    
    
