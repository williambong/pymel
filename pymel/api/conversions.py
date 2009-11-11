""" Imports Maya API methods in the 'api' namespace, and defines various utilities for Python<->API communication """

# They will be imported / redefined later in Pymel, but we temporarily need them here
import sys, inspect, time, os.path

from allapi import *
from pymel.util import Singleton, metaStatic, expandArgs, IndexedFrozenTree, treeFromDict
import pymel.util as util
import pymel.mayahook as mayahook
_logger = mayahook.getLogger(__name__)

_thisModule = sys.modules[__name__]

class Enum(tuple):
    def __str__(self): return '.'.join( [str(x) for x in self] )
    def __repr__(self): return repr(str(self))
    def pymelName(self, forceType=None):
        parts = list(self)
        if forceType:
            parts[0] = forceType
        else:
            mfn = getattr( _thisModule, self[0] )
            mayaTypeDict = ApiEnumsToMayaTypes()[ mfn().type() ]
            parts[0] = util.capitalize( mayaTypeDict.keys()[0] )

        return '.'.join( [str(x) for x in parts] )
                          

# Maya static info :
# Initializes various static look-ups to speed up Maya types conversions


class ApiTypesToApiEnums(dict) :
    """Lookup of Maya API types to corresponding MFn::Types enum"""
    __metaclass__ = Singleton   
class ApiEnumsToApiTypes(dict) :
    """Lookup of MFn::Types enum to corresponding Maya API types"""
    __metaclass__ = Singleton
class ApiTypesToApiClasses(dict) :
    """Lookup of Maya API types to corresponding MFnBase Function sets"""
    __metaclass__ = Singleton
    
# Reserved Maya types and API types that need a special treatment (abstract types)
# TODO : parse docs to get these ? Pity there is no kDeformableShape to pair with 'deformableShape'
# strangely createNode ('cluster') works but dgMod.createNode('cluster') doesn't

# added : filters them to weed out those not present in current version

#class ReservedMayaTypes(dict) :
#    __metaclass__ =  metaStatic
## Inverse lookup
#class ReservedApiTypes(dict) :
#   

class ReservedMayaTypes(dict) :
    __metaclass__ = Singleton
class ReservedApiTypes(dict) :
    __metaclass__ = Singleton
    
def _buildMayaReservedTypes():
    """ Build a list of Maya reserved types.
        These cannot be created directly from the API, thus the dgMod trick to find the corresonding Maya type won't work """

    ReservedMayaTypes().clear()
    ReservedApiTypes().clear()
    
    reservedTypes = { 'invalid':'kInvalid', 'base':'kBase', 'object':'kNamedObject', 'dependNode':'kDependencyNode', 'dagNode':'kDagNode', \
                'entity':'kDependencyNode', \
                'constraint':'kConstraint', 'field':'kField', \
                'geometryShape':'kGeometric', 'shape':'kShape', 'deformFunc':'kDeformFunc', 'cluster':'kClusterFilter', \
                'dimensionShape':'kDimension', \
                'abstractBaseCreate':'kCreate', 'polyCreator':'kPolyCreator', \
                'polyModifier':'kMidModifier', 'subdModifier':'kSubdModifier', \
                'curveInfo':'kCurveInfo', 'curveFromSurface':'kCurveFromSurface', \
                'surfaceShape': 'kSurface', 'revolvedPrimitive':'kRevolvedPrimitive', 'plane':'kPlane', 'curveShape':'kCurve', \
                'animCurve': 'kAnimCurve', 'resultCurve':'kResultCurve', 'cacheBase':'kCacheBase', 'filter':'kFilter',
                'blend':'kBlend', 'ikSolver':'kIkSolver', \
                'light':'kLight', 'renderLight':'kLight', 'nonAmbientLightShapeNode':'kNonAmbientLight', 'nonExtendedLightShapeNode':'kNonExtendedLight', \
                'texture2d':'kTexture2d', 'texture3d':'kTexture3d', 'textureEnv':'kTextureEnv', \
                'primitive':'kPrimitive', 'reflect':'kReflect', 'smear':'kSmear', \
                'plugin':'kPlugin', 'THdependNode':'kPluginDependNode', 'THlocatorShape':'kPluginLocatorNode', 'pluginData':'kPluginData', \
                'THdeformer':'kPluginDeformerNode', 'pluginConstraint':'kPluginConstraintNode', \
                'unknown':'kUnknown', 'unknownDag':'kUnknownDag', 'unknownTransform':'kUnknownTransform',\
                'xformManip':'kXformManip', 'moveVertexManip':'kMoveVertexManip', # creating these 2 crash Maya 
                'dynBase': 'kDynBase', 'polyPrimitive': 'kPolyPrimitive','nParticle': 'kNParticle', 'birailSrf': 'kBirailSrf', 'pfxGeometry': 'kPfxGeometry', } # Reserved types that crash when            

    # filter to make sure all these types exist in current version (some are Maya2008 only)
    ReservedMayaTypes ( dict( (item[0], item[1]) for item in filter(lambda i:i[1] in ApiTypesToApiEnums(), reservedTypes.iteritems()) ) )
    # build reverse dict
    ReservedApiTypes ( dict( (item[1], item[0]) for item in ReservedMayaTypes().iteritems() ) )
    
    return ReservedMayaTypes(), ReservedApiTypes()

# some handy aliases / shortcuts easier to remember and use than actual Maya type name
class ShortMayaTypes(dict) :
    __metaclass__ =  metaStatic
    
ShortMayaTypes({'all':'base', 'valid':'base', 'any':'base', 'node':'dependNode', 'dag':'dagNode', \
                'deformer':'geometryFilter', 'weightedDeformer':'weightGeometryFilter', 'geometry':'geometryShape', \
                'surface':'surfaceShape', 'revolved':'revolvedPrimitive', 'deformable':'deformableShape', \
                'curve':'curveShape' })                
                   
class MayaTypesToApiTypes(dict) :
    """ Lookup of currently existing Maya types as keys with their corresponding API type as values.
    Not a read only (static) dict as these can change (if you load a plugin)"""
    __metaclass__ = Singleton

class ApiTypesToMayaTypes(dict) :
    """ Lookup of currently existing Maya API types as keys with their corresponding Maya type as values.
    Not a read only (static) dict as these can change (if you load a plugin)
    In the case of a plugin a single API 'kPlugin' type corresponds to a tuple of types )"""
    __metaclass__ = Singleton
    
#: lookup tables for a direct conversion between Maya type to their MFn::Types enum
class MayaTypesToApiEnums(dict) :
    """Lookup from Maya types to API MFn::Types enums """
    __metaclass__ = Singleton
    
#: lookup tables for a direct conversion between API type to their MFn::Types enum 
class ApiEnumsToMayaTypes(dict) :
    """Lookup from API MFn::Types enums to Maya types """
    __metaclass__ = Singleton
 
# Cache API types hierarchy, using MFn classes hierarchy and additionnal trials
# TODO : do the same for Maya types, but no clue how to inspect them apart from parsing docs


#: Reserved API type hierarchy, for virtual types where we can not use the 'create trick'
#: to query inheritance, as of 2008 types and API types seem a bit out of sync as API types
#: didn't follow latest Maya types additions...
class ReservedApiHierarchy(dict) :
    __metaclass__ =  metaStatic
ReservedApiHierarchy({ 'kNamedObject':'kBase', 'kDependencyNode':'kNamedObject', 'kDagNode':'kDependencyNode', \
                    'kConstraint':'kTransform', 'kField':'kTransform', \
                    'kShape':'kDagNode', 'kGeometric':'kShape', 'kDeformFunc':'kShape', 'kClusterFilter':'kWeightGeometryFilt', \
                    'kDimension':'kShape', \
                    'kCreate':'kDependencyNode', 'kPolyCreator':'kDependencyNode', \
                    'kMidModifier':'kDependencyNode', 'kSubdModifier':'kDependencyNode', \
                    'kCurveInfo':'kCreate', 'kCurveFromSurface':'kCreate', \
                    'kSurface':'kGeometric', 'kRevolvedPrimitive':'kGeometric', 'kPlane':'kGeometric', 'kCurve':'kGeometric', \
                    'kAnimCurve':'kDependencyNode', 'kResultCurve':'kAnimCurve', 'kCacheBase':'kDependencyNode' ,'kFilter':'kDependencyNode', \
                    'kBlend':'kDependencyNode', 'kIkSolver':'kDependencyNode', \
                    'kLight':'kShape', 'kNonAmbientLight':'kLight', 'kNonExtendedLight':'kNonAmbientLight', \
                    'kTexture2d':'kDependencyNode', 'kTexture3d':'kDependencyNode', 'kTextureEnv':'kDependencyNode', \
                    'kPlugin':'kBase', 'kPluginDependNode':'kDependencyNode', 'kPluginLocatorNode':'kLocator', \
                    'kPluginDeformerNode':'kGeometryFilt', 'kPluginConstraintNode':'kConstraint', 'kPluginData':'kData', \
                    'kUnknown':'kDependencyNode', 'kUnknownDag':'kDagNode', 'kUnknownTransform':'kTransform',\
                    'kXformManip':'kTransform', 'kMoveVertexManip':'kXformManip' })  

apiTypeHierarchy = {}

def ApiTypeHierarchy() :
    return apiTypeHierarchy

# get the API type from a maya type
def mayaTypeToApiType(mayaType) :
    """ Get the Maya API type from the name of a Maya type """
    try:
        return MayaTypesToApiTypes()[mayaType]
    except KeyError:
        apiType = 'kInvalid'
        # Reserved types must be treated specially
        if ReservedMayaTypes().has_key(mayaType) :
            # It's an abstract type            
            apiType = ReservedMayaTypes()[mayaType]
        else :
            # we create a dummy object of this type in a dgModifier
            # as the dgModifier.doIt() method is never called, the object
            # is never actually created in the scene
            obj = MObject() 
            dagMod = MDagModifier()
            dgMod = MDGModifier()
            #if mayaType == 'directionalLight': print "MayaTypesToApiTypes", "directionalLight" in MayaTypesToApiTypes().keys(), len(MayaTypesToApiTypes().keys())
            obj = _makeDgModGhostObject(mayaType, dagMod, dgMod)
            if isValidMObject(obj):
                apiType = obj.apiTypeStr()
        return apiType


def addMayaType(mayaType, apiType=None ) :
    """ Add a type to the MayaTypes lists. Fill as many dictionary caches as we have info for. 
    
        - MayaTypesToApiTypes
        - ApiTypesToMayaTypes
        - ApiTypesToApiEnums
        - ApiEnumsToApiTypes
        - MayaTypesToApiEnums
        - ApiEnumsToMayaTypes
    """


    if apiType is None:
        apiType = mayaTypeToApiType(mayaType)    
    if apiType is not 'kInvalid' :
        
        apiEnum = getattr( MFn, apiType )
        
        defType = ReservedMayaTypes().has_key(mayaType)
        
        MayaTypesToApiTypes()[mayaType] = apiType
        if not ApiTypesToMayaTypes().has_key(apiType) :
            ApiTypesToMayaTypes()[apiType] = { mayaType : defType }
        else :
            ApiTypesToMayaTypes()[apiType][mayaType] = defType
        
        # these are static and are build elsewhere
        #ApiTypesToApiEnums()[apiType] = apiEnum
        #ApiEnumsToApiTypes()[apiEnum] = apiType
        
        MayaTypesToApiEnums()[mayaType] = apiEnum
        if not ApiEnumsToMayaTypes().has_key(apiEnum) :
            ApiEnumsToMayaTypes()[apiEnum] = { mayaType : None }
        else:
            ApiEnumsToMayaTypes()[apiEnum][mayaType] = None 

def removeMayaType( mayaType ):
    """ Remove a type from the MayaTypes lists. 
    
        - MayaTypesToApiTypes
        - ApiTypesToMayaTypes
        - ApiTypesToApiEnums
        - ApiEnumsToApiTypes
        - MayaTypesToApiEnums
        - ApiEnumsToMayaTypes
    """
    try:
        apiEnum = MayaTypesToApiEnums().pop( mayaType )
    except KeyError: pass
    else:
        enums = ApiEnumsToMayaTypes()[apiEnum]
        enums.pop( mayaType, None )
        if not enums:
            ApiEnumsToMayaTypes().pop(apiEnum)
            ApiEnumsToApiTypes().pop(apiEnum)
    try:
        apiType = MayaTypesToApiTypes().pop( mayaType, None )
    except KeyError: pass
    else:
        types = ApiTypesToMayaTypes()[apiType]
        types.pop( mayaType, None )
        if not types:
            ApiTypesToMayaTypes().pop(apiType)
            ApiTypesToApiEnums().pop(apiType)
    
       

def _getMObject(nodeType, dagMod, dgMod) :
    """ Returns a queryable MObject from a given apiType or mayaType"""
    
    # cant create these nodes, some would crahs MAya also
    if ReservedApiTypes().has_key(nodeType) or ReservedMayaTypes().has_key(nodeType) :
        return None   

    if ApiTypesToMayaTypes().has_key(nodeType) :
        mayaType = ApiTypesToMayaTypes()[nodeType].keys()[0]
        #apiType = nodeType
    elif MayaTypesToApiTypes().has_key(nodeType) :
        mayaType = nodeType
        #apiType = MayaTypesToApiTypes()[nodeType]
    else :
        return None    
    
    return _makeDgModGhostObject(mayaType, dagMod, dgMod)


def _makeDgModGhostObject(mayaType, dagMod, dgMod):
    # we create a dummy object of this type in a dgModifier (or dagModifier)
    # as the dgModifier.doIt() method is never called, the object
    # is never actually created in the scene
    
    # Note that you need to call the dgMod/dagMod.deleteNode method as well - if we don't,
    # and we call this function while loading a scene (for instance, if the scene requires
    # a plugin that isn't loaded, and defines custom node types), then the nodes are still
    # somehow created, despite never explicitly calling doIt()
    if type(dagMod) is not MDagModifier or type(dgMod) is not MDGModifier :
        raise ValueError, "Need a valid MDagModifier and MDGModifier or cannot return a valid MObject"

    # Regardless of whether we're making a DG or DAG node, make a parent first - 
    # for some reason, this ensures good cleanup (don't ask me why...??)
    parent = dagMod.createNode ( 'transform', MObject())
    
    try:
        try :
            # Try making it with dgMod FIRST - this way, we can avoid making an
            # unneccessary transform if it is a DG node
            obj = dgMod.createNode ( mayaType )
        except RuntimeError:
            # DagNode
            obj = dagMod.createNode ( mayaType, parent )
            _logger.debug( "Made ghost DAG node of type '%s'" % mayaType )
        else:
            # DependNode
            _logger.debug( "Made ghost DG node of type '%s'" % mayaType )
            dgMod.deleteNode(obj)
    except:
        obj = MObject()

    dagMod.deleteNode(parent)

    if isValidMObject(obj) :
        return obj
    else :
        _logger.debug("Error trying to create ghost node for '%s'" %  mayaType)
        return None


# check if a an API type herits from another
# it can't b e done for "virtual" types (in ReservedApiTypes)
def _hasFn (apiType, dagMod, dgMod, parentType=None) :
    """ Get the Maya API type from the name of a Maya type """
    if parentType is None :
        parentType = 'kBase'
    # Reserved we can't determine it as we can't create the node, all we can do is check if it's
    # in the ReservedApiHierarchy
    if ReservedApiTypes().has_key(apiType) :
        return ReservedApiHierarchy().get(apiType, None) == parentType
    # Need the MFn::Types enum for the parentType
    if ApiTypesToApiEnums().has_key(parentType) :
        typeInt = ApiTypesToApiEnums()[parentType]
    else :
        return False
    # print "need creation for %s" % apiType
    obj = _getMObject(apiType, dagMod, dgMod, parentType) 
    if isValidMObject(obj) :
        return obj.hasFn(typeInt)
    else :
        return False
 

# Filter the given API type list to retain those that are parent of apiType
# can pass a list of types to check for being possible parents of apiType
# or a dictionnary of types:node to speed up testing
def _parentFn(apiType, dagMod, dgMod, *args, **kwargs) :
    """ Checks the given API type list, or API type:MObject dictionnary to return the first parent of apiType """
    if not kwargs :
        if not args :
            args = ('kBase', )
        kwargs = dict( (args[k], None) for k in args )
    else :
        for k in args :
            if not kwargs.has_key(k) :
                kwargs[k] = None
    # Reserved we can't determine it as we can't create the node, all we can do is check if it's
    # in the ReservedApiHierarchy
    if ReservedApiTypes().has_key(apiType) :
        p = ReservedApiHierarchy().get(apiType, None)
        if p is not None :
            for t in kwargs.keys() :
                if p == t :
                    return t
        return None

    result = None           
    obj = kwargs.get(apiType, None)        
    if not isValidMObject(obj) :
        # print "need creation for %s" % apiType
        obj = _getMObject(apiType, dagMod, dgMod)
    if isValidMObject(obj) :
        if not kwargs.get(apiType, None) :
            kwargs[apiType] = obj          # update it if we had to create
        parents = []
        for t in kwargs.keys() :
            # Need the MFn::Types enum for the parentType
            if t != apiType :
                if ApiTypesToApiEnums().has_key(t) :
                    ti = ApiTypesToApiEnums()[t]
                    if obj.hasFn(ti) :
                        parents.append(t)
        # problem is the MObject.hasFn method returns True for all ancestors, not only first one
        if len(parents) :
            if len(parents) > 1 :
                for p in parents :
                    if ApiTypesToApiEnums().has_key(p) :
                        ip = ApiTypesToApiEnums()[p]
                        isFirst = True
                        for q in parents :
                            if q != p :
                                stored = kwargs.get(q, None)
                                if not stored :
                                    if ReservedApiTypes().has_key(q) :
                                        isFirst = not ReservedApiHierarchy().get(q, None) == p
                                    else :                                    
                                        stored = _getMObject(q, dagMod, dgMod)
                                        if not kwargs.get(q, None) :
                                            kwargs[q] = stored          # update it if we had to create                                        
                                if stored :
                                    isFirst = not stored.hasFn(ip)
                            if not isFirst :
                                break
                        if isFirst :
                            result = p
                            break
            else :
                result = parents[0]
                                 
    return result

def _createNodes(dagMod, dgMod, *args) :
    """pre-build a apiType:MObject, and mayaType:apiType lookup for all provided types, be careful that these MObject
        can be used only as long as dagMod and dgMod are not deleted"""

    result = {}
    mayaResult = {}
    unableToCreate = set()
    
        
    for mayaType in args :
        if ReservedMayaTypes().has_key(mayaType) :
            apiType = ReservedMayaTypes()[mayaType]
            #print "reserved", mayaType, apiType
            mayaResult[mayaType] = apiType
            result[apiType] = None
      
        else :
            obj = _makeDgModGhostObject(mayaType, dagMod, dgMod)
            if obj :
                apiType = obj.apiTypeStr()
                mayaResult[mayaType] = apiType
                result[apiType] = obj
            else:
                unableToCreate.add(mayaType)
    return result, mayaResult, unableToCreate

# child:parent lookup of the Maya API classes hierarchy (based on the existing MFn class hierarchy)
# TODO : fix that, doesn't accept the Singleton base it seems
# class ApiTypeHierarchy(FrozenTree) :
#    """ Hierarchy Tree of all API Types """
#    __metaclass__ = Singleton

def _buildApiTypesList():
    """the list of api types is static.  even when a plugin registers a new maya type, it will be associated with 
    an existing api type"""
    
    ApiTypesToApiEnums().clear()
    ApiEnumsToApiTypes().clear()
    
    ApiTypesToApiEnums( dict( inspect.getmembers(MFn, lambda x:type(x) is int)) )
    ApiEnumsToApiTypes( dict( (ApiTypesToApiEnums()[k], k) for k in ApiTypesToApiEnums().keys()) )

    #apiTypesToApiEnums = dict( inspect.getmembers(MFn, lambda x:type(x) is int)) 
    #apiEnumsToApiTypes = dict( (ApiTypesToApiEnums()[k], k) for k in ApiTypesToApiEnums().keys()) 
    #return apiTypesToApiEnums, apiEnumsToApiTypes
    
## Initialises MayaTypes for a faster later access
#def _buildMayaTypesList() :
#    """Updates the cached MayaTypes lists """
#    start = time.time()
#    from maya.cmds import ls as _ls
#    # api types/enums dicts must be created before reserved type bc they are used for filtering
#    _buildMayaReservedTypes()
#    
#    # use dict of empty keys just for faster random access
#    # the nodes returned by ls will be added by createPyNodes and pluginLoadedCB
#    # add new types
#    print "reserved types", ReservedMayaTypes()
#    for mayaType, apiType in ReservedMayaTypes().items() + [(k, None) for k in _ls(nodeTypes=True)]:
#         #if not MayaTypesToApiTypes().has_key(mayaType) :
#         addMayaType( mayaType, apiType )
#    elapsed = time.time() - start
#    print "Updated Maya types list in %.2f sec" % elapsed


# Build a dictionnary of api types and parents to represent the MFn class hierarchy
def _buildApiTypeHierarchy(apiClassInfo=None) :
    """
    Used to rebuild api info from scratch.
    
    Set 'apiClassInfo' to a valid apiClassInfo structure to disable rebuilding of apiClassInfo
    - this is useful for versions < 2009, as these versions cannot parse the api docs; by passing
    in an apiClassInfo, you can rebuild all other api information.  If left at the default value
    of 'None', then it will be rebuilt using the apiDocParser.
    """
    def _MFnType(x) :
        if x == MFnBase :
            return ApiEnumsToApiTypes()[ 1 ]  # 'kBase'
        else :
            try :
                return ApiEnumsToApiTypes()[ x().type() ]
            except :
                return ApiEnumsToApiTypes()[ 0 ] # 'kInvalid'
    
    #global apiTypeHierarchy, ApiTypesToApiClasses
    _buildMayaReservedTypes()
    
    if not mayahook.mayaIsRunning():
        mayahook.mayaInit()
    import maya.cmds
    
    # load all maya plugins
    mayaLoc = mayahook.getMayaLocation()
    # need to set to os.path.realpath to get a 'canonical' path for string comparison...
    pluginPaths = [os.path.realpath(x) for x in os.environ['MAYA_PLUG_IN_PATH'].split(os.path.pathsep)]
    for pluginPath in [x for x in pluginPaths if x.startswith( mayaLoc ) and os.path.isdir(x) ]:
        for x in os.listdir( pluginPath ):
            if os.path.isfile( os.path.join(pluginPath,x)):
                try:
                    maya.cmds.loadPlugin( x )
                except RuntimeError: pass

    allMayaTypes = ReservedMayaTypes().keys() + maya.cmds.ls(nodeTypes=True)
    
    apiTypesToApiClasses = {}
    
    # all of maya OpenMaya api is now imported in module api's namespace
    MFnClasses = inspect.getmembers(_thisModule, lambda x: inspect.isclass(x) and issubclass(x, MFnBase))
    MFnTree = inspect.getclasstree( [x[1] for x in MFnClasses] )
    MFnDict = {}
    
    for x in expandArgs(MFnTree, type='list') :
        MFnClass = x[0]
        current = _MFnType(MFnClass)
        if current and current != 'kInvalid' and len(x[1]) > 0:
            #Check that len(x[1]) > 0 because base python 'object' will have no parents...
            parent = _MFnType(x[1][0])
            if parent:
                apiTypesToApiClasses[ current ] = MFnClass
                #ApiTypesToApiClasses()[ current ] = x[0]
                MFnDict[ current ] = parent
    
    if apiClassInfo is None:
        from pymel.mayahook.parsers import ApiDocParser
        apiClassInfo = {}
#        try:
        parser = ApiDocParser(_thisModule)
#        except IOError, msg: 
#            _logger.warn( "failed to find docs for current version: %s", name )
            
        for name, obj in inspect.getmembers( _thisModule, lambda x: type(x) == type and x.__name__.startswith('M') ):
            if not name.startswith( 'MPx' ):
                
                try:
                    try:
                        info = parser.parse(name)
                        apiClassInfo[ name ] = info
                    except IOError:
                        _logger.warn( "failed to parse docs: %s", name )

                except (ValueError,IndexError), msg: 
                    _logger.warn( "failed %s %s" % ( name, msg ) )
                    
    # print MFnDict.keys()
    # Fixes for types that don't have a MFn by faking a node creation and testing it
    # Make it faster by pre-creating the nodes used to test
    dagMod = MDagModifier()
    dgMod = MDGModifier()      
    #nodeDict = _createNodes(dagMod, dgMod, *ApiTypesToApiEnums().keys())
    nodeDict, mayaDict, unableToCreate = _createNodes( dagMod, dgMod, *allMayaTypes )
    if len(unableToCreate) > 0:
        _logger.warn("Unable to create the following nodes: %s" % ", ".join(unableToCreate))
    
    for mayaType, apiType in mayaDict.items() :
        MayaTypesToApiTypes()[mayaType] = apiType
        addMayaType( mayaType, apiType )
    
    # Fix? some MFn results are not coherent with the hierarchy presented in the docs :
    MFnDict.pop('kWire', None)
    MFnDict.pop('kBlendShape', None)
    MFnDict.pop('kFFD', None)
    for k in ApiTypesToApiEnums().keys() :
        if k not in MFnDict.keys() :
            #print "%s not in MFnDict, looking for parents" % k
            #startParent = time.time()
            p = _parentFn(k, dagMod, dgMod, **nodeDict)
            #endParent = time.time()
            if p :
                #print "Found parent: %s in %.2f sec" % (p, endParent-startParent)
                MFnDict[k] = p
            else :
                #print "Found none in %.2f sec" % (endParent-startParent)     
                pass         
                                       
    # print MFnDict.keys()
    # make a Tree from that child:parent dictionnary

    # assign the hierarchy to the module-level variable
    apiTypeHierarchy = IndexedFrozenTree(treeFromDict(MFnDict))
    return apiTypeHierarchy, apiTypesToApiClasses, apiClassInfo

def _buildApiCache(rebuildAllButClassInfo=False):
    """
    Used to rebuild api cache, either by loading from a cache file, or rebuilding from scratch.
    
    Set 'rebuildAllButClassInfo' to True to force rebuilding of all info BUT apiClassInfo -
    this is useful for versions < 2009, as these versions cannot parse the api docs; by setting
    this to False, you can rebuild all other api information.
    """        

    apiToMelData, apiClassOverrides = loadApiToMelBridge()
    
    # Need to initialize this to possibly pass into _buildApiTypeHierarchy, if rebuildAllButClassInfo
    apiClassInfo = None
    
    data = mayahook.loadCache( 'mayaApi', 'the API cache', compressed=False )
    if data is not None:
        
        ReservedMayaTypes(data[0])
        ReservedApiTypes(data[1])
        ApiTypesToApiEnums(data[2])
        ApiEnumsToApiTypes(data[3])
        MayaTypesToApiTypes(data[4])
        ApiTypesToApiClasses(data[5])
        apiTypeHierarchy = data[6]
        apiClassInfo = data[7]
        
        
        if not rebuildAllButClassInfo:
            # Note that even if rebuildAllButClassInfo, we still want to load
            # the cache file, in order to grab apiClassInfo
            return apiTypeHierarchy, apiClassInfo, apiToMelData, apiClassOverrides
            
    
    _logger.info( "Rebuilding the API Caches..." )
    
    # fill out the data structures
    _buildApiTypesList()
    #apiTypesToApiEnums, apiEnumsToApiTypes = _buildApiTypesList()
    #_buildMayaTypesList()
    
    if not rebuildAllButClassInfo:
        apiClassInfo = None
    apiTypeHierarchy, apiTypesToApiClasses, apiClassInfo = _buildApiTypeHierarchy(apiClassInfo=apiClassInfo)

    # merge in the manual overrides: we only do this when we're rebuilding or in the pymelControlPanel
    _logger.info( 'merging in dictionary of manual api overrides')
    util.mergeCascadingDicts( apiClassOverrides, apiClassInfo, allowDictToListMerging=True )

    mayahook.writeCache( ( dict(ReservedMayaTypes()), dict(ReservedApiTypes()), 
                           dict(ApiTypesToApiEnums()), dict(ApiEnumsToApiTypes()), 
                           dict(MayaTypesToApiTypes()), 
                           apiTypesToApiClasses, apiTypeHierarchy, apiClassInfo 
                          )
                         , 'mayaApi', 'the API cache' )
    
    return apiTypeHierarchy, apiClassInfo, apiToMelData, apiClassOverrides

# TODO : to represent plugin registered types we might want to create an updatable (dynamic, not static) MayaTypesHierarchy ?

def saveApiCache():
    mayahook.writeCache( ( dict(ReservedMayaTypes()), dict(ReservedApiTypes()), 
                           dict(ApiTypesToApiEnums()), dict(ApiEnumsToApiTypes()), 
                           dict(MayaTypesToApiTypes()), 
                           dict(ApiTypesToApiClasses()), apiTypeHierarchy, apiClassInfo 
                          )
                         , 'mayaApi', 'the API cache' )

def loadApiToMelBridge():

    data = mayahook.loadCache( 'mayaApiMelBridge', 'the api-mel bridge', useVersion=False, compressed=False )
    if data is not None:
        # maya 8.5 fix: convert dict to defaultdict
        bridge, overrides = data
        bridge = util.defaultdict(dict, bridge)
        return bridge, overrides
    
    # no bridge cache exists. create default
    bridge = util.defaultdict(dict)
    
    # no api overrides exist. create default
    overrides = {}
    
    return bridge, overrides

def saveApiToMelBridge():
    # maya 8.5 fix: convert defaultdict to dict
    bridge = dict(apiToMelData)
    mayahook.writeCache( (bridge,apiClassOverrides ), 'mayaApiMelBridge', 'the api-mel bridge', useVersion=False )


#-------------------------------------------------------------------------------------

_start = time.time()
apiTypeHierarchy, apiClassInfo, apiToMelData, apiClassOverrides = _buildApiCache(rebuildAllButClassInfo=False)

    
_elapsed = time.time() - _start
_logger.debug( "Initialized API Cache in in %.2f sec" % _elapsed )

#-------------------------------------------------------------------------------------

def toApiTypeStr( obj ):
    if isinstance( obj, int ):
        return ApiEnumsToApiTypes().get( obj, None )
    elif isinstance( obj, basestring ):
        return MayaTypesToApiTypes().get( obj, None)
    
def toApiTypeEnum( obj ):
    try:
        return ApiTypesToApiEnums()[obj]
    except KeyError:
        return MayaTypesToApiEnums().get(obj,None)

def toMayaType( obj ):
    if isinstance( obj, int ):
        return ApiEnumsToMayaTypes().get( obj, None )
    elif isinstance( obj, basestring ):
        return ApiTypesToMayaTypes().get( obj, None)
    
def toApiFunctionSet( obj ):
    if isinstance( obj, basestring ):
        try:
            return ApiTypesToApiClasses()[ obj ]
        except KeyError:
            return ApiTypesToApiClasses().get( MayaTypesToApiTypes().get( obj, None ) )
         
    elif isinstance( obj, int ):
        try:
            return ApiTypesToApiClasses()[ ApiEnumsToApiTypes()[ obj ] ]
        except KeyError:
            return

def getComponentTypes():
    # WTF is kMeshFaceVertComponent?? it doesn't inherit from MFnComponent,
    # and there's also a kMeshVtxFaceComponent (which does)??
    mfnCompBase = MFnComponent()
    mfnCompTypes = (MFnSingleIndexedComponent(),
                    MFnDoubleIndexedComponent(),
                    MFnTripleIndexedComponent())
    # Maya 2008 and before didn't haveMFnUint64SingleIndexedComponent
    if hasattr(MFn, 'kUint64SingleIndexedComponent'):
        mfnCompTypes += (MFnUint64SingleIndexedComponent(),)
    
    componentTypes = {}
    for compType in mfnCompTypes + (mfnCompBase,):
        componentTypes[compType.type()] = []

    for apiEnum in ApiEnumsToApiTypes():
        if mfnCompBase.hasObj(apiEnum):
            for compType in mfnCompTypes:
                if compType.hasObj(apiEnum):
                    break
            else:
                compType = mfnCompBase
            componentTypes[compType.type()].append(apiEnum)
                
    return componentTypes
