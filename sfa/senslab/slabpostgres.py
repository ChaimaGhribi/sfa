import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sfa.util.config import Config
from sfa.util.sfalogging import logger

from sqlalchemy import Column, Integer, String
from sqlalchemy import Table, Column, MetaData
from sqlalchemy.ext.declarative import declarative_base

from sqlalchemy.dialects import postgresql

from sqlalchemy import MetaData, Table
from sqlalchemy.exc import NoSuchTableError

from sqlalchemy import String

#Dict holding the columns names of the table as keys
#and their type, used for creation of the table
slice_table = {'record_id_user':'integer PRIMARY KEY references X ON DELETE \
CASCADE ON UPDATE CASCADE','oar_job_id':'integer DEFAULT -1',  \
'record_id_slice':'integer', 'slice_hrn':'text NOT NULL'}

#Dict with all the specific senslab tables
tablenames_dict = {'slice_senslab': slice_table}

##############################



SlabBase = declarative_base()

class SliceSenslab (SlabBase):
    __tablename__ = 'slice_senslab' 
    #record_id_user = Column(Integer, primary_key=True)

    slice_hrn = Column(String, primary_key=True)
    peer_authority = Column(String, nullable = True)
    record_id_slice = Column(Integer)    
    record_id_user = Column(Integer) 

    #oar_job_id = Column( Integer,default = -1)
    #node_list = Column(postgresql.ARRAY(String), nullable =True)
    
    def __init__ (self, slice_hrn =None, record_id_slice=None, \
                                    record_id_user= None,peer_authority=None):
        """
        Defines a row of the slice_senslab table
        """
        if record_id_slice: 
            self.record_id_slice = record_id_slice
        if slice_hrn:
            self.slice_hrn = slice_hrn
        if record_id_user: 
            self.record_id_user= record_id_user
        if peer_authority:
            self.peer_authority = peer_authority
            
            
    def __repr__(self):
        """Prints the SQLAlchemy record to the format defined
        by the function.
        """
        result="<Record id user =%s, slice hrn=%s, Record id slice =%s , \
                peer_authority =%s"% (self.record_id_user, self.slice_hrn, \
                self.record_id_slice, self.peer_authority)
        result += ">"
        return result
          
    def dump_sqlalchemyobj_to_dict(self):
        """Transforms a SQLalchemy record object to a python dictionary.
        Returns the dictionary.
        """
        
        dict = {'slice_hrn':self.slice_hrn,
        'peer_authority':self.peer_authority,
        'record_id':self.record_id_slice, 
        'record_id_user':self.record_id_user,
        'record_id_slice':self.record_id_slice, }
        return dict 
          
          
class SlabDB:
    def __init__(self,config, debug = False):
        self.sl_base = SlabBase
        dbname="slab_sfa"
        if debug == True :
            l_echo_pool = True
            l_echo=True 
        else :
            l_echo_pool = False
            l_echo = False 
        # will be created lazily on-demand
        self.slab_session = None
        # the former PostgreSQL.py used the psycopg2 directly and was doing
        #self.connection.set_client_encoding("UNICODE")
        # it's unclear how to achieve this in sqlalchemy, nor if it's needed 
        # at all
        # http://www.sqlalchemy.org/docs/dialects/postgresql.html#unicode
        # we indeed have /var/lib/pgsql/data/postgresql.conf where
        # this setting is unset, it might be an angle to tweak that if need be
        # try a unix socket first - omitting the hostname does the trick
        unix_url = "postgresql+psycopg2://%s:%s@:%s/%s"%\
            (config.SFA_DB_USER, config.SFA_DB_PASSWORD, \
                                    config.SFA_DB_PORT, dbname)

        # the TCP fallback method
        tcp_url = "postgresql+psycopg2://%s:%s@%s:%s/%s"%\
            (config.SFA_DB_USER, config.SFA_DB_PASSWORD, config.SFA_DB_HOST, \
                                    config.SFA_DB_PORT, dbname)
        for url in [ unix_url, tcp_url ] :
            try:
                self.slab_engine = create_engine (url, echo_pool = \
                                            l_echo_pool, echo = l_echo)
                self.check()
                self.url = url
                return
            except:
                pass
        self.slab_engine = None
        raise Exception, "Could not connect to database"
    
    
    
    def check (self):
        self.slab_engine.execute ("select 1").scalar()
        
        
        
    def session (self):
        """
        Creates a SQLalchemy session. Once the session object is created
        it should be used throughout the code for all the operations on 
        tables for this given database.
        
        """ 
        if self.slab_session is None:
            Session = sessionmaker()
            self.slab_session = Session(bind = self.slab_engine)
        return self.slab_session
        
       
    def close(self):
        """
        Closes connection to database. 
        
        """
        if self.connection is not None:
            self.connection.close()
            self.connection = None
            

    def exists(self, tablename):
        """
        Checks if the table specified as tablename exists.
    
        """
       
        try:
            metadata = MetaData (bind=self.slab_engine)
            table=Table (tablename, metadata, autoload=True)
           
            return True
        except NoSuchTableError:
            logger.log_exc("SLABPOSTGRES tablename %s does not exists" \
                            %(tablename))
            return False
       
    
    def createtable(self, tablename ):
        """
        Creates the specifed table. Uses the global dictionnary holding the 
        tablenames and the table schema.
    
        """

        logger.debug("SLABPOSTGRES createtable SlabBase.metadata.sorted_tables \
            %s \r\n engine %s" %(SlabBase.metadata.sorted_tables , slab_engine))
        SlabBase.metadata.create_all(slab_engine)
        return
    

from sfa.util.config import Config

slab_alchemy= SlabDB(Config())
slab_engine=slab_alchemy.slab_engine
slab_dbsession=slab_alchemy.session()
