from sfa.util.faults import *
from sfa.util.namespace import *
from sfa.util.method import Method
from sfa.util.parameter import Parameter
from sfa.methods.Stop import Stop

class Shutdown(Stop):
    """
    Perform an emergency shut down of a sliver. This operation is intended for administrative use. 
    The sliver is shut down but remains available for further forensics.

    @param slice_urn (string) URN of slice to renew
    @param credentials ([string]) of credentials    
    """
    interfaces = ['aggregate', 'slicemgr', 'geni_am']
    accepts = [
        Parameter(str, "Slice URN"),
        Parameter(type([str]), "List of credentials"),
        ]
    returns = Parameter(bool, "Success or Failure")

    def call(self, slice_xrn, creds):

        return Stop.call(self, slice_xrn, creds)
    
