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
'''
import multiprocessing
import threading
import hashlib
import time
import traceback
import gc
#import tracemalloc

import utils
from NetworkClasses import *
from Marketplace import *
from StatisticsGatherer import *


class ConnectionNetwork:
	def __init__(self, itemDict, simManagerId=None, logFile=True, logLevel="INFO", outputDir="OUTPUT", simulationSettings={}):
		self.id = "ConnectionNetwork"
		self.simManagerId = simManagerId

		self.outputDir = outputDir
		#self.logger = utils.getLogger("{}".format(__name__), logFile=logFile, outputdir=os.path.join(outputDir, "LOGS"), fileLevel=logLevel)   #This causes a serious performance hit. Only enable it if you REALLY need to
		self.logger = utils.getLogger("{}".format(__name__), logFile=logFile, outputdir=os.path.join(outputDir, "LOGS"), fileLevel="INFO")
		self.lockTimeout = 10

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

		#Keep track of spawned threads
		self.spawnedThreads = []

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
			marketplaceObj = ItemMarketplace(marketDict, market_agentLink, simManagerId=self.simManagerId, outputDir=self.outputDir)
			self.addConnection(marketplaceObj.agentId, market_networkLink)

		if (marketType=="LaborMarketplace"):
			marketplaceObj = LaborMarketplace(market_agentLink, simManagerId=self.simManagerId, outputDir=self.outputDir)
			self.addConnection(marketplaceObj.agentId, market_networkLink)

		if (marketType=="LandMarketplace"):
			marketplaceObj = LandMarketplace(market_agentLink, simManagerId=self.simManagerId, outputDir=self.outputDir)
			self.addConnection(marketplaceObj.agentId, market_networkLink)

		return marketplaceObj

	def addStatisticsGatherer(self, settings, itemDict, logFile=True):
		#Instantiate communication pipes
		networkPipeRecv, marketPipeSend = multiprocessing.Pipe()
		marketPipeRecv, networkPipeSend = multiprocessing.Pipe()

		market_networkLink = Link(sendPipe=networkPipeSend, recvPipe=networkPipeRecv)
		market_agentLink = Link(sendPipe=marketPipeSend, recvPipe=marketPipeRecv)

		#Instantiate gatherer
		statsGatherer = StatisticsGatherer(settings=settings, itemDict=itemDict, networkLink=market_agentLink, logFile=logFile, outputDir=self.outputDir)
		self.addConnection(statsGatherer.agentId, market_networkLink)

		return statsGatherer

	def startMonitors(self):
		for agentId in self.agentConnections:
			monitorThread = threading.Thread(target=self.monitorLink, args=(agentId,))
			monitorThread.start()

	def sendPacket(self, pipeId, packet):
		self.logger.debug("ConnectionNetwork.sendPacket({}, {}) start".format(pipeId, packet))
		try:
			if (pipeId in self.agentConnections):
				self.logger.debug("Requesting lock sendLocks[{}]".format(pipeId))
				acquired_sendLock = self.sendLocks[pipeId].acquire()
				if (acquired_sendLock):
					self.logger.debug("Acquired lock sendLocks[{}]".format(pipeId))
					self.logger.debug("OUTBOUND {} {}".format(packet, pipeId))
					self.agentConnections[pipeId].sendPipe.send(packet)
					self.sendLocks[pipeId].release()
					self.logger.debug("Release lock sendLocks[{}]".format(pipeId))
				else:
					self.logger.error("ConnectionNetwork.sendPacket() Lock sendLocks[{}] acquire timeout".format(pipeId))
			else:
				self.logger.warning("Cannot send {}. Pipe[{}] already killed".format(pipeId, packet))
		except:
			self.logger.critical("UNHANLDED ERROR in sendPacket({}, {})\n{}".format(pipeId, packet, traceback.format_exc()))

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
			self.logger.debug("Monitoring {} link {}".format(agentId, agentLink))
			incommingPacket = agentLink.recvPipe.recv()
			self.logger.debug("INBOUND {} {}".format(agentId, incommingPacket))
			destinationId = incommingPacket.destinationId

			#Handle kill packets
			if (incommingPacket.msgType == PACKET_TYPE.KILL_PIPE_NETWORK):
				#We've received a kill command for this pipe. Remove destPipe from connections, then kill this monitor thread
				self.logger.info("Killing pipe {} {}".format(agentId, agentLink))
				try:
					#Remove agent from blocking list
					self.timeTickBlockers_Lock.acquire()
					if (incommingPacket.senderId in self.timeTickBlockers):
						del self.timeTickBlockers[incommingPacket.senderId]
					self.timeTickBlockers_Lock.release()

					#Remove connection pipe
					acquired_agentConnectionsLock = self.agentConnectionsLock.acquire(timeout=self.lockTimeout)  #<== acquire agentConnectionsLock
					if (acquired_agentConnectionsLock):
						del self.agentConnections[incommingPacket.senderId]
						del self.sendLocks[incommingPacket.senderId]
						self.agentConnectionsLock.release()  #<== release agentConnectionsLock
						break
					else:
						self.logger.error("monitorLink() Lock \"agentConnectionsLock\" acquisition timeout")
						break
				except:
					self.logger.critical(traceback.format_exc())
					break

			#Handle broadcasts
			elif ((incommingPacket.msgType == PACKET_TYPE.KILL_ALL_BROADCAST) or (incommingPacket.msgType == PACKET_TYPE.INFO_REQ_BROADCAST) or (incommingPacket.msgType == PACKET_TYPE.CONTROLLER_START_BROADCAST) or 
				(incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG_BROADCAST) or (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT_BROADCAST) or (incommingPacket.msgType == PACKET_TYPE.SAVE_CHECKPOINT_BROADCAST) or
				(incommingPacket.msgType == PACKET_TYPE.LOAD_CHECKPOINT_BROADCAST)):
				#Check if this is a KILL_ALL broadcast
				if (incommingPacket.msgType == PACKET_TYPE.KILL_ALL_BROADCAST):
					self.killAllLock.acquire()
					if (self.killAllFlag):
						#All agents were already killed by another thread. Skip this broadcast
						self.logger.debug("killAllFlag has already been set. Ignoring {}".format(incommingPacket))
						continue

				#Check if this is the start of the sim
				if not (self.simStarted):
					if (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT_BROADCAST):
						for agentId in self.timeTickBlockers:
							self.timeTickBlockers[agentId] = False
						self.simStarted = True

				#We've received a broadcast message. Foward to all pipes
				self.logger.debug("Fowarding broadcast")
				acquired_agentConnectionsLock = self.agentConnectionsLock.acquire()  #<== acquire agentConnectionsLock
				pipeIdList = list(self.agentConnections.keys())
				self.agentConnectionsLock.release()  #<== release agentConnectionsLock

				if (incommingPacket.msgType == PACKET_TYPE.INFO_REQ_BROADCAST):
					#Prefilter info req requests for improved performance
					agentFilter = ""
					try:
						agentFilter = incommingPacket.payload.agentFilter
					except:
						agentFilter = ""
					enableFiltering = len(agentFilter) > 0

					for pipeId in pipeIdList:
						if (not enableFiltering):
							self.sendPacket(pipeId, incommingPacket)
						elif (agentFilter in pipeId):
							self.sendPacket(pipeId, incommingPacket)
				else:
					for pipeId in pipeIdList:
						self.sendPacket(pipeId, incommingPacket)

				self.logger.debug("Ending broadcast")

				#Set killAllFlag
				if (incommingPacket.msgType == PACKET_TYPE.KILL_ALL_BROADCAST):
					self.logger.debug("Setting killAllFlag")
					self.killAllFlag = True
					self.killAllLock.release()

			#Handle snoop requests
			elif (incommingPacket.msgType == PACKET_TYPE.SNOOP_START):
				#We've received a snoop start request. Add to snooping dict
				self.setupSnoop(incommingPacket)

			#Handle tick block subscriptions
			elif (incommingPacket.msgType == PACKET_TYPE.TICK_BLOCK_SUBSCRIBE):
				self.logger.info("{} has subscribed to tick blocking".format(incommingPacket.senderId))
				self.timeTickBlockers_Lock.acquire()
				self.timeTickBlockers[incommingPacket.senderId] = True
					
				if not (self.tickBlocksMonitoring):
					self.tickBlocksMonitoring = True
					blockMonitorThread = threading.Thread(target=self.monitorTickBlockers)
					blockMonitorThread.start()

				self.timeTickBlockers_Lock.release()

			#Handle tick blocked packets
			elif (incommingPacket.msgType == PACKET_TYPE.TICK_BLOCKED):
				if (incommingPacket.senderId in self.timeTickBlockers):
					self.timeTickBlockers[incommingPacket.senderId] = True

				responsePacket = NetworkPacket(senderId=self.id, destinationId=incommingPacket.senderId, msgType=PACKET_TYPE.TICK_BLOCKED_ACK, transactionId=incommingPacket.transactionId)
				self.sendPacket(incommingPacket.senderId, responsePacket)

			#Handle marketplace packets
			elif ((incommingPacket.msgType == PACKET_TYPE.ITEM_MARKET_UPDATE) or (incommingPacket.msgType == PACKET_TYPE.ITEM_MARKET_REMOVE) or (incommingPacket.msgType == PACKET_TYPE.ITEM_MARKET_SAMPLE) or (incommingPacket.msgType == PACKET_TYPE.ITEM_MARKET_SAMPLE_ACK)):
				#We've received an item market packet
				self.itemMarketplace.handlePacket(incommingPacket, self.agentConnections[incommingPacket.senderId], self.sendLocks[incommingPacket.senderId])
			elif ((incommingPacket.msgType == PACKET_TYPE.LABOR_MARKET_UPDATE) or (incommingPacket.msgType == PACKET_TYPE.LABOR_MARKET_REMOVE) or (incommingPacket.msgType == PACKET_TYPE.LABOR_MARKET_SAMPLE) or (incommingPacket.msgType == PACKET_TYPE.LABOR_MARKET_SAMPLE_ACK)):
				#We've received an item market packet
				self.laborMarketplace.handlePacket(incommingPacket, self.agentConnections[incommingPacket.senderId], self.sendLocks[incommingPacket.senderId])
			elif ((incommingPacket.msgType == PACKET_TYPE.LAND_MARKET_UPDATE) or (incommingPacket.msgType == PACKET_TYPE.LAND_MARKET_REMOVE) or (incommingPacket.msgType == PACKET_TYPE.LAND_MARKET_SAMPLE) or (incommingPacket.msgType == PACKET_TYPE.LAND_MARKET_SAMPLE_ACK)):
				#We've received an item market packet
				self.landMarketplace.handlePacket(incommingPacket, self.agentConnections[incommingPacket.senderId], self.sendLocks[incommingPacket.senderId])
					
			#Handle notification packets
			elif (incommingPacket.msgType == PACKET_TYPE.PRODUCTION_NOTIFICATION):
				#Check for active snoops
				if (incommingPacket.msgType in self.snoopDict):
					snoopThread = threading.Thread(target=self.statsGatherer.handleSnoop, args=(incommingPacket,))
					snoopThread.start()
					self.spawnedThreads.append(snoopThread)

			#Handle info response packets
			elif (incommingPacket.msgType == PACKET_TYPE.INFO_RESP):
				if (destinationId == "StatisticsGatherer"):
					#Foward to statistics gatherer
					infoRespThread = threading.Thread(target=self.statsGatherer.handleInfoResp, args=(incommingPacket,))
					infoRespThread.start()
					self.spawnedThreads.append(infoRespThread)
				else:
					#Foward packet to destination
					self.sendPacket(destinationId, incommingPacket)

			#Route all over packets
			elif (destinationId in self.agentConnections):
				#Foward packet to destination
				self.sendPacket(destinationId, incommingPacket)

				#Check for active snoops
				if (incommingPacket.msgType in self.snoopDict):
					snoopThread = threading.Thread(target=self.statsGatherer.handleSnoop, args=(incommingPacket,))
					snoopThread.start()
					self.spawnedThreads.append(snoopThread)

			else:
				#Invalid packet destination
				errorMsg = "Destination \"{}\" not connected to network".format(destinationId)
				responsePacket = NetworkPacket(senderId=self.id, destinationId=incommingPacket.senderId, msgType=PACKET_TYPE.ERROR, payload=errorMsg, transactionId=incommingPacket.transactionId)

				self.sendPacket(agentId, responsePacket)


	def monitorTickBlockers(self):
		self.logger.info("monitorTickBlockers() start")

		#Memory leak finder
		# tracemalloc.start(10)
		# warmupSnapshot = None

		prevBlockerAgent = None
		prevStartTime = time.time()
		averageLoopTime = 0
		warningSent = False

		stepCounter = -1
		garbageCollectionFrequency = 20
		while True:
			if (self.killAllFlag):
				break

			#Check if all agents are tick blocked
			allAgentsBlocked = True
			try:
				if (self.simStarted):
					for agentId in self.timeTickBlockers:
						agentBlocked = self.timeTickBlockers[agentId]
						if (not agentBlocked):
							if (agentId != prevBlockerAgent):
								self.logger.info("Still waiting for {} to be tick blocked".format(agentId))
							if not (warningSent):
								if (averageLoopTime > 0):
									currentWaitTime = time.time() - prevStartTime
									if (currentWaitTime > (20*averageLoopTime)):
										self.logger.warning("Still waiting for {} to be tick blocked. Current step time {} seconds is 20x the average step time {} seconds. {} is probably stuck.".format(agentId, currentWaitTime, averageLoopTime, agentId))
										warningSent = True
										
							allAgentsBlocked = False
							prevBlockerAgent = agentId
							break
			except:
				self.logger.warning(traceback.format_exc())
				allAgentsBlocked = False

			if (allAgentsBlocked and self.simStarted):
				#Mark all spawned threads as elgible for garbage collection
				self.logger.debug("Joining spawned threads")
				for thread in self.spawnedThreads:
					thread.join()
				self.spawnedThreads.clear()

				#Run garbage collector
				stepCounter += 1
				if (stepCounter%garbageCollectionFrequency == 0):
					self.logger.debug("Running garbage collector")
					gc.collect()

				#Memory leak finder
				# warmupStep = 50
				# snapshotStep = 500
				# if (stepCounter == warmupStep):
				# 	gc.collect()
				# 	warmupSnapshot = tracemalloc.take_snapshot()
				# 	self.logger.info("Allocation snapshot taken")
				# elif (stepCounter == snapshotStep):
				# 	gc.collect()
				# 	#top_stats = tracemalloc.take_snapshot().compare_to(warmupSnapshot, 'lineno')
				# 	top_stats = tracemalloc.take_snapshot().compare_to(warmupSnapshot, 'traceback')
				# 	self.logger.debug("Allocation snapshot taken")
				# 	allocatingLines = []
				# 	statNumber = 10
				# 	self.logger.info("### Top {} new memory allocations\n".format(statNumber))
				# 	statCounter = 0
				# 	for stat in top_stats[:statNumber]:
				# 		allocatingLines.append(str(stat))
				# 		statString = "## {} ##\n{}".format(statCounter, stat)
				# 		for line in stat.traceback.format():
				# 			statString = statString + "\n{}".format(line)
				# 		self.logger.info(statString)
				# 		statCounter += 1

				#Calculate step time
				warningSent = False
				endTime = time.time()
				if (averageLoopTime == 0):
					averageLoopTime = endTime-prevStartTime
				alpha = 0.3
				averageLoopTime = ((1-alpha)*averageLoopTime) + (alpha*(endTime-prevStartTime))
				self.lockTimeout = 2*averageLoopTime
				prevStartTime = time.time()

				#Reset tick block flags
				self.logger.info("All agents are tick blocked. Reseting blocks and notifying simulation manager")
				self.timeTickBlockers_Lock.acquire()
				for agentId in self.timeTickBlockers:
					self.timeTickBlockers[agentId] = False
				self.timeTickBlockers_Lock.release()

				#Notify sim manager to start the next step
				controllerMsg = NetworkPacket(senderId=self.id, destinationId=self.simManagerId, msgType=PACKET_TYPE.ADVANCE_STEP)
				networkPacket = NetworkPacket(senderId=self.id, destinationId=self.simManagerId, msgType=PACKET_TYPE.CONTROLLER_MSG, payload=controllerMsg)
				self.sendPacket(self.simManagerId, networkPacket)

			time.sleep(0.001)

		self.logger.info("monitorTickBlockers() end")
