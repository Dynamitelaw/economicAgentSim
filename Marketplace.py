'''
These marketplaces live inside the ConnectionNetwork.
They basically function like billboards, where sellers can post listings that can be viewed by other agents.
They do not handle transactions.

Types:
	ItemMarketplace: Where sellers can post ItemListings
	LaborMarketplace: Where employers can post LaborListings
'''
import threading
import os
import random
import time

from NetworkClasses import *
import utils


class ItemMarketplace:
	def __init__(self, itemDict, networkLink, simManagerId=None, logFile=True, fileLevel="INFO"):
		self.agentId = "ItemMarketplace"
		self.logger = utils.getLogger("ItemMarketplace", logFile=logFile, console="ERROR", outputdir=os.path.join("LOGS", "Markets"), fileLevel=fileLevel)
		self.logger.info("ItemMarketplace instantiated")

		self.lockTimeout = 15

		self.simManagerId = simManagerId

		#Pipe connections to the connection network
		self.networkLink = networkLink
		self.networkSendLock = threading.Lock()
		self.responseBuffer = {}
		self.responseBufferLock = threading.Lock()

		#Item marketplace dict
		self.itemMarket = {}
		self.itemMarketLocks = {}
		if (itemDict):
			for itemName in itemDict:
				self.itemMarket[itemName] = {}
				self.itemMarketLocks[itemName] = threading.Lock()
		else:
			self.logger.error("No item dict passed to {}. Ending simulation".format(self.agentId))
			terminatePacket = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="TERMINATE_SIMULATION")
			networkPacket = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="CONTROLLER_MSG", payload=terminatePacket)
			self.sendPacket(networkPacket)	

		#Keep track of time since last update
		self.stallTime = 0.5
		self.latestHandleTime = time.time()

		#Start monitoring network link
		if (self.networkLink):
			linkMonitor = threading.Thread(target=self.monitorNetworkLink)
			linkMonitor.start()	
		

	#########################
	# Network functions
	#########################
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
				self.subcribeTickBlocking()

			#Hanle incoming tick grants
			elif ((incommingPacket.msgType == "TICK_GRANT") or (incommingPacket.msgType == "TICK_GRANT_BROADCAST")):
				currentTime = time.time()
				if (currentTime > self.latestHandleTime):
					self.latestHandleTime = currentTime

				#Wait until we're not busy to send TICK_BLOCK
				stallMonitor = threading.Thread(target=self.waitForStall)
				stallMonitor.start()

			#Handle errors
			elif ("ERROR" in incommingPacket.msgType):
				self.logger.error("{} {}".format(incommingPacket, incommingPacket.payload))

			#Handle incoming information requests
			elif (incommingPacket.msgType == "INFO_REQ"):
				infoRequest = incommingPacket.payload
				infoThread =  threading.Thread(target=self.handleInfoRequest, args=(infoRequest, ))
				infoThread.start()

		self.logger.info("Ending networkLink monitor".format(self.networkLink))


	def sendPacket(self, packet, agentLink=None, agentSendLock=None):
		if (agentLink):
			#Bypass network and send packet directly to agent
			if (agentSendLock):
				acquired_agentSendLock = agentSendLock.acquire(timeout=self.lockTimeout)
				if (acquired_agentSendLock):
					self.logger.info("OUTBOUND {}".format(packet))
					agentLink.sendPipe.send(packet)
					agentSendLock.release()
				else:
					self.logger.error("{}.sendPacket() Lock networkSendLock acquire timeout".format(self.agentId))
			else:
				agentLink.sendPipe.send(packet)
		else:
			#Send this packet over the network
			acquired_networkSendLock = self.networkSendLock.acquire(timeout=self.lockTimeout)
			if (acquired_networkSendLock):
				self.logger.info("OUTBOUND {}".format(packet))
				self.networkLink.sendPipe.send(packet)
				self.networkSendLock.release()
			else:
				self.logger.error("{}.sendPacket() Lock networkSendLock acquire timeout".format(self.agentId))


	def handlePacket(self, incommingPacket, agentLink, agentSendLock):
		self.logger.info("INBOUND {}".format(incommingPacket))
		currentTime = time.time()
		if (currentTime > self.latestHandleTime):
			self.latestHandleTime = currentTime

		handled = False
		if (incommingPacket.msgType == "ITEM_MARKET_UPDATE"):
			handled = self.updateItemListing(incommingPacket)
		elif (incommingPacket.msgType == "ITEM_MARKET_REMOVE"):
			handled = self.removeItemListing(incommingPacket)
		elif (incommingPacket.msgType == "ITEM_MARKET_SAMPLE"):
			handled = self.sampleItemListings(incommingPacket, agentLink, agentSendLock)

		return handled

	#########################
	# Time functions
	#########################
	def subcribeTickBlocking(self):
		'''
		Subscribes this agent as a tick blocker with the sim manager
		'''
		self.logger.info("Subscribing as a tick blocker")
		tickBlockPacket = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="TICK_BLOCK_SUBSCRIBE")
		self.sendPacket(tickBlockPacket)


	def waitForStall(self):
		'''
		Subscribes this agent as a tick blocker with the sim manager
		'''
		#Wait for stall
		while True:
			time.sleep(self.stallTime/4)
			timeDiff = time.time() - self.latestHandleTime
			if (timeDiff > self.stallTime):
				break

		self.logger.info("Stall of {} seconds detected. Sending TICK_BLOCKED".format(self.stallTime))

		#Send tick blocked
		tickBlockedPacket = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="TICK_BLOCKED")
		self.sendPacket(tickBlockedPacket)

	#########################
	# Market functions
	#########################
	def updateItemListing(self, incommingPacket):
		'''
		Update the item marketplace.
		Returns True if succesful, False otherwise
		'''
		itemListing = incommingPacket.payload

		self.logger.debug("{}.updateItemListing({}) start".format(self.agentId, itemListing))

		updateSuccess = False

		if not (itemListing.sellerId in self.itemMarket[itemListing.itemId]):
			#Seller is new to this item. Add them to the market
			itemLock = self.itemMarketLocks[itemListing.itemId]
			acquired_itemMarketLock = itemLock.acquire(timeout=self.lockTimeout)  # <== itemMarketLock acquire
			if (acquired_itemMarketLock):
				self.itemMarket[itemListing.itemId][itemListing.sellerId] = itemListing
				itemLock.release()  # <== itemMarketLock release
			else:
				self.logger.error("updateItemListing() Lock \"itemMarketLock\" acquisition timeout")
				updateSuccess = False
		else:
			#Seller is already in selling this item. Dict size won't change. No need to acquire thread lock
			self.itemMarket[itemListing.itemId][itemListing.sellerId] = itemListing

		#Return status
		self.logger.debug("{}.updateItemListing({}) return {}".format(self.agentId, itemListing, updateSuccess))
		return updateSuccess

	def removeItemListing(self, incommingPacket):
		'''
		Remove a listing from the item marketplace
		Returns True if succesful, False otherwise
		'''
		itemListing = incommingPacket.payload

		self.logger.debug("{}.removeItemListing({}) start".format(self.agentId, itemListing))

		updateSuccess = False

		#Update local item market with listing
		itemLock = self.itemMarketLocks[itemListing.itemId]
		acquired_itemMarketLock = itemLock.acquire(timeout=self.lockTimeout)  # <== itemMarketLock acquire
		if (acquired_itemMarketLock):
			if (itemListing.itemId in self.itemMarket):
				if (itemListing.sellerId in self.itemMarket[itemListing.itemId]):
					del self.itemMarket[itemListing.itemId][itemListing.sellerId]

			itemLock.release()  # <== itemMarketLock release
			updateSuccess = True
		else:
			self.logger.error("removeItemListing() Lock \"itemMarketLock\" acquisition timeout")
			updateSuccess = False

		#Return status
		self.logger.debug("{}.removeItemListing({}) return {}".format(self.agentId, itemListing, updateSuccess))
		return updateSuccess

	def sampleItemListings(self, incommingPacket, agentLink, agentSendLock):
		'''
		Sends a list of randomly sampled item listings that match itemContainer to the requesting agent.
			ItemListing.itemId == itemContainer.id

		Returns True if successful
		'''

		itemContainer = incommingPacket.payload["itemContainer"]
		sampleSize = incommingPacket.payload["sampleSize"]

		sampledListings = []
		
		#We are the item market. Get information from itemMarket dict
		if (itemContainer.id in self.itemMarket):
			itemListings = self.itemMarket[itemContainer.id]
			if (len(itemListings) > sampleSize):
				sampledListings = random.sample(list(itemListings.values()), sampleSize).copy()
			else:
				sampledListings = list(itemListings.values()).copy()

		#Send out sampled listings if request came from network
		if (incommingPacket):
			responsePacket = NetworkPacket(senderId=self.agentId, destinationId=incommingPacket.senderId, transactionId=incommingPacket.transactionId, msgType="ITEM_MARKET_SAMPLE_ACK", payload=sampledListings)
			self.sendPacket(responsePacket, agentLink, agentSendLock)


		return True


	#########################
	# Misc functions
	#########################
	def handleInfoRequest(self, infoRequest):
		if (self.agentId == infoRequest.agentId):
			infoKey = infoRequest.infoKey
			if (infoKey == "itemMarket"):
				infoRequest.info = self.itemMarket
			elif (infoKey == "inventory"):
				infoRequest.info = None
			else:
				infoRequest.info = None
			
			infoRespPacket = NetworkPacket(senderId=self.agentId, destinationId=infoRequest.requesterId, msgType="INFO_RESP", payload=infoRequest)
			self.sendPacket(infoRespPacket)
		else:
			self.logger.warning("Received infoRequest for another agent {}".format(infoRequest))

	def __str__(self):
		return str(self.agentInfo)


class LaborMarketplace:
	def __init__(self, networkLink, simManagerId=None, logFile=True, fileLevel="INFO"):
		self.agentId = "LaborMarketplace"
		self.logger = utils.getLogger("LaborMarketplace", logFile=logFile, console="ERROR", outputdir=os.path.join("LOGS", "Markets"), fileLevel=fileLevel)
		self.logger.info("LaborMarketplace instantiated")

		self.lockTimeout = 15

		self.simManagerId = simManagerId

		#Pipe connections to the connection network
		self.networkLink = networkLink
		self.networkSendLock = threading.Lock()
		self.responseBuffer = {}
		self.responseBufferLock = threading.Lock()

		#Labor marketplace dict
		self.laborMarket = {}
		self.laborMarketLock = threading.Lock()
		self.laborMarketEmployerLocks = {}

		#Keep track of time since last update
		self.stallTime = 0.5
		self.latestHandleTime = time.time()

		#Start monitoring network link
		if (self.networkLink):
			linkMonitor = threading.Thread(target=self.monitorNetworkLink)
			linkMonitor.start()	
		

	#########################
	# Network functions
	#########################
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
				self.subcribeTickBlocking()

			#Hanle incoming tick grants
			elif ((incommingPacket.msgType == "TICK_GRANT") or (incommingPacket.msgType == "TICK_GRANT_BROADCAST")):
				currentTime = time.time()
				if (currentTime > self.latestHandleTime):
					self.latestHandleTime = currentTime

				#Wait until we're not busy to send TICK_BLOCK
				stallMonitor = threading.Thread(target=self.waitForStall)
				stallMonitor.start()

			#Handle errors
			elif ("ERROR" in incommingPacket.msgType):
				self.logger.error("{} {}".format(incommingPacket, incommingPacket.payload))

			#Handle incoming information requests
			elif (incommingPacket.msgType == "INFO_REQ"):
				infoRequest = incommingPacket.payload
				infoThread =  threading.Thread(target=self.handleInfoRequest, args=(infoRequest, ))
				infoThread.start()

		self.logger.info("Ending networkLink monitor".format(self.networkLink))


	def sendPacket(self, packet, agentLink=None, agentSendLock=None):
		if (agentLink):
			#Bypass network and send packet directly to agent
			if (agentSendLock):
				acquired_agentSendLock = agentSendLock.acquire(timeout=self.lockTimeout)
				if (acquired_agentSendLock):
					self.logger.info("OUTBOUND {}".format(packet))
					agentLink.sendPipe.send(packet)
					agentSendLock.release()
				else:
					self.logger.error("{}.sendPacket() Lock networkSendLock acquire timeout".format(self.agentId))
			else:
				agentLink.sendPipe.send(packet)
		else:
			#Send this packet over the network
			acquired_networkSendLock = self.networkSendLock.acquire(timeout=self.lockTimeout)
			if (acquired_networkSendLock):
				self.logger.info("OUTBOUND {}".format(packet))
				self.networkLink.sendPipe.send(packet)
				self.networkSendLock.release()
			else:
				self.logger.error("{}.sendPacket() Lock networkSendLock acquire timeout".format(self.agentId))


	def handlePacket(self, incommingPacket, agentLink, agentSendLock):
		self.logger.info("INBOUND {}".format(incommingPacket))
		currentTime = time.time()
		if (currentTime > self.latestHandleTime):
			self.latestHandleTime = currentTime

		handled = False
		if (incommingPacket.msgType == "LABOR_MARKET_UPDATE"):
			handled = self.updateLaborListing(incommingPacket)
		elif (incommingPacket.msgType == "LABOR_MARKET_REMOVE"):
			handled = self.removeLaborListing(incommingPacket)
		elif (incommingPacket.msgType == "LABOR_MARKET_SAMPLE"):
			handled = self.sampleLaborListings(incommingPacket, agentLink, agentSendLock)

		return handled

	#########################
	# Time functions
	#########################
	def subcribeTickBlocking(self):
		'''
		Subscribes this agent as a tick blocker with the sim manager
		'''
		self.logger.info("Subscribing as a tick blocker")
		tickBlockPacket = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="TICK_BLOCK_SUBSCRIBE")
		self.sendPacket(tickBlockPacket)


	def waitForStall(self):
		'''
		Subscribes this agent as a tick blocker with the sim manager
		'''
		#Wait for stall
		while True:
			time.sleep(self.stallTime/4)
			timeDiff = time.time() - self.latestHandleTime
			if (timeDiff > self.stallTime):
				break

		self.logger.info("Stall of {} seconds detected. Sending TICK_BLOCKED".format(self.stallTime))

		#Send tick blocked
		tickBlockedPacket = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="TICK_BLOCKED")
		self.sendPacket(tickBlockedPacket)

	#########################
	# Market functions
	#########################
	def updateLaborListing(self, incommingPacket):
		'''
		Update the labor marketplace.
		Returns True if succesful, False otherwise
		'''
		laborListing = incommingPacket.payload

		self.logger.debug("{}.updateItemListing({}) start".format(self.agentId, laborListing))

		updateSuccess = False
		#Update local labor market with listing
		skillLevel = laborListing.minSkillLevel
		if (not skillLevel in self.laborMarket):
			self.laborMarketLock.acquire()
			self.laborMarket[skillLevel] = {}
			self.laborMarketLock.release()

		employerId = laborListing.employerId
		if (not employerId in self.laborMarket[skillLevel]):
			self.laborMarketEmployerLocks[employerId] = threading.Lock()
			self.laborMarketLock.acquire()
			self.laborMarket[skillLevel][employerId] = {}
			self.laborMarketLock.release()

		self.laborMarketEmployerLocks[employerId].acquire()
		self.laborMarket[skillLevel][employerId][laborListing.listingName] = laborListing
		self.laborMarketEmployerLocks[employerId].release()

		updateSuccess = True

		#Return status
		self.logger.debug("{}.updateItemListing({}) return {}".format(self.agentId, laborListing, updateSuccess))
		return updateSuccess

	def removeLaborListing(self, incommingPacket):
		'''
		Remove a listing from the labor marketplace
		Returns True if succesful, False otherwise
		'''
		laborListing = incommingPacket.payload

		self.logger.debug("{}.removeItemListing({}) start".format(self.agentId, laborListing))

		updateSuccess = False

		#Remove listing from local labor market
		skillLevel = laborListing.minSkillLevel
		if (not skillLevel in self.laborMarket):
			self.logger.warning("{}.removeItemListing({}) failed. Listing not in labor market".format(self.agentId, laborListing))
			updateSuccess = False
			return updateSuccess

		employerId = laborListing.employerId
		if (not employerId in self.laborMarket[skillLevel]):
			self.logger.warning("{}.removeItemListing({}) failed. Listing not in labor market".format(self.agentId, laborListing))
			updateSuccess = False
			return updateSuccess

		if (not laborListing.listingStr in self.laborMarket[skillLevel][employerId]):
			self.logger.warning("{}.removeItemListing({}) failed. Listing not in labor market".format(self.agentId, laborListing))
			updateSuccess = False
			return updateSuccess

		self.laborMarketEmployerLocks[employerId].acquire()
		del self.laborMarket[skillLevel][employerId][laborListing.listingStr]

		if (len(self.laborMarket[skillLevel][employerId]) == 0):
			self.laborMarketLock.acquire()
			del self.laborMarket[skillLevel][employerId]
			self.laborMarketLock.release()

		self.laborMarketEmployerLocks[employerId].release()

		updateSuccess = True

		#Return status
		self.logger.debug("{}.removeItemListing({}) return {}".format(self.agentId, laborListing, updateSuccess))
		return updateSuccess

	def sampleLaborListings(self, incommingPacket, agentLink, agentSendLock):
		'''
		Sends a list of sampled labor listings that agent qualifies for (listing.minSkillLevel <= agent.skillLevel).
		Will sample listings in order of decreasing skill level, returning the highest possible skill-level listings. Samples are randomized within skill levels.
		Sends list directly to agent over agentLink

		Returns True if successful
		'''

		maxSkillLevel = incommingPacket.payload["maxSkillLevel"]
		minSkillLevel = incommingPacket.payload["minSkillLevel"]
		sampleSize = incommingPacket.payload["sampleSize"]
		
		#Get all valid skill levels
		possibleSkillKeys = [i for i in self.laborMarket.keys() if ((i <= maxSkillLevel) and (i >= minSkillLevel))]
		possibleSkillKeys.sort(reverse=True)

		#Sample listings, starting from highest skill level
		sampledListings = []
		for skillLevel in possibleSkillKeys:
			possibleEmployers = self.laborMarket[skillLevel].keys()
			if (len(possibleEmployers) > (sampleSize-len(sampledListings))):
				#Too many employers. Randomly sample from them
				possibleEmployers = random.sample(list(possibleEmployers), sampleSize-len(sampledListings))

			for employerId in possibleEmployers:
				employerListings = self.laborMarket[skillLevel][employerId]

				sampledListingStr = None
				if (len(employerListings) > 1):
					#Employer has multiple listings at this skill level. Sample one of them
					sampledListingStr = random.sample(list(employerListings.keys()), 1)[0]
				else:
					sampledListingStr = list(employerListings.keys())[0]

				sampledListing = employerListings[sampledListingStr]
				sampledListings.append(sampledListing)

			if (len(sampledListings) >= sampleSize):
				#We've already found enough listings. Exit loop
				break

		#Send out sampled listings if request came from network
		if (incommingPacket):
			responsePacket = NetworkPacket(senderId=self.agentId, destinationId=incommingPacket.senderId, transactionId=incommingPacket.transactionId, msgType="LABOR_MARKET_SAMPLE_ACK", payload=sampledListings)
			self.sendPacket(responsePacket, agentLink, agentSendLock)


		return True


	#########################
	# Misc functions
	#########################
	def handleInfoRequest(self, infoRequest):
		if (self.agentId == infoRequest.agentId):
			infoKey = infoRequest.infoKey
			if (infoKey == "laborMarket"):
				infoRequest.info = self.laborMarket
			elif (infoKey == "inventory"):
				infoRequest.info = None
			else:
				infoRequest.info = None
			
			infoRespPacket = NetworkPacket(senderId=self.agentId, destinationId=infoRequest.requesterId, msgType="INFO_RESP", payload=infoRequest)
			self.sendPacket(infoRespPacket)
		else:
			self.logger.warning("Received infoRequest for another agent {}".format(infoRequest))

	def __str__(self):
		return str(self.agentInfo)


class LandMarketplace:
	def __init__(self, networkLink, simManagerId=None, logFile=True, fileLevel="INFO"):
		self.agentId = "LandMarketplace"
		self.logger = utils.getLogger("LandMarketplace", logFile=logFile, console="ERROR", outputdir=os.path.join("LOGS", "Markets"), fileLevel=fileLevel)
		self.logger.info("LandMarketplace instantiated")

		self.lockTimeout = 15

		self.simManagerId = simManagerId

		#Pipe connections to the connection network
		self.networkLink = networkLink
		self.networkSendLock = threading.Lock()
		self.responseBuffer = {}
		self.responseBufferLock = threading.Lock()

		#Lane marketplace dict
		self.landMarket = {"UNALLOCATED": {}}
		self.landMarketLock = threading.Lock()
		self.landMarketLocks = {"UNALLOCATED": threading.Lock()}

		#Keep track of time since last update
		self.stallTime = 0.5
		self.latestHandleTime = time.time()

		#Start monitoring network link
		if (self.networkLink):
			linkMonitor = threading.Thread(target=self.monitorNetworkLink)
			linkMonitor.start()	
		

	#########################
	# Network functions
	#########################
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
				self.subcribeTickBlocking()

			#Hanle incoming tick grants
			elif ((incommingPacket.msgType == "TICK_GRANT") or (incommingPacket.msgType == "TICK_GRANT_BROADCAST")):
				currentTime = time.time()
				if (currentTime > self.latestHandleTime):
					self.latestHandleTime = currentTime

				#Wait until we're not busy to send TICK_BLOCK
				stallMonitor = threading.Thread(target=self.waitForStall)
				stallMonitor.start()

			#Handle errors
			elif ("ERROR" in incommingPacket.msgType):
				self.logger.error("{} {}".format(incommingPacket, incommingPacket.payload))

			#Handle incoming information requests
			elif (incommingPacket.msgType == "INFO_REQ"):
				infoRequest = incommingPacket.payload
				infoThread =  threading.Thread(target=self.handleInfoRequest, args=(infoRequest, ))
				infoThread.start()

		self.logger.info("Ending networkLink monitor".format(self.networkLink))


	def sendPacket(self, packet, agentLink=None, agentSendLock=None):
		if (agentLink):
			#Bypass network and send packet directly to agent
			if (agentSendLock):
				acquired_agentSendLock = agentSendLock.acquire(timeout=self.lockTimeout)
				if (acquired_agentSendLock):
					self.logger.info("OUTBOUND {}".format(packet))
					agentLink.sendPipe.send(packet)
					agentSendLock.release()
				else:
					self.logger.error("{}.sendPacket() Lock networkSendLock acquire timeout".format(self.agentId))
			else:
				agentLink.sendPipe.send(packet)
		else:
			#Send this packet over the network
			acquired_networkSendLock = self.networkSendLock.acquire(timeout=self.lockTimeout)
			if (acquired_networkSendLock):
				self.logger.info("OUTBOUND {}".format(packet))
				self.networkLink.sendPipe.send(packet)
				self.networkSendLock.release()
			else:
				self.logger.error("{}.sendPacket() Lock networkSendLock acquire timeout".format(self.agentId))


	def handlePacket(self, incommingPacket, agentLink, agentSendLock):
		self.logger.info("INBOUND {}".format(incommingPacket))
		currentTime = time.time()
		if (currentTime > self.latestHandleTime):
			self.latestHandleTime = currentTime
			
		handled = False
		if (incommingPacket.msgType == "LAND_MARKET_UPDATE"):
			handled = self.updateLandListing(incommingPacket)
		elif (incommingPacket.msgType == "LAND_MARKET_REMOVE"):
			handled = self.removeLandListing(incommingPacket)
		elif (incommingPacket.msgType == "LAND_MARKET_SAMPLE"):
			handled = self.sampleLandListings(incommingPacket, agentLink, agentSendLock)

		return handled

	#########################
	# Time functions
	#########################
	def subcribeTickBlocking(self):
		'''
		Subscribes this agent as a tick blocker with the sim manager
		'''
		self.logger.info("Subscribing as a tick blocker")
		tickBlockPacket = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="TICK_BLOCK_SUBSCRIBE")
		self.sendPacket(tickBlockPacket)


	def waitForStall(self):
		'''
		Subscribes this agent as a tick blocker with the sim manager
		'''
		#Wait for stall
		previousHandleTime = self.latestHandleTime
		while True:
			time.sleep(self.stallTime/4)
			timeDiff = time.time() - self.latestHandleTime
			if (timeDiff > self.stallTime):
				break

		self.logger.info("Stall of {} seconds detected. Sending TICK_BLOCKED".format(self.stallTime))

		#Send tick blocked
		tickBlockedPacket = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="TICK_BLOCKED")
		self.sendPacket(tickBlockedPacket)

	#########################
	# Market functions
	#########################
	def updateLandListing(self, incommingPacket):
		'''
		Update the land marketplace.
		Returns True if succesful, False otherwise
		'''
		landListing = incommingPacket.payload

		self.logger.debug("{}.updateLandListing({}) start".format(self.agentId, landListing))

		updateSuccess = False

		if not (landListing.allocation in self.landMarket):
			#New allocation type. Add empty dict to market
			self.landMarketLock.acquire()
			self.landMarket[landListing.allocation] = {}
			self.landMarketLocks[landListing.allocation] = threading.Lock()
			self.landMarketLock.release()

		if not (landListing.sellerId in self.landMarket[landListing.allocation]):
			#Seller is new to this allocation type. Add them to the market
			landLock = self.landMarketLocks[landListing.allocation]
			acquired_landMarketLock = landLock.acquire(timeout=self.lockTimeout)  # <== landMarketLock acquire
			if (acquired_landMarketLock):
				self.landMarket[landListing.allocation][landListing.sellerId] = landListing
				landLock.release()  # <== landMarketLock release
			else:
				self.logger.error("updateLandListing() Lock \"landMarketLock\" acquisition timeout")
				updateSuccess = False
		else:
			#Seller is already in selling this land. Dict size won't change. No need to acquire thread lock
			self.landMarket[landListing.allocation][landListing.sellerId] = landListing

		#Return status
		self.logger.debug("{}.updateLandListing({}) return {}".format(self.agentId, landListing, updateSuccess))
		return updateSuccess

	def removeLandListing(self, incommingPacket):
		'''
		Remove a listing from the land marketplace
		Returns True if succesful, False otherwise
		'''
		landListing = incommingPacket.payload

		self.logger.debug("{}.removeLandListing({}) start".format(self.agentId, landListing))

		updateSuccess = False

		#Update local land market with listing
		landLock = self.landMarketLocks[landListing.allocation]
		acquired_landMarketLock = landLock.acquire(timeout=self.lockTimeout)  # <== landMarketLock acquire
		if (acquired_landMarketLock):
			if (landListing.allocation in self.landMarket):
				if (landListing.sellerId in self.landMarket[landListing.allocation]):
					del self.landMarket[landListing.allocation][landListing.sellerId]

			landLock.release()  # <== landMarketLock release
			updateSuccess = True
		else:
			self.logger.error("removeLandListing() Lock \"landMarketLock\" acquisition timeout")
			updateSuccess = False

		#Return status
		self.logger.debug("{}.removeLandListing({}) return {}".format(self.agentId, landListing, updateSuccess))
		return updateSuccess

	def sampleLandListings(self, incommingPacket, agentLink, agentSendLock):
		'''
		Sends a list of randomly sampled land listings where
			LandListing.allocation == allocation
			LandListing.hectares >= hectares

		Returns True if successful
		'''

		hectares = incommingPacket.payload["hectares"]
		allocationType = incommingPacket.payload["allocation"]
		sampleSize = incommingPacket.payload["sampleSize"]

		sampledListings = []
		
		#We are the land market. Get information from landMarket dict
		if (allocationType):
			#Allocation type is specified. Only return land of that type
			if (allocationType in self.landMarket):
				landListings = [i for i in self.landMarket[allocationType].values() if i.hectares >= hectares]
				if (len(landListings) > sampleSize):
					sampledListings = random.sample(landListings, sampleSize).copy()
				else:
					sampledListings = landListings
		else:
			#No allocation type specified. All land listings are valid
			landListings = []
			for allocationType in self.landMarket:
				landListings += [i for i in self.landMarket[allocationType].values() if i.hectares >= hectares]

			if (len(landListings) > sampleSize):
				sampledListings = random.sample(list(landListings.values()), sampleSize).copy()
			else:
				sampledListings = list(landListings.values()).copy()

		#Send out sampled listings if request came from network
		if (incommingPacket):
			responsePacket = NetworkPacket(senderId=self.agentId, destinationId=incommingPacket.senderId, transactionId=incommingPacket.transactionId, msgType="LAND_MARKET_SAMPLE_ACK", payload=sampledListings)
			self.sendPacket(responsePacket, agentLink, agentSendLock)


		return True


	#########################
	# Misc functions
	#########################
	def handleInfoRequest(self, infoRequest):
		if (self.agentId == infoRequest.agentId):
			infoKey = infoRequest.infoKey
			if (infoKey == "landMarket"):
				infoRequest.info = self.landMarket
			elif (infoKey == "inventory"):
				infoRequest.info = None
			else:
				infoRequest.info = None
			
			infoRespPacket = NetworkPacket(senderId=self.agentId, destinationId=infoRequest.requesterId, msgType="INFO_RESP", payload=infoRequest)
			self.sendPacket(infoRespPacket)
		else:
			self.logger.warning("Received infoRequest for another agent {}".format(infoRequest))

	def __str__(self):
		return str(self.agentInfo)