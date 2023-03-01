'''
Calibrates item settings to match target economic metrics	
'''
import argparse
import json
import traceback
import os
import shutil
import pandas as pd

from SimulationRunner import RunSimulation
import utils


class ItemNode:
	def __init__(self, itemDict, itemTree, targetPrice=None, targetQuant=None):
		self.id = itemDict["id"]
		self.dict = itemDict
		self.itemTree = itemTree

		self.targetPrice = targetPrice
		self.targetQuant = targetQuant
		self.variableItemInputs = itemDict["ProductionInputs"]["VariableCosts"]["VariableItemCosts"]
		self.variableLaborInputs = itemDict["ProductionInputs"]["VariableCosts"]["VariableLaborCosts"]

		self.priceNudges = []

	def nudgePrice(self, ratio, priceDict, wageDict, nudgeHistory=[]):
		#Do not process this nudge if it's circular
		if self.id in nudgeHistory:
			return

		#Calculate how much each input makes up our total marginal cost
		totalLaborCost = 0
		for skillLevel in self.variableLaborInputs:
			averageWage = wageDict[skillLevel]
			totalLaborCost += averageWage*self.variableLaborInputs[skillLevel]

		totalItemCost = 0
		itemCostTotals = {}
		for itemId in self.variableItemInputs:
			quantityNeeded = self.variableItemInputs[itemId]
			itemCost = priceDict[itemId]*quantityNeeded
			itemCostTotals[itemId] = itemCost
			totalItemCost += itemCost

		totalMarginalCost = totalLaborCost + totalItemCost
		laborCostRatio = totalLaborCost/totalMarginalCost
		itemCostRatios = {}
		for itemId in itemCostTotals:
			itemCostRatios[itemId] = itemCostTotals[itemId]/totalMarginalCost

		#Propogate nudges based on cost ratios
		newNudgeHistory = nudgeHistory.copy()
		newNudgeHistory.append(self.id)
		for itemId in itemCostRatios:
			inputNudgeRatio = ratio*itemCostRatios[itemId]
			inputNode = self.itemTree.getNode(itemId)
			inputNode.nudgePrice(inputNudgeRatio, priceDict, wageDict, nudgeHistory=newNudgeHistory)

def getItemAverages(csvPath):
	try:
		#Trim dataframe to most recent sample
		itemStatsDf = pd.read_csv(csvPath)
		numDataPoints = len(itemStatsDf.index)

		sampleDf = itemStatsDf
		sampleSize = 50
		if (numDataPoints > sampleSize):
			sampleSize = itemStatsDf.tail(sampleSize)

		#Get column names
		priceColumnName = None
		quantColumnName = None
		for columnName in sampleDf.columns:
			if ("MinPrice" in columnName):
				priceColumnName = columnName
			if ("QuantityPurchased" in columnName):
				quantColumnName = columnName

		if (not priceColumnName):
			raise ValueError("Could not find min price column")
		if (not quantColumnName):
			raise ValueError("Could not find quantity purchased column")

		#Get averages
		averageUnitPrice = sampleDf[priceColumnName].mean()
		averageQuantPurchased = sampleDf[quantColumnName].mean()

		return averageUnitPrice, averageQuantPurchased

	except:
		raise ValueError("Could not get averages from \"{}\"".format(csvPath))

def overwriteItemSetting(allItemsDict, itemOutputDirPath):
	if (os.path.exists(itemOutputDirPath)):
		shutil.rmtree(itemOutputDirPath)

	for itemId in allItemsDict:
		itemDict = allItemsDict[itemId]

		outputPath = os.path.join(itemOutputDirPath, "{}.json".format(itemId))
		if ("category" in itemDict):
			outputPath = os.path.join(itemOutputDirPath, itemDict["category"], "{}.json".format(itemId))

		utils.dictToJsonFile(itemDict, outputPath)

def calibrateEconomy(settingsFilePath):
	try:
		#Load calibration config
		if (not os.path.exists(settingsFilePath)):
			raise ValueError("\"{}\" does not exist".format(settingsFilePath))

		calibrationDict = {}
		try:
			file = open(settingsFilePath, "r")
			calibrationDict = json.load(file)
			file.close()
		except:
			print(traceback.format_exc())
			raise ValueError("Could not open \"{}\"".format(settingsFilePath))


		#Initialize sim settings
		simSettings = calibrationDict["Simulation"]["settings"]

		#Copy initial item settings to calibration dir
		calibrationDir = "CALIBRATION"
		itemOutputDirPath = os.path.join(calibrationDir, "Items")
		initialItemDir = "Items"
		if (os.path.exists(itemOutputDirPath)):
			shutil.rmtree(itemOutputDirPath)
		utils.createFolderPath(itemOutputDirPath)
		shutil.copytree(initialItemDir, itemOutputDirPath)
		simSettings["ItemSettings"] = itemOutputDirPath

		#Parse targets and add required statistics gathers
		allTargets = {}
		statisticsSettings = {}
		if ("ItemTargets" in calibrationDict["targets"]):
			try:
				#Read in item targets csv
				targetPath = calibrationDict["targets"]["ItemTargets"]
				if (not os.path.exists(targetPath)):
					#The path is not absolute or relative to cwd. See if it's relative to cfg file
					cfgFileDir = os.path.dirname(settingsFilePath)
					targetPath = os.path.join(cfgFileDir, targetPath)
					if (not os.path.exists(targetPath)):
						raise ValueError("\"{}\" does not exist".format(targetPath))
				
				targetsDf = pd.read_csv(targetPath)
				allTargets["ItemTargets"] = targetsDf

				for index, row in targetsDf.iterrows():
					itemId = str(row["ItemId"])

					trackerType = "ItemPriceTracker"
					trackerName = "{}{}".format(itemId, trackerType)
					statOutputPath = "{}.csv".format(trackerName)

					statisticsSettings[trackerName] = {}
					statisticsSettings[trackerName][trackerType] = {"id": itemId, "OuputPath": statOutputPath}

			except:
				raise ValueError("Could not load item targets")

		simSettings["Statistics"] = statisticsSettings

		#Loop sim until calibration complete
		simOutputPath = os.path.join(calibrationDir, "SIM_OUTPUT")
		calibrationFinished = False
		iterationCntr = 0
		while (not calibrationFinished):
			print("### Calibration Iteration {} ###".format(iterationCntr))

			#Load item dict
			allItemsDict = utils.loadItemDict(itemOutputDirPath)

			#Run simulation
			RunSimulation(simSettings, "ERROR", outputDir=simOutputPath)

			#Get metrtics
			itemAdjustments = {}
			for targetType in allTargets:
				if (targetType == "ItemTargets"):
					itemVariance = 0.05
					itemTargetsDf = allTargets["ItemTargets"]
					for index, row in itemTargetsDf.iterrows():
						itemId = str(row["ItemId"])

						#Get the price and quantity from the lastest simulation
						csvPath = os.path.join(simOutputPath, "Statistics", "{}ItemPriceTracker.csv".format(itemId))
						unitPrice, dailyConsumption = getItemAverages(csvPath)
						consumerPopulation = 480
						yearlyConsumptionPerCapita = (dailyConsumption*365)/consumerPopulation

						#Compare stats to targets
						adjustmentRatios = {}

						targetPrice = row["UnitPrice"]
						if (targetPrice > 0):
							adjustmentRatio = targetPrice/unitPrice
							if (abs(adjustmentRatio-1) > itemVariance):
								adjustmentRatios["UnitPrice"] = adjustmentRatio

						targetQuant = row["YearlyConsumptionPerCapita"]
						if (targetQuant > 0):
							adjustmentRatio= targetQuant/yearlyConsumptionPerCapita
							if (abs(adjustmentRatio-1) > itemVariance):
								adjustmentRatios["YearlyConsumptionPerCapita"] = adjustmentRatio

						if (len(adjustmentRatios) > 0):
							itemAdjustments[itemId] = adjustmentRatios

			#Modify settings to closer match targets
			greedyFactor = 0.4
			for itemId in itemAdjustments:
				adjustmentRatios = itemAdjustments[itemId]
				if ("UnitPrice" in adjustmentRatios):
					allItemsDict[itemId]["ProductionInputs"]["VariableCosts"]["VariableLaborCosts"]["0"] = pow(adjustmentRatios["UnitPrice"], greedyFactor)*allItemsDict[itemId]["ProductionInputs"]["VariableCosts"]["VariableLaborCosts"]["0"]
				if ("YearlyConsumptionPerCapita" in adjustmentRatios):
					allItemsDict[itemId]["UtilityFunctions"]["BaseUtility"]["mean"] = pow(adjustmentRatios["YearlyConsumptionPerCapita"], greedyFactor)*allItemsDict[itemId]["UtilityFunctions"]["BaseUtility"]["mean"]

			overwriteItemSetting(allItemsDict, itemOutputDirPath)

			#Check if the calibration is complete
			if (len(itemAdjustments) == 0) or (iterationCntr > 12):
				calibrationFinished = True
			iterationCntr += 1

			#Overwrite initial checkpoint
			newCheckpointDir = os.path.join(simOutputPath, "CHECKPOINT")
			simSettings["InitialCheckpoint"] = newCheckpointDir
			
			
		print("### Calibration complete!! ###")
		
	except:
		print(traceback.format_exc())

if __name__ == "__main__":
	parser = argparse.ArgumentParser()
	parser.add_argument("-cfg", dest="cfgPath", help="Path to calibration cfg json")

	args = parser.parse_args()

	settingsFilePath = args.cfgPath
	calibrateEconomy(settingsFilePath)