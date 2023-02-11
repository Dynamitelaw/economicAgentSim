from EconAgent import *
import json
import random
import multiprocessing as mp
import os
import pickle

if __name__ == "__main__":
	######################
	# Parse All Items
	######################

	#Congregate items into into a single dict
	allItemsDict = {}
	for fileName in os.listdir("Items"):
		try:
			path = os.path.join("Items", fileName)
			if (os.path.isfile(path)):
				itemDictFile = open(path, "r")
				itemDict = json.load(itemDictFile)
				itemDictFile.close()

				allItemsDict[itemDict["id"]] = itemDict
			elif (os.path.isdir(path)):
				for subFileName in os.listdir(path):
					subPath = os.path.join(path, subFileName)
					if (os.path.isfile(subPath)):
						itemDictFile = open(subPath, "r")
						itemDict = json.load(itemDictFile)
						itemDictFile.close()

						allItemsDict[itemDict["id"]] = itemDict
		except:
			pass
	
	#Create test agent
	farmerSeed = AgentSeed("potatoFarmer", agentType="TestProducer", itemDict=allItemsDict, disableNetworkLink=True, outputDir="testCheckpoint")
	farmer = farmerSeed.spawnAgent()
	farmer.timeTicks = 48

	#Test pickling on dict
	testObj = {"message": "Hello world!"}
	with open("OUTPUT\\testObj.dict.pickle", "wb") as pickleFile:
		pickle.dump(testObj, pickleFile)

	loadedObj = {}
	with open("OUTPUT\\testObj.dict.pickle", "rb") as pickleFileLoad:
		loadedObj = pickle.load(pickleFileLoad)

	print("loadedObj = {}".format(loadedObj))

	#Test pickling on econ agent
	farmer.saveCheckpoint()
	print(farmer)

	farmerSeed2 = AgentSeed("potatoFarmer_raw", agentType="TestProducer", itemDict=allItemsDict, disableNetworkLink=True, outputDir="testCheckpoint")
	farmerLoaded = farmerSeed2.spawnAgent()
	print(farmerLoaded)
	farmerLoaded.loadCheckpoint(filePath="testCheckpoint\\CHECKPOINT\\potatoFarmer.TestProducer.checkpoint.pickle")
	print(farmerLoaded)

	#print("farmerLoaded = {}".format(farmerLoaded))