from PersonAgent import *
import json

itemDictFile = open("ItemDictionary.json", "r")
itemDict = json.load(itemDictFile)
itemDictFile.close()

person1 = PersonAgent(itemDict)

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