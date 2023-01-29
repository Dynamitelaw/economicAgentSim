'''
These agent controllers have simple and/or impossible characteristics.
Used for simulation testing.
'''
import random
import os
import threading
import math
from sortedcontainers import SortedList
import traceback

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
		self.searchStart = False


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
		if not (self.searchStart):
			randomNum = random.random()
			if (randomNum < 0.67):
				self.agent.relinquishTimeTicks()
				return
			self.searchStart = True

		if (len(self.agent.laborContracts) == 0):
			#Select a job listing
			sampledListings = self.agent.sampleLaborListings(sampleSize=7)

			#Sort listings by wage
			wageDict = {}
			for listing in sampledListings:
				if not (listing.wagePerTick in wageDict):
					wageDict[listing.wagePerTick] = []
				wageDict[listing.wagePerTick].append(listing)

			sortedWages = list(wageDict.keys())
			sortedWages.sort()

			#Send applications
			applicationAccepted = False
			for wageKey in sortedWages:
				for listing in wageDict[wageKey]:
					applicationAccepted = self.agent.sendJobApplication(listing)
					if (applicationAccepted):
						break
				if (applicationAccepted):
					break

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

		alpha = 0.2
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


class TestEmployerCompetetive:
	'''
	This controller will try to fulfill it's labor requirements by adjusting wages until laborReceived ~= laborDemanded. 
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

		#Determine how much labor we need and initial wage
		self.laborSkillLevel = float(int(self.agent.skillLevel*10))/10
		self.wagePerTick = 100*self.laborSkillLevel*random.random()+10
		self.ticksPerStep = 8
		self.contractLength = 3

		self.listing = LaborListing(employerId=self.agentId, ticksPerStep=self.ticksPerStep, wagePerTick=self.wagePerTick, minSkillLevel=self.laborSkillLevel, contractLength=self.contractLength, listingName="Employeer_{}".format(self.agentId))

		#How many applications have we recieved for this job
		self.applications = 0
		self.openSteps = 0
		self.nextWage = self.wagePerTick


	def controllerStart(self, incommingPacket):
		#Subscribe for tick blocking
		self.agent.subcribeTickBlocking()

		#Post job listing
		self.updateListing()

	def adjustNextWage(self):
		divisor = 1.0
		if (self.applications>0):
			divisor = pow(self.applications, 1.9)

		dividend = 1.0
		if (self.openSteps > 0):
			dividend = (pow(self.openSteps, 0.4))

		#Adjust the wage for next time
		adjustmentRatio = dividend/divisor
		alpha = 0.6
		self.nextWage = ((1-alpha)*self.wagePerTick)+(alpha*adjustmentRatio*self.wagePerTick)

		#Print stats
		self.logger.debug("applications={}, openSteps={}, adjustmentRatio={}, nextWage={}".format(self.applications, self.openSteps, adjustmentRatio, self.nextWage))

	def evalJobApplication(self, laborContract):
		if (self.openSteps > 0):
			self.applications = 0
		self.openSteps = 0

		#Remove labor listing
		if (self.applications == 0):
			self.agent.removeLaborListing(self.listing)

		self.applications += 1
		#Make sure we haven't already hired someone
		if (len(self.agent.laborContracts) > 0):
			#Adjust the wage for next time
			self.adjustNextWage()

			#Reject application
			return False

		#Spawn money needed for this contract
		self.logger.info("Recieved job application {}".format(laborContract))
		totalWages = int((laborContract.wagePerTick * laborContract.ticksPerStep * laborContract.contractLength + 100)*10)
		self.agent.receiveCurrency(totalWages)

		#Accept application
		return True

	def receiveMsg(self, incommingPacket):
		self.logger.info("INBOUND {}".format(incommingPacket))

		if (incommingPacket.msgType == "TICK_GRANT") or (incommingPacket.msgType == "TICK_GRANT_BROADCAST"):
			if (len(self.agent.laborContracts) == 0):
				#We have not hired anyone yet
				self.openSteps += 1

				#Adjust wages
				if (self.openSteps > 1):
					self.adjustNextWage()
					self.wagePerTick = self.nextWage
					self.updateListing()

			self.logger.info("Relinquishing time ticks")
			ticksRelinquished = self.agent.relinquishTimeTicks()
			self.logger.info("Ticks relinquished. Waiting for tick grant")

		if ((incommingPacket.msgType == "CONTROLLER_MSG") or (incommingPacket.msgType == "CONTROLLER_MSG_BROADCAST")):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == "STOP_TRADING"):
				self.killThreads = True

	def updateListing(self):
		self.listing = LaborListing(employerId=self.agentId, ticksPerStep=self.ticksPerStep, wagePerTick=self.wagePerTick, minSkillLevel=self.laborSkillLevel, contractLength=self.contractLength, listingName="Employeer_{}".format(self.agentId))
		self.logger.info("Updating job listing | {}".format(self.listing))
		listingUpdated = self.agent.updateLaborListing(self.listing)


class TestFarmWorker:
	'''
	This controller will try to find the highest paying job. Will automatically pruchase and consume food. 
	Used for testing.
	'''
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestFarmWorker".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join("LOGS", "Controller_Logs"), fileLevel=fileLevel)

		#Initiate thread kill flag to false
		self.killThreads = False

		#Spawn starting balance
		self.agent.receiveCurrency(9999)

		#Handle start skews
		self.startStep = 0
		if ("StartSkew" in settings):
			skewRate = settings["StartSkew"]+1
			self.startStep = int(random.random()/(1.0/skewRate))


	def controllerStart(self, incommingPacket):
		#Subscribe for tick blocking
		self.agent.subcribeTickBlocking()

		#Enable hunger
		self.agent.enableHunger()

		#Enable accounting
		self.agent.enableLaborIncomeTracking()

	def receiveMsg(self, incommingPacket):
		self.logger.info("INBOUND {}".format(incommingPacket))

		if (incommingPacket.msgType == "TICK_GRANT") or (incommingPacket.msgType == "TICK_GRANT_BROADCAST"):
			if (self.agent.stepNum == self.startStep):
				self.logger.info("StepNum = {}, Starting controller functionality".format(self.agent.stepNum))
				self.agent.enableHunger()

			if (self.agent.stepNum >= self.startStep):
				avgLaborIncome = self.agent.getAvgLaborIncome()
				self.logger.info("Avg Labor Income = {}".format(avgLaborIncome))
				self.searchJobs()

			self.agent.relinquishTimeTicks()

		if ((incommingPacket.msgType == "CONTROLLER_MSG") or (incommingPacket.msgType == "CONTROLLER_MSG_BROADCAST")):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == "STOP_TRADING"):
				self.killThreads = True

	def searchJobs(self):
		if (len(self.agent.laborContracts) == 0):
			self.logger.info("Searching for jobs")
			#Select a job listing
			sampledListings = self.agent.sampleLaborListings(sampleSize=7)
			self.logger.info("Found {} job listings".format(len(sampledListings)))

			#Sort listings by wage
			wageDict = {}
			for listing in sampledListings:
				if not (listing.wagePerTick in wageDict):
					wageDict[listing.wagePerTick] = []
				wageDict[listing.wagePerTick].append(listing)

			sortedWages = list(wageDict.keys())
			sortedWages.sort()

			#Send applications
			applicationAccepted = False
			for wageKey in sortedWages:
				for listing in wageDict[wageKey]:
					applicationAccepted = self.agent.sendJobApplication(listing)
					self.logger.info("Application accepted = {} for {}".format(applicationAccepted, listing))
					if (applicationAccepted):
						break
				if (applicationAccepted):
					break

			self.logger.info("Could not find a job this step")


class TestFarmCompetetive:
	'''
	This controller will hire workers and buy input costs to produce a single item.
	Will sell that item on the marketplace, and adjust the price to maxmimize revenue.
	Used for testing.
	'''
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestFarmCompetetive".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join("LOGS", "Controller_Logs"), fileLevel=fileLevel)

		#Initiate thread kill flag to false
		self.killThreads = False

		#Handle start skews
		self.startStep = 0
		if ("StartSkew" in settings):
			skewRate = settings["StartSkew"]+1
			self.startStep = int(random.random()/(1.0/skewRate))

		#Determine what to produce
		itemList = self.agent.utilityFunctions.keys()
		self.sellItemId = random.sample(itemList, 1)[0]
		if ("itemId" in settings):
			self.sellItemId = settings["itemId"]
			self.logger.info("Sell item specified. Will sell \"{}\"".format(self.sellItemId))
		else:
			self.logger.info("No item specified. Randomly selected \"{}\"".format(self.sellItemId))


		#Keep track of production targets
		self.targetProductionRate = 10
		if ("startingProductionRate" in settings):
			self.targetProductionRate = settings["startingProductionRate"]
			self.logger.info("Initial production rate specified. Will initialize target production to {} {} per step".format(self.targetProductionRate, self.sellItemId))
		else:
			self.logger.info("No initial production rate specified. Will initialize target production to {} {} per step".format(self.targetProductionRate, self.sellItemId))
		self.currentProductionRateAvg = self.targetProductionRate

		#Keep track of sell price
		averageCustomers = 13/2
		self.sellPrice = (self.agent.utilityFunctions[self.sellItemId].getMarginalUtility(self.targetProductionRate/averageCustomers)) * (1+(random.random()-0.5))
		self.currentSalesAvg = self.targetProductionRate 
		self.stepSales = self.currentSalesAvg
		#self.stepSalesLock = threading.Lock()  #TODO

		self.itemListing = ItemListing(sellerId=self.agentId, itemId=self.sellItemId, unitPrice=self.sellPrice, maxQuantity=self.currentProductionRateAvg/3)

		#Keep track of wages and hiring stats
		self.requiredLabor = 0

		self.laborSkillLevel = 0
		self.maxTicksPerStep = 8
		self.contractLength = int(5*(1+((random.random()-0.5)/2)))

		self.workerWage = 60*(1 + ((random.random()-0.5)/2))
		self.applications = 0
		self.openSteps = 0
		self.workerDeficit = math.ceil(self.requiredLabor/self.maxTicksPerStep)
		self.listingActive = False
		
		self.laborListing = LaborListing(employerId=self.agentId, ticksPerStep=self.maxTicksPerStep, wagePerTick=self.workerWage, minSkillLevel=self.laborSkillLevel, contractLength=self.contractLength, listingName="Employer_{}".format(self.agentId))


	def controllerStart(self, incommingPacket):
		#Subscribe for tick blocking
		self.agent.subcribeTickBlocking()

		#Spawn initial quantity of land
		self.agent.receiveLand("UNALLOCATED", 9999999999)

		#Spawn initial inventory of items
		self.agent.receiveItem(ItemContainer(self.sellItemId, self.targetProductionRate))

		#Enable accounting
		self.agent.enableCurrencyOutflowTracking()
		self.agent.enableCurrencyInflowTracking()

	def adjustProduction(self):
		#Alphas for moving exponential adjustments
		prodAlpha = 0.1
		priceAlpha = 0.2
		medianPriceAlpha = 0.4

		#Get total contracted labor
		contactLaborInventory = self.agent.getNetContractedEmployeeLabor()
		laborSum = 0
		for skillLevel in contactLaborInventory:
			laborSum += contactLaborInventory[skillLevel]

		#Get labor deficit ratio
		laborDeficitRatio = 1
		if (self.requiredLabor > 0):
			laborDeficitRatio = 1 - (self.requiredLabor/(laborSum+self.requiredLabor))  #TODO: FIX ME

		#Get product inventory
		productInventory = 0
		if (self.sellItemId in self.agent.inventory):
			productInventory = self.agent.inventory[self.sellItemId].quantity

		#Adjust target production
		self.logger.info("Old target production rate = {}".format(self.targetProductionRate))
		inventoryRatio = (self.currentProductionRateAvg+1) / (productInventory+1)
		self.targetProductionRate = ((1-prodAlpha)*self.targetProductionRate) + (prodAlpha*self.currentSalesAvg*inventoryRatio*1.1)#*(self.targetProductionRate/self.currentProductionRateAvg))
		self.logger.info("New target production rate = {}".format(self.targetProductionRate))
		self.logger.info("Average production rate = {}".format(self.currentProductionRateAvg))

		#Adjust target price based on median price
		self.logger.info("Old sale price = {}".format(self.sellPrice))

		medianPrice = self.sellPrice
		sampledListings = self.agent.sampleItemListings(ItemContainer(self.sellItemId, 0.01), sampleSize=30)
		sampledPrices = SortedList()
		if (len(sampledListings) > 0):
			for listing in sampledListings:
				sampledPrices.add(listing.unitPrice)
			medianPrice = sampledPrices[int(len(sampledListings)/2)]

		self.logger.info("Median market price = {}".format(medianPrice))
		self.sellPrice = ((1-priceAlpha)*self.sellPrice) + (priceAlpha*medianPrice)

		#Adjust price based on inventory ratios
		saleRatio = pow((self.currentSalesAvg+1)/(self.currentProductionRateAvg+1), 0.9)
		adjustmentRatio = saleRatio
		if (adjustmentRatio > 1.1) or (adjustmentRatio < 0.9):
			#Adjust sell price
			newPrice = self.sellPrice * adjustmentRatio
			self.sellPrice = ((1-priceAlpha)*self.sellPrice) + (priceAlpha*newPrice)
			self.logger.info("New sale price = {}".format(self.sellPrice))

		#See if we have any deficits for the new production rate
		inputDeficits = self.agent.getProductionInputDeficit(self.sellItemId, self.targetProductionRate)
		self.logger.info("Input deficits = {}".format(inputDeficits))
		self.acquireDeficits(inputDeficits)

		#Get rid of surplus inputs
		surplusInputs = self.agent.getProductionInputSurplus(self.sellItemId, self.targetProductionRate)
		self.logger.info("Input surplus = {}".format(surplusInputs))
		self.removeSurplus(surplusInputs)


	def liquidateItem(self, itemContainer):
		self.agent.consumeItem(itemContainer)


	def acquireDeficits(self, deficits):
		#Allocate more land if we don't have enough
		landDeficit = deficits["LandDeficit"] - self.agent.landHoldings["ALLOCATING"]
		if (landDeficit > 0):
			self.agent.allocateLand(self.sellItemId, landDeficit)

		#Spawn fixed item inputs
		for itemId in deficits["FixedItemDeficit"]:
			self.agent.receiveItem(deficits["FixedItemDeficit"][itemId])

		#Adjust labor requirements
		for skillLevel in deficits["LaborDeficit"]:
			self.requiredLabor = deficits["LaborDeficit"][skillLevel]

		#Spawn variable item inputs
		for itemId in deficits["VariableItemDeficit"]:
			self.agent.receiveItem(deficits["VariableItemDeficit"][itemId])


	def removeSurplus(self, surplusInputs):
		#Deallocate land if we have too much
		landSurplus = surplusInputs["LandSurplus"]
		if (landSurplus > 0):
			self.agent.deallocateLand(self.sellItemId, landSurplus)

		#Liquidate fixed item inputs
		for itemId in surplusInputs["FixedItemSurplus"]:
			self.liquidateItem(surplusInputs["FixedItemSurplus"][itemId])

		#Adjust labor requirements
		for skillLevel in surplusInputs["LaborSurplus"]:
			self.requiredLabor = -1*surplusInputs["LaborSurplus"][skillLevel]

		#Liquidate variable item inputs
		for itemId in surplusInputs["VariableItemSurplus"]:
			self.liquidateItem(surplusInputs["VariableItemSurplus"][itemId])


	def adjustNextWage(self):
		medianAlpha = 0.4
		adjustmentAlpha = 0.2
		#Adjust wage  based on market rate
		medianWage = self.workerWage
		sampledListings = self.agent.sampleLaborListings(sampleSize=30)
		sampledWages = SortedList()
		if (len(sampledListings) > 0):
			for listing in sampledListings:
				sampledWages.add(listing.wagePerTick)
			medianWage = sampledWages[int(len(sampledListings)/2)]
		self.workerWage = ((1-medianAlpha)*self.workerWage)+(medianAlpha*medianWage)

		#Adjust wage based on worker deficit and application number
		divisor = 1
		if (self.workerDeficit < 0):
			divisor = pow(abs(self.workerDeficit)*1.2, 1.2)
		if (self.workerDeficit > 0) and (self.openSteps > 2):
			divisor = 1/pow((self.workerDeficit), 0.3)
		if (abs(self.applications/self.workerDeficit)>1.5):
			divisor = pow(abs(self.applications/self.workerDeficit), 1.5)

		dividend = 1.0
		if (self.openSteps > 3):
			dividend = (pow(self.openSteps, 0.2))

		#Adjust the wage for next time
		adjustmentRatio = dividend/divisor
		self.workerWage = ((1-adjustmentAlpha)*self.workerWage)+(adjustmentAlpha*adjustmentRatio*self.workerWage)

		#Print stats
		self.logger.debug("HR Stats: requiredLabor={}, workerDeficit={}, applications={}, openSteps={}, adjustmentRatio={}, workerWage={}".format(self.requiredLabor, self.workerDeficit, self.applications, self.openSteps, adjustmentRatio, self.workerWage))


	def evalJobApplication(self, laborContract):
		self.logger.debug("Recieved job application {}".format(laborContract))
		if (self.openSteps > 0):
			self.applications = 0
		self.openSteps = 0

		self.applications += 1

		#Hire them if we need the labor
		if (self.requiredLabor > 0):
			self.logger.info("Accepting job application {}".format(laborContract))
			#Spawn money needed for this contract
			totalWages = int((laborContract.wagePerTick * laborContract.ticksPerStep * laborContract.contractLength + 100)*10)
			self.agent.receiveCurrency(totalWages)

			#Decrease required labor
			self.requiredLabor -= laborContract.ticksPerStep
			if (self.requiredLabor < 0):
				self.requiredLabor = 0

			self.logger.debug("Accepted job application {}".format(laborContract))
			return True
		else:
			#We don't need more labor. Reject this application
			self.logger.debug("Rejected job application {}".format(laborContract))
			return False


	def manageLabor(self):
		#Update worker deficit
		if (self.requiredLabor > 0):
			self.workerDeficit = math.ceil(self.requiredLabor/self.maxTicksPerStep)
		elif (self.requiredLabor < 0):
			self.workerDeficit = math.floor(self.requiredLabor/self.maxTicksPerStep)

		#Adjust wages
		self.adjustNextWage()

		#Update job listing
		if (self.requiredLabor > 0):
			self.laborListing = LaborListing(employerId=self.agentId, ticksPerStep=self.maxTicksPerStep, wagePerTick=self.workerWage, minSkillLevel=self.laborSkillLevel, contractLength=self.contractLength, listingName="Employer_{}".format(self.agentId))
			self.logger.info("Updating job listing | {}".format(self.laborListing))
			listingUpdated = self.agent.updateLaborListing(self.laborListing)
			if (self.listingActive):
				self.openSteps += 1
			self.listingActive = True
		else:
			#Remove listing
			self.agent.removeLaborListing(self.laborListing)
			self.listingActive = False
			self.applications = 0
			self.openSteps = 0

	def produce(self):
		#Produce items
		maxProductionPossible = self.agent.getMaxProduction(self.sellItemId)

		productionAmount = self.targetProductionRate
		if (productionAmount > maxProductionPossible):
			productionAmount = maxProductionPossible

		producedItems = self.agent.produceItem(ItemContainer(self.sellItemId, productionAmount))

		#Update production average
		alpha = 0.4
		self.currentProductionRateAvg = ((1-alpha)*self.currentProductionRateAvg) + (alpha*productionAmount)

	def updateItemListing(self):
		self.itemListing = ItemListing(sellerId=self.agentId, itemId=self.sellItemId, unitPrice=self.sellPrice, maxQuantity=self.currentProductionRateAvg/3)
		self.logger.info("Updating item listing | {}".format(self.itemListing))
		listingUpdated = self.agent.updateItemListing(self.itemListing)


	def evalTradeRequest(self, request):
		productInventory = 0
		if (request.itemPackage.id in self.agent.inventory):
			productInventory = self.agent.inventory[request.itemPackage.id].quantity

		tradeAccepted = productInventory>request.itemPackage.quantity
		if (tradeAccepted):
			self.stepSales += request.itemPackage.quantity

		return tradeAccepted


	def receiveMsg(self, incommingPacket):
		self.logger.info("INBOUND {}".format(incommingPacket))

		if (incommingPacket.msgType == "TICK_GRANT") or (incommingPacket.msgType == "TICK_GRANT_BROADCAST"):
			if (self.agent.stepNum == self.startStep):
				self.logger.info("StepNum = {}, Starting controller functionality".format(self.agent.stepNum))

			if (self.agent.stepNum >= self.startStep):
				#Update sales average
				alpha = 0.2
				self.currentSalesAvg = ((1-alpha)*self.currentSalesAvg) + (alpha*self.stepSales)
				self.stepSales = 0

				#Print business stats
				self.logger.info("Current sales average = {}".format(self.currentSalesAvg))
				avgRevenue = self.agent.getAvgCurrencyInflow()
				avgExpenses = self.agent.getAvgCurrencyOutflow()
				self.logger.info("Avg Daily Expenses={}, Avg Daily Revenue={}, Avg Daily Profit={}".format(avgExpenses, avgRevenue, avgRevenue-avgExpenses))

				#Adjust production
				self.adjustProduction()

				#Manage worker hiring
				self.manageLabor()

				#Produce items
				self.produce()

				#Update item listing
				self.updateItemListing()

			#Relinquish time ticks
			self.logger.info("Relinquishing time ticks")
			ticksRelinquished = self.agent.relinquishTimeTicks()
			self.logger.info("Ticks relinquished. Waiting for tick grant")

		if ((incommingPacket.msgType == "CONTROLLER_MSG") or (incommingPacket.msgType == "CONTROLLER_MSG_BROADCAST")):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == "STOP_TRADING"):
				self.killThreads = True


class TestFarmWorkerV2:
	'''
	This controller will try to find the highest paying job. Will automatically pruchase and consume food. 
	Used for testing.
	'''
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestFarmWorkerV2".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join("LOGS", "Controller_Logs"), fileLevel=fileLevel)

		#Initiate thread kill flag to false
		self.killThreads = False

		#Spawn starting balance
		self.agent.receiveCurrency(99999)

		#Wage expectations
		self.expectedWage = 0

		#Handle start skews
		self.startStep = 0
		if ("StartSkew" in settings):
			skewRate = settings["StartSkew"]+1
			self.startStep = int(random.random()/(1.0/skewRate))


	def controllerStart(self, incommingPacket):
		#Subscribe for tick blocking
		self.agent.subcribeTickBlocking()

		#Enable hunger
		self.agent.enableHunger()

		#Enable accounting
		self.agent.enableLaborIncomeTracking()

	def receiveMsg(self, incommingPacket):
		self.logger.info("INBOUND {}".format(incommingPacket))

		if (incommingPacket.msgType == "TICK_GRANT") or (incommingPacket.msgType == "TICK_GRANT_BROADCAST"):
			if (self.agent.stepNum == self.startStep):
				self.logger.info("StepNum = {}, Starting controller functionality".format(self.agent.stepNum))
				self.agent.enableHunger()

			if (self.agent.stepNum >= self.startStep):
				avgLaborIncome = self.agent.getAvgLaborIncome()
				self.logger.info("Avg Labor Income = {}".format(avgLaborIncome))
				self.searchJobs()

			self.agent.relinquishTimeTicks()

		if ((incommingPacket.msgType == "CONTROLLER_MSG") or (incommingPacket.msgType == "CONTROLLER_MSG_BROADCAST")):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == "STOP_TRADING"):
				self.killThreads = True

	def searchJobs(self):
		if (len(self.agent.laborContracts) == 0):
			self.logger.info("Searching for jobs")
			self.logger.info("Wage expectation = {}".format(self.expectedWage))
			#Select a job listing
			sampledListings = self.agent.sampleLaborListings(sampleSize=7)
			self.logger.info("Found {} job listings".format(len(sampledListings)))

			#Sort listings by wage
			wageDict = {}
			for listing in sampledListings:
				if not (listing.wagePerTick in wageDict):
					wageDict[listing.wagePerTick] = []
				wageDict[listing.wagePerTick].append(listing)

			sortedWages = list(wageDict.keys())
			sortedWages.sort()

			#Send applications
			applicationAccepted = False
			for wageKey in sortedWages:
				if (wageKey < self.expectedWage):
					break
				for listing in wageDict[wageKey]:
					applicationAccepted = self.agent.sendJobApplication(listing)
					self.logger.info("Application accepted = {} for {}".format(applicationAccepted, listing))
					if (applicationAccepted):
						self.expectedWage = wageKey
						return

			self.expectedWage = self.expectedWage*0.9
			self.logger.info("Could not find a job this step")

class TestFarmCompetetiveV2:
	'''
	This controller will hire workers and buy input costs to produce a single item.
	Will sell that item on the marketplace, and adjust the price to maxmimize profit.
	Used for testing.
	'''
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestFarmCompetetiveV2".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join("LOGS", "Controller_Logs"), fileLevel=fileLevel)

		#Initiate thread kill flag to false
		self.killThreads = False

		#Handle start skews
		self.startStep = 0
		if ("StartSkew" in settings):
			skewRate = settings["StartSkew"]+1
			self.startStep = int(random.random()/(1.0/skewRate))
		self.updateRate = 5
		self.updateOffset = self.startStep

		#Determine what to produce
		itemList = self.agent.utilityFunctions.keys()
		self.sellItemId = random.sample(itemList, 1)[0]
		if ("itemId" in settings):
			self.sellItemId = settings["itemId"]
			self.logger.info("Sell item specified. Will sell \"{}\"".format(self.sellItemId))
		else:
			self.logger.info("No item specified. Randomly selected \"{}\"".format(self.sellItemId))


		#Keep track of production targets
		self.targetProductionRate = 10
		if ("startingProductionRate" in settings):
			self.targetProductionRate = settings["startingProductionRate"]
			self.logger.info("Initial production rate specified. Will initialize target production to {} {} per step".format(self.targetProductionRate, self.sellItemId))
		else:
			self.logger.info("No initial production rate specified. Will initialize target production to {} {} per step".format(self.targetProductionRate, self.sellItemId))
		self.currentProductionRateAvg = self.targetProductionRate

		#Keep track of sell price
		averageCustomers = 480/9
		self.sellPrice = (self.agent.utilityFunctions[self.sellItemId].getMarginalUtility(self.targetProductionRate/averageCustomers)) * (1+(random.random()-0.5))
		self.currentSalesAvg = self.targetProductionRate 
		self.stepSales = self.currentSalesAvg
		#self.stepSalesLock = threading.Lock()  #TODO

		self.itemListing = ItemListing(sellerId=self.agentId, itemId=self.sellItemId, unitPrice=self.sellPrice, maxQuantity=self.currentProductionRateAvg/3)

		#Keep track of wages and hiring stats
		self.requiredLabor = 0

		self.laborSkillLevel = 0
		self.maxTicksPerStep = 8
		self.contractLength = int(10*(1+((random.random()-0.5)/2)))

		self.workerWage = 60*(1 + ((random.random()-0.5)/2))
		self.applications = 0
		self.openSteps = 0
		self.workerDeficit = math.ceil(self.requiredLabor/self.maxTicksPerStep)
		self.listingActive = False
		
		self.laborListing = LaborListing(employerId=self.agentId, ticksPerStep=self.maxTicksPerStep, wagePerTick=self.workerWage, minSkillLevel=self.laborSkillLevel, contractLength=self.contractLength, listingName="Employer_{}".format(self.agentId))


	def controllerStart(self, incommingPacket):
		#Subscribe for tick blocking
		self.agent.subcribeTickBlocking()

		#Spawn initial quantity of land
		self.agent.receiveLand("UNALLOCATED", 9999999999)

		#Spawn initial inventory of items
		self.agent.receiveItem(ItemContainer(self.sellItemId, self.targetProductionRate))

		#Enable accounting
		self.agent.enableCurrencyOutflowTracking()
		self.agent.enableCurrencyInflowTracking()

	def adjustProduction(self):
		#Alphas for moving exponential adjustments
		prodAlpha = 0.2
		priceAlpha = 0.2
		medianPriceAlpha = 0.2

		#Get current profit margins
		avgRevenue = self.agent.getAvgCurrencyInflow()
		avgExpenses = self.agent.getAvgCurrencyOutflow()
		profitMargin = 0
		if (avgExpenses > 0):
			profitMargin = (avgRevenue-avgExpenses)/avgExpenses
		self.logger.debug("Profit margin = {}".format(profitMargin))

		#Get product inventory
		productInventory = 0
		if (self.sellItemId in self.agent.inventory):
			productInventory = self.agent.inventory[self.sellItemId].quantity

		#Adjust target production based on current profit margin and inventory ratio
		self.logger.info("Old target production rate = {}".format(self.targetProductionRate))
		saleRatio = (self.currentSalesAvg+1)/(self.currentProductionRateAvg+1)
		inventoryRatio = (self.currentProductionRateAvg+1) / (productInventory+1)
		productionAdjustmentRatio = pow((1+profitMargin), 0.6)*pow(inventoryRatio, 0.5)
		self.logger.debug("Production adjustment ratio = {}".format(productionAdjustmentRatio))
		self.targetProductionRate = ((1-prodAlpha)*self.targetProductionRate) + (prodAlpha*self.currentProductionRateAvg*productionAdjustmentRatio)
		self.logger.info("New target production rate = {}".format(self.targetProductionRate))
		self.logger.info("Average production rate = {}".format(self.currentProductionRateAvg))

		#Adjust target price based on median price
		self.logger.info("Old sale price = {}".format(self.sellPrice))

		medianPrice = self.sellPrice
		sampledListings = self.agent.sampleItemListings(ItemContainer(self.sellItemId, 0.01), sampleSize=30)
		sampledPrices = SortedList()
		if (len(sampledListings) > 0):
			for listing in sampledListings:
				sampledPrices.add(listing.unitPrice)
			#medianPrice = sampledPrices[int(len(sampledListings)/2)]
			medianPrice = sampledPrices[0]

		self.logger.info("Median market price = {}".format(medianPrice))
		self.sellPrice = ((1-medianPriceAlpha)*self.sellPrice) + (medianPriceAlpha*medianPrice)

		#Adjust price based on sale ratios
		adjustmentRatio = pow(saleRatio, 0.9)
		self.logger.debug("Inventory ratio = {}".format(inventoryRatio))
		self.logger.debug("Sale ratio = {}".format(saleRatio))
		self.logger.debug("Price adjustment ratio = {}".format(adjustmentRatio))
		if (adjustmentRatio > 1.05) or (adjustmentRatio < 0.95):
			#Adjust sell price
			newPrice = self.sellPrice * adjustmentRatio
			self.sellPrice = ((1-priceAlpha)*self.sellPrice) + (priceAlpha*newPrice)

		#Adjust price based on minimum expenses
		# targetRevenue = self.targetProductionRate*self.sellPrice
		# if (targetRevenue < avgExpenses):
		# 	self.logger.debug("Adjusted price {} too low to cover costs. Resetting target revenue".format(self.sellPrice))
		# 	self.sellPrice = (avgExpenses/self.targetProductionRate)*1.1

		self.logger.info("New sale price = {}".format(self.sellPrice))


	def liquidateItem(self, itemContainer):
		self.agent.consumeItem(itemContainer)


	def acquireDeficits(self, deficits):
		#Allocate more land if we don't have enough
		landDeficit = deficits["LandDeficit"] - self.agent.landHoldings["ALLOCATING"]
		if (landDeficit > 0):
			self.agent.allocateLand(self.sellItemId, landDeficit)

		#Spawn fixed item inputs
		for itemId in deficits["FixedItemDeficit"]:
			self.agent.receiveItem(deficits["FixedItemDeficit"][itemId])

		#Adjust labor requirements
		for skillLevel in deficits["LaborDeficit"]:
			self.requiredLabor = deficits["LaborDeficit"][skillLevel]

		#Spawn variable item inputs
		for itemId in deficits["VariableItemDeficit"]:
			self.agent.receiveItem(deficits["VariableItemDeficit"][itemId])


	def removeSurplus(self, surplusInputs):
		#Deallocate land if we have too much
		landSurplus = surplusInputs["LandSurplus"]
		if (landSurplus > 0):
			self.agent.deallocateLand(self.sellItemId, landSurplus)

		#Liquidate fixed item inputs
		for itemId in surplusInputs["FixedItemSurplus"]:
			self.liquidateItem(surplusInputs["FixedItemSurplus"][itemId])

		#Adjust labor requirements
		for skillLevel in surplusInputs["LaborSurplus"]:
			self.requiredLabor = -1*surplusInputs["LaborSurplus"][skillLevel]

		#Liquidate variable item inputs
		for itemId in surplusInputs["VariableItemSurplus"]:
			self.liquidateItem(surplusInputs["VariableItemSurplus"][itemId])


	def adjustNextWage(self):
		medianAlpha = 0.2
		adjustmentAlpha = 0.1
		#Adjust wage  based on market rate
		medianWage = self.workerWage
		sampledListings = self.agent.sampleLaborListings(sampleSize=30)
		sampledWages = SortedList()
		if (len(sampledListings) > 0):
			for listing in sampledListings:
				sampledWages.add(listing.wagePerTick)
			medianWage = sampledWages[int(len(sampledListings)/2)]
		self.workerWage = ((1-medianAlpha)*self.workerWage)+(medianAlpha*medianWage)

		#Adjust wage based on worker deficit and application number
		divisor = 1
		if (self.workerDeficit < 0):
			divisor = pow(abs(self.workerDeficit)*1.2, 0.8)
		if (self.workerDeficit > 0) and (self.openSteps > 2):
			divisor = 1/pow((self.workerDeficit), 0.2)
		if (self.workerDeficit > 0):
			if (abs(self.applications/self.workerDeficit)>1.5):
				divisor = pow(abs(self.applications/self.workerDeficit), 0.9)

		dividend = 1.0
		if (self.openSteps > 3):
			dividend = (pow(self.openSteps, 0.2))

		#Adjust the wage for next time
		adjustmentRatio = dividend/divisor
		self.workerWage = ((1-adjustmentAlpha)*self.workerWage)+(adjustmentAlpha*adjustmentRatio*self.workerWage)

		#Print stats
		self.logger.debug("HR Stats: requiredLabor={}, workerDeficit={}, applications={}, openSteps={}, adjustmentRatio={}, workerWage={}".format(self.requiredLabor, self.workerDeficit, self.applications, self.openSteps, adjustmentRatio, self.workerWage))


	def evalJobApplication(self, laborContract):
		self.logger.debug("Recieved job application {}".format(laborContract))
		if (self.openSteps > 0):
			self.applications = 0
		self.openSteps = 0

		self.applications += 1

		#Hire them if we need the labor
		if (self.requiredLabor > 0):
			self.logger.info("Accepting job application {}".format(laborContract))
			#Spawn money needed for this contract
			totalWages = int((laborContract.wagePerTick * laborContract.ticksPerStep * laborContract.contractLength + 100)*10)
			self.agent.receiveCurrency(totalWages)

			#Decrease required labor
			self.requiredLabor -= laborContract.ticksPerStep
			if (self.requiredLabor < 0):
				self.requiredLabor = 0

			self.logger.debug("Accepted job application {}".format(laborContract))
			return True
		else:
			#We don't need more labor. Reject this application
			self.logger.debug("Rejected job application {}".format(laborContract))
			return False


	def manageLabor(self):
		#Update worker deficit
		if (self.requiredLabor > 0):
			self.workerDeficit = math.ceil(self.requiredLabor/self.maxTicksPerStep)
		elif (self.requiredLabor < 0):
			self.workerDeficit = math.floor(self.requiredLabor/self.maxTicksPerStep)

		#Adjust wages
		self.adjustNextWage()

		#Update job listing
		if (self.requiredLabor > 0):
			self.laborListing = LaborListing(employerId=self.agentId, ticksPerStep=self.maxTicksPerStep, wagePerTick=self.workerWage, minSkillLevel=self.laborSkillLevel, contractLength=self.contractLength, listingName="Employer_{}".format(self.agentId))
			self.logger.info("Updating job listing | {}".format(self.laborListing))
			listingUpdated = self.agent.updateLaborListing(self.laborListing)
			if (self.listingActive):
				self.openSteps += 1
			self.listingActive = True
		else:
			#Remove listing
			self.agent.removeLaborListing(self.laborListing)
			self.listingActive = False
			self.applications = 0
			self.openSteps = 0

	def produce(self):
		#See if we have any deficits for the new production rate
		inputDeficits = self.agent.getProductionInputDeficit(self.sellItemId, self.targetProductionRate)
		self.logger.debug("Input deficits = {}".format(inputDeficits))
		self.acquireDeficits(inputDeficits)

		#Get rid of surplus inputs
		surplusInputs = self.agent.getProductionInputSurplus(self.sellItemId, self.targetProductionRate)
		self.logger.debug("Input surplus = {}".format(surplusInputs))
		self.removeSurplus(surplusInputs)

		#Produce items
		maxProductionPossible = self.agent.getMaxProduction(self.sellItemId)

		productionAmount = self.targetProductionRate
		if (productionAmount > maxProductionPossible):
			productionAmount = maxProductionPossible

		producedItems = self.agent.produceItem(ItemContainer(self.sellItemId, productionAmount))
		self.logger.debug("Produced {}".format(producedItems))

		#Update production average
		alpha = 0.4
		self.currentProductionRateAvg = ((1-alpha)*self.currentProductionRateAvg) + (alpha*productionAmount)

	def updateItemListing(self):
		self.itemListing = ItemListing(sellerId=self.agentId, itemId=self.sellItemId, unitPrice=self.sellPrice, maxQuantity=self.currentProductionRateAvg/3)
		self.logger.info("Updating item listing | {}".format(self.itemListing))
		listingUpdated = self.agent.updateItemListing(self.itemListing)


	def evalTradeRequest(self, request):
		productInventory = 0
		if (request.itemPackage.id in self.agent.inventory):
			productInventory = self.agent.inventory[request.itemPackage.id].quantity

		tradeAccepted = productInventory>request.itemPackage.quantity
		if (tradeAccepted):
			self.stepSales += request.itemPackage.quantity

		return tradeAccepted


	def receiveMsg(self, incommingPacket):
		self.logger.info("INBOUND {}".format(incommingPacket))

		if (incommingPacket.msgType == "TICK_GRANT") or (incommingPacket.msgType == "TICK_GRANT_BROADCAST"):
			if (self.agent.stepNum == self.startStep):
				self.logger.info("StepNum = {}, Starting controller functionality".format(self.agent.stepNum))

			if (self.agent.stepNum >= self.startStep):
				#Update sales average
				alpha = 0.2
				self.currentSalesAvg = ((1-alpha)*self.currentSalesAvg) + (alpha*self.stepSales)
				self.stepSales = 0

				#Print business stats
				self.logger.info("Current sales average = {}".format(self.currentSalesAvg))
				avgRevenue = self.agent.getAvgCurrencyInflow()
				avgExpenses = self.agent.getAvgCurrencyOutflow()
				self.logger.info("Avg Daily Expenses={}, Avg Daily Revenue={}, Avg Daily Profit={}".format(avgExpenses, avgRevenue, avgRevenue-avgExpenses))

				if ((self.agent.stepNum-self.updateOffset)%self.updateRate == 0):
					try:
						#Adjust production
						self.adjustProduction()

						#Manage worker hiring
						self.manageLabor()

						#Produce items
						self.produce()

						#Update item listing
						self.updateItemListing()
					except:
						self.logger.critical("UNHANDLED ERROR DURING STEP")
						self.logger.critical(traceback.format_exc())
						self.logger.debug(self.getInfoDumpString())
				else:
					try:
						#Produce items
						self.produce()
					except:
						self.logger.critical("UNHANDLED ERROR DURING STEP")
						self.logger.critical(traceback.format_exc())
						self.logger.debug(self.getInfoDumpString())

			#Relinquish time ticks
			self.logger.info("Relinquishing time ticks")
			ticksRelinquished = self.agent.relinquishTimeTicks()
			self.logger.info("Ticks relinquished. Waiting for tick grant")

		if ((incommingPacket.msgType == "CONTROLLER_MSG") or (incommingPacket.msgType == "CONTROLLER_MSG_BROADCAST")):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == "STOP_TRADING"):
				self.killThreads = True


	def getInfoDumpString(self):
		infoString = "CONTROLLER_INFO_DUMP: "
		infoString += "\ntargetProductionRate={}".format(self.targetProductionRate)
		infoString += "\ncurrentProductionRateAvg={}".format(self.currentProductionRateAvg)
		infoString += "\nsellPrice={}".format(self.sellPrice)
		infoString += "\ncurrentSalesAvg={}".format(self.currentSalesAvg)
		infoString += "\nstepSales={}".format(self.stepSales)
		infoString += "\nrequiredLabor={}".format(self.requiredLabor)
		infoString += "\nworkerWage={}".format(self.workerWage)
		infoString += "\napplications={}".format(self.applications)
		infoString += "\nopenSteps={}".format(self.openSteps)
		infoString += "\nworkerDeficit={}".format(self.workerDeficit)
		infoString += "\nlistingActive={}".format(self.listingActive)

		return infoString
		
