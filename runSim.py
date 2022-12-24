'''
Runs a simulation

Command line args:
	-cfg: Path to simulation cfg json. Defaults to "SimulationSettings/test.json
	-log: Determine output level for agent/controller log files. Options are [CRITICAL, ERROR, WARNING, INFO, DEBUG]. Defaults to WARNING.
'''
import argparse
import json
import traceback
import os

from SimulationRunner import RunSimulation


def runSim(settingsFilePath, logLevel="INFO"):
	if (not os.path.exists(settingsFilePath)):
		raise ValueError("\"{}\" does not exist".format(settingsFilePath))

	fileDict = {}
	try:
		file = open(settingsFilePath, "r")
		fileDict = json.load(file)
		file.close()
	except:
		print(traceback.format_exc())
		raise ValueError("Could not open \"{}\"".format(settingsFilePath))

	if ("description" in fileDict):
		description = fileDict["description"]
		print("\n{}\n".format(description))

	if (not "settings" in fileDict):
		raise ValueError("\"settings\" missing from \"{}\"".format(settingsFilePath))

	settingsDict = fileDict["settings"]
	RunSimulation(settingsDict, logLevel)

if __name__ == "__main__":
	parser = argparse.ArgumentParser()
	parser.add_argument("-cfg", dest="cfgPath", default="SimulationSettings\\test.json", help="Path to simulation cfg json. Defaults to \"SimulationSettings\\test.json\"")
	parser.add_argument("-log", dest="logLevel", default="INFO", help="Determine output level for generated agent/controller log files. Options are [CRITICAL, ERROR, WARNING, INFO, DEBUG]. Defaults to INFO.")

	args = parser.parse_args()

	settingsFilePath = args.cfgPath
	runSim(settingsFilePath, args.logLevel)