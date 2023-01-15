'''
These agent controllers have simple and/or impossible characteristics.
Used for simulation testing.
'''
import random
import os
import threading

import utils
from TradeClasses import *
from NetworkClasses import *


class PushoverController:
	'''
	This controller will accept all valid trade requests, and will not take any other action. Used for testing.
	'''
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO"):
		self.agent = agent
		self.agentId = agent.agentId
		self.name = "{}_PushoverController".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join("LOGS", "Controller_Logs"), fileLevel=fileLevel)

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
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO"):
		self.agent = agent
		self.agentId = agent.agentId
		self.name = "{}_TestSnooper".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join("LOGS", "Controller_Logs"), fileLevel=fileLevel)

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
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestSeller".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join("LOGS", "Controller_Logs"), fileLevel=fileLevel)

		#Keep track of agent assets
		self.currencyBalance = agent.currencyBalance  #(int) cents  #This prevents accounting errors due to float arithmetic (plus it's faster)
		self.inventory = agent.inventory

		#Keep track of time ticks
		self.timeTicks = self.agent.timeTicks
		self.tickBlockFlag = self.agent.tickBlockFlag


		#Agent preferences
		self.utilityFunctions = agent.utilityFunctions

		#Determine what to sell
		itemList = self.utilityFunctions.keys()
		self.sellItemId = random.sample(itemList, 1)[0]
		if ("itemId" in settings):
			self.sellItemId = settings["itemId"]
			self.logger.info("Sell item specified. Will sell \"{}\"".format(self.sellItemId))
		else:
			self.logger.info("No item specified. Randomly selected \"{}\"".format(self.sellItemId))

		baseUtility = self.utilityFunctions[self.sellItemId].baseUtility
		self.sellPrice = round(baseUtility*random.random())

		initialQuantity = int(200*random.random())

		#Spawn items into inventory
		inventoryEntry = ItemContainer(self.sellItemId, initialQuantity)
		self.agent.receiveItem(inventoryEntry)

		#Initialize item listing
		self.myItemListing = ItemListing(sellerId=self.agentId, itemId=self.sellItemId, unitPrice=self.sellPrice, maxQuantity=initialQuantity)
		self.myItemListing_Lock = threading.Lock()

		
	def controllerStart(self, incommingPacket):
		#Subscribe for tick blocking
		tickBlockReq = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="TICK_BLOCK_SUBSCRIBE")
		tickBlockPacket = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="CONTROLLER_MSG", payload=tickBlockReq)
		self.logger.debug("OUTBOUND {}->{}".format(tickBlockReq, tickBlockPacket))
		self.agent.sendPacket(tickBlockPacket)


	def receiveMsg(self, incommingPacket):
		self.logger.info("INBOUND {}".format(incommingPacket))
		if ((incommingPacket.msgType == "TICK_GRANT") or (incommingPacket.msgType == "TICK_GRANT_BROADCAST")):
			#Launch production function
			self.produceItems()

		if ((incommingPacket.msgType == "CONTROLLER_MSG") or (incommingPacket.msgType == "CONTROLLER_MSG_BROADCAST")):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == "STOP_TRADING"):
				self.killThreads = True


	def produceItems(self):
		#Spawn items into inventory
		spawnQuantity = int(200*random.random())
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
		self.agent.relinquishTimeTicks()
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
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestBuyer".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join("LOGS", "Controller_Logs"), fileLevel=fileLevel)

		#Keep track of agent assets
		self.currencyBalance = agent.currencyBalance  #(int) cents  #This prevents accounting errors due to float arithmetic (plus it's faster)
		self.inventory = agent.inventory

		#Agent preferences
		self.utilityFunctions = agent.utilityFunctions

		#Initiate thread kill flag to false
		self.killThreads = False


	def controllerStart(self, incommingPacket):
		#Subscribe for tick blocking
		tickBlockReq = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="TICK_BLOCK_SUBSCRIBE")
		tickBlockPacket = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="CONTROLLER_MSG", payload=tickBlockReq)
		self.logger.debug("OUTBOUND {}->{}".format(tickBlockReq, tickBlockPacket))
		self.agent.sendPacket(tickBlockPacket)

	def receiveMsg(self, incommingPacket):
		self.logger.info("INBOUND {}".format(incommingPacket))

		if (incommingPacket.msgType == "TICK_GRANT") or (incommingPacket.msgType == "TICK_GRANT_BROADCAST"):
			#Launch buying loop
			self.shoppingSpree()

		if ((incommingPacket.msgType == "CONTROLLER_MSG") or (incommingPacket.msgType == "CONTROLLER_MSG_BROADCAST")):
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
		while ((not self.agent.tickBlockFlag) and (not self.killThreads)):
			if (self.killThreads):
				self.logger.debug("Received kill command")
				break

			if (self.agent.timeTicks > 0):  #We have timeTicks to use
				itemsBought = False

				for itemId in self.utilityFunctions:
					#Find best price/seller from sample
					minPrice = None
					bestSeller = None

					itemContainer = ItemContainer(itemId, 1)
					sampledListings = self.agent.sampleItemListings(itemContainer, sampleSize=3)
					for itemListing in sampledListings:
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
							self.agent.useTimeTicks(1)
							if (self.agent.timeTicks <= 0):
								#End shopping spree
								break
				
				if (not itemsBought):
					self.logger.info("No good item listings found in the market right now. Relinquishing time timeTicks")
					self.agent.relinquishTimeTicks()

			else:
				#We are out of timeTicks
				self.logger.debug("Waiting for tick grant")
				break  #exit while loop


		self.logger.info("Ending shopping spree")


class TestEmployer:
	'''
	This controller will submit random job listings. 
	Will create currency out of thin air.
	Used for testing.
	'''
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestEmployer".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join("LOGS", "Controller_Logs"), fileLevel=fileLevel)

		#Initiate thread kill flag to false
		self.killThreads = False

		#Keep track of job listings we've posted
		self.openJobListings = {}


	def controllerStart(self, incommingPacket):
		#Subscribe for tick blocking
		#tickBlockReq = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="TICK_BLOCK_SUBSCRIBE")
		#tickBlockPacket = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="CONTROLLER_MSG", payload=tickBlockReq)
		#self.logger.debug("OUTBOUND {}->{}".format(tickBlockReq, tickBlockPacket))
		#self.agent.sendPacket(tickBlockPacket)

		#Post random job listings
		self.postRandomListings(3)

	def evalJobApplication(self, laborContract):
		#Span money needed for this contract
		totalWages = laborContract.wagePerTick * laborContract.ticksPerStep * laborContract.contractLength
		self.agent.receiveCurrency(totalWages)

		#Accept application
		return True

	def receiveMsg(self, incommingPacket):
		self.logger.info("INBOUND {}".format(incommingPacket))

		if (incommingPacket.msgType == "TICK_GRANT") or (incommingPacket.msgType == "TICK_GRANT_BROADCAST"):
			pass

		if ((incommingPacket.msgType == "CONTROLLER_MSG") or (incommingPacket.msgType == "CONTROLLER_MSG_BROADCAST")):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == "STOP_TRADING"):
				self.killThreads = True

	def postRandomListings(self, numListings):
		'''
		Post random job listings to job market
		'''
		for i in range(numListings):
			wage = random.randint(800, 5000)
			minSkill = float((wage-800)/4200)
			contractLength = 4
			listing = LaborListing(employerId=self.agentId, ticksPerStep=8, wagePerTick=wage, minSkillLevel=minSkill, contractLength=contractLength, listingName="Employee_{}_{}".format(self.agentId, i))
			self.openJobListings[listing.hash] = listing
			listingUpdated = self.agent.updateLaborListing(listing)
	

class TestWorker:
	'''
	This controller will accept random job listings. 
	Used for testing.
	'''
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestWorker".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join("LOGS", "Controller_Logs"), fileLevel=fileLevel)

		#Initiate thread kill flag to false
		self.killThreads = False


	def controllerStart(self, incommingPacket):
		#Subscribe for tick blocking
		tickBlockReq = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="TICK_BLOCK_SUBSCRIBE")
		tickBlockPacket = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="CONTROLLER_MSG", payload=tickBlockReq)
		self.logger.debug("OUTBOUND {}->{}".format(tickBlockReq, tickBlockPacket))
		self.agent.sendPacket(tickBlockPacket)


	def receiveMsg(self, incommingPacket):
		self.logger.info("INBOUND {}".format(incommingPacket))

		if (incommingPacket.msgType == "TICK_GRANT") or (incommingPacket.msgType == "TICK_GRANT_BROADCAST"):
			self.searchJobs()

		if ((incommingPacket.msgType == "CONTROLLER_MSG") or (incommingPacket.msgType == "CONTROLLER_MSG_BROADCAST")):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == "STOP_TRADING"):
				self.killThreads = True

	def searchJobs(self):
		if (len(self.agent.laborContracts) == 0):
			#Select a job listing
			sampledListings = self.agent.sampleLaborListings()

			highestWage = 0
			bestListing = None
			for listing in sampledListings:
				if (listing.wagePerTick > highestWage):
					highestWage = listing.wagePerTick
					bestListing = listing

			#Send application
			if (bestListing):
				applicationAccepted = self.agent.sendJobApplication(bestListing)

		self.agent.relinquishTimeTicks()


class TestLandSeller:
	'''
	This controller will sell a random amount of land for a random price. 
	Will create land out of thin air.
	Used for testing.
	'''
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestLandSeller".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join("LOGS", "Controller_Logs"), fileLevel=fileLevel)

		#Determine what land to sell
		landTypes = ["UNALLOCATED", "apple", "potato"]
		allocation = random.sample(landTypes, 1)[0]

		hectares = 200
		pricePerHectare = 100*random.random()

		#Spawn land into inventory
		self.agent.receiveLand(allocation, hectares)

		#Initialize item listing
		self.myLandListing = LandListing(sellerId=self.agentId, allocation=allocation, hectares=hectares, pricePerHectare=pricePerHectare)
		self.myLandListing_Lock = threading.Lock()

		
	def controllerStart(self, incommingPacket):
		self.agent.updateLandListing(self.myLandListing)


	def receiveMsg(self, incommingPacket):
		self.logger.info("INBOUND {}".format(incommingPacket))
		if ((incommingPacket.msgType == "TICK_GRANT") or (incommingPacket.msgType == "TICK_GRANT_BROADCAST")):
			pass

		if ((incommingPacket.msgType == "CONTROLLER_MSG") or (incommingPacket.msgType == "CONTROLLER_MSG_BROADCAST")):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == "STOP_TRADING"):
				self.killThreads = True


	def evalLandTradeRequest(self, request):
		'''
		Accept trade request if it is possible
		'''
		self.logger.info("Evaluating land trade request {}".format(request))

		offerAccepted = False
		if (request.hectares == 0):
			self.logger.warning("Invalid trade offer {}".format(request))
			offerAccepted = False
			return offerAccepted

		if (self.agentId == request.sellerId):
			#Check price and quantity
			pricePerHectare = round(request.currencyAmount / request.hectares)
			if (pricePerHectare >= self.myLandListing.pricePerHectare) and (request.hectares <= self.myLandListing.hectares):
				#Trade terms are good. 
				offerAccepted = True
			else:
				self.logger.debug("Bad term offers for {}".format(request))
				self.logger.debug("{} | pricePerHectare >= self.myLandListing.pricePerHectare = {} | request.hectares <= self.myLandListing.hectares = {}".format(request.hash, pricePerHectare >= self.myLandListing.pricePerHectare, request.hectares <= self.myLandListing.hectares))
				offerAccepted = False
	
		else:
			self.logger.warning("Invalid trade offer {}".format(request))
			self.logger.debug("{} | self.agentId({}) != request.sellerId({})".format(request.hash, self.agentId, request.sellerId))
			offerAccepted = False

		self.logger.info("{} accepted={}".format(request, offerAccepted))

		#Remove land listing if we're out of land
		newLandAmount = self.agent.landHoldings[request.allocation] - request.hectares
		if (newLandAmount == 0) and (offerAccepted):
			self.logger.info("Out of land. Removing land listing {}".format(self.myLandListing))
			self.agent.removeItemListing(self.myLandListing)
		elif (offerAccepted):
			newListing = LandListing(sellerId=self.agentId, allocation=self.myLandListing.allocation, hectares=newLandAmount, pricePerHectare=self.myLandListing.pricePerHectare)
			self.myLandListing_Lock.acquire()
			self.myLandListing = newListing
			self.myLandListing_Lock.release()

			self.logger.info("Update land listing with new stock")
			self.logger.info("OUTBOUND {}".format(newListing))
			self.agent.updateLandListing(newListing)

		return offerAccepted


class TestLandBuyer:
	'''
	This controller will keep buying land until it runs out of money. 
	Will create currency out of thin air.
	Used for testing.
	'''
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestLandBuyer".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join("LOGS", "Controller_Logs"), fileLevel=fileLevel)

		self.landTypes = ["UNALLOCATED", "apple", "potato"]

		#Initiate thread kill flag to false
		self.killThreads = False


	def controllerStart(self, incommingPacket):
		#Subscribe for tick blocking
		tickBlockReq = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="TICK_BLOCK_SUBSCRIBE")
		tickBlockPacket = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="CONTROLLER_MSG", payload=tickBlockReq)
		self.logger.debug("OUTBOUND {}->{}".format(tickBlockReq, tickBlockPacket))
		self.agent.sendPacket(tickBlockPacket)
		self.agent.receiveCurrency(10000)

	def receiveMsg(self, incommingPacket):
		self.logger.info("INBOUND {}".format(incommingPacket))

		if (incommingPacket.msgType == "TICK_GRANT") or (incommingPacket.msgType == "TICK_GRANT_BROADCAST"):
			#Launch buying loop
			self.shoppingSpree()

		if ((incommingPacket.msgType == "CONTROLLER_MSG") or (incommingPacket.msgType == "CONTROLLER_MSG_BROADCAST")):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == "STOP_TRADING"):
				self.killThreads = True

		
	def shoppingSpree(self):
		'''
		Keep buying land until we're broke
		'''
		self.logger.info("Starting shopping spree")

		numSellerCheck = 3
		while ((not self.agent.tickBlockFlag) and (not self.killThreads)):
			if (self.killThreads):
				self.logger.debug("Received kill command")
				break

			if (self.agent.timeTicks > 0):  #We have timeTicks to use
				#Find best price/seller from sample
				minPrice = None
				bestSeller = None

				desiredLandType = random.sample(self.landTypes, 1)[0]
				desiredLandAmount = int(20*random.random())+1

				sampledListings = self.agent.sampleLandListings(desiredLandType, desiredLandAmount, sampleSize=3)
				for landListing in sampledListings:
					if (minPrice):
						if (landListing.pricePerHectare < minPrice):
							minPrice = landListing.pricePerHectare
							bestSeller = landListing.sellerId
					else:
						minPrice = landListing.pricePerHectare
						bestSeller = landListing.sellerId

				#Determing whether to buy
				if (minPrice):
					#We're buying this land
					landBought = True

					#Print money required for purchase
					currencyAmount = minPrice*desiredLandAmount
					self.agent.receiveCurrency(currencyAmount)

					#Send trade request
					tradeRequest = LandTradeRequest(sellerId=bestSeller, buyerId=self.agentId, hectares=desiredLandAmount, allocation=desiredLandType, currencyAmount=currencyAmount)
					self.logger.debug("Buying land | {}".format(tradeRequest))
					tradeCompleted = self.agent.sendLandTradeRequest(request=tradeRequest, recipientId=bestSeller)
					self.logger.debug("Trade completed={} | {}".format(tradeCompleted, tradeRequest))

					#We bought land today. Relinquish time ticks
					self.agent.relinquishTimeTicks()
					break
				
				if (not landBought):
					self.logger.info("No good land listings found in the market right now. Relinquishing time timeTicks")
					self.agent.relinquishTimeTicks()

			else:
				#We are out of timeTicks
				self.logger.debug("Waiting for tick grant")
				break  #exit while loop


		self.logger.info("Ending shopping spree")


class TestEater:
	'''
	This controller will eating shit until it's satisfied. 
	Will create currency out of thin air.
	Used for testing.
	'''
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestEater".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join("LOGS", "Controller_Logs"), fileLevel=fileLevel)

		#Keep track of agent assets
		self.currencyBalance = agent.currencyBalance  #(int) cents  #This prevents accounting errors due to float arithmetic (plus it's faster)
		self.inventory = agent.inventory

		#Agent preferences
		self.utilityFunctions = agent.utilityFunctions

		#Initiate thread kill flag to false
		self.killThreads = False


	def controllerStart(self, incommingPacket):
		#Subscribe for tick blocking
		tickBlockReq = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="TICK_BLOCK_SUBSCRIBE")
		tickBlockPacket = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="CONTROLLER_MSG", payload=tickBlockReq)
		self.logger.debug("OUTBOUND {}->{}".format(tickBlockReq, tickBlockPacket))
		self.agent.sendPacket(tickBlockPacket)

		#Enable nutritional tracking
		self.agent.enableHunger()

	def receiveMsg(self, incommingPacket):
		self.logger.info("INBOUND {}".format(incommingPacket))

		if (incommingPacket.msgType == "TICK_GRANT") or (incommingPacket.msgType == "TICK_GRANT_BROADCAST"):
			#Print a shit ton of money
			self.agent.receiveCurrency(50000)
			self.agent.relinquishTimeTicks()

		if ((incommingPacket.msgType == "CONTROLLER_MSG") or (incommingPacket.msgType == "CONTROLLER_MSG_BROADCAST")):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == "STOP_TRADING"):
				self.killThreads = True


class TestSpawner:
	'''
	This controller will spawn and sell a single item. 
	Will spawn items out of thin air at a constant rate.
	Will adjust sell price until quantityProduces ~= quantityPurchased
	Used for testing.
	'''
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestFarmer".format(agent.agentId)
		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join("LOGS", "Controller_Logs"), fileLevel=fileLevel)

		self.inventory = agent.inventory

		#Agent preferences
		self.utilityFunctions = agent.utilityFunctions

		#Determine what to sell
		itemList = self.utilityFunctions.keys()
		self.sellItemId = random.sample(itemList, 1)[0]
		if ("itemId" in settings):
			self.sellItemId = settings["itemId"]
			self.logger.info("Sell item specified. Will sell \"{}\"".format(self.sellItemId))
		else:
			self.logger.info("No item specified. Randomly selected \"{}\"".format(self.sellItemId))

		#Set production rate
		self.productionRate = 10
		if ("spawnRate" in settings):
			self.productionRate = settings["spawnRate"]
			self.logger.info("Spawn rate specified. Will spawn {} {} per step".format(self.productionRate, self.sellItemId))
		else:
			self.logger.info("No spawn rate specified. Will spawn {} {} per step".format(self.productionRate, self.sellItemId))

		#Set ititial price
		baseUtility = self.utilityFunctions[self.sellItemId].baseUtility
		self.sellPrice = round(baseUtility*random.random())
		self.previousSales = self.productionRate
		self.previousPrice = self.sellPrice

		#Spawn initial inventory
		inventoryEntry = ItemContainer(self.sellItemId, self.productionRate*7)
		self.agent.receiveItem(inventoryEntry)

		#Initialize item listing
		self.myItemListing = ItemListing(sellerId=self.agentId, itemId=self.sellItemId, unitPrice=self.sellPrice, maxQuantity=self.productionRate*2)
		self.myItemListing_Lock = threading.Lock()

		
	def controllerStart(self, incommingPacket):
		#Subscribe for tick blocking
		self.agent.subcribeTickBlocking()


	def receiveMsg(self, incommingPacket):
		self.logger.info("INBOUND {}".format(incommingPacket))
		if ((incommingPacket.msgType == "TICK_GRANT") or (incommingPacket.msgType == "TICK_GRANT_BROADCAST")):
			#Launch production function
			self.produceItems()
			self.previousSales = 0

		if ((incommingPacket.msgType == "CONTROLLER_MSG") or (incommingPacket.msgType == "CONTROLLER_MSG_BROADCAST")):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == "STOP_TRADING"):
				self.killThreads = True


	def produceItems(self):
		#Spawn items into inventory
		spawnQuantity = self.productionRate
		inventoryEntry = ItemContainer(self.sellItemId, spawnQuantity)
		self.logger.info("Spawning new items to sell {}".format(inventoryEntry))
		self.agent.receiveItem(inventoryEntry)

		#Update listing
		self.previousPrice = self.sellPrice
		self.logger.info("Updating price...")

		alpha = 0.4
		saleRatio = self.previousSales/self.productionRate
		newPrice = ((1-alpha)*self.sellPrice) + (alpha*saleRatio*self.sellPrice)
		self.sellPrice = newPrice
		self.logger.info("Previous sale ratio = {}".format(saleRatio))
		self.logger.info("New price = {}".format(newPrice))

		self.myItemListing_Lock.acquire()
		self.myItemListing = ItemListing(sellerId=self.agentId, itemId=self.sellItemId, unitPrice=self.sellPrice, maxQuantity=self.myItemListing.maxQuantity)
		self.myItemListing_Lock.release()

		self.logger.debug("OUTBOUND {}".format(self.myItemListing))
		self.agent.updateItemListing(self.myItemListing)

		#Relinquish time ticks
		self.agent.relinquishTimeTicks()
		self.logger.debug("Waiting for tick grant")


	def evalTradeRequest(self, request):
		'''
		Accept trade request if it is possible
		'''
		self.logger.info("Evaluating trade request {}".format(request))

		offerAccepted = False

		newInventory = 0

		if (request.itemPackage.quantity <= 0):
			self.logger.debug("Requested quantity <= 0. Rejecting")
			offerAccepted = False
			return offerAccepted

		if (self.agentId == request.sellerId):
			itemId = request.itemPackage.id

			#Check price and quantity
			unitPrice = round(request.currencyAmount / request.itemPackage.quantity)+1
			if ((unitPrice >= self.sellPrice) or (unitPrice >= self.previousPrice)) and (request.itemPackage.quantity <= self.myItemListing.maxQuantity):
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
				self.logger.debug("{} | unitPrice({}) >= self.myItemListing.unitPrice({}) = {} | request.itemPackage.quantity({}) <= self.myItemListing.maxQuantity({}) = {}".format(request.hash, unitPrice, self.sellPrice, unitPrice >= self.sellPrice, request.itemPackage.quantity, self.myItemListing.maxQuantity, request.itemPackage.quantity <= self.myItemListing.maxQuantity))
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
			self.previousSales += request.itemPackage.quantity

		return offerAccepted