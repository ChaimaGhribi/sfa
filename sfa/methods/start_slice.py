### $Id$
### $URL$

from sfa.util.faults import *
from sfa.util.misc import *
from sfa.util.method import Method
from sfa.util.parameter import Parameter, Mixed
from sfa.trust.auth import Auth
from sfa.util.slices import Slices

class start_slice(Method):
    """
    Start the specified slice      

    @param cred credential string specifying the rights of the caller
    @param hrn human readable name of slice to instantiate
    @return 1 is successful, faults otherwise  
    """

    interfaces = ['aggregate', 'slicemgr']
    
    accepts = [
        Parameter(str, "Credential string"),
        Parameter(str, "Human readable name of slice to instantiate"),
        ]

    returns = [Parameter(int, "1 if successful")]
    
    def call(self, cred, hrn):
       
        self.api.auth.check(cred, 'startslice')
        slices = Slices(self.api)
        slices.start_slice(hrn)
        
        return 1 
