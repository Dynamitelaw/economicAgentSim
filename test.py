from EconAgent import *
import json
import random
import multiprocessing as mp
import os


allItemsDict = {}
for fileName in os.listdir("Items"):
	try:
		filePath = os.path.join("Items", fileName)
		itemDictFile = open(filePath, "r")
		itemDict = json.load(itemDictFile)
		itemDictFile.close()

		allItemsDict[itemDict["id"]] = itemDict
	except Exception as e:
		print(e)


if __name__ == "__main__":
	apple_5 = InventoryEntry("apple", 5)
	apple_3 = InventoryEntry("apple", 3)

	person1 = Agent(agentInfo=AgentInfo("person1", "human"), itemDict=allItemsDict)

	person1.receiveItem(apple_5)
	print(person1.inventory)
	person1.receiveItem(apple_3)
	print(person1.inventory)

	apple_5 += "Hello"
