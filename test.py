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
	
	#Create test agent
	farmerSeed = AgentSeed("potatoFarmer", agentType="TestProducer", itemDict=allItemsDict, disableNetworkLink=True)
	farmer = farmerSeed.spawnAgent()
	farmer.timeTicks = 16

	#Give agent needed production inputs
	farmer.landHoldings["potato"] = 2

	farmer.receiveItem(ItemContainer("shovel", 1))

	farmer.laborInventory[0.6] = 8
	farmer.laborInventory[0.2] = 5

	farmer.receiveItem(ItemContainer("water", 1000))
	maxQuant = farmer.getMaxProduction("potato")
	print(maxQuant)

	#Produce some potatos
	farmer.produceItem(ItemContainer("potato", 1))
	print(farmer.inventory)
	farmer.produceItem(ItemContainer("potato", 1))
	print(farmer.inventory)
	farmer.produceItem(ItemContainer("potato", 1))
	print(farmer.inventory)