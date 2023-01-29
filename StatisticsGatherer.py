'''
The StatisticsGatherer gathers and calculates statistics during a simulation
'''
import json
import os
import logging
import time
import traceback
import threading
import statistics
from sortedcontainers import SortedList

from EconAgent import *
from NetworkClasses import *
from TradeClasses import *
import utils


#######################
# Stat Calculators
#######################
class ConsumptionTracker:
	'''
	Keeps track of consumption over time
	'''
	def __init__(self, gathererParent, settings, name, outputDir="OUTPUT"):
		self.gathererParent = gathererParent
		self.settings = settings
		self.logger = gathererParent.logger
		self.name = "{}.ConsumptionTracker".format(name)
		self.lockTimout = 5

		self.outputPath = os.path.join(outputDir, "Statistics", "Consumption.csv")
		if ("OuputPath" in settings):
			self.outputPath = os.path.join(outputDir, "Statistics", settings["OuputPath"])
		utils.createFolderPath(self.outputPath)

		self.outputFile = open(self.outputPath, "w")
		self.columns = ["DayStepNumber", "Consumption(cents)"]
		csvHeader = ",".join(self.columns)+"\n"
		self.outputFile.write(csvHeader)

		self.startStep = 0
		if ("StartStep" in settings):
			self.startStep = int(settings["StartStep"])

		self.stepNum = -1
		self.stepNumLock = threading.Lock()
		self.netConsumption = 0
		self.netConsumptionLock = threading.Lock()

		self.consumerClasses = []
		if ("ConsumerClasses" in settings):
			self.consumerClasses = list(settings["ConsumerClasses"])

	def __str__(self):
		return str(self.name)

	def start(self):
		#Submit snoop requests
		self.gathererParent.startSnoop(self, "TRADE_REQ_ACK")

	def end(self):
		csvLine = "{},{}\n".format(self.stepNum, self.netConsumption)
		self.outputFile.write(csvLine)
		self.outputFile.close()

	def advanceStep(self):
		acquired_stepNumLock = self.stepNumLock.acquire(timeout=self.lockTimout)
		if (acquired_stepNumLock):
			acquired_netConsumptionLock = self.netConsumptionLock.acquire(timeout=self.lockTimout)
			if (acquired_netConsumptionLock):
				#Output data to csv
				if (self.stepNum >= self.startStep):
					csvLine = "{},{}\n".format(self.stepNum, self.netConsumption)
					self.outputFile.write(csvLine)

				self.stepNum += 1
				self.netConsumption = 0

				self.netConsumptionLock.release()
			else:
				self.logger.error("{}.advanceStep() Lock netConsumptionLock acquisition timout".format(self.name))

			self.stepNumLock.release()
		else:
			self.logger.error("{}.advanceStep() Lock stepNumLock acquisition timout".format(self.name))

	def handleSnoop(self, incommingPacket):
		if (self.stepNum >= self.startStep):
			#Handle incomming snooped packet
			if (incommingPacket.msgType == "TRADE_REQ_ACK"):
				if (incommingPacket.payload["accepted"]):
					#This item trade request was accepted
					tradeRequest = incommingPacket.payload["tradeRequest"]
					buyerId = tradeRequest.buyerId

					#Check the buyerId to make sure it was a consumer
					buyerConsumer = False
					if (len(self.consumerClasses) == 0):
						#No consumer classes specified. Will keep track of ALL consumption
						buyerConsumer = True
					else:
						for consumerClass in self.consumerClasses:
							if (consumerClass in buyerId):
								#The buying agent is a consumer
								buyerConsumer = True
								break

					if (buyerConsumer):
						#The buying agent is a consumer. Increment net consumption
						acquired_netConsumptionLock = self.netConsumptionLock.acquire(timeout=self.lockTimout)
						if (acquired_netConsumptionLock):
							self.netConsumption += tradeRequest.currencyAmount
							self.netConsumptionLock.release()
						else:
							self.logger.error("{}.handleSnoop() Lock netConsumptionLock acquisition timout".format(self.name))


class ItemPriceTracker:
	'''
	Keeps track of price and quantity purchased of an item over time
	'''
	def __init__(self, gathererParent, settings, name, outputDir="OUTPUT"):
		self.gathererParent = gathererParent
		self.settings = settings
		self.logger = gathererParent.logger
		self.name = "{}.ItemPriceTracker".format(name)
		self.lockTimout = 5

		if not ("id" in settings):
			errorMsg = "{}.ItemPriceTracker: \"id\" field is not specified in settings {}".format(name, settings)
			self.logger.critical(errorMsg)
			raise ValueError(errorMsg)
		self.itemId = settings["id"]

		self.outputPath = os.path.join(outputDir, "Statistics", "Price_{}.csv".format(self.itemId))
		if ("OuputPath" in settings):
			self.outputPath = os.path.join(outputDir, "Statistics", settings["OuputPath"])
		utils.createFolderPath(self.outputPath)

		self.outputFile = open(self.outputPath, "w")
		itemUnit = "unit"
		if (self.itemId in self.gathererParent.itemDict):
			itemUnit = "{}".format(self.gathererParent.itemDict[self.itemId]["unit"])
		self.columns = ["DayStepNumber", "MinPrice(cents/{})".format(itemUnit), "MaxPrice(cents/{})".format(itemUnit), "MeanPrice(cents/{})".format(itemUnit), "MedianPrice(cents/{})".format(itemUnit), "QuantityPurchased({})".format(itemUnit)]
		csvHeader = ",".join(self.columns)+"\n"
		self.outputFile.write(csvHeader)

		self.startStep = 0
		if ("StartStep" in settings):
			self.startStep = int(settings["StartStep"])

		self.stepNum = -1
		self.stepNumLock = threading.Lock()
		self.unitPrices = []
		self.prevMin = -1
		self.prevMax = -1
		self.prevMedian = -1
		self.prevMean = -1
		self.quantityPurchased = 0
		self.priceTrackingLock = threading.Lock()

	def __str__(self):
		return str(self.name)

	def start(self):
		#Submit snoop requests
		self.gathererParent.startSnoop(self, "TRADE_REQ_ACK")

	def end(self):
		#Get datapoints
		minPrice = self.prevMin
		maxPrice = self.prevMax
		medianPrice = self.prevMedian
		meanPrice = self.prevMean
		if (len(self.unitPrices) > 0):
			minPrice = min(self.unitPrices)
			maxPrice = max(self.unitPrices)
			medianPrice = statistics.median(self.unitPrices)
			meanPrice = statistics.mean(self.unitPrices)

			self.prevMin = minPrice
			self.prevMax = maxPrice
			self.prevMedian = medianPrice
			self.prevMean = meanPrice

		#Output data to csv
		if (self.stepNum != -1):
			csvLine = "{},{},{},{},{},{}\n".format(self.stepNum, minPrice, maxPrice, meanPrice, medianPrice, self.quantityPurchased)
			self.outputFile.write(csvLine)

		#Close output file
		self.outputFile.close()

	def advanceStep(self):
		acquired_stepNumLock = self.stepNumLock.acquire(timeout=self.lockTimout)
		if (acquired_stepNumLock):
			acquired_priceTrackingLock = self.priceTrackingLock.acquire(timeout=self.lockTimout)
			if (acquired_priceTrackingLock):
				#Get datapoints
				minPrice = self.prevMin
				maxPrice = self.prevMax
				medianPrice = self.prevMedian
				meanPrice = self.prevMean
				if (len(self.unitPrices) > 0):
					minPrice = min(self.unitPrices)
					maxPrice = max(self.unitPrices)
					medianPrice = statistics.median(self.unitPrices)
					meanPrice = statistics.mean(self.unitPrices)

					self.prevMin = minPrice
					self.prevMax = maxPrice
					self.prevMedian = medianPrice
					self.prevMean = meanPrice

				#Output data to csv
				if (self.stepNum >= self.startStep):
					csvLine = "{},{},{},{},{},{}\n".format(self.stepNum, minPrice, maxPrice, meanPrice, medianPrice, self.quantityPurchased)
					self.outputFile.write(csvLine)

				#Advance to next step
				self.unitPrices = []
				self.quantityPurchased = 0
				self.stepNum += 1

				self.priceTrackingLock.release()
			else:
				self.logger.error("{}.advanceStep() Lock priceTrackingLock acquisition timout".format(self.name))

			self.stepNumLock.release()
		else:
			self.logger.error("{}.advanceStep() Lock stepNumLock acquisition timout".format(self.name))

	def handleSnoop(self, incommingPacket):
		itemPackage = incommingPacket.payload["tradeRequest"].itemPackage
		itemId = itemPackage.id
		if (itemId == self.itemId):
			#This trade is for the item we're looking for

			if (self.stepNum >= self.startStep):
				#Handle incomming snooped packet
				if (incommingPacket.msgType == "TRADE_REQ_ACK"):
					if (incommingPacket.payload["accepted"]):
						#This item trade request was accepted
						quantity = itemPackage.quantity
						if (quantity > 0):
							tradeRequest = incommingPacket.payload["tradeRequest"]
							currencyAmount = tradeRequest.currencyAmount
							unitPrice = currencyAmount/quantity

							acquired_priceTrackingLock = self.priceTrackingLock.acquire(timeout=self.lockTimout)
							if (acquired_priceTrackingLock):
								self.unitPrices.append(unitPrice)
								self.quantityPurchased += quantity
								self.priceTrackingLock.release()
							else:
								self.logger.error("{}.handleSnoop() Lock priceTrackingLock acquisition timout B".format(self.name))


class LaborContractTracker:
	'''
	Keeps track of signed labor contracts over time
	'''
	def __init__(self, gathererParent, settings, name, outputDir="OUTPUT"):
		self.gathererParent = gathererParent
		self.settings = settings
		self.logger = gathererParent.logger
		self.name = "{}.LaborContractTracker".format(name)
		self.lockTimout = 5

		self.startStep = 0
		if ("StartStep" in settings):
			self.startStep = int(settings["StartStep"])

		self.stepNum = -1
		self.stepNumLock = threading.Lock()
		
		#Keep track of contracts
		self.hourWageListSorted = SortedList()
		self.hourWageTotal = 0

		self.hoursListSorted = SortedList()
		self.hoursTotal = 0

		self.dayWageListSorted = SortedList()
		self.dayWageTotal = 0

		self.listLen = 0
		self.endTimes = {}
		self.endMappingDict = {"hourWage": self.hourWageListSorted, "hours": self.hoursListSorted, "dayWage": self.dayWageListSorted}

		self.wageMetricsLock = threading.Lock()

		#Keep track of labor statistics
		self.hourWageMin = -1
		self.hourWageMax = -1
		self.hourWageMean = -1
		self.hourWageMedian = -1
		
		self.hourMin = -1
		self.hourMax = -1
		self.hourMean = -1
		self.hourMedian = -1

		self.dayWageMin = -1
		self.dayWageMax = -1
		self.dayWageMean = -1
		self.dayWageMedian = -1

		#Set skill boundaries
		self.minSkill = 0
		if ("SkillMin" in settings):
			self.minSkill = float(settings["SkillMin"])
		self.maxSkill = 1
		if ("SkillMax" in settings):
			self.maxSkill = float(settings["SkillMax"])

		#Set agent filters
		self.workerClassSet = False
		self.workerClasses = []
		if ("WorkerClasses" in settings):
			self.workerClassSet = True
			self.workerClasses = settings["WorkerClasses"]

		self.employerClassSet = False
		self.employerClasses = []
		if ("EmployerClasses" in settings):
			self.employerClassSet = True
			self.employerClasses = settings["EmployerClasses"]

		#Initialize output file
		self.outputPath = os.path.join(outputDir, "Statistics", "LaborContractTracker_{}_{}.csv".format(self.minSkill, self.maxSkill))
		if ("OuputPath" in settings):
			self.outputPath = os.path.join(outputDir, "Statistics", settings["OuputPath"])
		utils.createFolderPath(self.outputPath)

		self.outputFile = open(self.outputPath, "w")
		self.columns = ["DayStepNumber", 
		"MinHourWage(cents)", "MaxHourWage(cents)", "MeanHourWage(cents)", "MedianHourWage(cents)", 
		"MinHoursPerDay", "MaxHoursPerDay", "MeanHoursPerDay", "MedianHoursPerDay",
		"MinDailyWage(cents)", "MaxDailyWage(cents)", "MeanDailyWage(cents)", "MedianDailyWage(cents)",
		"Quantity"]
		csvHeader = ",".join(self.columns)+"\n"
		self.outputFile.write(csvHeader)

	def __str__(self):
		return str(self.name)

	def start(self):
		#Submit snoop requests
		self.gathererParent.startSnoop(self, "LABOR_APPLICATION_ACK")

	def end(self):
		rowData = [self.stepNum,
		self.hourWageMin, self.hourWageMax, self.hourWageMean, self.hourWageMedian,
		self.hourMin, self.hourMax, self.hourMean, self.hourMedian,
		self.dayWageMin, self.dayWageMax, self.dayWageMean, self.dayWageMedian,
		self.listLen]
		csvLine = "{}\n".format(",".join([str(i) for i in rowData]))
		self.outputFile.write(csvLine)
		self.outputFile.close()

	def advanceStep(self):
		acquired_stepNumLock = self.stepNumLock.acquire(timeout=self.lockTimout)
		if (acquired_stepNumLock):
			acquired_wageMetricsLock = self.wageMetricsLock.acquire(timeout=self.lockTimout)
			if (acquired_wageMetricsLock):
				#Update labor statistics
				if (self.listLen > 0):
					self.hourWageMin = self.hourWageListSorted[0]
					self.hourWageMax = self.hourWageListSorted[-1]
					self.hourWageMean = self.hourWageTotal/self.listLen
					self.hourWageMedian = self.hourWageListSorted[int(self.listLen/2)]

					self.hourMin = self.hoursListSorted[0]
					self.hourMax = self.hoursListSorted[-1]
					self.hourMean = self.hoursTotal/self.listLen
					self.hourMedian = self.hoursListSorted[int(self.listLen/2)]

					self.dayWageMin = self.dayWageListSorted[0]
					self.dayWageMax = self.dayWageListSorted[-1]
					self.dayWageMean = self.dayWageTotal/self.listLen
					self.dayWageMedian = self.dayWageListSorted[int(self.listLen/2)]

				#Output stats to csv
				if (self.stepNum >= self.startStep):
					rowData = [self.stepNum,
					self.hourWageMin, self.hourWageMax, self.hourWageMean, self.hourWageMedian,
					self.hourMin, self.hourMax, self.hourMean, self.hourMedian,
					self.dayWageMin, self.dayWageMax, self.dayWageMean, self.dayWageMedian,
					self.listLen]
					csvLine = "{}\n".format(",".join([str(i) for i in rowData]))
					self.outputFile.write(csvLine)

				#Increment step
				self.stepNum += 1
				#Remove stale labor contracts
				if (self.stepNum in self.endTimes):
					staleMetrics = self.endTimes[self.stepNum]
					for key in staleMetrics:
						removalList = staleMetrics[key]
						sortedList = self.endMappingDict[key]
						for metric in removalList:
							#Remove from sorted list
							sortedList.remove(metric)

							#Decrement counters
							if (key == "hourWage"):
								self.hourWageTotal -= metric
							if (key == "hours"):
								self.hoursTotal -= metric
							if (key == "dayWage"):
								self.dayWageTotal -= metric

						if (key == "hourWage"):
							self.listLen -= len(removalList)

					del self.endTimes[self.stepNum]

				self.wageMetricsLock.release()
			else:
				self.logger.error("{}.advanceStep() Lock wageMetricsLock acquisition timout".format(self.name))

			self.stepNumLock.release()
		else:
			self.logger.error("{}.advanceStep() Lock stepNumLock acquisition timout".format(self.name))

	def handleSnoop(self, incommingPacket):
		if (self.stepNum >= self.startStep):
			#Handle incomming snooped packet
			if (incommingPacket.msgType == "LABOR_APPLICATION_ACK"):
				if (incommingPacket.payload["accepted"]):
					#This labor application was accepted
					laborContract = incommingPacket.payload["laborContract"]
					skillLevel = laborContract.workerSkillLevel
					if ((skillLevel >= self.minSkill) and (skillLevel < self.maxSkill)):  #Skill level is within range
						#Make sure this employee is valid
						if (self.workerClassSet):  #Employee class has been specified
							contractWorkerId = laborContract.workerId
							workerValid = False
							for workerType in self.workerClasses:
								if (workerType in contractWorkerId):
									workerValid = True
									break

							if not (workerValid):
								#This worker type is not valid. Skip this contract
								return

						#Make sure this employer is valid
						if (self.employerClassSet):  #Employer class has been specified
							contractEmployerId = laborContract.employerId
							employerValid = False
							for employerType in self.employerClasses:
								if (employerType in contractEmployerId):
									employerValid = True
									break

							if not (employerValid):
								#This employer type is not valid. Skip this contract
								return

						#This contract passes all our filters. Add it to our metrics
						acquired_wageMetricsLock = self.wageMetricsLock.acquire(timeout=self.lockTimout)
						if (acquired_wageMetricsLock):
							#Get contract metrics
							hourlyWage = laborContract.wagePerTick
							hours = laborContract.ticksPerStep
							dailyWage = laborContract.wagePerTick * laborContract.ticksPerStep

							#Add metrics to endStep dict
							endStep = laborContract.endStep  #TODO: Handle startStep
							if not (endStep in self.endTimes):
								self.endTimes[endStep] = {}
								self.endTimes[endStep]["hourWage"] = []
								self.endTimes[endStep]["hours"] = []
								self.endTimes[endStep]["dayWage"] = []

							self.endTimes[endStep]["hourWage"].append(hourlyWage)
							self.endTimes[endStep]["hours"].append(hours)
							self.endTimes[endStep]["dayWage"].append(dailyWage)

							#Add metrics to sorted lists
							self.hourWageListSorted.add(hourlyWage)
							self.hoursListSorted.add(hours)
							self.dayWageListSorted.add(dailyWage)

							#Increment running totals
							self.hourWageTotal += hourlyWage
							self.hoursTotal += hours
							self.dayWageTotal += dailyWage

							self.listLen += 1

							self.wageMetricsLock.release()
						else:
							self.logger.error("{}.handleSnoop() Lock wageMetricsLock acquisition timout".format(self.name))


class ProductionTracker:
	'''
	Keeps track of the production of an item
	'''
	def __init__(self, gathererParent, settings, name, outputDir="OUTPUT"):
		self.gathererParent = gathererParent
		self.settings = settings
		self.logger = gathererParent.logger
		self.name = "{}.ProductionTracker".format(name)
		self.lockTimout = 5

		if not ("id" in settings):
			errorMsg = "{}.ProductionTracker: \"id\" field is not specified in settings {}".format(name, settings)
			self.logger.critical(errorMsg)
			raise ValueError(errorMsg)
		self.itemId = settings["id"]

		self.outputPath = os.path.join(outputDir, "Statistics", "Production_{}.csv".format(self.itemId))
		if ("OuputPath" in settings):
			self.outputPath = os.path.join(outputDir, "Statistics", settings["OuputPath"])
		utils.createFolderPath(self.outputPath)

		self.outputFile = open(self.outputPath, "w")
		itemUnit = "unit"
		if (self.itemId in self.gathererParent.itemDict):
			itemUnit = "{}".format(self.gathererParent.itemDict[self.itemId]["unit"])
		self.columns = ["DayStepNumber", "QuantityProduced({})".format(itemUnit)]
		csvHeader = ",".join(self.columns)+"\n"
		self.outputFile.write(csvHeader)

		self.startStep = 0
		if ("StartStep" in settings):
			self.startStep = int(settings["StartStep"])

		self.stepNum = -1
		self.stepNumLock = threading.Lock()
		self.quantityProduced = 0
		self.quantityProducedLock = threading.Lock()

	def __str__(self):
		return str(self.name)

	def start(self):
		#Submit snoop requests
		self.gathererParent.startSnoop(self, "PRODUCTION_NOTIFICATION")

	def end(self):
		#Output data to csv
		if (self.stepNum != -1):
			csvLine = "{},{}\n".format(self.stepNum, self.quantityProduced)
			self.outputFile.write(csvLine)

		#Close output file
		self.outputFile.close()

	def advanceStep(self):
		acquired_stepNumLock = self.stepNumLock.acquire(timeout=self.lockTimout)
		if (acquired_stepNumLock):
			acquired_quantityProducedLock = self.quantityProducedLock.acquire(timeout=self.lockTimout)
			if (acquired_quantityProducedLock):
				#Output data to csv
				if (self.stepNum >= self.startStep):
					csvLine = "{},{}\n".format(self.stepNum, self.quantityProduced)
					self.outputFile.write(csvLine)

				#Advance to next step
				self.quantityProduced = 0
				self.stepNum += 1

				self.quantityProducedLock.release()
			else:
				self.logger.error("{}.advanceStep() Lock quantityProducedLock acquisition timout".format(self.name))

			self.stepNumLock.release()
		else:
			self.logger.error("{}.advanceStep() Lock stepNumLock acquisition timout".format(self.name))

	def handleSnoop(self, incommingPacket):
		itemPackage = incommingPacket.payload
		itemId = itemPackage.id
		if (itemId == self.itemId):
			#This trade is for the item we're looking for

			if (self.stepNum >= self.startStep):
				#Step number is fine. Add to production total
				quantity = itemPackage.quantity

				acquired_quantityProducedLock = self.quantityProducedLock.acquire(timeout=self.lockTimout)
				if (acquired_quantityProducedLock):
					self.quantityProduced += quantity
					self.quantityProducedLock.release()
				else:
					self.logger.error("{}.handleSnoop() Lock quantityProducedLock acquisition timout B".format(self.name))


class AccountingTracker:
	'''
	Keeps track of agent accounting stats
	'''
	def __init__(self, gathererParent, settings, name, outputDir="OUTPUT"):
		self.gathererParent = gathererParent
		self.settings = settings
		self.logger = gathererParent.logger
		self.name = "{}.AccountingTracker".format(name)
		self.lockTimout = 5

		self.outputPath = os.path.join(outputDir, "Statistics", "Accounting.csv")
		if ("OuputPath" in settings):
			self.outputPath = os.path.join(outputDir, "Statistics", settings["OuputPath"])
		utils.createFolderPath(self.outputPath)

		self.outputFile = open(self.outputPath, "w")
		self.columns = ["DayStepNumber", 
		"CurrencyInflowMedian", "CurrencyOutflowMedian",
		"ProfitMedian", "ProfitMarginMedian"]
		csvHeader = ",".join(self.columns)+"\n"
		self.outputFile.write(csvHeader)

		self.startStep = 0
		if ("StartStep" in settings):
			self.startStep = int(settings["StartStep"])

		self.stepNum = -1
		self.stepNumLock = threading.Lock()

		#Keep track of accounting stats
		self.statLock = threading.Lock()
		self.currencyInflows = SortedList()
		self.currencyOutflows = SortedList()
		self.profits = SortedList()
		self.profitMargins = SortedList()

		self.agentFilters = [""]
		if ("AgentFilters" in settings):
			self.agentFilters = list(settings["AgentFilters"])

	def __str__(self):
		return str(self.name)

	def start(self):
		pass

	def end(self):
		self.outputFile.close()

	def addInfo(self, infoReq):
		acquired_statLock = self.statLock.acquire(timeout=self.lockTimout)
		if (acquired_statLock):
			statsDict = infoReq.info
			self.currencyInflows.add(statsDict["stepCurrencyInflow"])
			self.currencyOutflows.add(statsDict["stepCurrencyOutflow"])
			self.profits.add(statsDict["stepCurrencyInflow"]-statsDict["stepCurrencyOutflow"])
			if (statsDict["stepCurrencyOutflow"] > 0):
				self.profitMargins.add((statsDict["stepCurrencyInflow"]-statsDict["stepCurrencyOutflow"])/statsDict["stepCurrencyOutflow"])

			self.statLock.release()
		else:
			self.logger.error("{}.addInfo() Lock statLock acquisition timout".format(self.name))

	def getCsvLine(self):
		DayStepNumber = self.stepNum-1
		csvLine = ""
		if (DayStepNumber >= self.startStep):
			CurrencyInflowMedian = 0
			currencyInflowLen = len(self.currencyInflows)
			if (currencyInflowLen > 0):
				CurrencyInflowMedian = self.currencyInflows[int(currencyInflowLen/2)]

			CurrencyOutflowMedian = 0
			currencyOutflowLen = len(self.currencyOutflows)
			if (currencyOutflowLen > 0):
				CurrencyOutflowMedian = self.currencyOutflows[int(currencyOutflowLen/2)]

			ProfitMedian = 0
			profitLen = len(self.profits)
			if (profitLen > 0):
				ProfitMedian = self.profits[int(profitLen/2)]

			ProfitMarginMedian = 0
			profitMarginLen = len(self.profitMargins)
			if (profitMarginLen > 0):
				ProfitMarginMedian = self.profitMargins[int(profitMarginLen/2)]

			rowData = [DayStepNumber, CurrencyInflowMedian, CurrencyOutflowMedian, ProfitMedian, ProfitMarginMedian]

			csvLine = ",".join([str(i) for i in rowData])
			csvLine = "{}\n".format(csvLine)

		return csvLine

	def advanceStep(self):
		#Update CSV with previous step data
		acquired_stepNumLock = self.stepNumLock.acquire(timeout=self.lockTimout)
		if (acquired_stepNumLock):
			acquired_statLock = self.statLock.acquire(timeout=self.lockTimout)
			if (acquired_statLock):
				#Output data to csv
				if (self.stepNum >= self.startStep):
					csvLine = self.getCsvLine()
					self.outputFile.write(csvLine)

				self.stepNum += 1
				self.currencyInflows.clear()
				self.currencyOutflows.clear()
				self.profits.clear()

				self.statLock.release()
			else:
				self.logger.error("{}.advanceStep() Lock statLock acquisition timout".format(self.name))

			self.stepNumLock.release()
		else:
			self.logger.error("{}.advanceStep() Lock stepNumLock acquisition timout".format(self.name))

		#Obtain new step data
		for agentFilter in self.agentFilters:
			infoReq = InfoRequest(requesterId=self.gathererParent.agentId, transactionId=self.name, agentFilter=agentFilter, infoKey="acountingStats")
			self.gathererParent.sendInfoReqBroadcast(self, infoReq)

	def handleInfoResp(self, incommingPacket):
		if (self.stepNum >= self.startStep):
			#Handle incomming info packet
			if (incommingPacket.msgType == "INFO_RESP"):
				infoReq = incommingPacket.payload
				if (infoReq.infoKey == "acountingStats"):
					if (infoReq.transactionId == self.name):
						self.addInfo(infoReq)


#######################
# StatisticsGatherer
#######################
class StatisticsGatherer:
	'''
	The StatisticsGatherer gathers and calculates statistics during a simulation
	'''
	def __init__(self, settings={}, itemDict=None, networkLink=None, logFile=True, fileLevel="INFO", outputDir="OUTPUT"):
		self.agentId = "StatisticsGatherer"

		self.logger = utils.getLogger(self.agentId, console="WARNING", logFile=logFile, fileLevel=fileLevel, outputdir=os.path.join(outputDir, "LOGS"))
		self.logger.info("{} instantiated".format(self.agentId))

		self.itemDict = itemDict
		self.lockTimeout = 5

		#Pipe connections to the connection network
		self.networkLink = networkLink
		self.networkSendLock = threading.Lock()
		self.responseBuffer = {}
		self.responseBufferLock = threading.Lock()

		#Statistics trackers
		self.settings = settings
		self.trackers = []
		if ("Statistics" in settings):
			for statName in settings["Statistics"]:
				for trackerType in settings["Statistics"][statName]:
					if (trackerType=="ConsumptionTracker"):
						self.logger.info("Spawning ConsumptionTracker({}) for {}".format(settings["Statistics"][statName][trackerType], statName))
						trackerObj = ConsumptionTracker(self, settings["Statistics"][statName][trackerType], statName, outputDir=outputDir)
						self.trackers.append(trackerObj)
					elif (trackerType=="ItemPriceTracker"):
						self.logger.info("Spawning ItemPriceTracker({}) for {}".format(settings["Statistics"][statName][trackerType], statName))
						trackerObj = ItemPriceTracker(self, settings["Statistics"][statName][trackerType], statName, outputDir=outputDir)
						self.trackers.append(trackerObj)
					elif (trackerType=="LaborContractTracker"):
						self.logger.info("Spawning LaborContractTracker({}) for {}".format(settings["Statistics"][statName][trackerType], statName))
						trackerObj = LaborContractTracker(self, settings["Statistics"][statName][trackerType], statName, outputDir=outputDir)
						self.trackers.append(trackerObj)
					elif (trackerType=="ProductionTracker"):
						self.logger.info("Spawning ProductionTracker({}) for {}".format(settings["Statistics"][statName][trackerType], statName))
						trackerObj = ProductionTracker(self, settings["Statistics"][statName][trackerType], statName, outputDir=outputDir)
						self.trackers.append(trackerObj)
					elif (trackerType=="AccountingTracker"):
						self.logger.info("Spawning AccountingTracker({}) for {}".format(settings["Statistics"][statName][trackerType], statName))
						trackerObj = AccountingTracker(self, settings["Statistics"][statName][trackerType], statName, outputDir=outputDir)
						self.trackers.append(trackerObj)
					else:
						self.logger.error("Unknown stat tracker \"{}\" specified in settings. Will not gather data for {}.{}".format(trackerType, statName, trackerType))

		#Snoopers
		self.snoopers = {}
		self.snoopersLock = threading.Lock()

		#Info reqs
		self.infoReqs = {}
		self.infoReqsLock = threading.Lock()

		#Start monitoring network link
		if (self.networkLink):
			linkMonitor = threading.Thread(target=self.monitorNetworkLink)
			linkMonitor.start()	


	def monitorNetworkLink(self):
		'''
		Monitor/handle incoming packets on the pipe link to the ConnectionNetork
		'''
		self.logger.info("Monitoring networkLink {}".format(self.networkLink))
		while True:
			incommingPacket = self.networkLink.recvPipe.recv()
			self.logger.info("INBOUND {}".format(incommingPacket))
			if ((incommingPacket.msgType == "KILL_PIPE_AGENT") or (incommingPacket.msgType == "KILL_ALL_BROADCAST")):
				#Kill the network pipe before exiting monitor
				killPacket = NetworkPacket(senderId=self.agentId, destinationId=self.agentId, msgType="KILL_PIPE_NETWORK")
				self.sendPacket(killPacket)
				self.logger.info("Killing networkLink {}".format(self.networkLink))
				break

			#Simulation start
			elif (incommingPacket.msgType == "CONTROLLER_START_BROADCAST"):
				self.startTrackers()

			#Hanle incoming tick grants
			elif ((incommingPacket.msgType == "TICK_GRANT") or (incommingPacket.msgType == "TICK_GRANT_BROADCAST")):
				for trackerObj in self.trackers:
					self.logger.info("Advancing step for {}".format(trackerObj))
					trackerObj.advanceStep()

			#Handle errors
			elif ("ERROR" in incommingPacket.msgType):
				self.logger.error("{} {}".format(incommingPacket, incommingPacket.payload))

			#Handle controller messages
			if ((incommingPacket.msgType == "CONTROLLER_MSG") or (incommingPacket.msgType == "CONTROLLER_MSG_BROADCAST")):
				controllerMsg = incommingPacket.payload
				self.logger.debug("INBOUND {}".format(controllerMsg))

				if (controllerMsg.msgType == "STOP_TRADING"):
					for trackerObj in self.trackers:
						self.logger.info("Ending {}".format(trackerObj))
						trackerObj.end()


		self.logger.info("Ending networkLink monitor".format(self.networkLink))


	def sendPacket(self, packet):
		#Send this packet over the network
		acquired_networkSendLock = self.networkSendLock.acquire(timeout=self.lockTimeout)
		if (acquired_networkSendLock):
			self.logger.info("OUTBOUND {}".format(packet))
			self.networkLink.sendPipe.send(packet)
			self.networkSendLock.release()
		else:
			self.logger.error("{}.sendPacket() Lock networkSendLock acquire timeout".format(self.agentId))


	def startTrackers(self):
		for trackerObj in self.trackers:
			self.logger.info("Starting {}".format(trackerObj))
			trackerObj.start()
	

	def startSnoop(self, trackerObj, msgType):
		#Setup snoop if not already done
		self.snoopersLock.acquire()
		if not (msgType in self.snoopers):
			self.snoopers[msgType] = []
			self.snoopersLock.release()

			#Send snoop request to ConnectionNetwork
			snoopRequest = {str(msgType): True}
			snoopStartPacket = NetworkPacket(senderId=self.agentId, msgType="SNOOP_START", payload=snoopRequest)

			self.logger.debug("Sending snoop request {}".format(snoopRequest))
			self.logger.debug("OUTBOUND {}".format(snoopStartPacket))
			self.sendPacket(snoopStartPacket)
		else:
			self.snoopersLock.release()

		#Add this tracker to the snoopers dict
		self.snoopersLock.acquire()
		self.snoopers[msgType].append(trackerObj)
		self.snoopersLock.release()

	def sendInfoReqBroadcast(self, trackerObj, infoReq):
		self.infoReqsLock.acquire()
		self.infoReqs[infoReq.transactionId] = trackerObj
		self.infoReqsLock.release()
		infoReqPacket = NetworkPacket(senderId=self.agentId, msgType="INFO_REQ_BROADCAST", payload=infoReq)
		self.sendPacket(infoReqPacket)


	def handleSnoop(self, snoopedPacket):
		#self.logger.debug("Snooped packet = {}".format(snoopedPacket))
		snoopType = snoopedPacket.msgType
		if (snoopType in self.snoopers):
			for trackerObj in self.snoopers[snoopType]:
				trackerObj.handleSnoop(snoopedPacket)

	def handleInfoResp(self, infoRespPacket):
		transactionId = infoRespPacket.payload.transactionId
		if (transactionId in self.infoReqs):
			self.infoReqs[transactionId].handleInfoResp(infoRespPacket)

