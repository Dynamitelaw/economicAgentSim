'''
The ConnectionNetwork is how all agents in the simulation communicate with each other. 
It is also the place where the StatisticsGather is instantiated.
It is also the place where all marketplaces are instantiated.

It's set up as a hub and spoke topology, where all agents have a single connection to the ConnectionNetwork object.
Each agent connection is monitored with it's own thread. 
Agents communicate using NetworkPacket objects. Each agent has a unique id to identify it on the network.

The ConnectionNetwork routes all packets to the specified recipient, or to all agents if msgTpye ends with "_BROADCAST", or to the specified marketplace.
The network also supports packet snooping, where an agent controller can request to be sent all packets of a specified type, regardless of recipient.

The network will route any packet with a valid destination, regardless of content.
A list of all currently-implemented packet types can be found at the bottom of this file.
'''
import multiprocessing
import threading
import hashlib
import time
import traceback

import utils
from NetworkClasses import *
from Marketplace import *
from StatisticsGatherer import *


class ConnectionNetwork:
	def __init__(self, itemDict, simManagerId=None, logFile=True, simulationSettings={}):
		self.id = "ConnectionNetwork"
		self.simManagerId = simManagerId

		self.logger = utils.getLogger("{}".format(__name__), logFile=logFile)
		self.lockTimeout = 5

		self.agentConnections = {}
		self.agentConnectionsLock = threading.Lock()
		self.sendLocks = {}

		self.snoopDict = {}
		self.snoopDictLock = threading.Lock()

		self.killAllFlag = False
		self.killAllLock = threading.Lock()

		#Instantiate Item Marketplace
		self.itemMarketplace = self.addMarketplace("ItemMarketplace", itemDict)
		self.laborMarketplace = self.addMarketplace("LaborMarketplace")
		self.landMarketplace = self.addMarketplace("LandMarketplace")

		#Instantiate statistics gatherer
		self.statsGatherer = self.addStatisticsGatherer(simulationSettings, itemDict, logFile)

		#Keep track of tick blockers
		self.simStarted = False
		self.tickBlocksMonitoring = False
		self.timeTickBlockers = {}
		self.timeTickBlockers_Lock = threading.Lock()

	def addConnection(self, agentId, networkLink):
		self.logger.info("Adding connection to {}".format(agentId))
		self.agentConnections[agentId] = networkLink
		self.sendLocks[agentId] = threading.Lock()

	def addMarketplace(self, marketType, marketDict=None):
		#Instantiate communication pipes
		networkPipeRecv, marketPipeSend = multiprocessing.Pipe()
		marketPipeRecv, networkPipeSend = multiprocessing.Pipe()

		market_networkLink = Link(sendPipe=networkPipeSend, recvPipe=networkPipeRecv)
		market_agentLink = Link(sendPipe=marketPipeSend, recvPipe=marketPipeRecv)

		#Instantiate marketplace
		marketplaceObj = None
		if (marketType=="ItemMarketplace"):
			marketplaceObj = ItemMarketplace(marketDict, market_agentLink, simManagerId=self.simManagerId)
			self.addConnection(marketplaceObj.agentId, market_networkLink)

		if (marketType=="LaborMarketplace"):
			marketplaceObj = LaborMarketplace(market_agentLink, simManagerId=self.simManagerId)
			self.addConnection(marketplaceObj.agentId, market_networkLink)

		if (marketType=="LandMarketplace"):
			marketplaceObj = LandMarketplace(market_agentLink, simManagerId=self.simManagerId)
			self.addConnection(marketplaceObj.agentId, market_networkLink)

		return marketplaceObj

	def addStatisticsGatherer(self, settings, itemDict, logFile=True):
		#Instantiate communication pipes
		networkPipeRecv, marketPipeSend = multiprocessing.Pipe()
		marketPipeRecv, networkPipeSend = multiprocessing.Pipe()

		market_networkLink = Link(sendPipe=networkPipeSend, recvPipe=networkPipeRecv)
		market_agentLink = Link(sendPipe=marketPipeSend, recvPipe=marketPipeRecv)

		#Instantiate gatherer
		statsGatherer = StatisticsGatherer(settings=settings, itemDict=itemDict, networkLink=market_agentLink, logFile=logFile)
		self.addConnection(statsGatherer.agentId, market_networkLink)

		return statsGatherer

	def startMonitors(self):
		for agentId in self.agentConnections:
			monitorThread = threading.Thread(target=self.monitorLink, args=(agentId,))
			monitorThread.start()

	def sendPacket(self, pipeId, packet):
		self.logger.debug("ConnectionNetwork.sendPacket({}, {}) start".format(pipeId, packet))
		if (pipeId in self.agentConnections):
			self.logger.debug("Requesting lock sendLocks[{}]".format(pipeId))
			acquired_sendLock = self.sendLocks[pipeId].acquire()
			if (acquired_sendLock):
				self.logger.debug("Acquired lock sendLocks[{}]".format(pipeId))
				self.logger.info("OUTBOUND {} {}".format(packet, pipeId))
				self.agentConnections[pipeId].sendPipe.send(packet)
				self.sendLocks[pipeId].release()
				self.logger.debug("Release lock sendLocks[{}]".format(pipeId))
			else:
				self.logger.error("ConnectionNetwork.sendPacket() Lock sendLocks[{}] acquire timeout".format(pipeId))
		else:
			self.logger.warning("Cannot send {}. Pipe[{}] already killed".format(pipeId, packet))

	def setupSnoop(self, incommingPacket):
		'''
		Add this snoop request to snoop dict
		'''
		self.logger.debug("Handling snoop request {}".format(incommingPacket))
		self.snoopDictLock.acquire()  #<== snoopDictLock acquire
		try:
			snooperId = incommingPacket.senderId
			snoopTypeDict = incommingPacket.payload
			for msgType in snoopTypeDict:
				if (not msgType in self.snoopDict):
					self.snoopDict[msgType] = {}

				self.logger.debug("Adding snoop {} > {} ({})".format(msgType, snooperId, incommingPacket.payload[msgType]))
				self.snoopDict[msgType][snooperId] = incommingPacket.payload[msgType]

		except Exception as e:
			self.logger.error("Could not setup snoop {} | {}".format(incommingPacket, e))

		self.snoopDictLock.release()  #<== snoopDictLock release


	def monitorLink(self, agentId):
		agentLink = self.agentConnections[agentId]
		while True:
			self.logger.info("Monitoring {} link {}".format(agentId, agentLink))
			incommingPacket = agentLink.recvPipe.recv()
			self.logger.info("INBOUND {} {}".format(agentId, incommingPacket))
			destinationId = incommingPacket.destinationId

			#Handle kill packets
			if (incommingPacket.msgType == "KILL_PIPE_NETWORK"):
					#We've received a kill command for this pipe. Remove destPipe from connections, then kill this monitor thread
					self.logger.info("Killing pipe {} {}".format(agentId, agentLink))
					acquired_agentConnectionsLock = self.agentConnectionsLock.acquire(timeout=self.lockTimeout)  #<== acquire agentConnectionsLock
					if (acquired_agentConnectionsLock):
						del self.agentConnections[incommingPacket.senderId]
						del self.sendLocks[incommingPacket.senderId]
						self.agentConnectionsLock.release()  #<== release agentConnectionsLock
						break
					else:
						self.logger.error("monitorLink() Lock \"agentConnectionsLock\" acquisition timeout")
						break

			#Handle broadcasts
			elif ("_BROADCAST" in incommingPacket.msgType):
					#Check if this is a KILL_ALL broadcast
					if (incommingPacket.msgType == "KILL_ALL_BROADCAST"):
						self.killAllLock.acquire()
						if (self.killAllFlag):
							#All agents were already killed by another thread. Skip this broadcast
							self.logger.debug("killAllFlag has already been set. Ignoring {}".format(incommingPacket))
							continue

					#Check if this is the start of the sim
					if not (self.simStarted):
						if (incommingPacket.msgType == "TICK_GRANT_BROADCAST"):
							for agentId in self.timeTickBlockers:
								self.timeTickBlockers[agentId] = False
							self.simStarted = True

					#We've received a broadcast message. Foward to all pipes
					self.logger.debug("Fowarding broadcast")
					acquired_agentConnectionsLock = self.agentConnectionsLock.acquire()  #<== acquire agentConnectionsLock
					pipeIdList = list(self.agentConnections.keys())
					self.agentConnectionsLock.release()  #<== release agentConnectionsLock

					for pipeId in pipeIdList:
						self.sendPacket(pipeId, incommingPacket)

					self.logger.debug("Ending broadcast")

					#CSet killAllFlag
					if (incommingPacket.msgType == "KILL_ALL_BROADCAST"):
						self.logger.debug("Setting killAllFlag")
						self.killAllFlag = True
						self.killAllLock.release()

			#Handle snoop requests
			elif ("SNOOP_START" in incommingPacket.msgType):
					#We've received a snoop start request. Add to snooping dict
					self.setupSnoop(incommingPacket)

			#Handle tick block subscriptions
			elif ("TICK_BLOCK_SUBSCRIBE" in incommingPacket.msgType):
					self.logger.info("{} has subscribed to tick blocking".format(incommingPacket.senderId))
					self.timeTickBlockers_Lock.acquire()
					self.timeTickBlockers[incommingPacket.senderId] = True
					
					if not (self.tickBlocksMonitoring):
						self.tickBlocksMonitoring = True
						blockMonitorThread = threading.Thread(target=self.monitorTickBlockers)
						blockMonitorThread.start()

					self.timeTickBlockers_Lock.release()

			#Handle tick blocked packets
			elif ("TICK_BLOCKED" in incommingPacket.msgType):
					self.timeTickBlockers[incommingPacket.senderId] = True

			#Handle marketplace packets
			elif ("ITEM_MARKET" in incommingPacket.msgType):
					#We've received an item market packet
					self.itemMarketplace.handlePacket(incommingPacket, self.agentConnections[incommingPacket.senderId], self.sendLocks[incommingPacket.senderId])
			elif ("LABOR_MARKET" in incommingPacket.msgType):
					#We've received an item market packet
					self.laborMarketplace.handlePacket(incommingPacket, self.agentConnections[incommingPacket.senderId], self.sendLocks[incommingPacket.senderId])
			elif ("LAND_MARKET" in incommingPacket.msgType):
					#We've received an item market packet
					self.landMarketplace.handlePacket(incommingPacket, self.agentConnections[incommingPacket.senderId], self.sendLocks[incommingPacket.senderId])
					
			#Handle notification packets
			elif ("_NOTIFICATION" in incommingPacket.msgType):
				#Check for active snoops
				if (incommingPacket.msgType in self.snoopDict):
					snoopThread = threading.Thread(target=self.statsGatherer.handleSnoop, args=(incommingPacket,))
					snoopThread.start()

			#Route all over packets
			elif (destinationId in self.agentConnections):
				#Foward packet to destination
				self.sendPacket(destinationId, incommingPacket)

				#Check for active snoops
				if (incommingPacket.msgType in self.snoopDict):
					snoopThread = threading.Thread(target=self.statsGatherer.handleSnoop, args=(incommingPacket,))
					snoopThread.start()

			else:
				#Invalid packet destination
				errorMsg = "Destination \"{}\" not connected to network".format(destinationId)
				responsePacket = NetworkPacket(senderId=self.id, destinationId=incommingPacket.senderId, msgType="ERROR", payload=errorMsg, transactionId=incommingPacket.transactionId)

				sendThread = threading.Thread(target=self.sendPacket, args=(agentId, responsePacket))
				sendThread.start()


	def monitorTickBlockers(self):
		self.logger.info("monitorTickBlockers() start")
		while True:
			if (self.killAllFlag):
				break

			allAgentsBlocked = True
			try:
				if (self.simStarted):
					for agentId in self.timeTickBlockers:
						agentBlocked = self.timeTickBlockers[agentId]
						if (not agentBlocked):
							self.logger.info("Still waiting for {} to be tick blocked".format(agentId))
							allAgentsBlocked = False
							break
			except:
				pass

			if (allAgentsBlocked and self.simStarted):
				self.logger.info("All agents are tick blocked. Reseting blocks and notifying simulation manager")
				for agentId in self.timeTickBlockers:
					self.timeTickBlockers[agentId] = False

				controllerMsg = NetworkPacket(senderId=self.id, destinationId=self.simManagerId, msgType="ADVANCE_STEP")
				networkPacket = NetworkPacket(senderId=self.id, destinationId=self.simManagerId, msgType="CONTROLLER_MSG", payload=controllerMsg)
				self.sendPacket(self.simManagerId, networkPacket)

			time.sleep(0.001)

		self.logger.info("monitorTickBlockers() end")

'''
#Format
NetworkPacket.msgType
	Info

#########################
# Network Packets
#########################

KILL_PIPE_AGENT
	If sent to an agent, the agent will send a KILL_PIPE_NETWORK packet to the network, then kill it's monitoring thread

KILL_ALL_BROADCAST
	Equivalent to sending a KILL_PIPE_AGENT to every agent on the network

KILL_PIPE_NETWORK
	If sent from an agent, the connection network will delete it's connection to the agent and kill it's monitoring thread

SNOOP_START
	payload = <dict> {msgType: <bool>, ...}
	If sent from the statistics gatherer, the network will set up a snoop protocol. Afterwards, all packets with the specified msgTypes (incommingPacket) will be fowarded to the statistics gatherer

ERROR
	If send to an agent, the agent will print out the packet in an error logger. Currently only used for network errors.

#########################
# Trade Packets
#########################

CURRENCY_TRANSFER
	payload = <dict> {"paymentId": <str>, "cents": <int>}
	Transfer currency (amount="cents") from packet sender to packet recipient

CURRENCY_TRANSFER_ACK
	payload = <dict> {"paymentId": <str>, "transferSuccess": <bool>}
	Sent from currency recipient to currency sender

ITEM_TRANSFER
	payload = <dict> {"transferId": <str>, "item": <ItemContainer>}
	Transfer an item from sender to recipient

ITEM_TRANSFER_ACK
	payload = <dict> {"transferId": <str>, "transferSuccess": <bool>}
	Sent from item recipient to item sender

TRADE_REQ
	payload = <TradeRequest>

TRADE_REQ_ACK
	payload = <dict> {"tradeRequest": <TradeRequest>, "accepted": <bool>}

LAND_TRANSFER
	payload = <dict> {"transferId": <str>, "allocation": <str>, "hectares": <float>}
	Transfer land from sender to recipient

LAND_TRANSFER_ACK
	payload = <dict> {"transferId": <str>, "transferSuccess": <bool>}
	Sent from land recipient to land sender

LAND_TRADE_REQ
	payload = <LandTradeRequest>

LAND_TRADE_REQ_ACK
	payload = <dict> {"tradeRequest": <LandTradeRequest>, "accepted": <bool>}

#########################
# Market Packets
#########################

ITEM_MARKET_UPDATE
	payload = <ItemListing>
	Will update the agent's item listing in the ItemMarketplace

ITEM_MARKET_REMOVE
	payload = <ItemListing>
	Will remove the agent's item listing in the ItemMarketplace

ITEM_MARKET_SAMPLE
	payload = <dict> {"itemContainer": <ItemContainer>, "sampleSize": <int>}
	Request a sample of sellers for a given item from the ItemMarketplace

ITEM_MARKET_SAMPLE_ACK
	payload = <list> [<ItemListing>, ...]
	Returns a list of item listings

LABOR_MARKET_UPDATE
	payload = <LaborListing>
	Will update the agent's labor listing in the LaborMarketplace

LABOR_MARKET_REMOVE
	payload = <LaborListing>
	Will remove the agent's labor listing in the LaborMarketplace

LABOR_MARKET_SAMPLE
	payload = <dict> {"maxSkillLevel": <float>, "minSkillLevel": <float>, "sampleSize": <int>}
	Request a sample of sellers for a given labor from the LaborMarketplace

LABOR_MARKET_SAMPLE_ACK
	payload = <list> [<LaborListing>, ...]
	Returns a list of labor listings

LABOR_APPLICATION
	payload = <dict> {"laborContract": <LaborContract>, "applicationId": <str>}
	Send by an agent to an employer agent to apply for a job listing

LABOR_APPLICATION_ACK
	payload = <dict> {"laborContract": <LaborContract>, "accepted": <bool>}
	Ack sent by employer to applying agent

LABOR_TIME_SEND
	payload = <dict> {"ticks": <int>, "skillLevel": <float>}
	Send time ticks from an agent to an employer

LAND_MARKET_UPDATE
	payload = <LandListing>
	Will update the agent's land listing in the LandMarketplace

LAND_MARKET_REMOVE
	payload = <LandListing>
	Will remove the agent's land listing in the LandMarketplace

LAND_MARKET_SAMPLE
	payload = <dict> {"allocation": <str>, "hectares": <float>, "sampleSize": <int>}
	Request a sample of sellers for a given land type from the LandMarketplace

LAND_MARKET_SAMPLE_ACK
	payload = <list> [<LandListing>, ...]
	Returns a list of land listings

#########################
# Other Agent Packets
#########################

PRODUCTION_NOTIFICATION
	payload = <ItemContainer>
	Send when an item is produced by an agent. Is only fowarded if snooped on, otherwise ignored

INFO_REQ
	payload = <InfoRequest>
	Request information from an agent

INFO_RESP
	payload = <InfoRequest>
	Response to information request

CONTROLLER_START
	Tells the agent to start it's controller by caling controller.controllerStart()

CONTROLLER_START_BROADCAST
	Tells all agents to start their controllers by caling controller.controllerStart()

ERROR_CONTROLLER_START
	Sent by an agent if they could not start their controller

CONTROLLER_MSG
	The recipient agent will foward this packet to it's controller.

CONTROLLER_MSG_BROADCAST
	All agents will foward this packet to their controller


#########################
# Simulation management
#########################
TICK_BLOCK_SUBSCRIBE:
	Sent by a controller to the ConnectionNetwork. Tells the network to block simulation step progress until controller send a TICK_BLOCKED message

TICK_BLOCKED
	Sent by a controller to the ConnectionNetwork. Tells the network that the controller is out of time ticks and cannot execute more actions

#########################
# Controller messages
#########################
These message types are fowarded to the agent controller, so they have no hardcoded behavior.
The following are the current types and their intended usage.

NetworkPacket(msgType="CONTROLLER_MSG|CONTROLLER_MSG_BROADCAST", payload=controllerMessage)

"controllerMessage" is expected to be a <NetworkPacket> obj.

controllerMessage.msgTypes:
	ADVANCE_STEP
		Sent by the ConnectionNetwork to the SimulationManager. Tells the manager that all agents are ready for the next simulation step
	STOP_TRADING:
		Tells the recipient controller to cease all trading activity
	TICK_GRANT:
		payload=<int> tickAmount
		Grants the recipient controller time ticks. Sent by the SimulationManager to synchronize sim time.
	PROC_READY
		Sent by child process to the SimulationManager. Tells the manager that all agents in the process have been instantiated
	PROC_ERROR
		Sent by child process to the SimulationManager. Tells the manager that there was an error during agent instantiation


'''