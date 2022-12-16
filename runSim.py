import argparse
import json
import traceback
import os

from SimulationRunner import RunSimulation


def runSim(settingsFilePath):
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
	RunSimulation(settingsDict)

if __name__ == "__main__":
	parser = argparse.ArgumentParser()
	parser.add_argument("-cfg", dest="cfgPath", default="SimulationSettings\\test.json", help="Path to simulation cfg json. Defaults to \"SimulationSettings\\test.json\"")

	args = parser.parse_args()

	settingsFilePath = args.cfgPath
	runSim(settingsFilePath)