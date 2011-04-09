from __future__ import with_statement 

import sys
import os

import boto
from boto.ec2.regioninfo import RegionInfo
from boto.exception import EC2ResponseError
from ConfigParser import ConfigParser
from xmlbuilder import XMLBuilder
from lxml import etree as ET
from sqlobject import *

from sfa.util.faults import *
from sfa.util.xrn import urn_to_hrn
from sfa.util.rspec import RSpec
from sfa.server.registry import Registries
from sfa.trust.credential import Credential
from sfa.plc.api import SfaAPI
from sfa.util.plxrn import hrn_to_pl_slicename, slicename_to_hrn
from sfa.util.callids import Callids

##
# The data structure used to represent a cloud.
# It contains the cloud name, its ip address, image information,
# key pairs, and clusters information.
#
cloud = {}

##
# The location of the RelaxNG schema.
#
EUCALYPTUS_RSPEC_SCHEMA='/etc/sfa/eucalyptus.rng'

# Quick hack
sys.stderr = file('/var/log/euca_agg.log', 'a+')
api = SfaAPI()

##
# A representation of an Eucalyptus instance. This is a support class
# for instance <-> slice mapping.
#
class EucaInstance(SQLObject):
    instance_id = StringCol(unique=True, default=None)
    kernel_id   = StringCol()
    image_id    = StringCol()
    ramdisk_id  = StringCol()
    inst_type   = StringCol()
    key_pair    = StringCol()
    slice = ForeignKey('Slice')

    ##
    # Contacts Eucalyptus and tries to reserve this instance.
    # 
    # @param botoConn A connection to Eucalyptus.
    # @param pubKeys A list of public keys for the instance.
    #
    def reserveInstance(self, botoConn, pubKeys):
        print >>sys.stderr, 'Reserving an instance: image: %s, kernel: ' \
                            '%s, ramdisk: %s, type: %s, key: %s' % \
                            (self.image_id, self.kernel_id, self.ramdisk_id, 
                             self.inst_type, self.key_pair)

        # XXX The return statement is for testing. REMOVE in production
        #return

        try:
            reservation = botoConn.run_instances(self.image_id,
                                                 kernel_id = self.kernel_id,
                                                 ramdisk_id = self.ramdisk_id,
                                                 instance_type = self.inst_type,
                                                 key_name  = self.key_pair,
                                                 user_data = pubKeys)
            for instance in reservation.instances:
                self.instance_id = instance.id

        # If there is an error, destroy itself.
        except EC2ResponseError, ec2RespErr:
            errTree = ET.fromstring(ec2RespErr.body)
            msg = errTree.find('.//Message')
            print >>sys.stderr, msg.text
            self.destroySelf()

##
# A representation of a PlanetLab slice. This is a support class
# for instance <-> slice mapping.
#
class Slice(SQLObject):
    slice_hrn = StringCol()
    #slice_index = DatabaseIndex('slice_hrn')
    instances = MultipleJoin('EucaInstance')

##
# Initialize the aggregate manager by reading a configuration file.
#
def init_server():
    configParser = ConfigParser()
    configParser.read(['/etc/sfa/eucalyptus_aggregate.conf', 'eucalyptus_aggregate.conf'])
    if len(configParser.sections()) < 1:
        print >>sys.stderr, 'No cloud defined in the config file'
        raise Exception('Cannot find cloud definition in configuration file.')

    # Only read the first section.
    cloudSec = configParser.sections()[0]
    cloud['name'] = cloudSec
    cloud['access_key'] = configParser.get(cloudSec, 'access_key')
    cloud['secret_key'] = configParser.get(cloudSec, 'secret_key')
    cloud['cloud_url']  = configParser.get(cloudSec, 'cloud_url')
    cloudURL = cloud['cloud_url']
    if cloudURL.find('https://') >= 0:
        cloudURL = cloudURL.replace('https://', '')
    elif cloudURL.find('http://') >= 0:
        cloudURL = cloudURL.replace('http://', '')
    (cloud['ip'], parts) = cloudURL.split(':')

    # Create image bundles
    images = getEucaConnection().get_all_images()
    cloud['images'] = images
    cloud['imageBundles'] = {}
    for i in images:
        if i.type != 'machine' or i.kernel_id is None: continue
        name = os.path.dirname(i.location)
        detail = {'imageID' : i.id, 'kernelID' : i.kernel_id, 'ramdiskID' : i.ramdisk_id}
        cloud['imageBundles'][name] = detail

    # Initialize sqlite3 database.
    dbPath = '/etc/sfa/db'
    dbName = 'euca_aggregate.db'

    if not os.path.isdir(dbPath):
        print >>sys.stderr, '%s not found. Creating directory ...' % dbPath
        os.mkdir(dbPath)

    conn = connectionForURI('sqlite://%s/%s' % (dbPath, dbName))
    sqlhub.processConnection = conn
    Slice.createTable(ifNotExists=True)
    EucaInstance.createTable(ifNotExists=True)

    # Make sure the schema exists.
    if not os.path.exists(EUCALYPTUS_RSPEC_SCHEMA):
        err = 'Cannot location schema at %s' % EUCALYPTUS_RSPEC_SCHEMA
        print >>sys.stderr, err
        raise Exception(err)

##
# Creates a connection to Eucalytpus. This function is inspired by 
# the make_connection() in Euca2ools.
#
# @return A connection object or None
#
def getEucaConnection():
    global cloud
    accessKey = cloud['access_key']
    secretKey = cloud['secret_key']
    eucaURL   = cloud['cloud_url']
    useSSL    = False
    srvPath   = '/'
    eucaPort  = 8773

    if not accessKey or not secretKey or not eucaURL:
        print >>sys.stderr, 'Please set ALL of the required environment ' \
                            'variables by sourcing the eucarc file.'
        return None
    
    # Split the url into parts
    if eucaURL.find('https://') >= 0:
        useSSL  = True
        eucaURL = eucaURL.replace('https://', '')
    elif eucaURL.find('http://') >= 0:
        useSSL  = False
        eucaURL = eucaURL.replace('http://', '')
    (eucaHost, parts) = eucaURL.split(':')
    if len(parts) > 1:
        parts = parts.split('/')
        eucaPort = int(parts[0])
        parts = parts[1:]
        srvPath = '/'.join(parts)

    return boto.connect_ec2(aws_access_key_id=accessKey,
                            aws_secret_access_key=secretKey,
                            is_secure=useSSL,
                            region=RegionInfo(None, 'eucalyptus', eucaHost), 
                            port=eucaPort,
                            path=srvPath)

##
# Returns a string of keys that belong to the users of the given slice.
# @param sliceHRN The hunman readable name of the slice.
# @return sting()
#
def getKeysForSlice(sliceHRN):
    try:
        # convert hrn to slice name
        plSliceName = hrn_to_pl_slicename(sliceHRN)
    except IndexError, e:
        print >>sys.stderr, 'Invalid slice name (%s)' % sliceHRN
        return []

    # Get the slice's information
    sliceData = api.plshell.GetSlices(api.plauth, {'name':plSliceName})
    if not sliceData:
        print >>sys.stderr, 'Cannot get any data for slice %s' % plSliceName
        return []

    # It should only return a list with len = 1
    sliceData = sliceData[0]

    keys = []
    person_ids = sliceData['person_ids']
    if not person_ids: 
        print >>sys.stderr, 'No users in slice %s' % sliceHRN
        return []

    persons = api.plshell.GetPersons(api.plauth, person_ids)
    for person in persons:
        pkeys = api.plshell.GetKeys(api.plauth, person['key_ids'])
        for key in pkeys:
            keys.append(key['key'])
 
    return ''.join(keys)

##
# A class that builds the RSpec for Eucalyptus.
#
class EucaRSpecBuilder(object):
    ##
    # Initizes a RSpec builder
    #
    # @param cloud A dictionary containing data about a 
    #              cloud (ex. clusters, ip)
    def __init__(self, cloud):
        self.eucaRSpec = XMLBuilder(format = True, tab_step = "  ")
        self.cloudInfo = cloud

    ##
    # Creates a request stanza.
    # 
    # @param num The number of instances to create.
    # @param image The disk image id.
    # @param kernel The kernel image id.
    # @param keypair Key pair to embed.
    # @param ramdisk Ramdisk id (optional).
    #
    def __requestXML(self, num, image, kernel, keypair, ramdisk = ''):
        xml = self.eucaRSpec
        with xml.request:
            with xml.instances:
                xml << str(num)
            with xml.kernel_image(id=kernel):
                xml << ''
            if ramdisk == '':
                with xml.ramdisk:
                    xml << ''
            else:
                with xml.ramdisk(id=ramdisk):
                    xml << ''
            with xml.disk_image(id=image):
                xml << ''
            with xml.keypair:
                xml << keypair

    ##
    # Creates the cluster stanza.
    #
    # @param clusters Clusters information.
    #
    def __clustersXML(self, clusters):
        cloud = self.cloudInfo
        xml = self.eucaRSpec

        for cluster in clusters:
            instances = cluster['instances']
            with xml.cluster(id=cluster['name']):
                with xml.ipv4:
                    xml << cluster['ip']
                with xml.vm_types:
                    for inst in instances:
                        with xml.vm_type(name=inst[0]):
                            with xml.free_slots:
                                xml << str(inst[1])
                            with xml.max_instances:
                                xml << str(inst[2])
                            with xml.cores:
                                xml << str(inst[3])
                            with xml.memory(unit='MB'):
                                xml << str(inst[4])
                            with xml.disk_space(unit='GB'):
                                xml << str(inst[5])
                            if 'instances' in cloud and inst[0] in cloud['instances']:
                                existingEucaInstances = cloud['instances'][inst[0]]
                                with xml.euca_instances:
                                    for eucaInst in existingEucaInstances:
                                        with xml.euca_instance(id=eucaInst['id']):
                                            with xml.state:
                                                xml << eucaInst['state']
                                            with xml.public_dns:
                                                xml << eucaInst['public_dns']

    def __imageBundleXML(self, bundles):
        xml = self.eucaRSpec
        with xml.bundles:
            for bundle in bundles.keys():
                with xml.bundle(id=bundle):
                    xml << ''

    ##
    # Creates the Images stanza.
    #
    # @param images A list of images in Eucalyptus.
    #
    def __imagesXML(self, images):
        xml = self.eucaRSpec
        with xml.images:
            for image in images:
                with xml.image(id=image.id):
                    with xml.type:
                        xml << image.type
                    with xml.arch:
                        xml << image.architecture
                    with xml.state:
                        xml << image.state
                    with xml.location:
                        xml << image.location

    ##
    # Creates the KeyPairs stanza.
    #
    # @param keypairs A list of key pairs in Eucalyptus.
    #
    def __keyPairsXML(self, keypairs):
        xml = self.eucaRSpec
        with xml.keypairs:
            for key in keypairs:
                with xml.keypair:
                    xml << key.name

    ##
    # Generates the RSpec.
    #
    def toXML(self):
        if not self.cloudInfo:
            print >>sys.stderr, 'No cloud information'
            return ''

        xml = self.eucaRSpec
        cloud = self.cloudInfo
        with xml.RSpec(type='eucalyptus'):
            with xml.cloud(id=cloud['name']):
                with xml.ipv4:
                    xml << cloud['ip']
                #self.__keyPairsXML(cloud['keypairs'])
                #self.__imagesXML(cloud['images'])
                self.__imageBundleXML(cloud['imageBundles'])
                self.__clustersXML(cloud['clusters'])
        return str(xml)

##
# A parser to parse the output of availability-zones.
#
# Note: Only one cluster is supported. If more than one, this will
#       not work.
#
class ZoneResultParser(object):
    def __init__(self, zones):
        self.zones = zones

    def parse(self):
        if len(self.zones) < 3:
            return
        clusterList = []
        cluster = {} 
        instList = []

        cluster['name'] = self.zones[0].name
        cluster['ip']   = self.zones[0].state

        for i in range(2, len(self.zones)):
            currZone = self.zones[i]
            instType = currZone.name.split()[1]

            stateString = currZone.state.split('/')
            rscString   = stateString[1].split()

            instFree      = int(stateString[0])
            instMax       = int(rscString[0])
            instNumCpu    = int(rscString[1])
            instRam       = int(rscString[2])
            instDiskSpace = int(rscString[3])

            instTuple = (instType, instFree, instMax, instNumCpu, instRam, instDiskSpace)
            instList.append(instTuple)
        cluster['instances'] = instList
        clusterList.append(cluster)

        return clusterList

def ListResources(api, creds, options, call_id): 
    if Callids().already_handled(call_id): return ""
    global cloud
    # get slice's hrn from options
    xrn = options.get('geni_slice_urn', '')
    hrn, type = urn_to_hrn(xrn)

    # get hrn of the original caller
    origin_hrn = options.get('origin_hrn', None)
    if not origin_hrn:
        origin_hrn = Credential(string=creds[0]).get_gid_caller().get_hrn()

    conn = getEucaConnection()

    if not conn:
        print >>sys.stderr, 'Error: Cannot create a connection to Eucalyptus'
        return 'Cannot create a connection to Eucalyptus'

    try:
        # Zones
        zones = conn.get_all_zones(['verbose'])
        p = ZoneResultParser(zones)
        clusters = p.parse()
        cloud['clusters'] = clusters
        
        # Images
        images = conn.get_all_images()
        cloud['images'] = images
        cloud['imageBundles'] = {}
        for i in images:
            if i.type != 'machine' or i.kernel_id is None: continue
            name = os.path.dirname(i.location)
            detail = {'imageID' : i.id, 'kernelID' : i.kernel_id, 'ramdiskID' : i.ramdisk_id}
            cloud['imageBundles'][name] = detail

        # Key Pairs
        keyPairs = conn.get_all_key_pairs()
        cloud['keypairs'] = keyPairs

        if hrn:
            instanceId = []
            instances  = []

            # Get the instances that belong to the given slice from sqlite3
            # XXX use getOne() in production because the slice's hrn is supposed
            # to be unique. For testing, uniqueness is turned off in the db.
            # If the slice isn't found in the database, create a record for the 
            # slice.
            matchedSlices = list(Slice.select(Slice.q.slice_hrn == hrn))
            if matchedSlices:
                theSlice = matchedSlices[-1]
            else:
                theSlice = Slice(slice_hrn = hrn)
            for instance in theSlice.instances:
                instanceId.append(instance.instance_id)

            # Get the information about those instances using their ids.
            if len(instanceId) > 0:
                reservations = conn.get_all_instances(instanceId)
            else:
                reservations = []
            for reservation in reservations:
                for instance in reservation.instances:
                    instances.append(instance)

            # Construct a dictionary for the EucaRSpecBuilder
            instancesDict = {}
            for instance in instances:
                instList = instancesDict.setdefault(instance.instance_type, [])
                instInfoDict = {} 

                instInfoDict['id'] = instance.id
                instInfoDict['public_dns'] = instance.public_dns_name
                instInfoDict['state'] = instance.state
                instInfoDict['key'] = instance.key_name

                instList.append(instInfoDict)
            cloud['instances'] = instancesDict

    except EC2ResponseError, ec2RespErr:
        errTree = ET.fromstring(ec2RespErr.body)
        errMsgE = errTree.find('.//Message')
        print >>sys.stderr, errMsgE.text

    rspec = EucaRSpecBuilder(cloud).toXML()

    # Remove the instances records so next time they won't 
    # show up.
    if 'instances' in cloud:
        del cloud['instances']

    return rspec

"""
Hook called via 'sfi.py create'
"""
def CreateSliver(api, xrn, creds, xml, users, call_id):
    if Callids().already_handled(call_id): return ""

    global cloud
    hrn = urn_to_hrn(xrn)[0]

    conn = getEucaConnection()
    if not conn:
        print >>sys.stderr, 'Error: Cannot create a connection to Eucalyptus'
        return ""

    # Validate RSpec
    schemaXML = ET.parse(EUCALYPTUS_RSPEC_SCHEMA)
    rspecValidator = ET.RelaxNG(schemaXML)
    rspecXML = ET.XML(xml)
    if not rspecValidator(rspecXML):
        error = rspecValidator.error_log.last_error
        message = '%s (line %s)' % (error.message, error.line) 
        # XXX: InvalidRSpec is new. Currently, I am not working with Trunk code.
        #raise InvalidRSpec(message)
        raise Exception(message)

    # Get the slice from db or create one.
    s = Slice.select(Slice.q.slice_hrn == hrn).getOne(None)
    if s is None:
        s = Slice(slice_hrn = hrn)

    # Process any changes in existing instance allocation
    pendingRmInst = []
    for sliceInst in s.instances:
        pendingRmInst.append(sliceInst.instance_id)
    existingInstGroup = rspecXML.findall('.//euca_instances')
    for instGroup in existingInstGroup:
        for existingInst in instGroup:
            if existingInst.get('id') in pendingRmInst:
                pendingRmInst.remove(existingInst.get('id'))
    for inst in pendingRmInst:
        print >>sys.stderr, 'Instance %s will be terminated' % inst
        dbInst = EucaInstance.select(EucaInstance.q.instance_id == inst).getOne(None)
        dbInst.destroySelf()
    conn.terminate_instances(pendingRmInst)

    # Process new instance requests
    requests = rspecXML.findall('.//request')
    if requests:
        # Get all the public keys associate with slice.
        pubKeys = getKeysForSlice(s.slice_hrn)
        print >>sys.stderr, "Passing the following keys to the instance:\n%s" % pubKeys
        sys.stderr.flush()
    for req in requests:
        vmTypeElement = req.getparent()
        instType = vmTypeElement.get('name')
        numInst  = int(req.find('instances').text)
        
        bundleName = req.find('bundle').text
        if not cloud['imageBundles'][bundleName]:
            print >>sys.stderr, 'Cannot find bundle %s' % bundleName
        bundleInfo = cloud['imageBundles'][bundleName]
        instKernel  = bundleInfo['kernelID']
        instDiskImg = bundleInfo['imageID']
        instRamDisk = bundleInfo['ramdiskID']
        instKey     = None

        # Create the instances
        for i in range(0, numInst):
            eucaInst = EucaInstance(slice = s, 
                                    kernel_id = instKernel,
                                    image_id = instDiskImg,
                                    ramdisk_id = instRamDisk,
                                    key_pair = instKey,
                                    inst_type = instType)
            eucaInst.reserveInstance(conn, pubKeys)

    # xxx - should return altered rspec 
    # with enough data for the client to understand what's happened
    return xml

def main():
    init_server()

    #theRSpec = None
    #with open(sys.argv[1]) as xml:
    #    theRSpec = xml.read()
    #CreateSliver(None, 'planetcloud.pc.test', theRSpec, 'call-id-cloudtest')

    #rspec = ListResources('euca', 'planetcloud.pc.test', 'planetcloud.pc.marcoy', 'test_euca')
    #print rspec
    print getKeysForSlice('gc.gc.test1')

if __name__ == "__main__":
    main()

