from EconAgent import *
import json
import random
import multiprocessing as mp
import os


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

	potatoFunction = ProductionFunction(allItemsDict["potato"], baseEfficiency=1)
	
	#Create test agent
	farmerSeed = AgentSeed("potatoFarmer", agentType="TestProducer")
	farmer = farmerSeed.spawnAgent()
	farmer.timeTicks = 16

	#Give agent needed production inputs
	#maxQuant = potatoFunction.getMaxProduction(farmer)
	#print(maxQuant)

	farmer.landHoldings["potato"] = 2
	#maxQuant = potatoFunction.getMaxProduction(farmer)
	#print(maxQuant)

	farmer.inventory["shovel"] = 1
	#maxQuant = potatoFunction.getMaxProduction(farmer)
	#print(maxQuant)

	farmer.laborInventory[0.6] = 8
	farmer.laborInventory[0.2] = 5
	#maxQuant = potatoFunction.getMaxProduction(farmer)
	#print(maxQuant)

	farmer.inventory["water"] = 900
	maxQuant = potatoFunction.getMaxProduction(farmer)
	print(maxQuant)