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
	farmer.timeTicks = 48

	#Get initial production deltas
	dozenDeltas = farmer.getProductionInputDeltas("potato", 12)
	print("# A # dozenDeltas = {}".format(dozenDeltas))

	#Give agent needed production inputs
	allocate = True
	if (allocate):
		#print(farmer.landHoldings)
		farmer.receiveLand("UNALLOCATED", 2)
		#print(farmer.landHoldings)
		farmer.allocateLand("potato", 2)
		#print(farmer.landHoldings)
		farmer.useTimeTicks(12)
		#print(farmer.landHoldings)
		farmer.useTimeTicks(12)
		#print(farmer.landHoldings)
	else:
		farmer.receiveLand("potato", 2)
		#print(farmer.landHoldings)
	dozenDeltas = farmer.getProductionInputDeltas("potato", 12)
	print("# B # dozenDeltas = {}".format(dozenDeltas))


	farmer.receiveItem(ItemContainer("shovel", 1))
	dozenDeltas = farmer.getProductionInputDeltas("potato", 12)
	print("# C # dozenDeltas = {}".format(dozenDeltas))

	lowSkillContract = LaborContract(employerId=None, workerId=None, ticksPerStep=50, wagePerTick=10, workerSkillLevel=0.1, contractLength=10, startStep=0, endStep=10)
	farmer.laborContracts[10] = {}
	farmer.laborContracts[10]["A"] = lowSkillContract
	farmer.laborContracts[10]["B"] = lowSkillContract

	highSkillContract = LaborContract(employerId=None, workerId=None, ticksPerStep=16, wagePerTick=10, workerSkillLevel=0.9, contractLength=10, startStep=0, endStep=10)
	farmer.laborContracts[10]["C"] = highSkillContract

	farmer.laborInventory[0.6] = 50
	farmer.laborInventory[0.2] = 50
	dozenDeltas = farmer.getProductionInputDeltas("potato", 12)
	print("# D # dozenDeltas = {}".format(dozenDeltas))

	farmer.receiveItem(ItemContainer("water", 1000))
	dozenDeltas = farmer.getProductionInputDeltas("potato", 12)
	print("# E # dozenDeltas = {}".format(dozenDeltas))
	dozenDeficits = farmer.getProductionInputDeficit("potato", 12)
	print("# E # dozenDeficits = {}".format(dozenDeficits))
	dozenSurplus = farmer.getProductionInputSurplus("potato", 12)
	print("# E # dozenSurplus = {}".format(dozenSurplus))
	#maxQuant = farmer.getMaxProduction("potato")
	#print(maxQuant)

	#Produce some potatos
	#farmer.produceItem(ItemContainer("potato", 1))
	#print(farmer.inventory)
	#farmer.produceItem(ItemContainer("potato", 1))
	#print(farmer.inventory)
	#farmer.produceItem(ItemContainer("potato", 1))
	#print(farmer.inventory)