##
# SFA Configuration Info
#
# This module holds configuration parameters for SFA. There are two
# main pieces of information that are used: the database connection and
# the PLCAPI connection
##

##
# SFA uses a MYSQL database to store records. This database may be
# co-located with the PLC database, or it may be a separate database. The
# following parameters define the connection to the database.
#
# Note that SFA does not access any of the PLC databases directly via
# a mysql connection; All PLC databases are accessed via PLCAPI.

### $Id$
### $URL$

import os.path
import traceback

from sfa.util.debug import log

class Config:
    """
    Parse the bash/Python/PHP version of the configuration file. Very
    fast but no type conversions.
    """

    def __init__(self, config_file = "/etc/sfa/sfa_config.py"):
        self.config_file = None
        self.config_path = None
        self.data_path = None
        self.load(config_file)

    def load(self, config_file):
        try:
            execfile(config_file, self.__dict__)
            self.config_file = config_file
            # path to configuration data
            self.config_path = os.path.dirname(config_file)
            
            # path to server data
            if not hasattr(self, 'SFA_DATA_DIR'):
                # default to /var/lib/sfa not specified in config
                self.SFA_DATA_DIR="/var/lib/sfa"
                self.data_path = self.SFA_DATA_DIR
            else:
                self.data_path = self.SFA_DATA_DIR
                
            # path to config data
            if not hasattr(self, 'SFA_CONFIG_DIR'):
                # default to /var/lib/sfa not specified in config
                self.SFA_CONFIG_DIR="/etc/sfa"

            if not hasattr(self, 'SFA_REGISTRY_LEVEL1_AUTH'):
                self.SFA_REGISTRY_LEVEL1_AUTH=None

            # define interface types
            # this will determine which manager to use
            if not hasattr(self, 'SFA_REGISTRY_TYPE'):
                self.SFA_REGISTRY_TYPE='pl'

            if not hasattr(self, 'SFA_AGGREGATE_TYPE'):
                self.SFA_AGGREGATE_TYPE='pl'

            if not hasattr(self, 'SFA_SM_TYPE'):
                self.SFA_SM_TYPE='pl'

            if not hasattr(self, 'SFA_CM_TYPE'):
                self.SFA_COMPONENT_TYPE='pl'

            # create the data directory if it doesnt exist
            if not os.path.isdir(self.SFA_DATA_DIR):
                try:
                    os.mkdir(self.SFA_DATA_DIR)
                except: pass
             
        except IOError, e:
            raise IOError, "Could not find the configuration file: %s" % config_file

    def get_trustedroots_dir(self):
        return self.config_path + os.sep + 'trusted_roots'

    def get_openflow_aggrMgr_info(self):
        aggr_mgr_ip = 'localhost'
        if (hasattr(self,'OPENFLOW_AGGREGATE_MANAGER_IP')):
            aggr_mgr_ip = self.OPENFLOW_AGGREGATE_MANAGER_IP

        aggr_mgr_port = 2603
        if (hasattr(self,'OPENFLOW_AGGREGATE_MANAGER_PORT')):
            aggr_mgr_port = self.OPENFLOW_AGGREGATE_MANAGER_PORT

        return (aggr_mgr_ip,aggr_mgr_port)

    def get_aggregate_type(self):
        if (hasattr(self,'SFA_AGGREGATE_TYPE')):
            return self.SFA_AGGREGATE_TYPE
        else:
            return "pl"

    def get_plc_dbinfo(self):
        return {
            'dbname' : self.SFA_PLC_DB_NAME,
            'address' : self.SFA_PLC_DB_HOST,
            'port' : self.SFA_PLC_DB_PORT,
            'user' : self.SFA_PLC_DB_USER,
            'password' : self.SFA_PLC_DB_PASSWORD
            }

    ##
    # SFA uses a PLCAPI connection to perform operations on the registry,
    # such as creating and deleting slices. This connection requires an account
    # on the PLC server with full administrator access.
    #
    # The Url parameter controls whether the connection uses PLCAPI directly (i.e.
    # SFA is located on the same machine as PLC), or uses a XMLRPC connection
    # to the PLC machine. If you wish to use the API directly, then remove the Url
    # field from the dictionary. 

    def get_plc_auth(self):
        return {
            'AuthMethod': 'capability',
            'Username': self.SFA_PLC_USER,
            'AuthString':  self.SFA_PLC_PASSWORD,
            "Url": self.SFA_PLC_URL
            }
