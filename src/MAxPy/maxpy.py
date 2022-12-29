from errno import EROFS, errorcode
import os
import sys
import re
import sysconfig
import subprocess
import itertools
#import importlib
import copy

# if sys.version_info < (3, 9):
# 	import importlib_resources
# else:
# 	import importlib.resources as importlib_resources


from .utility import *

from .resources import Resources
from .synth import synth
from .estimations import est_area, est_power_timing
from .verilate import verilate
from .wrapper import wrapper
from .compile import compile



#------------------------------------------------------------------------------
#------------------------------------------------------------------------------

class AxCircuit:

	res = Resources()

	def __init__(self,
		top_name="",
		tech="NanGate15nm",
		synth_tool=None,
		xml_opt="verilator",
		clk_signal="",
		group_dir="",
		testbench_script=None,
		#dot_opt = 'verilator',
		#target_clk_period = 100000,
		):

		# initial message
		print(f"MAxPy - Version {version}\n")

		self.res.load_tech(tech)




		self.top_name = top_name
		self.tech = tech
		self.xml_opt = xml_opt
		self.clk_signal = clk_signal
		self.parameters = {}
		self.group_dir = group_dir
		self.testbench_script = testbench_script
		self.synth_tool = synth_tool
		self.prob_pruning_threshold = 0
		self.node_info = []
		self.prun_flag = False
		self.prun_netlist = False




	# . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .
	# getters and setters

	def set_group(self, path):
		self.group_dir = path


	def set_testbench_script(self, testbench_script):
		self.testbench_script = testbench_script


	def set_synth_tool(self, synth_tool):
		self.synth_tool = synth_tool


	def set_prob_pruning_threshold(self, threshold):
		self.prob_pruning_threshold = threshold


	# . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .
	# . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .
	# . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .

	def rtl2py(
		self,
		base="",
		target="",
		area_estimation=True,
		log_opt=True,
		vcd_opt=False,
		saif_opt=True,
		):

		self.vcd_opt = vcd_opt
		self.log_opt = log_opt
		self.saif_opt = saif_opt

		if base == "":
			base = 'rtl'

		if target == "":
			target = "level_00"
			self.current_parameter = ""
		else:
			self.current_parameter = target

		self.class_name = f"{self.top_name}_{target}"

		print(f">>> Converting Verilog RTL design \"{self.top_name}\" into Python module, base \"{base}\", target \"{target}\"")

		print(">>> Start: " + get_time_stamp())
		print("")

		if self.synth_tool is not None:
			if self.synth_tool in self.res.synth_tools:
				self.synth_opt = True
			else:
				self.synth_opt = False
		else:
			self.synth_opt = False

		if area_estimation is True and self.synth_opt is False:
			self.synth_tool = "yosys"

		self.base_path = f"{base}/*.v"
		if self.group_dir == "":
			self.target_compile_dir = f"{self.top_name}_{target}_build/"
			self.pymod_path = f"{self.top_name}_{target}_build"
		else:
			self.target_compile_dir = f"{self.group_dir}/{self.top_name}_{target}_build/"
			self.pymod_path = f"{self.group_dir}.{self.top_name}_{target}_build"
		self.target_netlist_dir = "{t}netlist_{s}/".format(t=self.target_compile_dir, s=self.synth_tool)
		self.source_output_dir = "{t}source/".format(t=self.target_compile_dir)

		self.compiled_module_path = "{t}{c}.so".format(t=self.target_compile_dir, c=self.top_name)
		self.netlist_target_path = "{d}{c}.v".format(d=self.target_netlist_dir, c=self.top_name)
		self.wrapper_cpp_path = "{d}verilator_pybind_wrapper.cpp".format(d=self.source_output_dir)
		self.wrapper_header_path = "{d}verilator_pybind_wrapper.h".format(d=self.source_output_dir)
		self.area_report_path = "{t}area_report.txt".format(t=self.target_compile_dir, c=self.top_name)
		self.power_report_path = "{t}power_report.txt".format(t=self.target_compile_dir, c=self.top_name)

		os.makedirs(self.target_compile_dir, exist_ok = True)
		os.makedirs(self.source_output_dir, exist_ok = True)

		if self.synth_opt is True or area_estimation is True:
			os.makedirs(self.target_netlist_dir, exist_ok = True)

		self.trace_levels = 99  ##TODO: ???

		self.area = 0.0
		self.power = 0.0
		self.timing = 0.0

		# synth: synthesize RTL file (optional)
		if self.prun_netlist is False:
			if self.synth_opt is True or area_estimation is True:
				ret_val = synth(self)
				#print("  > End\n")
				if ret_val is not ErrorCodes.OK:
					print(">>> End: " + get_time_stamp())
					print(">>> MAxPy ERROR: synth process exited with error code \"{error}\". Please check log files".format(error=ret_val))
					return ret_val
				else:
					if self.synth_opt is True:
						self.base_path = self.netlist_target_path
					else:
						self.synth_tool = None

					self.working_netlist = self.netlist_target_path

		else:
			self.working_netlist = f"{base}/{self.top_name}.v"

		est_area(self)
		est_power_timing(self)

		print(f"  > Netlist estimated area: {self.area:.3f}")
		print(f"  > Netlist estimated power = {self.power:.3f} uW")
		print(f"  > Netlist estimated maximum delay = {self.timing:.3f} nS")


		verilate(self)
		wrapper(self)
		compile(self)

		exit(0)

		process_list = [
			self.veri2c,
			self.c2py_parse,
			self.c2py_compile,
			self.checkpymod,
			self.testbench
		]

		#process_list = [self.c2py_compile]

		for process in process_list:
			ret_val = process()
			#print("  > End\n")
			if ret_val is not ErrorCodes.OK:
				print(">>> End: " + get_time_stamp())
				print(">>> MAxPy ERROR: process exited with error code \"{error}\". Please check log files".format(error=ret_val))
				return ret_val

		print("")
		print(">>> End: " + get_time_stamp())
		print(">>> Circuit \"{t}\" compiled successfully!".format(t=self.top_name))
		print("")


		return ErrorCodes.OK


	# . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .


	def rtl2py_param_loop(self, base = '', area_estimation=True, saif_opt=True):

		# change variable parameters in rtl source file
		file =  open(f"{base}/{self.top_name}.v", 'r')
		rtl_source_original = file.read()
		file.close()

		keys = self.parameters.keys()
		values = (self.parameters[key] for key in keys)
		combinations = [dict(zip(keys, combination)) for combination in itertools.product(*values)]

		count=len(combinations)
		print(f">>> Converting Verilog RTL design \"{self.top_name}\" into Python module with variable parameters")
		print(f">>> Iterating through {count} combinations")
		print("")

		for param_list in combinations:
			s = ""
			rtl_source_edit = rtl_source_original
			for key in param_list:
				value = param_list[key]
				if s != "":
					s = s + "_"
				s = s + f"{value}"
				rtl_source_edit = rtl_source_edit.replace(key, value)

			if self.synth_tool is not None:
				s = s + "_" +  self.synth_tool

			if self.group_dir == "":
				base = f"{self.top_name}_{s}_rtl"
			else:
				base = f"{self.group_dir}/{self.top_name}_{s}_rtl"
			#os.makedirs(base, exist_ok = True)

			try:
				os.makedirs(base)

				target = f"{s}"
				file =  open(f"{base}/{self.top_name}.v", 'w')
				file.write(rtl_source_edit)
				file.close()

				ret_val = self.rtl2py(
					base=base,
					target=target,
					area_estimation=area_estimation,
					saif_opt=saif_opt
				)

				#if ret_val is ErrorCodes.OK:
				#	self.testbench()

			except FileExistsError:
				print(f">>> Skipping combination \"{s}\" because it already exists (dir: {base}")
				print("")

	# . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .


	def testbench(self):

		if self.testbench_script is not None:
			print("> Testbench init")
			mod_name = f"{self.pymod_path}.{self.top_name}"
			mod = importlib.import_module(mod_name, package=None)
			self.prun_flag, self.node_info = self.testbench_script(mod, f"{self.target_compile_dir}log-testbench.txt", True)
			print("> Testbench end\n")
			return ErrorCodes.OK

	# . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .


	def probprun(self, base, prun_level):

		print(f"> Probabilistic pruning (level {prun_level}%)")
		print(f"  > Original netlist: {self.netlist_target_path}")

		original_node_info = self.node_info.copy()
		original_netlist_target_path = self.netlist_target_path
		original_current_parameter = self.current_parameter

		prun_level_str = "%02d" % (prun_level)

		if "_build" in base:
			base = base.split("_build")[0]

		if self.group_dir == "":
			probprun_netlist_path = f"{self.top_name}_{base}_probprun_{prun_level_str}_netlist"
		else:
			probprun_netlist_path = f"{self.group_dir}/{self.top_name}_{base}_probprun_{prun_level_str}_netlist"

		os.makedirs(probprun_netlist_path, exist_ok = True)

		print(f"  > Creating directory with pruned netlist: {probprun_netlist_path}")

		fhandle = open(self.netlist_target_path, "r")
		netlist_text = fhandle.readlines()
		fhandle.close()
		netlist_node_count = len(self.node_info)
		print(f"  > Evaluating {netlist_node_count} nodes")

		for node in self.node_info:
			if node["p0"] >= node["p1"]:
				high_prob_value = node["p0"]
				high_prob_logic_level = "p0"
			else:
				high_prob_value = node["p1"]
				high_prob_logic_level = "p1"
			node["high_prob_value"] = high_prob_value
			node["high_prob_logic_level"] = high_prob_logic_level

		sorted_node_list = sorted(self.node_info, key=lambda d: d["high_prob_value"], reverse=True)
		nodes_to_prun = int(float(netlist_node_count)*float(prun_level)/100.0)
		if nodes_to_prun == 0:
			nodes_to_prun = 1
		print("  > Pruning %d%% of the netlist nodes (%d/%d)" % (prun_level, nodes_to_prun, netlist_node_count))
		node_count = 0
		for node in sorted_node_list:
			output_gate_count = 0
			input_gate_count = 0
			for i in range(len(netlist_text)):
				if node['node'] in netlist_text[i]:
					if "Z" in netlist_text[i]:
						output_gate_count += 1
						netlist_text[i] = netlist_text[i].replace(node['node'], "")
					elif "wire" in netlist_text[i]:
						netlist_text[i] = ""
					elif node['high_prob_logic_level'] == "p0":
						input_gate_count += 1
						netlist_text[i] = netlist_text[i].replace(node['node'], "1'b0")
					elif node['high_prob_logic_level'] == "p1":
						input_gate_count += 1
						netlist_text[i] = netlist_text[i].replace(node['node'], "1'b1")
			print(f"    > Node: {node['node']}, {node['high_prob_logic_level']}: {node['high_prob_value']}, gate outputs: {output_gate_count}, gate inputs: {input_gate_count}")
			node_count += 1
			if node_count >= nodes_to_prun:
				break

		pruned_netlist_path = f"{probprun_netlist_path}/{self.top_name}.v"
		fhandle = open(pruned_netlist_path, "w")
		fhandle.write("".join(netlist_text))
		fhandle.close()

		self.prun_netlist = True
		self.rtl2py(
			base=probprun_netlist_path,
			target=f"{self.current_parameter}_probprun_{prun_level_str}",
		)
		self.prun_netlist = False

		self.node_info = original_node_info.copy()
		self.netlist_target_path = original_netlist_target_path
		self.current_parameter = original_current_parameter

	# . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .


	def testbench_param_loop(self):

		if self.testbench_script is None:
			print("Error! Testbench script is None!\n")
			return

		keys = self.parameters.keys()
		values = (self.parameters[key] for key in keys)
		combinations = [dict(zip(keys, combination)) for combination in itertools.product(*values)]

		for param_list in combinations:
			target = ""
			for key in param_list:
				value = param_list[key]
				#key_name = key.split("[[PARAM_")[1].replace("]]", "")
				if target != "":
					target = target + "_"
				target = target + f"{value}"

			if self.synth_tool is not None:
				target = target + "_" +  self.synth_tool

			if self.group_dir == "":
				self.target_compile_dir = f"{self.top_name}_{target}_build/"
				self.pymod_path = f"{self.top_name}_{target}_build"
			else:
				self.target_compile_dir = f"{self.group_dir}/{self.top_name}_{target}_build/"
				self.pymod_path = f"{self.group_dir}.{self.top_name}_{target}_build"

			self.target_netlist_dir = "{t}netlist_{s}/".format(t=self.target_compile_dir, s=self.synth_tool)
			self.netlist_target_path = "{d}{c}.v".format(d=self.target_netlist_dir, c=self.top_name)
			self.current_parameter = target

			self.testbench()


	# . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .
	# c2py-parse


	# . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .
	# c2py-compile



	# . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .
	# checkpymod

	def checkpymod (self):

		print("> Module check (should print module\'s name)")

		#print('  > Runnin test script (should print module\'s name):')

		module_test_string = "python -c \""
		module_test_string += "from {m} import {n};".format(m=self.pymod_path, n=self.top_name)
		module_test_string += "print('  >', %s.%s().name())\"" % (self.top_name, self.top_name)

		#print(module_test_string)

		child = subprocess.Popen(module_test_string, shell=True)
		child.communicate()
		error_code = child.wait()

		if error_code != 0:
			ret_val = ErrorCodes.CHECKPYMOD_ERROR
		else:
			ret_val = ErrorCodes.OK

		return ret_val






#----------------------------------------------------------------------------------------------------------------------
#	end of file
#----------------------------------------------------------------------------------------------------------------------