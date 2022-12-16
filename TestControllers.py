'''
These agent controllers have simple and/or impossible characteristics.
Used for simulation testing.
'''
import random
import os
import threading

import utils
from TradeClasses import *
from ConnectionNetwork import *


class PushoverController:
	'''
	This controller will accept all valid trade requests, and will not take any other action. Used for testing.
	'''
	def __init__(self, agent, logFile=True):
		self.agent = agent
		self.agentId = agent.agentId
		self.name = "{}_PushoverController".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join("LOGS", "Controller_Logs"))

		#Keep track of agent assets
		self.currencyBalance = agent.currencyBalance  #(int) cents  #This prevents accounting errors due to float arithmetic (plus it's faster)
		self.inventory = agent.inventory

	def controllerStart(self, incommingPacket):
		return

	def receiveMsg(self, incommingPacket):
		return

	def evalTradeRequest(self, request):
		'''
		Accept trade request if it is possible
		'''
		self.logger.info("Evaluating trade request {}".format(request))

		offerAccepted = False

		if (self.agentId == request.buyerId):
			#We are the buyer. Check balance
			offerAccepted = request.currencyAmount < self.currencyBalance
		if (self.agentId == request.sellerId):
			#We are the seller. Check item inventory
			itemId = request.itemPackage.id
			if (itemId in self.inventory):
				currentInventory = self.inventory[request.itemPackage.id]
				newInventory = currentInventory.quantity - request.itemPackage.quantity
				offerAccepted = newInventory > 0
			else:
				offerAccepted = False

		self.logger.info("{} accepted={}".format(request, offerAccepted))
		return offerAccepted


class TestSnooper:
	'''
	All this controller does is snoop on packets in the network. Used for testing
	'''
	def __init__(self, agent, logFile=True):
		self.agent = agent
		self.agentId = agent.agentId
		self.name = "{}_TestSnooper".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join("LOGS", "Controller_Logs"))

	def controllerStart(self, incommingPacket):
		'''
		Start snoop protocols 
		'''
		snoopRequest = {"TRADE_REQ": True, "TRADE_REQ_ACK": True}
		#snoopRequest = {"INFO_RESP": True}
		snoopStartPacket = NetworkPacket(senderId=self.agentId, msgType="SNOOP_START", payload=snoopRequest)

		self.logger.info("Sending snoop request {}".format(snoopRequest))
		self.logger.info("OUTBOUND {}".format(snoopStartPacket))
		self.agent.sendPacket(snoopStartPacket)

	def receiveMsg(self, incommingPacket):
		self.logger.debug("INBOUND {}".format(incommingPacket.payload))
		if (incommingPacket.payload.msgType == "INFO_RESP"):
			infoRequest = incommingPacket.payload.payload
			self.logger.debug("{} balance = ${}".format(infoRequest.agentId, infoRequest.info/100))

	def evalTradeRequest(self, request):
		return False


class TestSeller:
	'''
	This controller will sell a random item type for a fixed price. 
	Will create items out of thin air.
	Used for testing.
	'''
	def __init__(self, agent, logFile=True):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestSeller".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join("LOGS", "Controller_Logs"))

		#Keep track of agent assets
		self.currencyBalance = agent.currencyBalance  #(int) cents  #This prevents accounting errors due to float arithmetic (plus it's faster)
		self.inventory = agent.inventory

		#Keep track of time ticks
		self.timeTicks = 0

		#Marketplaces
		self.itemMarket = agent.itemMarket

		#Agent preferences
		self.utilityFunctions = agent.utilityFunctions

		#Determine what to sell
		itemList = self.itemMarket.keys()
		self.sellItemId = random.sample(itemList, 1)[0]

		baseUtility = self.utilityFunctions[self.sellItemId].baseUtility
		self.sellPrice = round(baseUtility*random.random())

		initialQuantity = int(20*random.random())

		#Spawn items into inventory
		inventoryEntry = ItemContainer(self.sellItemId, initialQuantity)
		self.agent.receiveItem(inventoryEntry)

		#Post item listing
		self.myItemListing = ItemListing(sellerId=self.agentId, itemId=self.sellItemId, unitPrice=self.sellPrice, maxQuantity=initialQuantity)
		self.myItemListing_Lock = threading.Lock()
		self.logger.info("OUTBOUND {}".format(self.myItemListing))
		self.agent.updateItemListing(self.myItemListing)

		
	def controllerStart(self, incommingPacket):
		#Subscribe for tick blocking
		tickBlockReq = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="TICK_BLOCK_SUBSCRIBE")
		tickBlockPacket = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="CONTROLLER_MSG", payload=tickBlockReq)
		self.logger.debug("OUTBOUND {}->{}".format(tickBlockReq, tickBlockPacket))
		self.agent.sendPacket(tickBlockPacket)


	def receiveMsg(self, incommingPacket):
		controllerMsg = incommingPacket.payload
		self.logger.info("INBOUND {}".format(controllerMsg))
		
		if (controllerMsg.msgType == "STOP_TRADING"):
			self.killThreads = True

		if (controllerMsg.msgType == "TICK_GRANT"):
			self.timeTicks += int(controllerMsg.payload)
			#Launch production function
			self.produceItems()


	def produceItems(self):
		#Spawn items into inventory
		spawnQuantity = int(20*random.random())
		inventoryEntry = ItemContainer(self.sellItemId, spawnQuantity)
		self.logger.info("Spawning new items to sell {}".format(inventoryEntry))
		self.agent.receiveItem(inventoryEntry)

		#Update listing
		self.logger.info("Updating item listing")

		currentInventory = self.inventory[self.sellItemId]
		self.myItemListing_Lock.acquire()
		self.myItemListing = ItemListing(sellerId=self.agentId, itemId=self.sellItemId, unitPrice=self.sellPrice, maxQuantity=currentInventory.quantity)
		self.myItemListing_Lock.release()

		self.logger.info("OUTBOUND {}".format(self.myItemListing))
		self.agent.updateItemListing(self.myItemListing)

		#Relinquish time ticks
		self.logger.info("Relinquishing time ticks")
		self.timeTicks = 0

		tickBlocked = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="TICK_BLOCKED")
		tickBlockPacket = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="CONTROLLER_MSG", payload=tickBlocked)
		self.logger.debug("OUTBOUND {}->{}".format(tickBlocked, tickBlockPacket))
		self.agent.sendPacket(tickBlockPacket)

		self.logger.debug("Waiting for tick grant")


	def evalTradeRequest(self, request):
		'''
		Accept trade request if it is possible
		'''
		self.logger.info("Evaluating trade request {}".format(request))

		offerAccepted = False

		newInventory = 0

		if (self.agentId == request.sellerId):
			itemId = request.itemPackage.id

			#Check price and quantity
			unitPrice = round(request.currencyAmount / request.itemPackage.quantity)
			if (unitPrice >= self.myItemListing.unitPrice) and (request.itemPackage.quantity <= self.myItemListing.maxQuantity):
				#Trade terms are good. Make sure we have inventory
				if (itemId in self.inventory):
					currentInventory = self.inventory[itemId]
					newInventory = currentInventory.quantity - request.itemPackage.quantity
					offerAccepted = newInventory >= 0
					if (not offerAccepted):
						self.logger.debug("Current Inventory({}) not enough inventory to fulfill {}".format(currentInventory, request))
				else:
					self.logger.debug("{} not in inventory. Can't fulfill {}".format(itemId, request))
					offerAccepted = False
			else:
				self.logger.debug("Bad term offers for {}".format(request))
				self.logger.debug("{} | unitPrice >= self.myItemListing.unitPrice = {} | request.itemPackage.quantity <= self.myItemListing.maxQuantity = {}".format(request.hash, unitPrice >= self.myItemListing.unitPrice, request.itemPackage.quantity <= self.myItemListing.maxQuantity))
				offerAccepted = False
	
		else:
			self.logger.warning("Invalid trade offer {}".format(request))
			self.logger.debug("{} | self.agentId({}) != request.sellerId({})".format(request.hash, self.agentId, request.sellerId))
			offerAccepted = False

		self.logger.info("{} accepted={}".format(request, offerAccepted))

		#Remove item listing if we're out of stock
		if (newInventory == 0) and (offerAccepted):
			self.logger.info("Out of stock. Removing item listing {}".format(self.myItemListing))
			self.agent.removeItemListing(self.myItemListing)
		elif (offerAccepted):
			newListing = ItemListing(sellerId=self.agentId, itemId=itemId, unitPrice=self.myItemListing.unitPrice, maxQuantity=newInventory)
			self.myItemListing_Lock.acquire()
			self.myItemListing = newListing
			self.myItemListing_Lock.release()

			self.logger.info("Update item listing with new stock")
			self.logger.info("OUTBOUND {}".format(newListing))
			self.agent.updateItemListing(newListing)

		return offerAccepted


class TestBuyer:
	'''
	This controller will keep buying items until it can no longer find a good price. 
	Will create currency out of thin air.
	Used for testing.
	'''
	def __init__(self, agent, logFile=True):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestBuyer".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join("LOGS", "Controller_Logs"))

		#Keep track of agent assets
		self.currencyBalance = agent.currencyBalance  #(int) cents  #This prevents accounting errors due to float arithmetic (plus it's faster)
		self.inventory = agent.inventory

		#Marketplaces
		self.itemMarket = agent.itemMarket

		#Agent preferences
		self.utilityFunctions = agent.utilityFunctions

		#Initiate thread kill flag to false
		self.killThreads = False

		#Keep track of time ticks
		self.timeTicks = 0
		self.tickBlockFlag = False
		self.tickBlockFlag_Lock = threading.Lock()


	def controllerStart(self, incommingPacket):
		#Subscribe for tick blocking
		tickBlockReq = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="TICK_BLOCK_SUBSCRIBE")
		tickBlockPacket = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="CONTROLLER_MSG", payload=tickBlockReq)
		self.logger.debug("OUTBOUND {}->{}".format(tickBlockReq, tickBlockPacket))
		self.agent.sendPacket(tickBlockPacket)

	def receiveMsg(self, incommingPacket):
		controllerMsg = incommingPacket.payload
		self.logger.info("INBOUND {}".format(controllerMsg))
		
		if (controllerMsg.msgType == "STOP_TRADING"):
			self.killThreads = True

		if (controllerMsg.msgType == "TICK_GRANT"):
			self.timeTicks += int(controllerMsg.payload)

			self.tickBlockFlag_Lock.acquire()
			self.tickBlockFlag = False
			self.tickBlockFlag_Lock.release()

			#Launch buying loop
			self.shoppingSpree()
		
	def shoppingSpree(self):
		'''
		Keep buying everything until we're statiated (marginalUtility < unitPrice)
		'''
		self.logger.info("Starting shopping spree")

		numSellerCheck = 3
		while ((not self.tickBlockFlag) and (not self.killThreads)):
			if (self.killThreads):
				self.logger.debug("Received kill command")
				break

			if (self.timeTicks > 0):  #We have timeTicks to use
				itemsBought = False

				for itemId in self.itemMarket:
					#Find best price/seller from sample
					possibeSellers = self.itemMarket[itemId].keys()
					sampleSize = 3
					if (sampleSize > len(possibeSellers)):
						sampleSize = len(possibeSellers)
					consideredSellers = random.sample(possibeSellers, sampleSize)

					minPrice = None
					bestSeller = None
					for sellerId in consideredSellers:
						itemListing = self.itemMarket[itemId][sellerId]
						if (minPrice):
							if (itemListing.unitPrice < minPrice):
								minPrice = itemListing.unitPrice
								bestSeller = itemListing.sellerId
						else:
							minPrice = itemListing.unitPrice
							bestSeller = itemListing.sellerId

					#Determing whether to buy
					if (minPrice):
						marginalUtility = self.agent.getMarginalUtility(itemId)
						if (marginalUtility > minPrice):
							#We're buying this item
							itemsBought = True

							#Print money required for purchase
							self.agent.receiveCurrency(minPrice)

							#Send trade request
							itemRequest = ItemContainer(itemId, 1)
							tradeRequest = TradeRequest(sellerId=bestSeller, buyerId=self.agentId, currencyAmount=minPrice, itemPackage=itemRequest)
							self.logger.debug("Buying item | {}".format(tradeRequest))
							tradeCompleted = self.agent.sendTradeRequest(request=tradeRequest, recipientId=bestSeller)
							self.logger.debug("Trade completed={} | {}".format(tradeCompleted, tradeRequest))

							#We used up a tick for this trade. Decrement allotment
							self.timeTicks -= 1
							if (self.timeTicks <= 0):
								#End shopping spree
								break

				if (len(self.itemMarket) == 0):
					self.logger.info("No item listing in the market right now. Relinquishing time timeTicks")
					self.timeTicks = 0
				
				if (not itemsBought):
					self.logger.info("No good item listings found in the market right now. Relinquishing time timeTicks")
					self.timeTicks = 0

			else:
				#We are out of timeTicks
				if (not self.tickBlockFlag):
					#We have not set the block flag yet. Set blocked flag to True
					self.tickBlockFlag_Lock.acquire()
					self.tickBlockFlag = True
					self.tickBlockFlag_Lock.release()

					#Send blocking signal to sim manager
					self.logger.debug("We're tick blocked. Sending TICK_BLOCKED to simManager")

					tickBlocked = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="TICK_BLOCKED")
					tickBlockPacket = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="CONTROLLER_MSG", payload=tickBlocked)
					self.logger.debug("OUTBOUND {}->{}".format(tickBlocked, tickBlockPacket))
					self.agent.sendPacket(tickBlockPacket)

					self.logger.debug("Waiting for tick grant")
					break  #exit while loop


		self.logger.info("Ending shopping spree")