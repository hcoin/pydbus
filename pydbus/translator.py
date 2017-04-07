'''
Created on Feb 24, 2017

@author: Harry G. Coin
@copyright: 2017 Quiet Fountain LLC

When opening access to a dbus path, if you enable a dictionary for these
routines that describes anything special about it, all the dbus-specific issues
are invisibly managed so well it's very hard to tell the difference between a
local python method, property or signal vs. one handled by a partner over the
dbus. Given a well written translation spec, the user need know nothing further
about dbus operations.

For complete user and translation writer documentation, read here:

https://github.com/hcoin/pydbus/wiki
             

'''

# from exceptions import ValueError
from gi.repository.GLib import (Variant)  # ,VariantBuilder,VariantType)
from importlib import import_module
from ipaddress import (IPv4Address, IPv6Address, IPv4Network)
import re
from builtins import list
from cProfile import label




def _isolate_format(args):
    '''a helper function that breaks an introspection string
    into single variable instances. So a{sa{si}}u would
    return a{sa{si}} on the first call, and u on the second.
    when there is no further guidance, None is returned.
    '''
    if args == None: return (None, None)
    if len(args) == 0: return (None, None)
    if args[0] not in 'a({v':
        rem = args[1:]
        return (args[0], rem if len(rem) > 0 else None)
    if len(args) < 2: return (None, None)
    if args[0] == 'a':
        next_arg, remainder = _isolate_format(args[1:])
        return ('a' + next_arg, remainder)
    if args[0] == 'v':
        level = 1
        index = 2
        next_arg = 'v:'
        while (level > 0) and (index < len(args)):
            if args[index] == 'v': level += 2
            elif args[index] == ':': level -= 1
            next_arg += args[index]
            index += 1
        if level != 0: next_arg += ':'  # 'defensive programming 101'
        return (next_arg, args[index:])
    next_arg = args[0]  # '( or {'
    target = ')' if args[0] == '(' else '}' 
    inner_arg = ' '
    pattern = args[1:]
    while inner_arg != target:
        inner_arg, remainder = _isolate_format(pattern)
        next_arg += inner_arg
        pattern = remainder
    return (next_arg, remainder)



            
class DataFlowGuidance(object):
#    Here we transform everything in the user translation definition
#    about a specific dbus path and key into usable guidance.
    def __init__(self, keyname):
        self.key_for_this_dbus_path = keyname
        
    def init_helper_validate_arglistspec(self, lsg:list, \
                                           from_python_to_dbus:bool) -> bool:
        '''Return validated guidance instances.
        
        Given the list of per path/per key translation specs which support a
        single flow direction, replace the spec with a validated, optimized guidance
        structure.  Return True if at least one item has active translations.
        
        Add the translation writer convenience of turning single argument simple
        specifications as if passed as a one-item specification dictionary.'''
        
        got_one = False
        list_of_direction_specific_guidance = [ None for i in range(0, len(lsg)) ]
        if from_python_to_dbus:
            self.to_dbus_guidance = list_of_direction_specific_guidance
        else:
            self.from_dbus_guidance = list_of_direction_specific_guidance
        self.original_guidance_list = list(lsg)
        for i in range(0, len(self.original_guidance_list)): 
            if self.original_guidance_list[i] != None: 
                if not isinstance(self.original_guidance_list[i], dict) : 
                    # here we provide a convenience for one-argument methods/signals and all properties
                    # just use the value as what is to be done with argument 0, instead of forcing
                    # everyone to add { 0 : arg0action } when all that's needed is an action for 1 arg.
                    self.original_guidance_list[i] = {0:self.original_guidance_list[i]}
                got_one_arg = False
                arglist = ArgSpecGuidance()
                list_of_direction_specific_guidance[i] = arglist
                self.dbus_side_argument_list_size=0
                for arg_position_index, arg_specific_translation_spec in self.original_guidance_list[i].items():
                    if isinstance(arg_position_index, int): 
                        got_one_arg = True
                        arg_guidance = SingleArgumentOptimizedGuidance(arg_specific_translation_spec, arg_position_index, from_python_to_dbus)
                        arglist.arguments[arg_position_index] = arg_guidance
                        arglist.overall_variant_expansion_list += arg_guidance.local_variant_expansion_list
                        if self.dbus_side_argument_list_size < arg_position_index:
                            self.dbus_side_argument_list_size = arg_position_index
                        if arg_guidance.all_arguments: arglist.all_arguments_in_one_call = True

                        # This one is a little special in that we have a usage dependent
                        # default that can be forced to a specified value.  However,
                        # True specifications over-ride any False specifications.
                        if arg_guidance.new_return_instance == None:
                            arglist.new_return_instance = arg_guidance.new_return_instance
                        else:
                            if arg_guidance.new_return_instance:
                                arglist.new_return_instance = True
                                
                        if arg_guidance.attributename: 
                            arglist.associate_position_with_name(arg_guidance.attributename, arg_position_index, True)
                        if arg_guidance.dictkey:
                            arglist.associate_position_with_name(arg_guidance.dictkey, arg_position_index, False)
                        if arglist.python_side_named_args_as_dict and arglist.python_side_named_args_as_object_attributes:
                            raise ValueError("Arguments must be either passed as one of a list, a dict or object attributes, not both for key " + self.key_for_this_dbus_path)
                if got_one_arg == False:
                    # There has to be at least one argument position defined
                    # or it's the same as no spec at all.
                    list_of_direction_specific_guidance[i] = None
                else:
                    got_one = True
        return got_one
    

class ArgSpecGuidance(object):
    def __init__(self):
        # The expansion of variants is variable by
        # specific key, call, and call direction
        self.overall_variant_expansion_list = []
        self.arguments = {}
        self.all_arguments_in_one_call = False
        self.python_side_named_args_as_dict = False
        self.python_side_named_args_as_object_attributes = False
        self.dbus_side_argument_list_size = -1
        self.arg_position_from_name = {}
        self.arg_name_from_position = {}
        self.new_return_instance = None
        self.overall_variant_expansion_list = [] 
    
    def associate_position_with_name(self, name, position, is_attribute):
        self.arg_position_from_name[name] = position
        self.arg_name_from_position[position] = name
        if is_attribute:
            self.python_side_named_args_as_object_attributes = True
        else:
            self.python_side_named_args_as_dict = True


class SingleArgumentOptimizedGuidance(object):
    '''A container holding guidance ready for argument processing.
    
    This is a container holding a guidance for one argument
    either in the to or from dbus/python direction of a specific
    signal, property or method n optimized result.'''
         
    def __init__(self, arg, arg_position_index, direction_is_from_python_to_dbus):
        '''Return a optimized, validated translation guidance from an argument spec.
        
        Here we receive a translation specification for a specific dbus path, and
        for a specific key on that path, and for a specific method, signal or property,
        and whether we are translating from python to dbus, or dbus to python.
        
        Validate the translation spec, then return a guidance structure optimized
        for the particular use.  Does not alter anything in the translation spec.'''
    
        self.arg_position_index = arg_position_index
        self.direction_is_from_python_to_dbus = direction_is_from_python_to_dbus
        self.local_variant_expansion_list=[]
        
        self.auto_container_active = False
        # If true, and any convencience feature is used, during argument processing
        #   if a list, tuple or dict is encountered, behave as though
        #   this specfication was meant for the list or dict values.

        if isinstance(arg, tuple) or isinstance(arg, list):
            # lists or tuples here are syntax sugar
            # for the equivalent dictionary where the
            # index is the key and the content the value.
            # make the dictionary.
            arg = { i : arg[i] for i in range(0, len(arg)) }
            arg["_from_python_to_dbus"] = False
            self.auto_container_active = True
                
        elif not isinstance(arg, dict):
            # This is just a name for the variable.
            arg = { '_dictkey' : str(arg) }
            
        # arg is a translation dictionary, process it into an 
        # optimized guidance structure instance.

        # What to do here depends a lot on the content.  Do common attribute 
        # extraction and validation.
        special_names = ("_is_bitfield", "_from_python_to_dbus", "_dictkey", "_attributename",
                    "_show_all_names", "_return_as_list", "_container", "_container_keys",
                    "_match_to_function", "_all_arguments", "_variant_expansion",
                    "_replace_unknowns", "_forced_replacement", "_default", "_new_return_instance",
                    "_arg_format")
        for s in special_names:
            # trim the leading _ we put there to avoid conflicting with user argument names,
            # then create attributes in our optimized spec for all possible flags at
            # this level.
            setattr(self, s[1:], arg.get(s, False))
        self.new_return_instance = None  # We require the guidance to specify a non-default.
        self.force_replacement_specified = "_forced_replacement" in arg 
            
        if self.replace_unknowns:
            if not (isinstance(self.replace_unknowns, list) or isinstance(self.replace_unknowns, tuple)): 
                raise ValueError("The _replace_unknowns key must have a two value list or tuple value")
            if len(self.replace_unknowns) != 2:
                raise ValueError("The _replace_unknowns guidance must have two entries (<string>,<number>), not " + \
                                 str(self.replace_unknowns))
                
        if self.dictkey and self.attributename:
            raise ValueError("Argument format can't be both _dictkey and also _attributname")
        
        if self.arg_format == False: self.arg_format = 'dict'
        allowed_arg_formats = ('dict', 'list', 'shortlist', 'single', 'prettydict', 'prettylist')
        if self.arg_format not in allowed_arg_formats:
                raise ValueError("arg_format must be one of " + str(allowed_arg_formats))
        
        if self.all_arguments and (arg_position_index != 0) :
            raise ValueError("When causing all the arguments to be recast as if a tuple single argument, there can be only one arg spec.")
        
        # Do some basic syntax checks:
        if self.dictkey:
            if not isinstance(self.dictkey, str) or len(self.dictkey) < 1:
                raise ValueError("Names for argument positions as dictionary keys must be strings and not ''")
        if self.attributename:
            if not isinstance(self.attributename, str) or len(self.attributename) < 1:
                raise ValueError("Names for argument positions as attribute names must be strings and not ''")
            
        if self.variant_expansion:
            if not isinstance(self.variant_expansion, str) or len(self.variant_expansion) < 1:
                raise ValueError("Variant parsing guidance must be strings and not " + str(self.variant_expansion))
            self.local_variant_expansion_list = self.variant_expansion.split(',')
        

            
        if self.return_as_list not in (False, 'single', 'shortest', True):
                raise ValueError("_return as list must either omitted or be one of True, False, 'single','shortest'")
            
        
        # That's all the pre-processing we can do on spec parts that affect all the arguments. 
        # get the keys and values in k,v or v,k format expected owing to the
        # direction of this usage.
        # map values: 
        

        self.original_spec = []  # (tuples of (python side,dbus side)

        flip = self.from_python_to_dbus
        if self.match_to_function:
            flip = False
 
        for a, b in arg.items():
            if a in special_names: continue
            if self.force_replacement_specified:
                raise ValueError("Forcing a replacement implies no other argument interpretation should be included.")
            
            if flip:
                # otherwise, the arguments need flipping.
                self.original_spec += [(b, a)]
            else:
                self.original_spec += [(a, b)]
        # at this point, self.original_spec are tuples in the order dbus,python
        
        if self.match_to_function:
            self.compiled_re = {}
            for match, function in self.original_spec:
                try:
                    cre = re.compile(match)
                    self.compiled_re[match]= [cre, function, None]
                except:
                    self.compiled_re[match] = [None, function,None]
                if not callable(function):
                    try:
                        self.compiled_re[match][2] = import_module(function[0])
                        self.compiled_re[match][1] = eval('self.compiled_re[match][2].'+function[1])
                    except:
                        raise ValueError("Match functions must be callable or (a,b): m=import_module(a), callable(eval('m.'+b)")
                    if not callable(self.compiled_re[match][1]):           
                        raise ValueError("Match module " + str(function[0]) + " object " + str(function[1]) + "  found, but not callable.")
        
                
        # and now we're off to the races. Optimize the
        # guidance with the intention of the particular spec.
        self.map = {} 
        # When the following is done, this will hold, more or less
        # map(the argument have) --> the thing we want to return.

        # Remove when there are more options beyond 1 <--> maps and bitfields requring
        # the processing of processing specific details.
        self.is_one_to_one_map = (not self.match_to_function) and (not self.is_bitfield) and (len(self.original_spec) > 0)

            
        if self.is_bitfield:
                self.init_helper_guidance_validate_bitfield(direction_is_from_python_to_dbus)
        elif self.is_one_to_one_map:
                self._init_helper_validate_one_to_one_map(direction_is_from_python_to_dbus)
        else:  # Set no changes to this arg (but it might be named)
            self.map = None
                    



    def _init_helper_validate_one_to_one_map(self,direction_is_from_python_to_dbus):
        for dbus, python in self.original_spec:
            #python , dbus = (a , b) if direction_is_from_python_to_dbus else (b, a)
            if not isinstance(dbus, int):
                raise ValueError("All dbus values in number-means-label maps must be ints, not " + str(dbus))
            if not isinstance(python, str):
                raise ValueError("Names for labels in number-means-label maps must be strings, not " + str(python))
            if self.direction_is_from_python_to_dbus: 
                self.map[python.upper()] = dbus 
            else:
                self.map[dbus] = python
        
    def init_helper_guidance_validate_bitfield(self,direction_is_from_python_to_dbus):
        '''Validate and optimize the bitfield specification line items, set guidance.map.''' 

        self.wants_everything_else = False
        # Bitfields have an optional variable to mean 'everything not otherwise mentioned.'
        # By default, false.  Set it if we find it.
        for dbus,python in self.original_spec:
            #python , dbus = (a , b) if direction_is_from_python_to_dbus else (b, a)
            # python=line_item[0]
            # dbus=line_item[1]
            
            # Validate the dbus/bits side:
            if isinstance(dbus, tuple) or isinstance(dbus, list):
                # Set up for both on checking and off checking.
                # Can't be 'everything else'
                if len(dbus) != 2:
                    raise ValueError("bitfield mask specifications must be 1 or 2 ints, or '#everything_else', not : " + str(dbus))
                offbits = dbus[0]
                onbits = dbus[1]
            elif isinstance(dbus, str):
                if dbus.upper() != '#EVERYTHING_ELSE':
                    raise ValueError("The only string allowed in the number area of a bitfield is #everything_else, not " + dbus)
                self.wants_everything_else = True
                offbits = None
                onbits = None
            else:
                if not isinstance(dbus, int):
                    raise ValueError("Single value bitfield numbers must be either ints or #everything_else")
                offbits = None
                onbits = dbus
                
            # Validate type of variable & name(s)
            if isinstance(python, list) or isinstance(python, tuple):
                self.treat_as_mask = False  # treat these possibly consecutive bits like
                # index onto this list of labels
                label_value = 0
                for s in python:  # walk the labels
                    if not isinstance(s, str):
                        raise ValueError("bitfield list members names must all be strings, not: " + str(python))
                    if len(s) < 1:
                        raise ValueError("bitfield list member names must not be empty.")
                    if s[0] == '#':
                        raise ValueError("Only non-list, single variables as ints can lead with #, not " + s)
                    if self.direction_is_from_python_to_dbus: 
                        # case insensitive matching
                        s = s.upper()
                    # Create a map based on off/on bits so the final off/on mask associates
                    # label s according to its list position, with index composed of the
                    # on bits as a number ignoring any gaps between onbit positions. 
                    # So: onbits b101 label 2 would be index 2, the final onbits would be then
                    # old | b100 and the offbits would be old | b1
                    self.map[s] = self._bitfield_entry(offbits, onbits, s, True, label_value)
                    label_value += 1
                    # ##setattr(guidance,"label_tuple",label_tuple)
            elif isinstance(python, str):
                if self.direction_is_from_python_to_dbus: python = python.upper()
                if len(python) < 1:
                    raise ValueError("bitfield label names can't be empty.")
                if python[0] == '#':
                    if len(python) < 2:
                        raise ValueError("bitfield label names for ints '#...' can't be empty.")
                    # ##               setattr(guidance."_treat_as_mask",False) #treat these possibly consecutive bits like an int
                    python = python[1:]
                    self.map[python] = self._bitfield_entry(offbits, onbits, python, True)
                else:
                    self.map[python] = self._bitfield_entry(offbits, onbits, python, False)
                    
 

    
    class _bitfield_entry(object):
        '''set up and execute bit level label <--> bitmask int operations.'''
        def __init__(self, offbits_arg:int, onbits_arg:int, label:str, treat_as_int:bool=False, label_value=None):
            self.offbits = offbits_arg
            self.onbits = onbits_arg
            self.label = label
            self.is_zero_test = (self.offbits == -1) and (self.onbits == 0)
            self.treat_as_int = treat_as_int
            
            if self.offbits != None and (self.offbits & self.onbits != 0):
                raise ValueError("It's an error to require the same bit to be both on and off to match: " + format(self.onbits, "x") + ' ' + format(self.offbits, 'x'))
            
            # If this is used for a pure bit-for-bit mask based match, we are done.
            if self.treat_as_int == False: return
            # If we have a label, we want to turn a mini-int,
            # onbits off bits combinantion into 
            # The on and off bits are fixed for non-mini-ints.
            # But for bit patterns used as mini-ints, (label value==None)
            # And for bit patterns which are to create 
            # label_list[mini_int] <--> label
            # we have to do similar work. First,
            # save the runtime code from shifting through on bits
            # we know we don't care about.

            self.bitcount_lsb_to_first_onbit = 0
            self.onbits_no_leading_0s = self.onbits
            self.label_value = label_value  # probably could have left this out, but good for debugging.
            while (self.onbits_no_leading_0s & 1 == 0): 
                self.bitcount_lsb_to_first_onbit += 1
                self.onbits_no_leading_0s >>= 1
            
            # if this is a to map a label onto a mini-int, there's not much more
            # we can do to validate and/or optimize it. But...
            if label_value != None:
                
                # -- This isn't to be treated as a number, but as an index onto a
                # -- list of      labels. Since we know what index goes with what
                # - label, save lots of work later by converting this to a simple
                # pure off / on bits <--> label match. Go use the routine accessed
                # during runtime calls when going from a python mini-int to dbus.

                test, self.onbits, self.offbits = self.int_bitmask_and_value(label_value, False)  # @UnusedVariable

                self.treat_as_int = False
                
                
                

        def mask_test(self, target):
            '''True iif the right bits in target are on and maybe off.'''
            #ret = False
            if self.offbits != None:  # If there are bits that must be off, check them.
                if (target & self.offbits) != 0: return False
            #    ret = True # We've been asked to test for offbits, and they're off.
            if self.treat_as_int: 
                # in this case, it's legal for none to all of the on-bits to be anything,
                # so we match.
                return True
            # all the 'on bits' must match.
            if (target & self.onbits) != self.onbits: return False
            return True
        
        def bits_tested(self):
            '''Return the bits used by this test.
            
            We use this to support the 'everything_else' option.'''
            
            if self.is_zero_test: return 0
            
            #---------------- We don't count the zero test (-1,0) as referencing
            #----------- all the bits, thought it does mathematically.  Software
            #------- tends to use 'all zeros' in sets of bit-mapped on/off flags
            #--------- to have a meaning that's an inference made when all flags
            #--------- are 0 , more than what each flag off means.  For example,
            #----------- We see things like red_light_on 0x1, blue_light_on 0x2,
            #---------------------------------------- 'The room is dark' <--> 0.
            v = self.onbits if self.onbits else 0
            if self.offbits: v |= self.offbits
            return v
               
        
        def int_bitmask_and_value(self, val, to_mini_int=True):
            '''Use dbus and mask information to compute a mini-int/index value.'''
            
#==============================================================================
#            Easiest to explain by example.
#             
#            When the onbits are consecutive: from dbus
#            'and' with onbits, then shift right both until
#            the lowest onbit is in the 0 bit position.
#            Treat the 'onbits' as though its own integer
#            within an integer with more bits. From python
#            shift left the same number, then and with onbits.
#             
#            All 1/0 values binary. dc=don't care.
#            onbits   fromdbus topython |frompython todbus
#            1           1         1         1        1
#            1           0         0         0        0
#            0           dc        0         dc       0
#            11          10        10        10      10
#            11          11        11        11      11
#            110         110       11        11     110
#            10          10        1         1       10
# 
#              
#            But, when onbits are not consecutive, treat
#            0 onbits between two 1 onbits as if that bit
#            position did not exist at all.
#            101         111       11        11     101
#            10011       11        11        11      11
#            10011       10010     110      110     10010
#            10001       10001     11        11     10001
#             
#            Why? There are thousands of hardware device register specifications
#            wherein a high order bit changes the meaning of the lower order bits
#            to an extended or related aspect of their meaning with the high
#            order bit was 0.  This schema allows one translation specification
#            to give different labels to the same low order bits depending on the
#            state of the higher order bit.
#==============================================================================
            
                        
            #--------------- At init time, we want the target from the mini-int.
            #----------- At translate time, we want the mini int from the target
            #--------------------------- It's almost the same code, so do it all
            #------------------------------------------------------------- here.
            
            if to_mini_int:
                target = val
                mini_int = 0
            else:
                target = 0
                mini_int = val
            
            if self.treat_as_int == False: return 0

            
            # Move the first bit of target we care about into the lsb position.

            target >>= self.bitcount_lsb_to_first_onbit
             
            # Also capture the first bit of the onbits mask we care about into the same spot.

            current_onbit_mask = self.onbits_no_leading_0s 

            #===================================================================
            # Use current_wholeint_multiple to track the bits that must be on and
            # must be off so we can build a modified onbits and offbits mask
            # specific to this target. That way, we can create a simple
            # onbits/offbits mask to associate with a label and not recompute this
            # each trip over the bus.
            #===================================================================

            current_wholeint_multiple = 1 << self.bitcount_lsb_to_first_onbit

            # start with the definition of what the maximum value for the
            # target is in terms of onbits and offbits.            
            current_onbits = self.onbits  # we might be turning some of these off.
            current_offbits = self.offbits if self.offbits != None else 0  # We turn the matching one of these on if so.
            
            # We build our integer offset result one bit at a time, keep track
            # of which bit is current here.  It is advanced only on bits we care about.
            current_mini_int_multiple = 1 
            
            # We set about shifting the mask and target right, considering
            # what's in the lsb position to decide what to do next.
            while current_onbit_mask != 0:
                #===============================================================
                # if there's no more onbits, we don't care about what's left in the target.
                # as we're not going to be modifying any other mask positions.
                # We still may have work to do even if there are no more
                # bits on in the target.
                #===============================================================
                if current_onbit_mask & 1:  # We care about this bit.
                    if to_mini_int:
                        if target & 1 != 0:
                            # include this result in the result/offset 'mini-int'.
                            mini_int |= current_mini_int_multiple
                            # that's all we need to do since the bit is already on and off
                            # in the right spots in the masks.
                        else:
                            #===================================================
                            # Here we have a bit in the mask we care about that is off
                            # in this particular target.  Mark it as a required off-bit,
                            # and remove it from the required on-bits for this particular
                            # mini-int.
                            #===================================================
                            current_offbits |= current_wholeint_multiple
                            current_onbits &= (~current_wholeint_multiple)  
                    else: 
                        # build dbus target from mini-int
                        if mini_int & 1: 
                            # Turn this value on in the target.
                            target |= current_wholeint_multiple
                            # on in the onbits
                            current_onbits |= current_wholeint_multiple
                            # off in the offbits
                            current_offbits &= (~current_wholeint_multiple)
                        else:
                            # It's already off in the target
                            # off on the onbits
                            current_onbits &= (~current_wholeint_multiple)
                            # on in the offbits
                            current_offbits |= current_wholeint_multiple
                            
                        
                    # Since we cared about this bit, it was part of the return value
                    # index offset, whether or not it is on or off in the target. Set the
                    # next one to be the next higher as we're done with this one.
                    # but to squeeze out the 0's: only shift on 1 mask bits.
                    current_mini_int_multiple <<= 1
                    if not to_mini_int: 
                        mini_int >>= 1
                    
                # We're done with this bit position, whether or not it was on.
                # Move the next bit into the low position for consideration.
                if to_mini_int: 
                    target >>= 1 

                current_onbit_mask >>= 1
                # Likewise if we have to change the on/off bits, select
                # ##which one that will be.
                current_wholeint_multiple <<= 1
                
            #===================================================================
            # return a tuple (the mini int for the given target,the specific
            # onbits, the specific off bits) Remember: These are dbus on and
            # off bits- the ones having nothing to do with this mini-int combined
            # with the necessary for this particular mini int value.
            #===================================================================

            if to_mini_int:
                return (mini_int, current_onbits, current_offbits)
            else:
                if mini_int != 0:
                    raise ValueError("The field named " + self.label + " has value " + str(val) + ", which is too large for for onbit pattern 0x" + format(self.onbits, "x"))
                return (target, current_onbits, current_offbits)
            
        def int_value(self, target):
            '''Quick way to just convert a target to its mini-int'''
            return self.int_bitmask_and_value(target)[0]
                
        
        def target_value(self,mini_int):            
            return self.int_bitmask_and_value(mini_int,False)[0]
            
        
def default_pyarg_conversion_to_variant(python_arg):
    # The caller has provided python_arg on the way to dbus, and
    # the introspection string asks for a variant, and it is 
    # possible the caller has provided a variant.  The 
    # translation specification does not give any guidance
    # about what to do, so this is the default conversion
    # of python arguments to dbus variants.

    # # Here begins a series of helper functions that convert python basic
    # # to GLib/Dbus types.  These helper functions are used for conversion
    # # when the translation given by introspection and supplemented by the
    # # user provided translation guidance gives no specific guidance about
    # # which of many possible conversions are to be used.
    # # These routines are almost never called unless the introspection
    # # specification includes a 'v' / Variant member, and the user
    # # provided translation specification is absent/default. 
    
    
    def _list_to_variant(pylist):
        # When given no guidance about choosing which of many
        # possible python <--> dbus list conversions to use, return
        # a Variant array of variants if all the members do not
        # have the same type, otherwise return a variant array
        # of the specific type of the unpacked member. So:
        # ['these','are','all','strings'] gets dbus type 'as'
        # but [1,'plus',1,'equals',2] gets dbus type 'av'
        v_list = []
        v_types_of_list_members = None
        v_all_members_have_the_same_type = True
        for e in pylist:
            e_as_variant = default_pyarg_conversion_to_variant(e)
            e_type = e_as_variant.get_type_string()
            v_list += [e_as_variant]
            if v_types_of_list_members == None:
                v_types_of_list_members = e_type 
            else:
                if v_types_of_list_members != e_type: v_all_members_have_the_same_type = False
        if v_all_members_have_the_same_type:
            unpacked_list = []
            for v in v_list: unpacked_list += [v.unpack()]
            return Variant('a' + v_types_of_list_members, unpacked_list)
        else:
            return Variant('av' , v_list)

    
    def _tuple_to_variant(pytuple):
        # When given no guidance about choosing which of many
        # possible python <--> dbus conversions to use, return
        # a Variant tuple that uses as few other variants
        # as members as possible. So none of the tuple members
        # will be variants.
        v_tuple = ()
        v_types_of_tuple_members = ''
        for v in pytuple:
            v_as_variant = default_pyarg_conversion_to_variant(v)
            v_tuple += (v_as_variant.unpack(),)
            v_types_of_tuple_members += v_as_variant.get_type_string()
        return Variant('(' + v_types_of_tuple_members + ')', v_tuple)


    def _dict_to_variant(val):
        # When given no guidance about choosing which of many
        # possible python <--> dbus conversions to use, return
        # a Variant dictionary that uses as few other variants
        # as keys or values as possible. So, for example:
        
        # if all the keys are variant strings,
        #    use the unpacked strings as keys, and
        #    set the dictionary type as 'a{s...' and not 'a{v..'
        # if all the values as variant ints, 
        #    use the unpacked ints as values.
        #    set the dictionary format as '...i}' and not '...v}'
            
        # WARNING: Suppose one run of a program using this has
        # dict values that just so happens to map strings to all integers,
        # and another run of the same program has keys which are all 
        # strings and values that are a mix of integers and something else.
        # This routine will convert the first instance as 'a{si}' and 
        # the second instance as 'a{sv}'. If that is a problem:
        # Provide the preferred format as guidance in the translation
        # specification.
        k_type = None
        v_type = None
        keys_all_same_type = True
        values_all_same_type = True
        # First, build a list of dictionary items with
        # variant keys and variant values, see if all 
        # entries are the same type
        vlist = []
        for (k, v) in val.items():
            k_as_variant = default_pyarg_conversion_to_variant(k)
            v_as_variant = default_pyarg_conversion_to_variant(v)
            if k_type == None:
                k_type = k_as_variant.get_type_string()
                v_type = v_as_variant.get_type_string()
            else:
                if k_type != k_as_variant.get_type_string(): keys_all_same_type = False
                if v_type != v_as_variant.get_type_string(): values_all_same_type = False
            vlist += (k_as_variant, v_as_variant)
        # If the keys are all the same type, store them as unpacked in the final dictionary
        # Similarly for Values.  Otherwise store them as variants.
        vdict = {}
        if keys_all_same_type and values_all_same_type:
            for e in vlist: vdict[e[0].unpack()] = e[1].unpack()
        elif keys_all_same_type and (not values_all_same_type):
            for e in vlist: vdict[e[0].unpack()] = e[1]
        elif (not keys_all_same_type) and values_all_same_type:
            for e in vlist: vdict[e[0]] = e[1].unpack()
        else:
            for e in vlist: vdict[e[0]] = e[1]
        # Now, parse the result and return a variant dictionary.
        return Variant('a{' + (k_type if keys_all_same_type else 'v') + (v_type if values_all_same_type else 'v') + '}', vdict)
 
    # non-container types

    def _int_to_variant( v):  
        return Variant.new_int32(v)
    
    def _bool_to_variant( v):  
        return Variant.new_boolean(v)
        
    def _float_to_variant( v):  
        return Variant.new_double(v)

    def _string_to_variant( v):
        return Variant.new_string(v)


    #### End of 'Helper functions when no 'v' translation guidance is given'.

    tovariant_dict = {
                      bool: _bool_to_variant,
                      str: _string_to_variant,
                      int: _int_to_variant,
                      float : _float_to_variant,
                      list : _list_to_variant,
                      tuple : _tuple_to_variant,
                      dict  : _dict_to_variant,
                      }

    # This routine uses a function table above with
    # helper functions to handle the specific python variable base cases.
    # On those occasions these routines generally do the right thing for tuples, 
    # dictionaries and lists, returning dbus structures that include as
    # few variants under the introspection top level 'v' as possible.
    # If it is not desired for all single and larger character strings
    # to be interpreted as dbus strings, all python booleans to be 
    # interpreted as dbus booleans, all floating point numbers as dbus
    # doubles, and all integers as signed 32 bit values:
    # specific other conversion guidance on what to do when 
    # the introspection includes a 'v' must be given in the user
    # provided translation. See the example specification for formatting
    # details.

    # If we are passed a GLib Variant, there is no work to do, just return it.
    if isinstance(python_arg, Variant): return python_arg 
    try:
        return tovariant_dict[type(python_arg)](python_arg)
    except:
        return  Variant('s', repr(python_arg)) 
    

def variant_introspection_rewrite(introspection, translation_guidance):            
    if not isinstance(introspection, str):
        # if there is no introspection string, move on.
        modified_sargs = ''
    elif 'v' not in introspection:
        # if there is no variant request to process, move on.
        modified_sargs = introspection
    else:
        # if the translation spec has variant expansion, apply it
        index = -1
        modified_sargs = ''
        for nonvariantarg in introspection.split('v'):
            if index == -1:
                # accept any item before the first v
                modified_sargs += nonvariantarg 
            else:
                # we have a v
                modified_sargs += 'v:'
                try:  # if default guidance, do v::
                    modified_sargs += translation_guidance[index]
                except:
                    pass
                modified_sargs += ':'
            index += 1
    return modified_sargs       


def convert_arguments_python_to_dbus(arglist_guidance, python_args, python_kwargs):                
    if arglist_guidance.python_side_named_args_as_dict:
        # we have a dictionary of arguments, turn it into a list for dbus
        dbus_args = [ arglist_guidance[i].default for i in range(0, arglist_guidance.dbus_side_argument_list_size) ]
        # default unspecified variables.
        for arg_name, arg_value in (python_args if python_kwargs == None else python_kwargs):
            # If passed a number where a name is supposed to go, use it as a position.
            if isinstance(arg_name, int):
                dbus_args[arg_name] = arg_value
            else:
                dbus_args[ arglist_guidance.arg_position_from_name[ arg_name ] ] = arg_value     
    elif arglist_guidance.python_side_named_args_as_object_attributes:
        # we have an object with attributes as arguments
        dbus_args = [ arglist_guidance[i].default for i in range(0, arglist_guidance.dbus_side_argument_list_size)]
        # defaults are set
        for attribute_name, attribute_position in arglist_guidance.arg_position_from_name.items():
            # process attributes into positions
            # notice we allow positions to be named on the python side that can't
            # are not part of the dbus side, for use in the translation only.
            if attribute_position >= 0 and attribute_position < arglist_guidance.dbus_side_argument_list_size:
                dbus_args[attribute_position] = getattr(python_args, attribute_name, None)            
    else:  # from Dbus arguments are already in list format.
        # we have incoming dbus arguments, they are already an arglist
        dbus_args = python_args if isinstance(python_args,(tuple,list)) else [python_args]

    return dbus_args


def convert_arguments_dbus_to_python(arglist_guidance, post_call_args, retained_pyarg):
    if arglist_guidance.python_side_named_args_as_dict:
        # the spec calls for arguments as a dictionary
        if (arglist_guidance.new_return_instance == True) and isinstance(retained_pyarg, dict):
            post_trans_args = retained_pyarg
        else: post_trans_args = {}
        for attribute_name, attribute_position in arglist_guidance.arg_position_from_name.items():
            if attribute_position >= 0 and attribute_position < len(post_call_args):
                post_trans_args[attribute_name] = post_call_args[attribute_position]
            else:
                post_trans_args[attribute_name] = arglist_guidance.arguments[attribute_position].default
    elif arglist_guidance.python_side_named_args_as_object_attributes:
        # the spec calls for arguments as attributes
        if (arglist_guidance.new_return_instance == True) and (retained_pyarg != None):
            post_trans_args = retained_pyarg
            try:
                setattr(post_trans_args, '__IS_THIS_THING_SETTABLE__?', True)
                delattr(post_trans_args, '__IS_THIS_THING_SETTABLE__?')
            except:
                post_trans_args = BlankClass()
        else: post_trans_args = BlankClass()
        for arg in arglist_guidance.arguments:
            if arg.arg_position_index >= 0 and arg.arg_position_index < len(post_call_args):
                setattr(post_trans_args, arg.attribute, post_call_args[arg.arg_position_index])
            else:
                setattr(post_trans_args, arg.attribute, arg.default)
    else : 
        post_trans_args = post_call_args  # -- the arguments are already in the correct order.

    return (post_trans_args)




class BlankClass(object):
    def __init__(self):
        self._from_dbus_to_python = True
        

class PydbusCPythonTranslator(object):
    '''Top translation class, access point to all translation functionality.'''
    
#     See the example in the Main section at the bottom of this file for a quick
#     example. See translations/org_freedesktop_NetworkManager for an example
#     spec.
#     
#     The operation of this class is built in to method, property and signal routines.
#     
#     To activate translation, instead of 
#     bus.get(...) 
#     do
#     bus.get(...,translation_spec=your_translation) 
#     
#     See the top of this file for a full translation specification.
#     
#     All remaining documentation is meant for maintainers.
#     
#     The details of this class internally:  
#     
#     Upon initialization do an optimization so that conversions from numeric
#     results to pythonic format is as fast as the passed in tables associating
#     pythonic results to numeric format. Walk the dictionary tree to validate the
#     keys used match the argument type expected for the data direction.  Lookup
#     often fetched keys, save them for efficiency later.
#     
#     If there's anything clearly wrong with the dictionary tree, throw an 
#     error now so its easier on the translation writer than hitting it
#     during an operation.
#       
#     
#     There are four main routines, and many helper functions.
#     
#     Initialization discussed above, translate - the main entry point for all
#     later uses, ctop and ptoc for specific issues that depend on whether the
#     arguments are c/dbus going to python, or python arguments going to c/dbus.
#     
#     isolate_format is a routine used in all three, it peals off however
#     much of a dbus string is expressed in one argument.  so uu is 2 arguments.
#     It's also used within arguments when these routines are called on to
#     translate contents of containers.
#      
#     
#     instance.ctop(pydbus_item,"property_or_method_name",value_or_tuple_to_be_translated_from_c_to_pythonic)
#     
#     instance.ptoc(pydbus_item,"property_or_method_name",value_or_tuple_to_be_translated_from_pythonic_to_c)
#     
#     These will return a tuple if passed a tuple, or a value if passed a value,
#     in the expected format. So, for example, networkmanager_transinstance.ctop(p
#     ydev_network_manager_instance,"Metered",0) would return "UNKNOWN" and networ
#     kmanager_transinstance.ctop(pydev_network_manager_instance,"Metered","UNKNOW
#     N") would return 0.
  
   
    def __init__(self, translation_spec, bus_name, unit_test_dictname=None):
        self.bus_name = bus_name
        self._underscored_bus_name = bus_name.replace('.', '_')
        if isinstance(translation_spec, str):
            try:
                m = import_module(translation_spec)  # @UnusedVariable
            except:
                m = import_module(translation_spec + '.py')  # @UnusedVariable
            try:
                self.original_guidance = eval('m.' + self._underscored_bus_name)
            except:
                raise ValueError("Can't find pydbus translation dictionary " + self._underscored_bus_name + " in caller specified module " + translation_spec)
        elif isinstance(translation_spec, dict):
            self.original_guidance = translation_spec
        else:
            try:
                m = import_module('pydbus.translations.' + self._underscored_bus_name)  # @UnusedVariable
            except:
                raise ValueError("Built-in translation library has no file named " + self._underscored_bus_name)
            try:
                self.original_guidance = eval('m.' + (self._underscored_bus_name if unit_test_dictname == None else unit_test_dictname))
            except:
                raise ValueError("Built-in translation library module pydbus.translations." + self._underscored_bus_name + " missing translation dictionary " + self._underscored_bus_name)

        if not isinstance(self.original_guidance, dict):
            raise ValueError("The translation specification object must be a dictionary, not a " + type(self.spec))
        
        self.dataflow_guidance = {}
        if len(self.original_guidance)==0:
            raise ValueError("There are no keys in the dictionary for dbus path "+ self.bus_name)
        for key_for_this_dbus_path, per_key_desired_translation_types_and_directions in self.original_guidance.items():
            # Validate the input
            if not isinstance(key_for_this_dbus_path, str):
                raise ValueError("Each key value for a dbus path must be a string, not " + str(key_for_this_dbus_path))
            if per_key_desired_translation_types_and_directions == None:
                continue
            if not isinstance(per_key_desired_translation_types_and_directions, dict):
                raise ValueError("Each per-key translation spec must be either None or a dict, not "+repr(per_key_desired_translation_types_and_directions))
            
            # Create the object representing this key for this path.
            guidance_for_one_key = DataFlowGuidance(key_for_this_dbus_path)
            # Save it so it can be found during runtime.
            self.dataflow_guidance[key_for_this_dbus_path] = guidance_for_one_key
            
            # Now we populate the key specific item.
            flow_directions = ("method_py_to_dbus", "method_dbus_to_py",
                           "signal_dbus_to_py", "signal_py_to_dbus", "property",
                           "property_dbus_to_py", "property_py_to_dbus")
            for f in flow_directions:
                setattr(guidance_for_one_key, 'original_' + f, per_key_desired_translation_types_and_directions.get(f, None))

            if guidance_for_one_key.original_property and (guidance_for_one_key.original_property_py_to_dbus == None):
                guidance_for_one_key.original_property_py_to_dbus = guidance_for_one_key.original_property
            if guidance_for_one_key.original_property and (guidance_for_one_key.original_property_dbus_to_py == None):
                guidance_for_one_key.original_property_dbus_to_py = guidance_for_one_key.original_property

            guidance_for_one_key.original_to_dbus_guidance = (guidance_for_one_key.original_method_py_to_dbus,
                                                                guidance_for_one_key.original_signal_py_to_dbus,
                                                                guidance_for_one_key.original_property_py_to_dbus)
            guidance_for_one_key.original_from_dbus_guidance = (guidance_for_one_key.original_method_dbus_to_py,
                                                                guidance_for_one_key.original_signal_dbus_to_py,
                                                                guidance_for_one_key.original_property_dbus_to_py)
    
            # here we expect each xxx_py_to_dbus and xxx_dbus_to_py to describe what, if anything
            # should be done to the arguments during the course of the respective event.
        
            got_one = guidance_for_one_key.init_helper_validate_arglistspec(guidance_for_one_key.original_to_dbus_guidance, True) | \
                  guidance_for_one_key.init_helper_validate_arglistspec(guidance_for_one_key.original_from_dbus_guidance, False)
            if got_one == False:
                raise ValueError("The translation dictionary provided needs at least one active key/value for key " + key_for_this_dbus_path + 
                             str(flow_directions))
    

 
        
    #### End of code dealing with 'v' in introspection format to be 
    #### converted to dbus without guidance from the translation spec.   

    def _one_ctop(self, trans, cvalue, argformat='', argument_index=0, enable_auto_container=True,key_for_this_dbus_path='Unknown'):
        # Here we are given a single dbus/Glib cvalue,
        # with instructions to use a translation dictionary
        # entry to return a pythonic representation of it, possibly
        # converting defined bitfields to informative
        # string tuples and, integers not used as numbers
        # but instead as indications of state to strings
        # describing the state.
        
        # transdict is the compiled dictionary class matching the dbus address AND
        # the key relating to the values passed.
        
        # cvalue is dbus/glib version we examine
        
        # argformat is the smallest possible glib/dbus format
        # string describing what was unpacked into cvalue.
        # It will be a single variable or a single container
        # of any content of any depth. note that argformat
        # will have instead of v, v:to-dbusconversionguidanceinfo:
        # as provided for in the specific translation in use.
        
        # argument_index is a 0 based offset of the argument number, left to right.
         
        if not isinstance(trans, SingleArgumentOptimizedGuidance):
            # If this isn't guidance we understand, return the variable unchanged.
            return cvalue

        if trans.match_to_function:
            # We have a match function.  See whether the introspection 
            # exists directly
            match_this = str(argument_index) + ":" + str(argformat)
            match_tuple = trans.compiled_re.get(argformat, None)
            
            function=None
            if match_tuple == None:
                for match_string, match_tuple in trans.compiled_re.items():  # @UnusedVariable
                    if match_tuple[0]!=None:
                        if match_tuple[0].match(match_this):
                            function = match_tuple[1]
                            break
            else: function=match_tuple[1]
            if function:  return (function)(cvalue, argument_index, argformat, True)
            raise ValueError("No supplied function matched or callable for " + self.bus_name + ", dbus to python key " + key_for_this_dbus_path + ", but none provided match string " + match_this + " ")

        if trans.force_replacement_specified:
            return trans.forced_replacement


        introspection_this_level, introspection_next_level = _isolate_format(argformat)
        if introspection_next_level: 
            # Dbus expects a container. What sort?
            if len(introspection_this_level) == 1:
                introspection_container = list
            else:
                introspection_container = tuple if (introspection_this_level[1] == '(') else dict
        else:
            introspection_container = None

        if isinstance(cvalue, (list, tuple)):
            if trans.container:
                container = trans.container
            elif  trans.auto_container_active and enable_auto_container:
                container = trans
            else:
                # We've been passed a tuple or list, introspection wants
                # a tuple, we have no guidance about what to do with it,
                # so, hope the caller knows what the needs are.
                return cvalue
            # apply the container guidance we have to the members of the container, make the tuple.
            if introspection_container == list:
                return list(self._one_ctop(container, x, introspection_next_level, argument_index, False,key_for_this_dbus_path) for x in cvalue)
            elif introspection_container == tuple:
                return tuple(self._one_ctop(container, x, introspection_next_level, argument_index, False,key_for_this_dbus_path) for x in cvalue)
            
        if isinstance(cvalue, dict):
            if trans.container:
                value_container = trans.container
            elif  trans.auto_container_active and enable_auto_container:
                value_container = trans
            else:
                value_container = None
            if (value_container == None) and (trans.container_keys == False):
                # if we have no guidance for this dictionary, and introspection expects one,
                # then return what we have.
                return cvalue
            # otherwise, build a translated dictionary
            return { self._one_ctop(trans.container_keys, k, introspection_next_level[0], argument_index, False,key_for_this_dbus_path) 
                     if trans.container_keys else k : 
                     self._one_ctop(value_container, v, introspection_next_level[1:], argument_index, False,key_for_this_dbus_path)
                     if value_container else v 
                     for k , v in cvalue.items()}
            

        # If we get here, it's not a container type we know what to do with, so
        # check to see whether it's anything expected, if so, do it, if not, 
        # return with no changes.

        if trans.is_one_to_one_map:
            if cvalue == None: cvalue = 0
            if not isinstance(cvalue, int): 
                raise ValueError("Int to string translation required an int from dbus, but got " + repr(cvalue) + " for dbus path " + self.bus_name + ", key " + key_for_this_dbus_path)
            try:
                return trans.map[cvalue]
            except:
                pass
            if trans.replace_unknowns:
                return trans.replace_unknowns[0]
            return "UNKNOWN_0x" + format(cvalue, 'X')
            

        if trans.is_bitfield:
            if cvalue == None: cvalue = 0
            if not isinstance(cvalue, int): 
                raise ValueError("Int to bitfield translation required an int from dbus, but got " + repr(cvalue) + " for dbus path " + self.bus_name + ", key " + key_for_this_dbus_path)
            retdict = {}
            touched_bits = 0
            everything_else_label = None
            for label, bitfield in trans.map.items():
                if trans.wants_everything_else: 
                    everything_else_label = label 
                touched_bits |= bitfield.bits_tested() 
                if bitfield.mask_test(cvalue):
                    if bitfield.treat_as_int:
                        retdict[label] = bitfield.int_value(cvalue)
                    else:
                        retdict[label] = True
                elif trans.show_all_names:
                    if bitfield.treat_as_int:
                        retdict[label] = 0
                    else:
                        retdict[label] = False
            if everything_else_label:
                retdict[everything_else_label] = ((~touched_bits) & cvalue)
            
            if trans.arg_format in ('single', 'prettydict', 'prettylist'):
                if len(retdict) != 1:
                    if trans.arg_format == 'prettydict': return retdict
                    if trans.arg_format != 'prettylist':
                        raise ValueError("Asked for single result, but " + str(len(retdict)) + " were returned: " + str(retdict) + " for dbus path " + self.bus_name + ", key " + key_for_this_dbus_path)
                else:
                    for v in retdict.values():
                        return v
            if trans.arg_format == 'dict': return retdict
            if trans.arg_format == 'list': return  list([k, v] for k, v in retdict.items())
            if trans.arg_format in ('shortlist', 'prettylist'):
                retlist = []
                for k, v in retdict.items():
                    if isinstance(v,bool) and (v == True):
                        retlist += [k]
                    else:
                        retlist += [[k, v]]
                return retlist
                        
                
        # if we get here, we either don't know what this is, or if we do we dont
        # need it translated.
        return cvalue
        
    

    def _IPv6Address_to_Variant(self, ipv6):
        return Variant.new_bytestring(ipv6.packed)
        
    def _IPv4Address_to_Variant(self, ipv4):
        return Variant.new_uint32(int(ipv4)).byteswap()

    def _IPv4Network_to_Variant(self, ipv4net):
        return Variant('au', int.from_bytes(int(ipv4net.network_address).to_bytes(4, 'little'), 'big'), ipv4net.prefixlen)
    
    # Here we convert known python classes that are not builtins to dbus format.
    to_dbus_format = { IPv4Address : _IPv4Address_to_Variant,
                       IPv6Address : _IPv6Address_to_Variant,
                       IPv4Network : _IPv4Network_to_Variant,
                    }

    
    def process_pyvar_bitfield(self,trans,pyvar,key_for_this_dbus_path,m=None):
        # If we've been passed an integer, pass it through as is.
        if pyvar == None: return 0  # None -> 0

        if isinstance(pyvar, bool):
            if m==None:
                m = trans.map.get('TRUE' if pyvar else 'FALSE', None)
            if m == None: return pyvar
            if m.treat_as_int == False: return m.onbits
            return m.target_value(pyvar)
            
        if isinstance(pyvar, int):
            try:
                if m == None:
                    m = trans.map[0]
                if m.treat_as_int:
                    return m.target_value(pyvar)
                return m.onbits
            except:
                return pyvar
            
        if isinstance(pyvar, str):
            try:
                if m == None:
                    m = trans.map[pyvar.upper()]
                if m.treat_as_int == False: return m.onbits
            except:
                pass
            raise ValueError("Can't match bitmask " + pyvar + " for " + self.bus_name + ", key " + key_for_this_dbus_path + ".")
        
        if isinstance(pyvar, dict):
            v = 0
            for key, val in pyvar.items():
                if isinstance(key,str): key = key.upper()
                try:
                    m = trans.map[key]
                    v |= self.process_pyvar_bitfield(trans, val, key_for_this_dbus_path, m)
                except:
                    raise ValueError("Can't match bitmask name " + str(key) + " for " + self.bus_name + ", key " + key_for_this_dbus_path + ".")
            return v

        if isinstance(pyvar, (tuple, list)):
            v = 0
            for element in pyvar:
                if isinstance(element, (tuple,list)):
                    if len(element) < 1: continue
                    if len(element) == 1:
                        key = element[0]
                        val = 1
                    else:
                        key, val = element[0:2]
                else:
                    key = element
                    val = 1
                if isinstance(key,str): key = key.upper()
                m = trans.map[key]
                v |= self.process_pyvar_bitfield(trans, val, key_for_this_dbus_path, m)
            return v
        raise ValueError("Can't match bitmask " + repr(pyvar) + " for " + self.bus_name + ", key " + key_for_this_dbus_path + ".")
        
        
        
        
        
    
    def _one_ptoc(self, trans, pyvar, argformat='', argument_index=0, enable_auto_container=True,key_for_this_dbus_path='Unknown'):
        '''Return a dbus friendly version of pythonic variable pyvar
        according to dbus spec argformat as per 
        https://developer.gnome.org/glib/stable/gvariant-format-strings.html
        except translate v:x/y/z: as a variant of the first successful type x, y or z'''
        # First, apply any python to dbus translation guidance
        # trans -> translation guidance
        # pyvar -> python version of the argument
        # argformat -> introspection string pyvar should be
        # argument_index -> None if doing arglist, otherwise 0..x
        
        if not isinstance(trans, SingleArgumentOptimizedGuidance):
            # If this isn't guidance we understand, return the variable unchanged.
            return pyvar
        
        # Here we process particular parsing options. 
        
        # Match functions, if any, take priority over anything else.
        if trans.match_to_function:
            # We have a match function.  See whether the introspection 
            # exists directly
            match_this = str(argument_index) + ":" + str(argformat)
            match_tuple = trans.compiled_re.get(argformat, None)
            
            function=None
            if match_tuple == None:
                for match_string, match_tuple in trans.compiled_re.items():  # @UnusedVariable
                    if match_tuple[0]!=None:
                        if match_tuple[0].match(match_this):
                            function = match_tuple[1]
                            break
            else: function=match_tuple[1]
            if function:  return (function)(pyvar, argument_index, argformat, True)
            raise ValueError("No supplied function matched or callable for " + self.bus_name + ", dbus to python key " + key_for_this_dbus_path + ", but none provided match string " + match_this + " ")



        if trans.force_replacement_specified:
            return trans.forced_replacement


        # If processing reaches here, we need to determine the mix of specification capability
        # and the requirements of this particular python argument.
        
                                         
        variant_parsing_required = (argformat != None) and (len(argformat) > 0) and (argformat[0] == 'v')
        
        if variant_parsing_required:
            for introspection_attempt_list in argformat[2:].split(':'):
                if len(introspection_attempt_list) < 1: continue
                for introspection_attempt in introspection_attempt_list.split('/'):
                    if len(introspection_attempt) < 1: continue
                    try:
                        not_variant_dbus_var = \
                            self._one_ptoc(trans, pyvar, introspection_attempt, argument_index,
                                           enable_auto_container,key_for_this_dbus_path)
                        # If we get here, the translation from python to dbus worked.  Now let's
                        # see if glib likes the result and the given introspection string.
                        return Variant(introspection_attempt, not_variant_dbus_var)
                    except:
                        # Not so much.  
                        pass
            # We are given either no guidance or failed guidance about how to 
            # parse pyvar into the variant required by dbus.  Use the default scheme
            # which makes use of any variant the caller may have
            # supplied.
            return default_pyarg_conversion_to_variant(pyvar)
                
        # Here we know the requested format is not a variant.  
        # Set about matching what we expect with what we have.       
        introspection_this_level, introspection_next_level = _isolate_format(argformat)
        if introspection_next_level: 
            # Dbus expects a container. What sort?
            if len(introspection_this_level) == 1:
                introspection_container = list
            else:
                introspection_container = tuple if (introspection_this_level[1] == '(') else dict
        else:
            introspection_container = None
        
        if introspection_container == tuple:
            if isinstance(pyvar, (list, tuple)):
                if trans.container:
                    container = trans.container
                elif  trans.auto_container_active and enable_auto_container:
                    container = trans
                else:
                    # We've been passed a tuple or list, introspection wants
                    # a tuple, we have no guidane about what to do with it,
                    # so, hope the caller knows what the needs are.
                    return pyvar if isinstance(pyvar, tuple) else tuple(pyvar)
                # apply the container guidance we have to the members of the container, make the tuple.
                return tuple(self._one_ptoc(container, x, introspection_next_level, argument_index, False, key_for_this_dbus_path) for x in pyvar)
            # else:
                # Introspection wants a tuple, and fortunately dbus doesn't care
                # about the types in a tuple. What we have isn't currently a list or tuple.
                # While the next version should have a 'permissive' option to return tuple(pyvar)... for now..
                # return tuple(pyvar)
            raise ValueError("Dbus requires a tuple '" + argformat + "', but argument '" + str(pyvar) + "' is not list or tuple for dbus path " + self.bus_name + ", key " + key_for_this_dbus_path)
            
        if introspection_container == list:
            if isinstance(pyvar, (list, tuple)):
                if trans.container:
                    container = trans.container
                elif  trans.auto_container_active and enable_auto_container:
                    container = trans
                else:
                    # We've been passed a tuple or list, introspection wants
                    # a tuple, we have no guidane about what to do with it,
                    # so, hope the caller knows what the needs are.
                    return pyvar if isinstance(pyvar, list) else list(pyvar)
                # apply the container guidance we have to the members of the container, make the tuple.
                return list(self._one_ptoc(container, x, introspection_next_level, argument_index, False,key_for_this_dbus_path) for x in pyvar)
            # else:
                # Introspection wants a list (dbus array), and unfortunately dbus cares
                # all elements be the same types in an array. What we have isn't currently a list or tuple.
                # While the next version should have a 'permissive' option to return tuple(pyvar) if all
                # the members are the same type,... for now..
                # return list(pyvar)
            raise ValueError("Dbus requires an array '" + argformat + "', but argument '" + str(pyvar) + "' is not list or tuple for dbus path " + self.bus_name + ", key " + key_for_this_dbus_path)
            
        if introspection_container == dict:
            if isinstance(pyvar, dict):
                if trans.container:
                    value_container = trans.container
                elif  trans.auto_container_active and enable_auto_container:
                    value_container = trans
                else:
                    value_container = None
                if (value_container == None) and (trans.container_keys == False):
                    # if we have no guidance for this dictionary, and introspection expects one,
                    # then return what we have.
                    return pyvar
                # otherwise, build a translated dictionary
                return { self._one_ptoc(trans.container_keys, k, introspection_next_level[0], argument_index, False,key_for_this_dbus_path) 
                         if trans.container_keys else k : 
                         self._one_ptoc(value_container, v, introspection_next_level[1:], argument_index, False,key_for_this_dbus_path)
                         if value_container else v 
                         for k , v in pyvar.items()}
            
            raise ValueError("Dbus requires a dictionary '" + argformat + "', but argument '" + str(pyvar) + "' is not for dbus path " + self.bus_name + ", key " + key_for_this_dbus_path)
                
        # If we get here, we know the introspection string does not expect a container type we know how to manage.
        # and not one contained in a variant.
        # So, if our guidance expects something in this spot, 
        # try to satisfy it or raise an exception.
        # if we have no translation guidance for whatever this is
        # just return it untranslated.
        
        
        if trans.is_one_to_one_map:
            if isinstance(pyvar, int): return pyvar
            try:
                return trans.map[pyvar.upper()]
            except:
                pass
            m = re.match("UNKNOWN_(.*)", pyvar, re.IGNORECASE)  # @UndefinedVariable
            try:
                return int(m[1], 16)
            except:
                raise ValueError("No value associated with " + repr(pyvar) + " for dbus path " + self.bus_name + ", key " + key_for_this_dbus_path)
    
        
                                         
        if trans.is_bitfield:
            # If we've been passed an integer, pass it through as is.
            return self.process_pyvar_bitfield(trans, pyvar, key_for_this_dbus_path)
            
        # If we get here, whatever sort of variable this is isn't something we either want or know how to
        # translate.  Return it as is.
        return pyvar

    
    def translate(self,
                pydevobject,
#               pydevobject is returned by pydbus.[SessionBus|SystemBus]().get(...) with optional ...[particular.device.path]
                keyname,
#               keyname is a string that's the name of either a dbus method, signal or property.
                itemvalue,
#               itemvalue is a tuple containing the argument(s) to be evaluated for translation.
                offset,
#               offset is 0 for a method, 1 for a signal, 2 for a property.
                direction_is_from_dbus_to_python=True,
#               direction_is_from_dbus_to_python =  True when processing arguments being
#               returned by a method, signal or property.
#               direction_is_from_dbus_to_python =  False when processing arguments being
#               passed to a method, signal or property.
                introspection=None,
#               introspection = the introspection provided GLib.Variant format string, or nothing if we're
#               to use defaults.
                retained_pyarg=None,
#               retained_pyarg is only populated on the return side of a method call (dbus to python). If the 
#               outgoing call had at least one argument, this points to argument[0], otherwise none.
#               If the guidance key { "_new_return_instance" : True } the same dictionary or object
#               used to supply name/value pairs to the call will be populated by the return values
#               using guidance names in the from call guidance. If the names match, the from dbus
#               item will replace the to dbus item.
                kwargs=None
#               keyword arguments passed on the call side of methods.
                ) :

#   Recap:
#   Each dbus path for which we have translation work has an 
#   instance of this class.  This is the top of the translation tree.
#
#   PydbusCPythonTranslator/self = {
#       { keyname : DataFlowGuidance }, ... }
#
#   DataFlowGuidance spec = { 
#       {  calltype_and_direction_key : ArgSpecGuidance },...}
# 
#   ArgSpecGuidance = {
#       {  argument_position_number : SingleArgumentOptimizedGuidance }, ... }
#
#   SingleArgumentOptimizedGuidance =  Lowest level of the dictionary, 
#       possibly top of the tree of this class if there are containers.

#       Here we step through all the classes making up this pydbus call,
#       Composing a list of those matching translation dictionaries we have.
        if isinstance(pydevobject, str):
            pathlist = (pydevobject,)
        else:
            class_str = str(pydevobject.__class__)
            if class_str.find('CompositeObject') >= 0:
                pathlist = re.split("\\(|\\)", class_str)[1].split('+')
            else:
                pathlist_m = re.search("'DBUS\.(.*)\'", class_str)
                if not pathlist_m: return itemvalue
                pathlist = (pathlist_m[1],)
               
            
        # If we find any matches, we'll replace the item as we go along.
        # Now, hunt for reasons to translate return items.
        translation_engaged = False
        for dbus_pathname in pathlist: 
            # pydev classes are often composite, search through all the classes
            # part of this one, hunting for dbus path match to our translation key
            if dbus_pathname != self.bus_name: continue
            # We found a translation match for a dbus path.
            
            # Are we to act on this key?
            if keyname not in self.dataflow_guidance: continue
            # We have  key and dbpus path.
            
            # load the dataflow spec from the key. 
            dataflow = self.dataflow_guidance[keyname]
            # We found all the possibilities for this key, is this
            # to or from signal/method/dbus to be translated?

            arglist_guidance = \
                dataflow.from_dbus_guidance[offset] if direction_is_from_dbus_to_python else \
                dataflow.to_dbus_guidance[offset]
            # select everything necessary to choose to/from
            # and whether method, signal or property version of this
            # keyname has translation work to do

            if arglist_guidance == None: continue
            translation_engaged = True
            # We found a translation request for this dbus path and and key 
            # and method, signal or property, and know wether the call is
            # going to or coming from the dbus. 
            # All that's lieft is to process the arguments.
            
            # Step one: Determine if there are variants in the argspec
            # and if so, whether the translation spec provides guidance
            # for it.  If so, rewrite the incoming introspection args
            # to our custom v -> v:detail: format so the right spot
            # in arglist processing gets the information.
            modified_introspection = \
                variant_introspection_rewrite(introspection,
                arglist_guidance.overall_variant_expansion_list)
            # now, self.modified_introspection is either empty or has all embedded 'v' items replaced
            # with v:: or v:<further format guidance>:
            # match the arguments, left to right, with corresponding GLib.Variant format item



            # Arguments on the python side can be in the traditional ordered list,
            # Or can take advantage of the argument naming feature, which allows
            # argument passing as either one dictionary with names as keys or
            # object with argument names as attribute names.            
            if direction_is_from_dbus_to_python == False:
                # We have python arguments. Do we need to unpack
                # them from an object or dict to relieve the user
                # from keeping track of article order?
                pre_call_args = convert_arguments_python_to_dbus(arglist_guidance, itemvalue, kwargs)
            else:
                # Dbus needs no 'on the way in' translation, the argument list is 
                # already in lisr format.
                pre_call_args = itemvalue 
                
            
            # The arguments are ready to present to the translation routines.
            # If dbus, then directly, if translated, then that.
            if arglist_guidance.all_arguments_in_one_call:
                if  0 in arglist_guidance.arguments:
                    post_call_args = (self._one_ctop  if direction_is_from_dbus_to_python else self._one_ptoc) \
                        (arglist_guidance.arguments[0], pre_call_args, modified_introspection, 0,True,keyname)
            else:
                # make the default return list the same as the passed list.
                post_call_args = []
                for t in pre_call_args: 
                    post_call_args += [t]
                for i in range(0, len(pre_call_args)):
                    this_arg_format , remaining_format = _isolate_format(modified_introspection)
                    modified_introspection = remaining_format
                    if i not in arglist_guidance.arguments: continue
                    post_call_args[i] = (self._one_ctop  if direction_is_from_dbus_to_python else self._one_ptoc) \
                        (arglist_guidance.arguments[i], pre_call_args[i], this_arg_format, i,True,keyname)
                break
              
            break

        if not translation_engaged: return itemvalue
  
        if direction_is_from_dbus_to_python:
            # We have translated the argument list, now see if we need
            # to pack them to relieve the user from arg order management,
            # or send them back as an ordered tuple.
            post_trans_args = convert_arguments_dbus_to_python(arglist_guidance, post_call_args, retained_pyarg)
        else:
            post_trans_args = post_call_args

        try:
            if offset == 0: return tuple(post_trans_args)
            if len(post_trans_args)>1: return tuple(post_trans_args)
            return post_trans_args[0]
        except:
            pass
        return post_trans_args
    