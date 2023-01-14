'''
The StatisticsGatherer gathers and calculates statistics during a simulation
'''
import json
import os
import logging
import time
import traceback
import threading

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

		self.outputFile = open(self.outputPath, "w")
		self.columns = ["DayStepNumber", "Consumption(cents)"]
		csvHeader = ",".join(self.columns)+"\n"
		self.outputFile.write(csvHeader)

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

	def handleSnoop(self, incommingPacket):
		#Check current step
		currentStep = self.agent.stepNum
		if (currentStep != self.stepNum):
			#Step num has changed. Acquire stepNumLock
			acquired_stepNumLock = self.stepNumLock.acquire(timeout=self.lockTimout)
			if (acquired_stepNumLock):
				#Check step num again to make sure it wasn't already updated
				currentStep = self.agent.stepNum
				if (currentStep != self.stepNum):
					#We are the first to get to update step number

					acquired_netConsumptionLock = self.netConsumptionLock.acquire(timeout=self.lockTimout)
					if (acquired_netConsumptionLock):
						#Output data to csv
						if (self.stepNum != -1):
							csvLine = "{},{}\n".format(self.stepNum, self.netConsumption)
							self.outputFile.write(csvLine)

						#Advance to next step
						self.stepNum = currentStep
						self.netConsumption = 0

						self.netConsumptionLock.release()
					else:
						self.logger.error("{}.handleSnoop() Lock netConsumptionLock acquisition timout A".format(self.name))

				self.stepNumLock.release()
			else:
				self.logger.error("{}.handleSnoop() Lock stepNumLock acquisition timout".format(self.name))

		#Handle incomming snooped packet
		if (incommingPacket.msgType == "TRADE_REQ_ACK"):
			self.logger.debug(incommingPacket.payload)
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
						self.logger.error("{}.handleSnoop() Lock netConsumptionLock acquisition timout B".format(self.name))


#######################
# StatisticsGatherer
#######################
class StatisticsGathererSeed:
	'''
	temp
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

		#Spawn agent
		self.agent = Agent(self.info, networkLink=networkLink, logFile=logFile, controller=self)

		#Statistics trackers
		self.settings = settings
		self.trackers = []
		for statName in settings["Statistics"]:
			for trackerType in settings["Statistics"][statName]:
				if (trackerType=="Consumption"):
					self.logger.info("Spawning ConsumptionTracker({}) for {}".format(settings["Statistics"][statName][trackerType], statName))
					trackerObj = ConsumptionTracker(self, settings["Statistics"][statName][trackerType], statName)
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
			self.logger.debug("INBOUND {}".format(controllerMsg))

			if (controllerMsg.msgType == "STOP_TRADING"):
				for trackerObj in self.trackers:
					self.logger.info("Ending {}".format(trackerObj))
					trackerObj.end()

		elif (incommingPacket.msgType == "SNOOP"):
			snoopedPacket = incommingPacket.payload
			snoopType = snoopedPacket.msgType
			if (snoopType in self.snoopers):
				for trackerObj in self.snoopers[snoopType]:
					trackerObj.handleSnoop(snoopedPacket)

	def startSnoop(self, trackerObj, msgType):
		#Add this tracker to the snoopers dict
		if not (msgType in self.snoopers):
			self.snoopers[msgType] = []
		self.snoopers[msgType].append(trackerObj)

		#Send snoop request to ConnectionNetwork
		snoopRequest = {str(msgType): True}
		snoopStartPacket = NetworkPacket(senderId=self.agentId, msgType="SNOOP_START", payload=snoopRequest)

		self.logger.debug("Sending snoop request {}".format(snoopRequest))
		self.logger.debug("OUTBOUND {}".format(snoopStartPacket))
		self.agent.sendPacket(snoopStartPacket)
