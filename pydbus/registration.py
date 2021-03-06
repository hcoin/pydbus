from __future__ import print_function



from . import generic
from .exitable import ExitableWithAliases
from .method_call_context import MethodCallContext
from gi.repository import GLib, Gio
import logging


try:
	from inspect import signature, Parameter  # @UnusedImport
except:
	from ._inspect3 import signature, Parameter  # @Reimport

native_glib=True
#global compat_dbus_connection_register_object, compat_dbus_invocation_return_value, compat_dbus_invocation_return_dbus_error  # @UnusedVariable
from .extensions.PatchPreGlib246 import compat_dbus_connection_register_object # @UnresolvedImport @Reimport @UnusedImport
from .extensions.PatchPreGlib246 import compat_dbus_invocation_return_value  # @UnresolvedImport @Reimport @UnusedImport
from .extensions.PatchPreGlib246 import compat_dbus_invocation_return_dbus_error  # @UnresolvedImport @Reimport @UnusedImport

class ObjectWrapper(ExitableWithAliases("unwrap")):
	__slots__ = ["object", "outargs", "readable_properties", "writable_properties"]

	def __init__(self, obj, interfaces):
		self.object = obj

		self.outargs = {}
		for iface in interfaces:
			for method in iface.methods:
				self.outargs[iface.name + "." + method.name] = [arg.signature for arg in method.out_args]

		self.readable_properties = {}
		self.writable_properties = {}
		for iface in interfaces:
			for prop in iface.properties:
				if prop.flags & Gio.DBusPropertyInfoFlags.READABLE:
					self.readable_properties[iface.name + "." + prop.name] = prop.signature
				if prop.flags & Gio.DBusPropertyInfoFlags.WRITABLE:
					self.writable_properties[iface.name + "." + prop.name] = prop.signature

		for iface in interfaces:
			for signal in iface.signals:
				# s_name = signal.name
				def EmitSignal(iface, signal):
					return lambda *args: self.SignalEmitted(iface.name, signal.name, GLib.Variant("(" + "".join(s.signature for s in signal.args) + ")", args))
				self._at_exit(getattr(self.object, signal.name).connect(EmitSignal(iface, signal)).__exit__)

		if "org.freedesktop.DBus.Properties" not in (iface.name for iface in interfaces):
			try:
				def onPropertiesChanged(iface, changed, invalidated):
					changed = {key: GLib.Variant(self.readable_properties[iface + "." + key], val) for key, val in changed.items()}
					args = GLib.Variant("(sa{sv}as)", (iface, changed, invalidated))
					self.SignalEmitted("org.freedesktop.DBus.Properties", "PropertiesChanged", args)
				self._at_exit(self.object.PropertiesChanged.connect(onPropertiesChanged).__exit__)
			except AttributeError:
				pass

	def dbus_return_value(self,inv,rv):
		global native_glib
		if native_glib:
			inv.return_value(rv)
		else:
			compat_dbus_invocation_return_value(inv,rv)  # @UndefinedVariable
			
	def dbus_err(self,inv,etype,emsg):
		global native_glib
		if native_glib:
			inv.return_dbus_error(etype,emsg)
		else:
			compat_dbus_invocation_return_dbus_error(inv,etype,emsg)  # @UndefinedVariable

			
	SignalEmitted = generic.signal()

#	def call_method(self, connection, sender, object_path, interface_name, method_name, parameters, invocation):
	def call_method(self, _1, _2, _3, interface_name, method_name, parameters, invocation):
		try:
			try:
				outargs = self.outargs[interface_name + "." + method_name]
				method = getattr(self.object, method_name)
			except KeyError:
				if interface_name == "org.freedesktop.DBus.Properties":
					if method_name == "Get":
						method = self.Get
						outargs = ["v"]
					elif method_name == "GetAll":
						method = self.GetAll
						outargs = ["a{sv}"]
					elif method_name == "Set":
						method = self.Set
						outargs = []
					else:
						raise
				else:
					raise

			sig = signature(method)

			kwargs = {}
			if "dbus_context" in sig.parameters and sig.parameters["dbus_context"].kind in (Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY):
				kwargs["dbus_context"] = MethodCallContext(invocation)
			unpacked_parameters = parameters.unpack()
			result = method(*(unpacked_parameters), **kwargs)

			if len(outargs) == 0:
				self.dbus_return_value(invocation,None)
			elif len(outargs) == 1:
				t = GLib.Variant("(" + "".join(outargs) + ")", (result,))
				self.dbus_return_value(invocation,t)
			else:
				self.dbus_return_value(invocation,GLib.Variant("(" + "".join(outargs) + ")", result))

		except Exception as e:
			logger = logging.getLogger(__name__)
			logger.exception("Exception while handling %s.%s()", interface_name, method_name)

			# TODO Think of a better way to translate Python exception types to DBus error types.
			e_type = type(e).__name__
			if not "." in e_type:
				e_type = "unknown." + e_type
			self.dbus_err(invocation,e_type, str(e))

	def Get(self, interface_name, property_name):
			typ = self.readable_properties[interface_name + "." + property_name]
			result = getattr(self.object, property_name)
			return GLib.Variant(typ, result)

	def GetAll(self, interface_name):
		ret = {}
		for name, typ in self.readable_properties.items():
			ns, local = name.rsplit(".", 1)
			if ns == interface_name:
				ret[local] = GLib.Variant(typ, getattr(self.object, local))
		return ret

	def Set(self, interface_name, property_name, value):
			self.writable_properties[interface_name + "." + property_name]
			setattr(self.object, property_name, value)

	def protected_Set(self, interface_name, property_name, value,**kwargs):
		try:
			self.Set(interface_name, property_name, value.unpack())
		except Exception as e:
			logger = logging.getLogger(__name__)
			kwargs['exception']= "Exception " + str(e) +" while getting " + interface_name + "." + property_name + " to " + str(value)
			logger.exception("%s",kwargs['exception'])
	
	def protected_Get(self, interface_name,property_name,**kwargs):
		try:
			return self.Get(interface_name,property_name)
		except Exception as e:
			logger = logging.getLogger(__name__)
			kwargs['exception']= "Exception " + str(e) +" while getting " + interface_name + "." + property_name
			logger.exception("%s",kwargs['exception'])
		return None
	
	
class ObjectRegistration(ExitableWithAliases("unregister")):
	__slots__ = ()

	def __init__(self, bus, path, interfaces, wrapper, own_wrapper=False):
		global native_glib
		if own_wrapper:
			self._at_exit(wrapper.__exit__)

		def func(interface_name, signal_name, parameters):
			bus.con.emit_signal(None, path, interface_name, signal_name, parameters)
		self._at_exit(wrapper.SignalEmitted.connect(func).__exit__)
		if native_glib:
			try:
				ids = [bus.con.register_object(path, interface, wrapper.call_method, None, None) for interface in interfaces]
			except:
				native_glib=False
		
		if not native_glib:
			ids = [compat_dbus_connection_register_object(bus.con, path, interface, wrapper.call_method, wrapper.protected_Get, wrapper.protected_Set) 
				for interface in interfaces]
			


		self._at_exit(lambda: [bus.con.unregister_object(objid) for objid in ids])

class RegistrationMixin:
	__slots__ = ()

	def register_object(self, path, obj, node_info):
		if node_info is None:
			try:
				node_info = type(obj).dbus
			except AttributeError:
				node_info = type(obj).__doc__

		if type(node_info) != list and type(node_info) != tuple:
			node_info = [node_info]

		node_info = [Gio.DBusNodeInfo.new_for_xml(ni) for ni in node_info]
		interfaces = sum((ni.interfaces for ni in node_info), [])

		wrapper = ObjectWrapper(obj, interfaces)
		return ObjectRegistration(self, path, interfaces, wrapper, own_wrapper=True)
