### $Id: get_slices.py 14387 2009-07-08 18:19:11Z faiyaza $
### $URL: https://svn.planet-lab.org/svn/sfa/trunk/sfa/methods/get_registries.py $
from types import StringTypes
from sfa.util.faults import *
from sfa.util.namespace import *
from sfa.util.method import Method
from sfa.util.parameter import Parameter, Mixed
from sfa.trust.auth import Auth
from sfa.server.registry import Registries

class get_registries(Method):
    """
    Get a list of connection information for all known registries.      

    @param cred credential string specifying the rights of the caller
    @param a Human readable name (hrn or urn), or list of names or None
    @return list of dictionaries with aggregate information.  
    """

    interfaces = ['registry', 'aggregate', 'slicemgr']
    
    accepts = [
        Parameter(str, "Credential string"),
        Mixed(Parameter(str, "Human readable name (hrn or urn)"),
              Parameter(None, "hrn not specified"))
        ]

    returns = [Parameter(dict, "Registry interface information")]
    
    def call(self, cred, xrn = None):
        hrn, type = urn_to_hrn(xrn)
        self.api.auth.check(cred, 'list')
        registries = Registries(self.api)
        hrn_list = []
        if hrn:
            if isinstance(hrn, StringTypes):
                hrn_list = [hrn]
            elif isinstance(hrn, list):
                hrn_list = hrn

        if not hrn_list:
            interfaces = registries.interfaces.keys()
        else:
            interfaces = [interface for interface in registries.interfaces if interface in hrn_list]

        return interfaces
