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
	def __init__(self, gathererParent, settings, name):
		self.gathererParent = gathererParent
		self.agent = gathererParent.agent
		self.settings = settings
		self.logger = gathererParent.logger
		self.name = "{}.ConsumptionTracker".format(name)
		self.lockTimout = 5

		self.outputPath = os.path.join("Statistics", "Consumption.csv")
		if ("OuputPath" in settings):
			self.outputPath = os.path.join("Statistics", settings["OuputPath"])
		utils.createFolderPath(self.outputPath)

		self.outputFile = open(self.outputPath, "w")
		self.columns = ["DayStepNumber", "Consumption(cents)"]
		csvHeader = ",".join(self.columns)+"\n"
		self.outputFile.write(csvHeader)

		self.startStep = 0
		if ("StartStep" in settings):
			self.startStep = int(settings["StartStep"])

		self.stepNum = self.agent.stepNum
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
	def __init__(self, gathererParent, settings, name):
		self.gathererParent = gathererParent
		self.agent = gathererParent.agent
		self.settings = settings
		self.logger = gathererParent.logger
		self.name = "{}.ConsumptionTracker".format(name)
		self.lockTimout = 5

		if not ("id" in settings):
			errorMsg = "{}.PriceTracker: \"id\" field is not specified in settings {}".format(name, settings)
			self.logger.critical(errorMsg)
			raise ValueError(errorMsg)
		self.itemId = settings["id"]

		self.outputPath = os.path.join("Statistics", "Price_{}.csv".format(self.itemId))
		if ("OuputPath" in settings):
			self.outputPath = os.path.join("Statistics", settings["OuputPath"])
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

		self.stepNum = self.agent.stepNum
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


#######################
# StatisticsGatherer
#######################
class StatisticsGathererSeed:
	'''
	Seed used to spawn a StatisticsGatherer
	'''
	def __init__(self, agentId, ticksPerStep=24, settings={}, simManagerId=None, itemDict=None, allAgentDict=None, logFile=True, fileLevel="INFO"):
		self.agentInfo = AgentInfo(agentId, "StatisticsGatherer")
		self.ticksPerStep = ticksPerStep
		self.settings = settings
		self.simManagerId = simManagerId
		self.itemDict = itemDict
		self.allAgentDict = allAgentDict
		self.logFile = logFile
		self.fileLevel = fileLevel

		networkPipeRecv, agentPipeSend = multiprocessing.Pipe()
		agentPipeRecv, networkPipeSend = multiprocessing.Pipe()

		self.networkLink = Link(sendPipe=networkPipeSend, recvPipe=networkPipeRecv)
		self.agentLink = Link(sendPipe=agentPipeSend, recvPipe=agentPipeRecv)

	def spawnGatherer(self):
		return StatisticsGatherer(self.agentInfo, simManagerId=self.simManagerId, ticksPerStep=self.ticksPerStep, settings=self.settings, itemDict=self.itemDict, allAgentDict=self.allAgentDict, networkLink=self.agentLink, logFile=self.logFile, fileLevel=self.fileLevel)

	def __str__(self):
		return "StatisticsGathererSeed({})".format(self.agentInfo)


class StatisticsGatherer:
	'''
	The StatisticsGatherer gathers and calculates statistics during a simulation
	'''
	def __init__(self, agentInfo, simManagerId=None, ticksPerStep=24, settings={}, itemDict=None, allAgentDict=None, networkLink=None, logFile=True, fileLevel="INFO"):
		self.info = agentInfo
		self.agentId = agentInfo.agentId
		self.agentType = agentInfo.agentType

		self.logger = utils.getLogger("{}:{}".format("StatisticsGatherer", self.agentId), console="WARNING", logFile=logFile, fileLevel=fileLevel)
		self.logger.info("{} instantiated".format(self.info))

		self.agentDict = allAgentDict
		self.itemDict = itemDict

		#Spawn agent
		self.agent = Agent(self.info, networkLink=networkLink, logFile=logFile, controller=self)

		#Statistics trackers
		self.settings = settings
		self.trackers = []
		if ("Statistics" in settings):
			for statName in settings["Statistics"]:
				for trackerType in settings["Statistics"][statName]:
					if (trackerType=="ConsumptionTracker"):
						self.logger.info("Spawning ConsumptionTracker({}) for {}".format(settings["Statistics"][statName][trackerType], statName))
						trackerObj = ConsumptionTracker(self, settings["Statistics"][statName][trackerType], statName)
						self.trackers.append(trackerObj)
					elif (trackerType=="ItemPriceTracker"):
						self.logger.info("Spawning ItemPriceTracker({}) for {}".format(settings["Statistics"][statName][trackerType], statName))
						trackerObj = ItemPriceTracker(self, settings["Statistics"][statName][trackerType], statName)
						self.trackers.append(trackerObj)
					else:
						self.logger.error("Unknown stat tracker \"{}\" specified in settings. Will not gather data for {}.{}".format(trackerType, statName, trackerType))

		#Snoopers
		self.snoopers = {}

	def controllerStart(self, incommingPacket):
		for trackerObj in self.trackers:
			self.logger.info("Starting {}".format(trackerObj))
			trackerObj.start()

	def receiveMsg(self, incommingPacket):
		self.logger.debug("INBOUND {}".format(incommingPacket))

		if ((incommingPacket.msgType == "CONTROLLER_MSG") or (incommingPacket.msgType == "CONTROLLER_MSG_BROADCAST")):
			controllerMsg = incommingPacket.payload
			#self.logger.debug("INBOUND {}".format(controllerMsg))

			if (controllerMsg.msgType == "STOP_TRADING"):
				for trackerObj in self.trackers:
					self.logger.info("Ending {}".format(trackerObj))
					trackerObj.end()

		if ((incommingPacket.msgType == "TICK_GRANT") or (incommingPacket.msgType == "TICK_GRANT_BROADCAST")):
				for trackerObj in self.trackers:
					self.logger.info("Advancing step for {}".format(trackerObj))
					trackerObj.advanceStep()

		if (incommingPacket.msgType == "SNOOP"):
			snoopedPacket = incommingPacket.payload
			snoopType = snoopedPacket.msgType
			if (snoopType in self.snoopers):
				for trackerObj in self.snoopers[snoopType]:
					trackerObj.handleSnoop(snoopedPacket)

	def startSnoop(self, trackerObj, msgType):
		#Add this tracker to the snoopers dict
		if not (msgType in self.snoopers):
			self.snoopers[msgType] = []

			#Send snoop request to ConnectionNetwork
			snoopRequest = {str(msgType): True}
			snoopStartPacket = NetworkPacket(senderId=self.agentId, msgType="SNOOP_START", payload=snoopRequest)

			self.logger.debug("Sending snoop request {}".format(snoopRequest))
			self.logger.debug("OUTBOUND {}".format(snoopStartPacket))
			self.agent.sendPacket(snoopStartPacket)

		self.snoopers[msgType].append(trackerObj)