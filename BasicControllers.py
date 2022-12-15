import random

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

		self.logger = utils.getLogger("{}:{}".format("PushoverController", self.agentId), logFile=logFile)

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

		self.logger = utils.getLogger("{}:{}".format("TestSnooper", self.agentId), logFile=logFile)

	def controllerStart(self, incommingPacket):
		'''
		Start snoop protocols 
		'''
		#snoopRequest = {"TRADE_REQ": True, "TRADE_REQ_ACK": True}
		snoopRequest = {"INFO_RESP": True}
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
		self.name = "{}_TestSeller".format(agent.agentId)

		self.logger = utils.getLogger("{}:{}".format("TestSeller", self.agentId), logFile=logFile)

		#Keep track of agent assets
		self.currencyBalance = agent.currencyBalance  #(int) cents  #This prevents accounting errors due to float arithmetic (plus it's faster)
		self.inventory = agent.inventory

		#Marketplaces
		self.itemMarket = agent.itemMarket

		#Agent preferences
		self.utilityFunctions = agent.utilityFunctions

		#Determine what to sell
		itemList = self.itemMarket.keys()
		itemId = random.sample(itemList, 1)[0]

		baseUtility = self.utilityFunctions[itemId].baseUtility
		sellPrice = round(baseUtility*random.random())

		maxQuantity = int(20*random.random())

		#Spawn items into inventory
		inventoryEntry = ItemContainer(itemId, maxQuantity)
		self.agent.receiveItem(inventoryEntry)

		#Post item listing
		itemListing = ItemListing(sellerId=self.agentId, itemId=itemId, unitPrice=sellPrice, maxQuantity=maxQuantity)
		self.agent.updateItemListing(itemListing)

		
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

		if (self.agentId == request.sellerId):
			itemId = request.itemPackage.id
			myListing = self.itemMarket[itemId][self.agentId]

			#Check price and quantity
			unitPrice = round(request.currencyAmount / request.itemPackage.quantity)
			if (unitPrice >= myListing.unitPrice) and (request.itemPackage.quantity <= myListing.maxQuantity):
				#Trade terms are good. Make sure we have inventory
				if (itemId in self.inventory):
					currentInventory = self.inventory[itemId]
					newInventory = currentInventory.quantity - request.itemPackage.quantity
					offerAccepted = newInventory > 0
				else:
					offerAccepted = False

		self.logger.info("{} accepted={}".format(request, offerAccepted))
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
		self.name = "{}_TestBuyer".format(agent.agentId)

		self.logger = utils.getLogger("{}:{}".format("TestBuyer", self.agentId), logFile=logFile)

		#Keep track of agent assets
		self.currencyBalance = agent.currencyBalance  #(int) cents  #This prevents accounting errors due to float arithmetic (plus it's faster)
		self.inventory = agent.inventory

		#Marketplaces
		self.itemMarket = agent.itemMarket

		#Agent preferences
		self.utilityFunctions = agent.utilityFunctions

		#Initiate thread kill flag to false
		self.killThreads = False


	def controllerStart(self, incommingPacket):
		#Launch buying loop
		self.shoppingSpree()

	def receiveMsg(self, incommingPacket):
		controllerMsg = incommingPacket.payload
		self.logger.info("INBOUND {}".format(controllerMsg))
		if (controllerMsg.msgType == "STOP_TRADING"):
			self.killThreads = True
		
	def shoppingSpree(self):
		'''
		Keep buying everything until we're statiated (marginalUtility < unitPrice)
		'''
		self.logger.info("Starting shopping spree")

		numSellerCheck = 3
		itemsBought = False
		while True:
			if (self.killThreads):
				self.logger.debug("Received kill command")
				break

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

			if (not itemsBought):
				#We bought no items in this loop. Exit
				break

		self.logger.info("Ending shopping spree")