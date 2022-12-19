'''
These marketplaces live inside the ConnectionNetwork.
They basically function like billboards, where sellers can post listings that can be viewed by other agents.
They do not handle transactions.

Types:
	ItemMarketplace: Where sellers can post ItemListings
'''
import threading
import os
import random

from NetworkClasses import *
import utils


class ItemMarketplace:
	def __init__(self, itemDict, networkLink, logFile=True, fileLevel="INFO"):
		self.agentId = "ItemMarketplace"
		self.logger = utils.getLogger("ItemMarketplace", logFile=logFile, outputdir=os.path.join("LOGS", "Markets"), fileLevel=fileLevel)
		self.logger.info("ItemMarketplace instantiated")

		self.lockTimeout = 5

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
		handled = False
		if (incommingPacket.msgType == "ITEM_MARKET_UPDATE"):
			handled = self.updateItemListing(incommingPacket)
		elif (incommingPacket.msgType == "ITEM_MARKET_REMOVE"):
			handled = self.removeItemListing(incommingPacket)
		elif (incommingPacket.msgType == "ITEM_MARKET_SAMPLE"):
			handled = self.sampleItemListings(incommingPacket, agentLink, agentSendLock)

		return handled

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
	def __init__(self, networkLink, logFile=True, fileLevel="INFO"):
		self.agentId = "LaborMarketplace"
		self.logger = utils.getLogger("LaborMarketplace", logFile=logFile, outputdir=os.path.join("LOGS", "Markets"), fileLevel=fileLevel)
		self.logger.info("LaborMarketplace instantiated")

		self.lockTimeout = 5

		#Pipe connections to the connection network
		self.networkLink = networkLink
		self.networkSendLock = threading.Lock()
		self.responseBuffer = {}
		self.responseBufferLock = threading.Lock()

		#Labor marketplace dict
		self.laborMarket = {}
		self.laborMarketLock = threading.lock()

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
		handled = False
		if (incommingPacket.msgType == "LABOR_MARKET_UPDATE"):
			handled = self.updateLaborListing(incommingPacket)
		elif (incommingPacket.msgType == "LABOR_MARKET_REMOVE"):
			handled = self.removeLaborListing(incommingPacket)
		elif (incommingPacket.msgType == "LABOR_MARKET_SAMPLE"):
			handled = self.sampleLaborListings(incommingPacket, agentLink, agentSendLock)

		return handled

	#########################
	# Market functions
	#########################
	def updateLaborListing(self, incommingPacket):
		'''
		Update the labor marketplace.
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

	def removeLaborListing(self, incommingPacket):
		'''
		Remove a listing from the labor marketplace
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