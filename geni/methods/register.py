from geni.util.faults import *
from geni.util.excep import *
from geni.util.method import Method
from geni.util.parameter import Parameter, Mixed
from geni.util.auth import Auth
from geni.util.record import GeniRecord
from geni.util.debug import log

class register(Method):
    """
    Register an object with the registry. In addition to being stored in the
    Geni database, the appropriate records will also be created in the
    PLC databases
    
    @param cred credential string
    @param record_dict dictionary containing record fields
    
    @return gid string representation
    """

    interfaces = ['registry']
    
    accepts = [
        Parameter(str, "Credential string"),
        Parameter(dict, "Record dictionary containing record fields")
        ]

    returns = Parameter(int, "String representation of gid object")
    
    def call(self, cred, record_dict):
        self.decode_authentication(cred, "register")
        record = GeniRecord(dict = record_dict)
        type = record.get_type()
        name = record.get_name()
        auth_name = self.api.auth.get_authority(name)
        self.api.auth.verify_object_permission(auth_name)
        auth_info = self.api.auth.get_auth_info(auth_name)
        table = self.api.auth.get_auth_table(auth_name)
        pkey = None

        # check if record already exists
        existing_records = table.resolve(type, name)
        if existing_records:
            raise ExistingRecord(name)

        geni_fields = record.get_geni_info()
        pl_fields = record.get_pl_info()
        
        if (type == "sa") or (type=="ma"):
            # update the tree
            if not self.api.auth.hierarchy.auth_exists(name):
                self.api.auth.hierarchy.create_auth(name)

            # authorities are special since they are managed by the registry
            # rather than by the caller. We create our own GID for the
            # authority rather than relying on the caller to supply one.

            # get the GID from the newly created authority
            child_auth_info = self.api.auth.get_auth_info(name)
            gid = auth_info.get_gid_object()
            record.set_gid(gid.save_to_string(save_parents=True))

            # if registering a sa, see if a ma already exists
            # if registering a ma, see if a sa already exists
            if (type == "sa"):
                other_rec = table.resolve("ma", record.get_name())
            elif (type == "ma"):
                other_rec = table.resolve("sa", record.get_name())

            if other_rec:
                print >> log, "linking ma and sa to the same plc site"
                pointer = other_rec[0].get_pointer()
            else:
                self.api.geni_fields_to_pl_fields(type, name, geni_fields, pl_fields)
                print >> log, "adding site with fields", pl_fields
                pointer = self.api.plshell.AddSite(self.api.plauth, pl_fields)

            record.set_pointer(pointer)

        elif (type == "slice"):
            self.api.geni_fields_to_pl_fields(type, name, geni_fields, pl_fields)
            pointer = self.api.plshell.AddSlice(self.api.plauth, pl_fields)
            record.set_pointer(pointer)

        elif (type == "user"):
            self.api.geni_fields_to_pl_fields(type, name, geni_fields, pl_fields)
            pointer = self.api.plshell.AddPerson(self.api.plauth, pl_fields)
            record.set_pointer(pointer)

        elif (type == "node"):
            self.api.geni_fields_to_pl_fields(type, name, geni_fields, pl_fields)
            login_base = self.api.hrn_to_pl_login_base(auth_name)
            pointer = self.api.plshell.AddNode(self.api.plauth, login_base, pl_fields)
            record.set_pointer(pointer)

        else:
            raise UnknownGeniType(type)

        table.insert(record)

        # update membership for researchers, pis, owners, operators
        self.api.update_membership(None, record)

        return record.get_gid_object().save_to_string(save_parents=True)
