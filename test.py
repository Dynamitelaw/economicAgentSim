from PersonAgent import *
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

person1 = PersonAgent("person1", allItemsDict)
person2 = PersonAgent("person2", allItemsDict)

if __name__ == "__main__":
	#Make sure utility functions work as expected
	print("# Potato")
	potatoUtilityFunc = person1.utilityFunctions["potato"]
	for i in range(0, 15):
		marginalUtility = potatoUtilityFunc.getMarginalUtility(i)
		totalUtility = potatoUtilityFunc.getTotalUtility(i)
		print("{} , {} , {}".format(i, totalUtility, marginalUtility))

	print("\n# Apple")
	appleUtilityFunc = person1.utilityFunctions["apple"]
	for i in range(0, 15):
		marginalUtility = appleUtilityFunc.getMarginalUtility(i)
		totalUtility = appleUtilityFunc.getTotalUtility(i)
		print("{} , {} , {}".format(i, totalUtility, marginalUtility))
