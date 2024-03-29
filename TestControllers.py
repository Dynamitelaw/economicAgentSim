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
import queue
import numpy as np
from sklearn.linear_model import LinearRegression

import utils
from TradeClasses import *
from NetworkClasses import *


class PushoverController:
	'''
	This controller will accept all valid trade requests, and will not take any other action. Used for testing.
	'''
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO", outputDir="OUTPUT"):
		self.agent = agent
		self.agentId = agent.agentId
		self.name = "{}_PushoverController".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join(outputDir, "LOGS", "Controller_Logs"), fileLevel=fileLevel)

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
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO", outputDir="OUTPUT"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestSeller".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join(outputDir, "LOGS", "Controller_Logs"), fileLevel=fileLevel)

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
		self.agent.subcribeTickBlocking()


	def receiveMsg(self, incommingPacket):
		self.logger.info("INBOUND {}".format(incommingPacket))
		if ((incommingPacket.msgType == PACKET_TYPE.TICK_GRANT) or (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT_BROADCAST)):
			#Launch production function
			self.produceItems()

		if ((incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG) or (incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG_BROADCAST)):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == PACKET_TYPE.STOP_TRADING):
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
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO", outputDir="OUTPUT"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestBuyer".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join(outputDir, "LOGS", "Controller_Logs"), fileLevel=fileLevel)

		#Keep track of agent assets
		self.currencyBalance = agent.currencyBalance  #(int) cents  #This prevents accounting errors due to float arithmetic (plus it's faster)
		self.inventory = agent.inventory

		#Agent preferences
		self.utilityFunctions = agent.utilityFunctions

		#Initiate thread kill flag to false
		self.killThreads = False


	def controllerStart(self, incommingPacket):
		#Subscribe for tick blocking
		self.agent.subcribeTickBlocking()

	def receiveMsg(self, incommingPacket):
		self.logger.info("INBOUND {}".format(incommingPacket))

		if (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT) or (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT_BROADCAST):
			#Launch buying loop
			self.shoppingSpree()

		if ((incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG) or (incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG_BROADCAST)):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == PACKET_TYPE.STOP_TRADING):
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
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO", outputDir="OUTPUT"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestEmployer".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join(outputDir, "LOGS", "Controller_Logs"), fileLevel=fileLevel)

		#Initiate thread kill flag to false
		self.killThreads = False

		#Keep track of job listings we've posted
		self.openJobListings = {}


	def controllerStart(self, incommingPacket):
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

		if (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT) or (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT_BROADCAST):
			pass

		if ((incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG) or (incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG_BROADCAST)):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == PACKET_TYPE.STOP_TRADING):
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
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO", outputDir="OUTPUT"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestWorker".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join(outputDir, "LOGS", "Controller_Logs"), fileLevel=fileLevel)

		#Initiate thread kill flag to false
		self.killThreads = False
		self.searchStart = False


	def controllerStart(self, incommingPacket):
		#Subscribe for tick blocking
		self.agent.subcribeTickBlocking()


	def receiveMsg(self, incommingPacket):
		self.logger.info("INBOUND {}".format(incommingPacket))

		if (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT) or (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT_BROADCAST):
			self.searchJobs()

		if ((incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG) or (incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG_BROADCAST)):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == PACKET_TYPE.STOP_TRADING):
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
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO", outputDir="OUTPUT"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestLandSeller".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join(outputDir, "LOGS", "Controller_Logs"), fileLevel=fileLevel)

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
		if ((incommingPacket.msgType == PACKET_TYPE.TICK_GRANT) or (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT_BROADCAST)):
			pass

		if ((incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG) or (incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG_BROADCAST)):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == PACKET_TYPE.STOP_TRADING):
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
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO", outputDir="OUTPUT"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestLandBuyer".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join(outputDir, "LOGS", "Controller_Logs"), fileLevel=fileLevel)

		self.landTypes = ["UNALLOCATED", "apple", "potato"]

		#Initiate thread kill flag to false
		self.killThreads = False


	def controllerStart(self, incommingPacket):
		#Subscribe for tick blocking
		self.agent.subcribeTickBlocking()
		self.agent.receiveCurrency(10000)

	def receiveMsg(self, incommingPacket):
		self.logger.info("INBOUND {}".format(incommingPacket))

		if (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT) or (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT_BROADCAST):
			#Launch buying loop
			self.shoppingSpree()

		if ((incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG) or (incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG_BROADCAST)):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == PACKET_TYPE.STOP_TRADING):
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
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO", outputDir="OUTPUT"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestEater".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join(outputDir, "LOGS", "Controller_Logs"), fileLevel=fileLevel)

		#Keep track of agent assets
		self.currencyBalance = agent.currencyBalance  #(int) cents  #This prevents accounting errors due to float arithmetic (plus it's faster)
		self.inventory = agent.inventory

		#Agent preferences
		self.utilityFunctions = agent.utilityFunctions

		#Initiate thread kill flag to false
		self.killThreads = False


	def controllerStart(self, incommingPacket):
		#Subscribe for tick blocking
		self.agent.subcribeTickBlocking()

		#Enable nutritional tracking
		self.agent.enableHunger()

	def receiveMsg(self, incommingPacket):
		self.logger.info("INBOUND {}".format(incommingPacket))

		if (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT) or (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT_BROADCAST):
			#Print a shit ton of money
			self.agent.receiveCurrency(500000)
			self.agent.relinquishTimeTicks()

		if ((incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG) or (incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG_BROADCAST)):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == PACKET_TYPE.STOP_TRADING):
				self.killThreads = True


class TestSpawner:
	'''
	This controller will spawn and sell a single item. 
	Will spawn items out of thin air at a constant rate.
	Will adjust sell price until quantityProduces ~= quantityPurchased
	Used for testing.
	'''
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO", outputDir="OUTPUT"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestFarmer".format(agent.agentId)
		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join(outputDir, "LOGS", "Controller_Logs"), fileLevel=fileLevel)

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
		if ((incommingPacket.msgType == PACKET_TYPE.TICK_GRANT) or (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT_BROADCAST)):
			#Launch production function
			self.produceItems()
			self.previousSales = 0

		if ((incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG) or (incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG_BROADCAST)):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == PACKET_TYPE.STOP_TRADING):
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
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO", outputDir="OUTPUT"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestEmployer".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join(outputDir, "LOGS", "Controller_Logs"), fileLevel=fileLevel)

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

		if (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT) or (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT_BROADCAST):
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

		if ((incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG) or (incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG_BROADCAST)):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == PACKET_TYPE.STOP_TRADING):
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
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO", outputDir="OUTPUT"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestFarmWorker".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join(outputDir, "LOGS", "Controller_Logs"), fileLevel=fileLevel)

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

		if (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT) or (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT_BROADCAST):
			if (self.agent.stepNum == self.startStep):
				self.logger.info("StepNum = {}, Starting controller functionality".format(self.agent.stepNum))
				self.agent.enableHunger()

			if (self.agent.stepNum >= self.startStep):
				avgLaborIncome = self.agent.getAvgLaborIncome()
				self.logger.info("Avg Labor Income = {}".format(avgLaborIncome))
				self.searchJobs()

			self.agent.relinquishTimeTicks()

		if ((incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG) or (incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG_BROADCAST)):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == PACKET_TYPE.STOP_TRADING):
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
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO", outputDir="OUTPUT"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestFarmCompetetive".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join(outputDir, "LOGS", "Controller_Logs"), fileLevel=fileLevel)

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

		if (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT) or (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT_BROADCAST):
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

		if ((incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG) or (incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG_BROADCAST)):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == PACKET_TYPE.STOP_TRADING):
				self.killThreads = True


class TestFarmWorkerV2:
	'''
	This controller will try to find the highest paying job. Will automatically pruchase and consume food. 
	Used for testing.
	'''
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO", outputDir="OUTPUT"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestFarmWorkerV2".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join(outputDir, "LOGS", "Controller_Logs"), fileLevel=fileLevel)

		#Initiate thread kill flag to false
		self.killThreads = False

		#Wage expectations
		self.expectedWage = 0

		#Handle start skews
		self.startStep = 0
		self.skewRate = 1
		if ("StartSkew" in settings):
			self.skewRate = settings["StartSkew"]+1
			self.startStep = int(random.random()/(1.0/self.skewRate))

		#Spawn starting balance
		self.initialIncome = 400000
		self.agent.receiveCurrency(self.initialIncome)
		self.initialIncomeSkewCntr = 2*self.skewRate


	def controllerStart(self, incommingPacket):
		#Subscribe for tick blocking
		self.agent.subcribeTickBlocking()

		#Enable hunger
		self.agent.enableHunger()

		#Enable accounting
		self.agent.enableLaborIncomeTracking()

	def receiveMsg(self, incommingPacket):
		self.logger.info("INBOUND {}".format(incommingPacket))

		if (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT) or (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT_BROADCAST):
			if (self.agent.stepNum == self.startStep):
				self.logger.info("StepNum = {}, Starting controller functionality".format(self.agent.stepNum))
				self.agent.enableHunger()

			if (self.agent.stepNum >= self.startStep):
				#Get free money early on in simulation to jump start economy
				#self.agent.receiveCurrency(self.initialIncome)
				if (self.initialIncomeSkewCntr > 0):
					self.agent.receiveCurrency(self.initialIncome)
					self.initialIncome = self.initialIncome*0.8
					self.initialIncomeSkewCntr -= 1

				#Look for jobs
				avgLaborIncome = self.agent.getAvgLaborIncome()
				self.logger.info("Avg Labor Income = {}".format(avgLaborIncome))
				self.searchJobs()

			self.agent.relinquishTimeTicks()

		if ((incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG) or (incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG_BROADCAST)):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == PACKET_TYPE.STOP_TRADING):
				self.killThreads = True

	def searchJobs(self):
		if (self.agent.laborContractsTotal < 2):
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
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO", outputDir="OUTPUT"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestFarmCompetetiveV2".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join(outputDir, "LOGS", "Controller_Logs"), fileLevel=fileLevel)

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
		self.targetInventoryDays = 3

		#Keep track of sell price
		averageCustomers = 480/9
		self.sellPrice = (self.agent.utilityFunctions[self.sellItemId].getMarginalUtility(self.targetProductionRate/averageCustomers)) * (1+(random.random()-0.5))
		self.currentSalesAvg = self.targetProductionRate 
		self.stepSales = self.currentSalesAvg
		#self.stepSalesLock = threading.Lock()  #TODO

		self.itemListing = ItemListing(sellerId=self.agentId, itemId=self.sellItemId, unitPrice=self.sellPrice, maxQuantity=self.currentProductionRateAvg/3)

		#Keep track of wages and hiring stats
		self.laborLock = threading.Lock()
		self.requiredLabor = 0

		self.laborSkillLevel = 0
		self.maxTicksPerStep = 4
		self.contractLength = int(14*(1+((random.random()-0.5)/2)))

		self.workerWage = 80*(1 + ((random.random()-0.5)/2))
		self.applications = 0
		self.openSteps = 0
		self.workerDeficit = math.ceil(self.requiredLabor/self.maxTicksPerStep)
		self.listingActive = False
		
		self.laborListing = LaborListing(employerId=self.agentId, ticksPerStep=self.maxTicksPerStep, wagePerTick=self.workerWage, minSkillLevel=self.laborSkillLevel, contractLength=self.contractLength, listingName="Employer_{}".format(self.agentId))


	#########################
	# Communication functions
	#########################
	def controllerStart(self, incommingPacket):
		#Subscribe for tick blocking
		self.agent.subcribeTickBlocking()

		#Spawn initial quantity of land
		self.agent.receiveLand("UNALLOCATED", 9999999999)

		#Spawn initial inventory of items
		self.agent.receiveItem(ItemContainer(self.sellItemId, self.targetProductionRate*self.targetInventoryDays))

		#Enable accounting
		self.agent.enableTradeRevenueTracking()
		self.agent.enableCurrencyOutflowTracking()
		self.agent.enableCurrencyInflowTracking()


	def receiveMsg(self, incommingPacket):
		self.logger.info("INBOUND {}".format(incommingPacket))

		if (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT) or (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT_BROADCAST):
			# A new step has started
			if (self.agent.stepNum == self.startStep):
				self.logger.info("StepNum = {}, Starting controller functionality".format(self.agent.stepNum))

			if (self.agent.stepNum >= self.startStep):
				self.logger.info("#### StepNum = {} ####".format(self.agent.stepNum))
				#Update sales average
				alpha = 0.2
				self.currentSalesAvg = ((1-alpha)*self.currentSalesAvg) + (alpha*self.stepSales)
				self.stepSales = 0

				#Print business stats
				self.logger.info("Current sales average = {}".format(self.currentSalesAvg))
				avgRevenue = self.agent.getAvgTradeRevenue()
				avgExpenses = self.agent.getAvgCurrencyOutflow()
				self.logger.debug(self.agent.getAccountingStats())
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
						print("\a")
				else:
					try:
						#Manage worker hiring
						#self.manageLabor()

						#Produce items
						self.produce()
					except:
						self.logger.critical("UNHANDLED ERROR DURING STEP")
						self.logger.critical(traceback.format_exc())
						self.logger.critical(self.getInfoDumpString())
						print("\a")

			#Relinquish time ticks
			self.logger.info("Relinquishing time ticks")
			ticksRelinquished = self.agent.relinquishTimeTicks()
			self.logger.info("Ticks relinquished. Waiting for tick grant")

		if (incommingPacket.msgType == PACKET_TYPE.KILL_PIPE_AGENT) or (incommingPacket.msgType == PACKET_TYPE.KILL_ALL_BROADCAST):
			self.killThreads = True

		if ((incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG) or (incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG_BROADCAST)):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == PACKET_TYPE.STOP_TRADING):
				self.killThreads = True


	def evalTradeRequest(self, request):
		self.logger.debug("evalTradeRequest({}) start".format(request))
		productInventory = 0
		if (request.itemPackage.id in self.agent.inventory):
			productInventory = self.agent.inventory[request.itemPackage.id].quantity

		tradeAccepted = productInventory>request.itemPackage.quantity
		if (tradeAccepted):
			self.stepSales += request.itemPackage.quantity

		self.logger.debug("evalTradeRequest({}) return {}".format(request, tradeAccepted))
		return tradeAccepted

	#########################
	# Production management 
	#########################

	def adjustProductionTarget(self, inventoryRatio, profitMargin):
		self.logger.debug("adjustProductionTarget(inventoryRatio={}, profitMargin={}) start".format(inventoryRatio, profitMargin))
		#Adjust target production based on current profit margin and inventory ratio
		prodAlpha = 0.2

		ratioList = []

		profitAdjustmentRatio = 1
		if (profitMargin > 0.05):
			profitAdjustmentRatio = pow((1+profitMargin), 0.6)
			ratioList.append(profitAdjustmentRatio)
			#productionAdjustmentRatio = profitAdjustmentRatio
			self.logger.debug("adjustProductionTarget() Profit adjustment ratio = {}".format(profitAdjustmentRatio))
			#self.logger.debug("adjustProductionTarget() Production adjustment ratio = {}".format(productionAdjustmentRatio))
			#targetProductionRate = ((1-prodAlpha)*((self.targetProductionRate+self.currentProductionRateAvg)/2)) + (prodAlpha*self.currentProductionRateAvg*productionAdjustmentRatio)

			#return round(targetProductionRate, g_ItemQuantityPercision)
		elif (profitMargin < 0):
			profitAdjustmentRatio = pow((1+profitMargin), 1.6)
			productionAdjustmentRatio = profitAdjustmentRatio
			self.logger.debug("adjustProductionTarget() Profit adjustment ratio = {}".format(profitAdjustmentRatio))
			self.logger.debug("adjustProductionTarget() Production adjustment ratio = {}".format(productionAdjustmentRatio))
			targetProductionRate = ((1-prodAlpha)*((self.targetProductionRate+self.currentProductionRateAvg)/2)) + (prodAlpha*self.currentProductionRateAvg*productionAdjustmentRatio)

			return round(targetProductionRate, g_ItemQuantityPercision)

		inventoryAdjustmentRatio = pow(self.targetInventoryDays*inventoryRatio, 0.7)
		self.logger.debug("adjustProductionTarget() Inventory adjustment ratio = {}".format(inventoryAdjustmentRatio))
		ratioList.append(inventoryAdjustmentRatio)

		#productionAdjustmentRatio = sum(ratioList)/len(ratioList)
		productionAdjustmentRatio = inventoryAdjustmentRatio*profitAdjustmentRatio
		self.logger.debug("adjustProductionTarget() Production adjustment ratio = {}".format(productionAdjustmentRatio))
		targetProductionRate = ((1-prodAlpha)*((self.targetProductionRate+self.currentProductionRateAvg)/2)) + (prodAlpha*self.currentProductionRateAvg*productionAdjustmentRatio)

		return round(targetProductionRate, g_ItemQuantityPercision)


	def adjustSalePrice(self, avgRevenue, avgExpenses, meanPrice, saleRatio):
		self.logger.debug("adjustProductionTarget(avgRevenue={}, avgExpenses={}, meanPrice={}, saleRatio={}) start".format(avgRevenue, avgExpenses, meanPrice, saleRatio))
		ratioList = []

		#Make sure sell price covers our costs
		if (self.targetProductionRate > 0):
			currentUnitCost = self.sellPrice
			if (self.currentProductionRateAvg > 0):
				currentUnitCost = (avgExpenses/self.currentProductionRateAvg) * (self.currentProductionRateAvg/self.targetProductionRate)
				self.logger.debug("adjustSalePrice() currentUnitCost = {}".format(currentUnitCost))

			if (self.sellPrice < currentUnitCost):
				costAdjustmentRatio = pow(currentUnitCost/self.sellPrice, 1)
				self.logger.debug("adjustSalePrice() Current price too low to cover costs. Cost adjustment ratio = {}".format(costAdjustmentRatio))
				#ratioList.append(costAdjustmentRatio)

				priceAlpha = 0.5
				sellPrice = ((1-priceAlpha)*self.sellPrice) + (priceAlpha*self.sellPrice*costAdjustmentRatio)
				if (sellPrice > 1.3*meanPrice):
					sellPrice = 1.3*meanPrice

				return sellPrice

		#Adjust target price based on median price
		marketAdjustmentRatio = pow(meanPrice/self.sellPrice, 0.7)
		self.logger.debug("adjustSalePrice() marketAdjustmentRatio = {}".format(marketAdjustmentRatio))
		ratioList.append(marketAdjustmentRatio)

		#Adjust price based on sale ratios
		if (saleRatio < 1):
			saleAdjustmentRatio = pow(saleRatio, 1.4) 
			self.logger.debug("adjustSalePrice() saleAdjustmentRatio = {}".format(saleAdjustmentRatio))
			ratioList.append(saleAdjustmentRatio)
		elif (saleRatio > 1):
			saleAdjustmentRatio = pow(saleRatio, 0.4) 
			self.logger.debug("adjustSalePrice() saleAdjustmentRatio = {}".format(saleAdjustmentRatio))
			ratioList.append(saleAdjustmentRatio)
		

		#Get final price
		priceAdjustmentRatio = sum(ratioList)/len(ratioList)  #take average adjustment ratio
		self.logger.debug("adjustSalePrice() priceAdjustmentRatio = {}".format(priceAdjustmentRatio))
		priceAlpha = 0.1
		sellPrice = ((1-priceAlpha)*self.sellPrice) + (priceAlpha*self.sellPrice*priceAdjustmentRatio)

		return sellPrice

	def adjustProduction(self):
		########
		# Get current algortithm inputs
		########

		#Get current profit margins
		avgRevenue = self.agent.getAvgTradeRevenue()
		avgExpenses = self.agent.getAvgCurrencyOutflow()
		profitMargin = 0
		if (avgExpenses > 0):
			profitMargin = (avgRevenue-avgExpenses)/avgExpenses
		self.logger.debug("Profit margin = {}".format(profitMargin))

		#Get product inventory
		self.logger.info("Average production rate = {}".format(self.currentProductionRateAvg))
		productInventory = 0
		if (self.sellItemId in self.agent.inventory):
			productInventory = self.agent.inventory[self.sellItemId].quantity
		self.logger.debug("productInventory = {}".format(productInventory))
		inventoryRatio = (self.currentSalesAvg+1) / (productInventory+1)
		self.logger.debug("Inventory ratio = {}".format(inventoryRatio))

		#Get current sales
		self.logger.debug("Sales average = {}".format(self.currentSalesAvg))
		saleRatio = (self.currentSalesAvg+1)/(self.currentProductionRateAvg+1)
		self.logger.debug("Sale ratio = {}".format(saleRatio))

		#Get median market price
		# medianPrice = self.sellPrice
		sampledListings = self.agent.sampleItemListings(ItemContainer(self.sellItemId, 0.01), sampleSize=30)
		# sampledPrices = SortedList()
		# if (len(sampledListings) > 0):
		# 	for listing in sampledListings:
		# 		sampledPrices.add(listing.unitPrice)
		# 	medianPrice = sampledPrices[int(len(sampledListings)/2)]
		# self.logger.info("Median market price = {}".format(medianPrice))

		#Get volume-adjusted mean market price
		meanPrice = self.sellPrice
		totalQuantity = 0
		totalPrice = 0
		if (len(sampledListings) > 0):
			for listing in sampledListings:
				totalPrice += listing.unitPrice*listing.maxQuantity
				totalQuantity += listing.maxQuantity
			if (totalQuantity > 0):
				meanPrice = totalPrice/totalQuantity
		self.logger.info("volume-adjusted average market price = {}".format(meanPrice))
		

		########
		# Get new production values
		########

		#Adjust target production rate
		self.logger.info("Old target production rate = {}".format(self.targetProductionRate))
		self.targetProductionRate = self.adjustProductionTarget(inventoryRatio, profitMargin)
		self.logger.info("New target production rate = {}".format(self.targetProductionRate))

		#Adjust sale price 
		self.logger.info("Old sale price = {}".format(self.sellPrice))
		self.sellPrice = self.adjustSalePrice(avgRevenue, avgExpenses, meanPrice, saleRatio)
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
		self.laborLock.acquire()
		for skillLevel in deficits["LaborDeficit"]:
			self.requiredLabor = deficits["LaborDeficit"][skillLevel]
			self.workerDeficit = round(self.requiredLabor/self.maxTicksPerStep, 0)
		self.laborLock.release()

		#Spawn variable item inputs
		for itemId in deficits["VariableItemDeficit"]:
			self.agent.receiveItem(deficits["VariableItemDeficit"][itemId])
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
		self.laborLock.acquire()
		for skillLevel in surplusInputs["LaborSurplus"]:
			self.requiredLabor = -1*surplusInputs["LaborSurplus"][skillLevel]
			self.workerDeficit = round(self.requiredLabor/self.maxTicksPerStep, 0)
		self.laborLock.release()

		#Liquidate variable item inputs
		for itemId in surplusInputs["VariableItemSurplus"]:
			self.liquidateItem(surplusInputs["VariableItemSurplus"][itemId])


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

		# productionAmount = self.targetProductionRate
		# if (productionAmount > maxProductionPossible):
		# 	productionAmount = maxProductionPossible
		productionAmount = maxProductionPossible
		self.logger.debug("targetProductionRate={}, productionAmount={}".format(self.targetProductionRate, productionAmount))

		producedItems = self.agent.produceItem(ItemContainer(self.sellItemId, productionAmount))
		self.logger.debug("Produced {}".format(producedItems))

		#Update production average
		alpha = self.agent.accountingAlpha
		self.currentProductionRateAvg = ((1-alpha)*self.currentProductionRateAvg) + (alpha*productionAmount)


	def updateItemListing(self):
		self.itemListing = ItemListing(sellerId=self.agentId, itemId=self.sellItemId, unitPrice=self.sellPrice, maxQuantity=self.currentProductionRateAvg/3)
		self.logger.info("Updating item listing | {}".format(self.itemListing))
		listingUpdated = self.agent.updateItemListing(self.itemListing)

	#########################
	# Labor management
	#########################
	def evalJobApplication(self, laborContract):
		self.logger.debug("Recieved job application {}".format(laborContract))
		if (self.openSteps > 0):
			self.applications = 0
		self.openSteps = 0

		self.applications += 1

		#Hire them if we need the labor
		acquired_laborLock = self.laborLock.acquire(timeout=5)
		if (acquired_laborLock):
			if (self.requiredLabor > 0):
				self.logger.info("Accepting job application {}".format(laborContract))

				#Decrease required labor
				self.requiredLabor -= laborContract.ticksPerStep
				self.laborLock.release()

				#Spawn money needed for this contract
				totalWages = int((laborContract.wagePerTick * laborContract.ticksPerStep * laborContract.contractLength + 100)*10)
				self.agent.receiveCurrency(totalWages)

				self.logger.debug("Accepted job application {}".format(laborContract))
				return True
			else:
				self.laborLock.release()
				#We don't need more labor. Reject this application
				self.logger.debug("Rejected job application {}".format(laborContract))
				return False
		else:
			self.logger.error("evalJobApplication({}) laborLock acquisition timeout".format(laborContract))
			return False


	def adjustWorkerWage(self):
		ratioList = []
		
		#Adjust wage  based on market rate
		medianWage = self.workerWage
		sampledListings = self.agent.sampleLaborListings(sampleSize=30)
		sampledWages = SortedList()
		if (len(sampledListings) > 0):
			for listing in sampledListings:
				sampledWages.add(listing.wagePerTick)
			medianWage = sampledWages[int(len(sampledListings)/2)]
		medianRatio = medianWage/self.workerWage
		ratioList.append(medianRatio)

		#Adjust wage based on worker deficit and application number
		divisor = 1
		if (self.workerDeficit < 0):
			divisor = pow(abs(self.workerDeficit)*1.2, 1.1)
		if (self.workerDeficit > 0) and (self.openSteps > 2):
			divisor = 1/pow((self.workerDeficit), 0.15)
		if (self.workerDeficit > 0):
			if (abs(self.applications/self.workerDeficit)>1.5):
				divisor = pow(abs(self.applications/self.workerDeficit), 1.5)

		dividend = 1.0
		if (self.openSteps > 3):
			dividend = (pow(self.openSteps, 0.2))

		deficitRatio = pow(dividend/divisor, 1.2)
		ratioList.append(deficitRatio)

		#Adjust the wage for next time
		adjustmentAlpha = 0.1
		adjustmentRatio = sum(ratioList)/len(ratioList)
		newWage = ((1-adjustmentAlpha)*self.workerWage)+(adjustmentAlpha*adjustmentRatio*self.workerWage)

		return newWage


	def manageLabor(self):
		#Lay off employees if required
		if (self.workerDeficit < 0):
			laborContracts = self.agent.getAllLaborContracts()
			wageDict = {}
			for contract in laborContracts:
				wagePerTick = contract.wagePerTick
				if not (contract.wagePerTick in wageDict):
					wageDict[wagePerTick] = []
				wageDict[wagePerTick].append(contract)
	
			sortedWageList = list(wageDict.keys())
			sortedWageList.sort()

			for wage in sortedWageList:
				if (self.workerDeficit >= 0):
					break
				for contract in wageDict[wage]:
					self.agent.cancelLaborContract(contract)
					self.workerDeficit += 1

					if (self.workerDeficit >= 0):
						break

		#Adjust wages
		self.logger.debug("Old wage = {}".format(self.workerWage))
		self.workerWage = self.adjustWorkerWage()
		self.logger.debug("New wage = {}".format(self.workerWage))

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
			if (self.listingActive):
				self.agent.removeLaborListing(self.laborListing)
				self.listingActive = False
				self.applications = 0
				self.openSteps = 0

		#Print stats
		self.logger.debug("HR Stats: employees={}, requiredLabor={}, workerDeficit={}, applications={}, openSteps={}, workerWage={}".format(self.agent.laborContractsTotal, self.requiredLabor, self.workerDeficit, self.applications, self.openSteps, self.workerWage))


	#########################
	# Misc functions
	#########################
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


class TestFarmCompetetiveV3:
	'''
	This controller will hire workers and buy input costs to produce a single item.
	Will sell that item on the marketplace, and adjust the price to maxmimize profit.
	Used for testing.
	'''
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO", outputDir="OUTPUT"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_TestFarmCompetetiveV3".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join(outputDir, "LOGS", "Controller_Logs"), fileLevel=fileLevel)

		#Initiate thread kill flag to false
		self.killThreads = False

		#Handle start skews
		self.startStep = 0
		if ("StartSkew" in settings):
			skewRate = settings["StartSkew"]+1
			self.startStep = int(random.random()/(1.0/skewRate))
		self.updateRate = 3
		self.updateOffset = self.startStep

		#Determine what to produce
		itemList = self.agent.utilityFunctions.keys()
		self.sellItemId = random.sample(itemList, 1)[0]
		if ("itemId" in settings):
			self.sellItemId = settings["itemId"]
			self.logger.info("Sell item specified. Will sell \"{}\"".format(self.sellItemId))
		else:
			self.logger.info("No item specified. Randomly selected \"{}\"".format(self.sellItemId))


		#Keep track of price elasticity
		elasticitySampleSize = 80
		self.elastDatapoints = queue.Queue(elasticitySampleSize)
		self.linearModel = LinearRegression()
		self.demandElasticity = None

		#Keep track of production targets
		self.targetProductionRate = 10
		if ("startingProductionRate" in settings):
			self.targetProductionRate = settings["startingProductionRate"]
			self.logger.info("Initial production rate specified. Will initialize target production to {} {} per step".format(self.targetProductionRate, self.sellItemId))
		else:
			self.logger.info("No initial production rate specified. Will initialize target production to {} {} per step".format(self.targetProductionRate, self.sellItemId))
		self.currentProductionRateAvg = self.targetProductionRate
		self.targetInventoryDays = 3

		#Keep track of sell price
		averageCustomers = 480/9
		self.sellPrice = (self.agent.utilityFunctions[self.sellItemId].getMarginalUtility(self.targetProductionRate/averageCustomers)) * (1+(random.random()-0.5))
		self.currentSalesAvg = self.targetProductionRate 
		self.stepSales = self.currentSalesAvg
		self.averageUnitCost = None
		#self.stepSalesLock = threading.Lock()  #TODO

		self.itemListing = ItemListing(sellerId=self.agentId, itemId=self.sellItemId, unitPrice=self.sellPrice, maxQuantity=self.currentProductionRateAvg/3)

		#Keep track of wages and hiring stats
		self.laborLock = threading.Lock()
		self.requiredLabor = 0

		self.laborSkillLevel = 0
		self.maxTicksPerStep = 4
		self.contractLength = int(14*(1+((random.random()-0.5)/2)))

		self.workerWage = 80*(1 + ((random.random()-0.5)/2))
		self.applications = 0
		self.openSteps = 0
		self.workerDeficit = math.ceil(self.requiredLabor/self.maxTicksPerStep)
		self.listingActive = False
		
		self.laborListing = LaborListing(employerId=self.agentId, ticksPerStep=self.maxTicksPerStep, wagePerTick=self.workerWage, minSkillLevel=self.laborSkillLevel, contractLength=self.contractLength, listingName="Employer_{}".format(self.agentId))

		#Keep track of business closing
		self.closingBusiness = False
		self.closingStep = 0
		self.liquidationListings = {}

	#########################
	# Communication functions
	#########################
	def controllerStart(self, incommingPacket):
		#Subscribe for tick blocking
		self.agent.subcribeTickBlocking()

		#Spawn initial quantity of land
		self.agent.receiveLand("UNALLOCATED", 9999999999)

		#Spawn starting capital
		self.agent.receiveCurrency(600000)
		#self.agent.receiveCurrency(9999999999999)

		#Spawn initial inventory of items
		self.agent.receiveItem(ItemContainer(self.sellItemId, self.targetProductionRate*self.targetInventoryDays))

		#Enable accounting
		self.agent.enableTradeRevenueTracking()
		self.agent.enableCurrencyOutflowTracking()
		self.agent.enableCurrencyInflowTracking()


	def receiveMsg(self, incommingPacket):
		self.logger.info("INBOUND {}".format(incommingPacket))

		if (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT) or (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT_BROADCAST):
			self.runStep()

		if (incommingPacket.msgType == PACKET_TYPE.KILL_PIPE_AGENT) or (incommingPacket.msgType == PACKET_TYPE.KILL_ALL_BROADCAST):
			self.killThreads = True

		if ((incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG) or (incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG_BROADCAST)):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == PACKET_TYPE.STOP_TRADING):
				self.killThreads = True


	def evalTradeRequest(self, request):
		self.logger.debug("evalTradeRequest({}) start".format(request))
		productInventory = 0
		if (request.itemPackage.id in self.agent.inventory):
			productInventory = self.agent.inventory[request.itemPackage.id].quantity

		tradeAccepted = productInventory>request.itemPackage.quantity
		if (tradeAccepted):
			self.stepSales += request.itemPackage.quantity

		if (self.closingBusiness):
			liquidationListing = self.liquidationListings[request.itemPackage.id]
			liquidationListing.updateMaxQuantity((productInventory-request.itemPackage.quantity)*0.93)
			listingUpdated = self.agent.updateItemListing(liquidationListing)

		self.logger.debug("evalTradeRequest({}) return {}".format(request, tradeAccepted))
		return tradeAccepted

	#########################
	# Production management 
	#########################

	def runStep(self):
		if (self.closingBusiness):
			self.logger.info("#### StepNum = {} ####".format(self.agent.stepNum))

			#This business is currently under liquidation
			#Check if liquidation is complete. If so, commit suicide
			allItemsLiquidated = True
			for itemId in self.agent.inventory:
				itemContainer = self.agent.inventory[itemId]
				self.logger.debug("Remainging inventory: {}".format(itemContainer))
				if (itemContainer.quantity <= 0.01):
					self.agent.consumeItem(itemContainer)
					self.agent.removeItemListing(ItemListing(sellerId=self.agentId, itemId=itemId, unitPrice=0, maxQuantity=0))
				else:
					if ((self.agent.stepNum-self.updateOffset)%self.updateRate == 0):
						self.liquidateItem(itemContainer)
					allItemsLiquidated = False

			if (allItemsLiquidated):
				self.logger.warning("Completed business liquidation. Commiting suicide")
				self.agent.commitSuicide()
				self.killThreads = True

		# A new step has started
		if (self.agent.stepNum == self.startStep):
			self.logger.info("StepNum = {}, Starting controller functionality".format(self.agent.stepNum))

		if ((self.agent.stepNum >= self.startStep) and (not self.closingBusiness)):
			self.logger.info("#### StepNum = {} ####".format(self.agent.stepNum))
			#Determine if we should go out of business
			currentCash = self.agent.getCurrencyBalance()
			avgExpenses = self.agent.getAvgCurrencyOutflow()
			stepExpenses = self.agent.getStepCurrencyOutflow()
			if ((currentCash < (avgExpenses*1.5)) or (currentCash < (stepExpenses*1.5))):
				#We're broke. Go out of business
				self.closeBusiness()
				
			if (not self.closingBusiness):
				#Update sales average
				alpha = 0.2
				self.currentSalesAvg = ((1-alpha)*self.currentSalesAvg) + (alpha*self.stepSales)
				self.stepSales = 0

				#Print business stats
				self.logger.info("Current sales average = {}".format(self.currentSalesAvg))
				avgRevenue = self.agent.getAvgTradeRevenue()
				avgExpenses = self.agent.getAvgCurrencyOutflow()
				self.logger.debug(self.agent.getAccountingStats())
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
						print("\a")
				else:
					try:
						#Produce items
						self.produce()
					except:
						self.logger.critical("UNHANDLED ERROR DURING STEP")
						self.logger.critical(traceback.format_exc())
						self.logger.critical(self.getInfoDumpString())
						print("\a")

		#Relinquish time ticks
		self.logger.info("Relinquishing time ticks")
		ticksRelinquished = self.agent.relinquishTimeTicks()
		self.logger.info("Ticks relinquished. Waiting for tick grant")


	def adjustProductionTarget(self, inventoryRatio, profitMargin):
		self.logger.debug("adjustProductionTarget(inventoryRatio={}, profitMargin={}) start".format(inventoryRatio, profitMargin))
		#Adjust target production based on current profit margin and inventory ratio
		prodAlpha = 0.07

		ratioList = []

		profitAdjustmentRatio = 1
		if (profitMargin > 0.05):
			profitAdjustmentRatio = pow((1+profitMargin), 0.6)
			ratioList.append(profitAdjustmentRatio)
			self.logger.debug("adjustProductionTarget() Profit adjustment ratio = {}".format(profitAdjustmentRatio))

		elif (profitMargin < 0):
			profitAdjustmentRatio = pow((1+profitMargin), 1.6)
			productionAdjustmentRatio = profitAdjustmentRatio
			self.logger.debug("adjustProductionTarget() Profit adjustment ratio = {}".format(profitAdjustmentRatio))
			self.logger.debug("adjustProductionTarget() Production adjustment ratio = {}".format(productionAdjustmentRatio))
			targetProductionRate = ((1-prodAlpha)*((self.targetProductionRate+self.currentProductionRateAvg)/2)) + (prodAlpha*self.currentProductionRateAvg*productionAdjustmentRatio)

			return round(targetProductionRate, g_ItemQuantityPercision)

		inventoryAdjustmentRatio = pow(self.targetInventoryDays*inventoryRatio, 0.7)
		self.logger.debug("adjustProductionTarget() Inventory adjustment ratio = {}".format(inventoryAdjustmentRatio))
		ratioList.append(inventoryAdjustmentRatio)

		#productionAdjustmentRatio = sum(ratioList)/len(ratioList)
		productionAdjustmentRatio = inventoryAdjustmentRatio*profitAdjustmentRatio
		self.logger.debug("adjustProductionTarget() Production adjustment ratio = {}".format(productionAdjustmentRatio))
		targetProductionRate = ((1-prodAlpha)*((self.targetProductionRate+self.currentProductionRateAvg)/2)) + (prodAlpha*self.currentProductionRateAvg*productionAdjustmentRatio)

		return round(targetProductionRate, g_ItemQuantityPercision)


	def adjustSalePrice(self, avgRevenue, avgExpenses, meanPrice, saleRatio):
		self.logger.debug("adjustProductionTarget(avgRevenue={}, avgExpenses={}, meanPrice={}, saleRatio={}) start".format(avgRevenue, avgExpenses, meanPrice, saleRatio))
		ratioList = []

		#Make sure sell price covers our costs
		if (self.targetProductionRate > 0):
			if ((self.currentProductionRateAvg > 0) and (avgExpenses > 0)): #TODO
			#if (self.currentProductionRateAvg > 0):
				currentUnitCost = (avgExpenses/self.currentProductionRateAvg) * (self.currentProductionRateAvg/self.targetProductionRate)
				self.logger.debug("adjustSalePrice() currentUnitCost = {}".format(currentUnitCost))

				unitCostAlpha = 0.15
				if (self.averageUnitCost):
					self.averageUnitCost = ((1-unitCostAlpha)*self.averageUnitCost) + (unitCostAlpha*currentUnitCost)
				else:
					self.averageUnitCost = currentUnitCost
				self.logger.debug("averageUnitCost = {}".format(self.averageUnitCost))

				#Calculate price that maximizes revenue based on demand elasticity
				'''
				#This shit doesn't work. 
				#TODO: Maybe I need to weigh the elasticity measurement towards more recent data? How do you do that with linear regression?
				if (self.demandElasticity): #TODO
					if (self.demandElasticity < 0):
						#We have a valid demand elasticity. Calculate price that maximizes profits
						idealPrice = (self.averageUnitCost/2) + (self.sellPrice/2) + (self.currentSalesAvg/(2*self.demandElasticity))  #see Docs/misc/IdealPrice_Derivation for derivation
						if (idealPrice > 0) and (idealPrice > self.averageUnitCost):
							self.logger.debug("Theoretical ideal unit price = {}".format(round(idealPrice, 4)))
							idealRatio = pow(idealPrice/self.sellPrice, 0.7)
							ratioList.append(idealRatio)
				'''				

				#Make sure we are breaking even
				if (self.sellPrice < self.averageUnitCost):
					costAdjustmentRatio = pow(self.averageUnitCost/self.sellPrice, 1)
					self.logger.debug("adjustSalePrice() Current price too low to cover costs. Cost adjustment ratio = {}".format(costAdjustmentRatio))

					priceAlpha = 0.5
					sellPrice = ((1-priceAlpha)*self.sellPrice) + (priceAlpha*self.sellPrice*costAdjustmentRatio)
					if (sellPrice > 1.3*meanPrice):
						sellPrice = 1.3*meanPrice

					try:
						x = int(sellPrice)
					except:
						self.logger.error("Invalid sell price {}".format(sellPrice))
						self.logger.error("adjustProductionTarget(avgRevenue={}, avgExpenses={}, meanPrice={}, saleRatio={}) start".format(avgRevenue, avgExpenses, meanPrice, saleRatio))
						sellPrice = self.sellPrice

					return sellPrice

		#Adjust target price based on median price
		marketAdjustmentRatio = pow(meanPrice/self.sellPrice, 0.7)
		self.logger.debug("adjustSalePrice() marketAdjustmentRatio = {}".format(marketAdjustmentRatio))
		ratioList.append(marketAdjustmentRatio)

		#Adjust price based on sale ratios
		if (saleRatio < 1):
			saleAdjustmentRatio = pow(saleRatio, 1.4) 
			self.logger.debug("adjustSalePrice() saleAdjustmentRatio = {}".format(saleAdjustmentRatio))
			ratioList.append(saleAdjustmentRatio)
		elif (saleRatio > 1):
			saleAdjustmentRatio = pow(saleRatio, 0.4) 
			self.logger.debug("adjustSalePrice() saleAdjustmentRatio = {}".format(saleAdjustmentRatio))
			ratioList.append(saleAdjustmentRatio)
		

		#Get final price
		priceAdjustmentRatio = sum(ratioList)/len(ratioList)  #take average adjustment ratio
		self.logger.debug("adjustSalePrice() priceAdjustmentRatio = {}".format(priceAdjustmentRatio))
		priceAlpha = 0.1
		sellPrice = ((1-priceAlpha)*self.sellPrice) + (priceAlpha*self.sellPrice*priceAdjustmentRatio)

		try:
			x = int(sellPrice)
		except:
			self.logger.error("Invalid sell price {}".format(sellPrice))
			self.logger.error("adjustProductionTarget(avgRevenue={}, avgExpenses={}, meanPrice={}, saleRatio={}) start".format(avgRevenue, avgExpenses, meanPrice, saleRatio))
			sellPrice = self.sellPrice

		return sellPrice

	def adjustProduction(self):
		########
		# Get current algortithm inputs
		########

		#Get current profit margins
		avgRevenue = self.agent.getAvgTradeRevenue()
		avgExpenses = self.agent.getAvgCurrencyOutflow()
		profitMargin = 0
		if (avgExpenses > (avgRevenue/20)):
			profitMargin = (avgRevenue-avgExpenses)/avgExpenses
		elif (avgExpenses > 0):
			profitMargin = 2
		
		self.logger.debug("Profit margin = {}".format(profitMargin))

		#Get product inventory
		self.logger.info("Average production rate = {}".format(self.currentProductionRateAvg))
		productInventory = 0
		if (self.sellItemId in self.agent.inventory):
			productInventory = self.agent.inventory[self.sellItemId].quantity
		self.logger.debug("productInventory = {}".format(productInventory))
		inventoryRatio = (self.currentSalesAvg+1) / (productInventory+1)
		self.logger.debug("Inventory ratio = {}".format(inventoryRatio))

		#Get current sales
		self.logger.debug("Sales average = {}".format(self.currentSalesAvg))
		saleRatio = (self.currentSalesAvg+1)/(self.currentProductionRateAvg+1)
		self.logger.debug("Sale ratio = {}".format(saleRatio))

		#Get volume-adjusted mean market price
		sampledListings = self.agent.sampleItemListings(ItemContainer(self.sellItemId, 0.01), sampleSize=30)
		meanPrice = self.sellPrice
		totalQuantity = 0
		totalPrice = 0
		if (len(sampledListings) > 0):
			for listing in sampledListings:
				totalPrice += listing.unitPrice*listing.maxQuantity
				totalQuantity += listing.maxQuantity
			if ((totalQuantity > 0) and (totalPrice > 0)):
				meanPrice = totalPrice/totalQuantity
		self.logger.info("volume-adjusted average market price = {}".format(meanPrice))

		#Update elasticity datapoints
		if (self.elastDatapoints.full()):
			self.elastDatapoints.get()
		newDataPoint = {"price": self.sellPrice, "avgSales": self.currentSalesAvg}
		self.elastDatapoints.put(newDataPoint)

		#Calculate demand elasticity
		if (self.elastDatapoints.qsize() > 10):
			#Get lists of price datapoints and sales datapoints
			priceList = []
			salesList = []
			for datapoint in list(self.elastDatapoints.queue):
				priceList.append(datapoint["price"])
				salesList.append(datapoint["avgSales"])

			priceAxis = np.array(priceList).reshape((-1, 1))
			salesAxis = np.array(salesList)

			#Use linear regression to find demand elasticity
			self.linearModel.fit(priceAxis, salesAxis)
			calcElastitcity = self.linearModel.coef_[0]
			r_sq = self.linearModel.score(priceAxis, salesAxis)
			if (self.demandElasticity):
				elastAlpha = 0.2*(r_sq)
				self.demandElasticity = ((1-elastAlpha)*self.demandElasticity) + (elastAlpha*calcElastitcity)
			else:
				self.demandElasticity = calcElastitcity

		if (self.demandElasticity):
			self.logger.info("Demand elasticity = {}".format(round(self.demandElasticity, 3)))

		

		########
		# Get new production values
		########

		#Adjust target production rate
		self.logger.info("Old target production rate = {}".format(self.targetProductionRate))
		self.targetProductionRate = self.adjustProductionTarget(inventoryRatio, profitMargin)
		self.logger.info("New target production rate = {}".format(self.targetProductionRate))

		#Adjust sale price 
		self.logger.info("Old sale price = {}".format(self.sellPrice))
		self.sellPrice = self.adjustSalePrice(avgRevenue, avgExpenses, meanPrice, saleRatio)
		self.logger.info("New sale price = {}".format(self.sellPrice))


	def liquidateItem(self, itemContainer):
		#Get volume-adjusted mean market price
		sampledListings = self.agent.sampleItemListings(ItemContainer(self.sellItemId, 0.01), sampleSize=30)
		meanPrice = 100
		if (itemContainer.id in self.liquidationListings):
			meanPrice = self.liquidationListings[itemContainer.id].unitPrice
		totalQuantity = 0
		totalPrice = 0
		if (len(sampledListings) > 0):
			for listing in sampledListings:
				if not (listing.sellerId == self.agentId):
					totalPrice += listing.unitPrice*listing.maxQuantity
					totalQuantity += listing.maxQuantity
			if ((totalQuantity > 0) and (totalPrice > 0)):
				meanPrice = totalPrice/totalQuantity

		#Determine liquidation price
		discountRatio = 0.85 + (0.1/(pow(1+self.agent.stepNum-self.closingStep, 0.2)))
		sellPrice = meanPrice*discountRatio
		self.logger.debug("{} discount ratio = {}".format(itemContainer.id, round(discountRatio, 3)))
		if (sellPrice <= 0):
			sellPrice = 1

		#Post item listing
		liquidationListing = ItemListing(sellerId=self.agentId, itemId=itemContainer.id, unitPrice=sellPrice, maxQuantity=itemContainer.quantity)
		self.liquidationListings[itemContainer.id] = liquidationListing
		listingUpdated = self.agent.updateItemListing(liquidationListing)


	def acquireDeficits(self, deficits):
		#Allocate more land if we don't have enough
		landDeficit = deficits["LandDeficit"] - self.agent.landHoldings["ALLOCATING"]
		if (landDeficit > 0):
			self.agent.allocateLand(self.sellItemId, landDeficit)

		#Spawn fixed item inputs
		for itemId in deficits["FixedItemDeficit"]:
			self.agent.receiveItem(deficits["FixedItemDeficit"][itemId])

		#Adjust labor requirements
		self.laborLock.acquire()
		for skillLevel in deficits["LaborDeficit"]:
			self.requiredLabor = deficits["LaborDeficit"][skillLevel]
			self.workerDeficit = round(self.requiredLabor/self.maxTicksPerStep, 0)
		self.laborLock.release()

		#Spawn variable item inputs
		for itemId in deficits["VariableItemDeficit"]:
			self.agent.receiveItem(deficits["VariableItemDeficit"][itemId])
			self.agent.receiveItem(deficits["VariableItemDeficit"][itemId])


	def removeSurplus(self, surplusInputs):
		#Deallocate land if we have too much
		landSurplus = surplusInputs["LandSurplus"]
		if (landSurplus > 0):
			self.agent.deallocateLand(self.sellItemId, landSurplus)

		#Adjust labor requirements
		self.laborLock.acquire()
		for skillLevel in surplusInputs["LaborSurplus"]:
			self.requiredLabor = -1*surplusInputs["LaborSurplus"][skillLevel]
			self.workerDeficit = round(self.requiredLabor/self.maxTicksPerStep, 0)
		self.laborLock.release()


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
		productionAmount = maxProductionPossible
		self.logger.debug("targetProductionRate={}, productionAmount={}".format(self.targetProductionRate, productionAmount))

		producedItems = self.agent.produceItem(ItemContainer(self.sellItemId, productionAmount))
		self.logger.debug("Produced {}".format(producedItems))

		#Update production average
		alpha = self.agent.accountingAlpha
		self.currentProductionRateAvg = ((1-alpha)*self.currentProductionRateAvg) + (alpha*productionAmount)


	def updateItemListing(self):
		productInventory = 0	
		if (self.sellItemId in self.agent.inventory):	
			productInventory = self.agent.inventory[self.sellItemId].quantity	
		self.itemListing = ItemListing(sellerId=self.agentId, itemId=self.sellItemId, unitPrice=self.sellPrice, maxQuantity=self.currentProductionRateAvg/3)  #productInventory/(2*self.targetInventoryDays))	
		if (self.itemListing.maxQuantity > 0):	
			self.logger.info("Updating item listing | {}".format(self.itemListing))	
			listingUpdated = self.agent.updateItemListing(self.itemListing)	
		else:	
			self.logger.info("Max quantity = 0. Removing item listing | {}".format(self.itemListing))	
			listingUpdated = self.agent.removeItemListing(self.itemListing)


	#########################
	# Labor management
	#########################
	def evalJobApplication(self, laborContract):
		self.logger.debug("Recieved job application {}".format(laborContract))

		if (self.closingBusiness):	
			return False

		if (self.openSteps > 0):
			self.applications = 0
		self.openSteps = 0

		self.applications += 1

		#Hire them if we need the labor
		acquired_laborLock = self.laborLock.acquire(timeout=5)
		if (acquired_laborLock):
			if (self.requiredLabor > 0):
				self.logger.info("Accepting job application {}".format(laborContract))

				#Decrease required labor
				self.requiredLabor -= laborContract.ticksPerStep
				self.laborLock.release()

				self.logger.debug("Accepted job application {}".format(laborContract))
				return True
			else:
				self.laborLock.release()
				#We don't need more labor. Reject this application
				self.logger.debug("Rejected job application {}".format(laborContract))
				return False
		else:
			self.logger.error("evalJobApplication({}) laborLock acquisition timeout".format(laborContract))
			return False


	def adjustWorkerWage(self):
		ratioList = []
		
		#Adjust wage  based on market rate
		medianWage = self.workerWage
		sampledListings = self.agent.sampleLaborListings(sampleSize=30)
		sampledWages = SortedList()
		if (len(sampledListings) > 0):
			for listing in sampledListings:
				sampledWages.add(listing.wagePerTick)
			medianWage = sampledWages[int(len(sampledListings)/2)]
		medianRatio = medianWage/self.workerWage
		ratioList.append(medianRatio)

		#Adjust wage based on worker deficit and application number
		divisor = 1
		if (self.workerDeficit < 0):
			divisor = pow(abs(self.workerDeficit)*1.2, 1.1)
		if (self.workerDeficit > 0) and (self.openSteps > 2):
			divisor = 1/pow((self.workerDeficit), 0.15)
		if (self.workerDeficit > 0):
			if (abs(self.applications/self.workerDeficit)>1.5):
				divisor = pow(abs(self.applications/self.workerDeficit), 1.5)

		dividend = 1.0
		if (self.openSteps > 3):
			dividend = (pow(self.openSteps, 0.2))

		deficitRatio = pow(dividend/divisor, 1.2)
		ratioList.append(deficitRatio)

		#Adjust the wage for next time
		adjustmentAlpha = 0.1
		adjustmentRatio = sum(ratioList)/len(ratioList)
		newWage = ((1-adjustmentAlpha)*self.workerWage)+(adjustmentAlpha*adjustmentRatio*self.workerWage)

		return newWage


	def manageLabor(self):
		#Lay off employees if required
		if (self.workerDeficit < 0):
			laborContracts = self.agent.getAllLaborContracts()
			wageDict = {}
			for contract in laborContracts:
				wagePerTick = contract.wagePerTick
				if not (contract.wagePerTick in wageDict):
					wageDict[wagePerTick] = []
				wageDict[wagePerTick].append(contract)
	
			sortedWageList = list(wageDict.keys())
			sortedWageList.sort()

			for wage in sortedWageList:
				if (self.workerDeficit >= 0):
					break
				for contract in wageDict[wage]:
					self.agent.cancelLaborContract(contract)
					self.workerDeficit += 1

					if (self.workerDeficit >= 0):
						break

		#Adjust wages
		self.logger.debug("Old wage = {}".format(self.workerWage))
		self.workerWage = self.adjustWorkerWage()
		self.logger.debug("New wage = {}".format(self.workerWage))

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
			if (self.listingActive):
				self.agent.removeLaborListing(self.laborListing)
				self.listingActive = False
				self.applications = 0
				self.openSteps = 0

		#Print stats
		self.logger.debug("HR Stats: employees={}, requiredLabor={}, workerDeficit={}, applications={}, openSteps={}, workerWage={}".format(self.agent.laborContractsTotal, self.requiredLabor, self.workerDeficit, self.applications, self.openSteps, self.workerWage))

	#########################
	# Business Suicide functions
	#########################
	def closeBusiness(self):
		self.logger.warning("### Going out of business ###")
		self.closingStep = self.agent.stepNum

		#Sell all inventory
		self.logger.info("Liquidating inventory")
		for itemId in self.agent.inventory:
			self.liquidateItem(self.agent.inventory[itemId])

		self.closingBusiness = True

		#Fire all employees
		self.logger.info("Firing all employees")
		if (self.listingActive):
			self.agent.removeLaborListing(self.laborListing)
		laborContracts = self.agent.getAllLaborContracts()
		for contract in laborContracts:
			self.agent.cancelLaborContract(contract)

		#Post all land for sale
		pass

	#########################
	# Misc functions
	#########################
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


class DoNothingBlocker:
	'''
	This controller will do nothing, and immediately relinquish time ticks upon receipt
	'''
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO", outputDir="OUTPUT"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_DoNothingBlocker".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join(outputDir, "LOGS", "Controller_Logs"), fileLevel=fileLevel)

		#Initiate thread kill flag to false
		self.killThreads = False

	def controllerStart(self, incommingPacket):
		#Subscribe for tick blocking
		self.agent.subcribeTickBlocking()

	def receiveMsg(self, incommingPacket):
		self.logger.info("INBOUND {}".format(incommingPacket))

		if (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT) or (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT_BROADCAST):
			self.agent.relinquishTimeTicks()

		if ((incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG) or (incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG_BROADCAST)):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			if (controllerMsg.msgType == PACKET_TYPE.STOP_TRADING):
				self.killThreads = True


####################
# BasicItemProducer
####################
class TestFarmCompetetiveV4_Checkpoint:
	'''
	Pickle safe object that can be saved to and loaded from a file
	'''
	def __init__(self, controllerObj):
		self.sellItemId = controllerObj.sellItemId
		self.targetProductionRate = controllerObj.targetProductionRate
		self.currentProductionRateAvg = controllerObj.currentProductionRateAvg
		self.targetInventoryDays = controllerObj.targetInventoryDays

		self.elastDatapoints = list(controllerObj.elastDatapoints.queue)
		self.demandElasticity = controllerObj.demandElasticity
		self.elasticityCorrelationCoef = controllerObj.elasticityCorrelationCoef

		self.sellPrice = controllerObj.sellPrice
		self.currentSalesAvg = controllerObj.currentSalesAvg
		self.stepSales = controllerObj.stepSales
		self.averageUnitCost = controllerObj.averageUnitCost
		self.itemListing = controllerObj.itemListing

		self.requiredLabor = controllerObj.requiredLabor
		self.laborSkillLevel = controllerObj.laborSkillLevel
		self.maxTicksPerStep = controllerObj.maxTicksPerStep
		self.contractLength = controllerObj.contractLength
		self.workerWage = controllerObj.workerWage
		self.applications = controllerObj.applications
		self.openSteps = controllerObj.openSteps
		self.workerDeficit = controllerObj.workerDeficit
		self.listingActive = controllerObj.listingActive
		self.laborListing = controllerObj.laborListing

	def loadCheckpoint(self, controllerObj):
		controllerObj.sellItemId = self.sellItemId
		controllerObj.targetProductionRate = self.targetProductionRate
		controllerObj.currentProductionRateAvg = self.currentProductionRateAvg
		controllerObj.targetInventoryDays = self.targetInventoryDays

		for datapoint in self.elastDatapoints:
			controllerObj.elastDatapoints.put(datapoint)
		controllerObj.demandElasticity = self.demandElasticity
		controllerObj.elasticityCorrelationCoef = self.elasticityCorrelationCoef

		controllerObj.sellPrice = self.sellPrice
		controllerObj.currentSalesAvg = self.currentSalesAvg
		controllerObj.stepSales = self.stepSales
		controllerObj.averageUnitCost = self.averageUnitCost
		controllerObj.itemListing = self.itemListing

		controllerObj.requiredLabor = self.requiredLabor
		controllerObj.laborSkillLevel = self.laborSkillLevel
		controllerObj.maxTicksPerStep = self.maxTicksPerStep
		controllerObj.contractLength = self.contractLength
		controllerObj.workerWage = self.workerWage
		controllerObj.applications = self.applications
		controllerObj.openSteps = self.openSteps
		controllerObj.workerDeficit = self.workerDeficit
		controllerObj.listingActive = self.listingActive
		controllerObj.laborListing = self.laborListing


class TestFarmCompetetiveV4:
	'''
	This controller will hire workers and buy input costs to produce a single item type.
	Will sell that item on the marketplace, and adjust the price and production amount to maxmimize profit.

	TODO:
		#Currently, input costs are spawned out of thin air. Make them buy them when the item chain is more fleshed out
		#Currently, this controller spawns with near infinite land. Limit land supply and add buying/selling of land
	'''
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO", outputDir="OUTPUT"):
		self.agent = agent
		self.agentId = agent.agentId
		self.outputDir = outputDir
		self.simManagerId = agent.simManagerId

		self.name = "{}_Controller".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join(outputDir, "LOGS", "Controller_Logs"), fileLevel=fileLevel)

		#Initiate thread kill flag to false
		self.killThreads = False

		######
		# Handle controller settings
		######

		#Handle start skews
		self.startStep = 0
		if ("StartSkew" in settings):
			skewRate = settings["StartSkew"]+1
			self.startStep = int(random.random()/(1.0/skewRate))
		self.updateRate = 3
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
		self.targetInventoryDays = 3

		#Initial cash balance and/or money printer
		self.startingCapital = 600000
		if ("startingCapital" in settings):
			self.startingCapital = int(settings["startingCapital"])

		self.infiniteCapital = False
		if ("infiniteCapital" in settings):
			self.infiniteCapital = bool(settings["infiniteCapital"])

		######
		# Keep track of stats/controller state
		######

		#Keep track of price elasticity
		elasticitySampleSize = 80
		self.elastDatapoints = queue.Queue(elasticitySampleSize)
		self.linearModel = LinearRegression()
		self.demandElasticity = None
		self.elasticityCorrelationCoef = 0

		#Keep track of sell price
		self.sellPrice = (self.agent.utilityFunctions[self.sellItemId].getMarginalUtility(1)) * (1+(random.random()-0.5))
		self.currentSalesAvg = self.targetProductionRate 
		self.stepSales = self.currentSalesAvg
		self.averageUnitCost = None
		self.stepSalesLock = threading.Lock()

		self.itemListing = ItemListing(sellerId=self.agentId, itemId=self.sellItemId, unitPrice=self.sellPrice, maxQuantity=self.currentProductionRateAvg/3)

		#Keep track of wages and hiring stats
		self.laborLock = threading.Lock()
		self.requiredLabor = 0

		self.laborSkillLevel = 0
		self.maxTicksPerStep = 4
		self.contractLength = int(14*(1+((random.random()-0.5)/2)))

		self.workerWage = 80*(1 + ((random.random()-0.5)/2))
		self.applications = 0
		self.openSteps = 0
		self.workerDeficit = math.ceil(self.requiredLabor/self.maxTicksPerStep)
		self.listingActive = False
		
		self.laborListing = LaborListing(employerId=self.agentId, ticksPerStep=self.maxTicksPerStep, wagePerTick=self.workerWage, minSkillLevel=self.laborSkillLevel, contractLength=self.contractLength, listingName="Employer_{}".format(self.agentId))

		#Keep track of business closing
		self.closingBusiness = False
		self.closingStep = 0
		self.liquidationListings = {}

	#########################
	# Communication functions
	#########################
	def controllerStart(self, incommingPacket):
		#Subscribe for tick blocking
		self.agent.subcribeTickBlocking()

		#Spawn initial quantity of land
		self.agent.receiveLand("UNALLOCATED", 9999999999)

		#Spawn starting capital
		self.agent.receiveCurrency(self.startingCapital)

		#Spawn initial inventory of items
		self.agent.receiveItem(ItemContainer(self.sellItemId, self.targetProductionRate*self.targetInventoryDays))

		#Spawn fixed item inputs
		inputDeficits = self.agent.getProductionInputDeficit(self.sellItemId, self.targetProductionRate)
		for itemId in deficits["FixedItemDeficit"]:
			self.agent.receiveItem(deficits["FixedItemDeficit"][itemId])

		#Enable accounting
		self.agent.enableTradeRevenueTracking()
		self.agent.enableCurrencyOutflowTracking()
		self.agent.enableCurrencyInflowTracking()


	def receiveMsg(self, incommingPacket):
		self.logger.info("INBOUND {}".format(incommingPacket))

		#Handle tick grants
		if (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT) or (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT_BROADCAST):
			self.runStep()

		#Handle kill commands
		if (incommingPacket.msgType == PACKET_TYPE.KILL_PIPE_AGENT) or (incommingPacket.msgType == PACKET_TYPE.KILL_ALL_BROADCAST):
			self.killThreads = True

		#Handle incoming save checkpoint commands
		elif ((incommingPacket.msgType == PACKET_TYPE.SAVE_CHECKPOINT) or (incommingPacket.msgType == PACKET_TYPE.SAVE_CHECKPOINT_BROADCAST)):
			#Save controller checkpoint
			self.saveCheckpoint()

		#Handle incoming load checkpoint commands
		elif ((incommingPacket.msgType == PACKET_TYPE.LOAD_CHECKPOINT) or (incommingPacket.msgType == PACKET_TYPE.LOAD_CHECKPOINT_BROADCAST)):
			#Load controller checkpoint
			filePath = incommingPacket.payload
			self.loadCheckpoint(filePath=filePath)
			self.startStep = 0

		#Handle controller messages
		if ((incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG) or (incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG_BROADCAST)):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))

			if (controllerMsg.msgType == PACKET_TYPE.RESET_ACCOUNTING):
				self.agent.resetAccountingTotals()
			
			if (controllerMsg.msgType == PACKET_TYPE.STOP_TRADING):
				self.killThreads = True


	def evalTradeRequest(self, request):
		self.logger.debug("evalTradeRequest({}) start".format(request))
		productInventory = 0
		if (request.itemPackage.id in self.agent.inventory):
			productInventory = self.agent.inventory[request.itemPackage.id].quantity

		tradeAccepted = productInventory>request.itemPackage.quantity
		if (tradeAccepted):
			self.stepSalesLock.acquire()
			self.stepSales += request.itemPackage.quantity
			self.stepSalesLock.release()

		if (self.closingBusiness):
			liquidationListing = self.liquidationListings[request.itemPackage.id]
			liquidationListing.updateMaxQuantity((productInventory-request.itemPackage.quantity)*0.93)
			listingUpdated = self.agent.updateItemListing(liquidationListing)

		self.logger.debug("evalTradeRequest({}) return {}".format(request, tradeAccepted))
		return tradeAccepted

	#########################
	# Step Logic 
	#########################
	def runStep(self):
		if (self.closingBusiness):
			self.logger.info("#### StepNum = {} ####".format(self.agent.stepNum))

			#This business is currently under liquidation
			#Check if liquidation is complete. If so, commit suicide
			allItemsLiquidated = True
			for itemId in self.agent.inventory:
				itemContainer = self.agent.inventory[itemId]
				self.logger.debug("Remainging inventory: {}".format(itemContainer))
				if (itemContainer.quantity <= 0.01):
					self.agent.consumeItem(itemContainer)
					self.agent.removeItemListing(ItemListing(sellerId=self.agentId, itemId=itemId, unitPrice=0, maxQuantity=0))
				else:
					if ((self.agent.stepNum-self.updateOffset)%self.updateRate == 0):
						self.liquidateItem(itemContainer)
					allItemsLiquidated = False

			if (allItemsLiquidated):
				self.logger.info("Completed business liquidation. Commiting suicide")
				self.agent.commitSuicide()
				self.killThreads = True

		# A new step has started
		if (self.agent.stepNum == self.startStep):
			self.logger.info("StepNum = {}, Starting controller functionality".format(self.agent.stepNum))

		if ((self.agent.stepNum >= self.startStep) and (not self.closingBusiness)):
			self.logger.info("#### StepNum = {} ####".format(self.agent.stepNum))
			#Determine if we should go out of business
			currentCash = self.agent.getCurrencyBalance()
			avgExpenses = self.agent.getAvgCurrencyOutflow()
			stepExpenses = self.agent.getStepCurrencyOutflow()
			if ((currentCash < (avgExpenses*1.5)) or (currentCash < (stepExpenses*1.5))):
				#We're broke. Go out of business
				self.closeBusiness()
				
			if (not self.closingBusiness):
				#Update sales average
				alpha = 0.2
				self.currentSalesAvg = ((1-alpha)*self.currentSalesAvg) + (alpha*self.stepSales)
				self.stepSales = 0

				#Print business stats
				self.logger.info("Current sales average = {}".format(self.currentSalesAvg))
				avgRevenue = self.agent.getAvgTradeRevenue()
				avgExpenses = self.agent.getAvgCurrencyOutflow()
				self.logger.debug(self.agent.getAccountingStats())
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
						print("\a")
				else:
					try:
						#Produce items
						self.produce()
					except:
						self.logger.critical("UNHANDLED ERROR DURING STEP")
						self.logger.critical(traceback.format_exc())
						self.logger.critical(self.getInfoDumpString())
						print("\a")

		#Relinquish time ticks
		self.logger.info("Relinquishing time ticks")
		ticksRelinquished = self.agent.relinquishTimeTicks()
		self.logger.info("Ticks relinquished. Waiting for tick grant")

	#########################
	# Production Functions 
	#########################
	def adjustProduction(self):
		########
		# Get current algortithm inputs
		########

		#Get current profit margins
		avgRevenue = self.agent.getAvgTradeRevenue()
		avgExpenses = self.agent.getAvgCurrencyOutflow()
		profitMargin = 0
		if (avgExpenses > (avgRevenue/20)):
			profitMargin = (avgRevenue-avgExpenses)/avgExpenses
		elif (avgExpenses > 0):
			profitMargin = 2
		
		self.logger.debug("Profit margin = {}".format(profitMargin))

		#Get product inventory
		self.logger.info("Average production rate = {}".format(self.currentProductionRateAvg))
		productInventory = 0
		if (self.sellItemId in self.agent.inventory):
			productInventory = self.agent.inventory[self.sellItemId].quantity
		self.logger.debug("productInventory = {}".format(productInventory))
		inventoryRatio = (self.currentSalesAvg+1) / (productInventory+1)
		self.logger.debug("Inventory ratio = {}".format(inventoryRatio))

		#Get current sales
		self.logger.debug("Sales average = {}".format(self.currentSalesAvg))
		saleRatio = (self.currentSalesAvg+1)/(self.currentProductionRateAvg+1)
		self.logger.debug("Sale ratio = {}".format(saleRatio))

		#Get volume-adjusted mean market price
		sampledListings = self.agent.sampleItemListings(ItemContainer(self.sellItemId, 0.01), sampleSize=30)
		meanPrice = self.sellPrice
		totalQuantity = 0
		totalPrice = 0
		if (len(sampledListings) > 0):
			for listing in sampledListings:
				totalPrice += listing.unitPrice*listing.maxQuantity
				totalQuantity += listing.maxQuantity
			if ((totalQuantity > 0) and (totalPrice > 0)):
				meanPrice = totalPrice/totalQuantity
		self.logger.info("volume-adjusted average market price = {}".format(meanPrice))

		#Update elasticity datapoints
		if (self.elastDatapoints.full()):
			self.elastDatapoints.get()
		newDataPoint = {"price": self.sellPrice, "avgSales": self.currentSalesAvg}
		self.elastDatapoints.put(newDataPoint)

		#Calculate demand elasticity
		if (self.elastDatapoints.qsize() > 10):
			#Get lists of price datapoints and sales datapoints
			priceList = []
			salesList = []
			for datapoint in list(self.elastDatapoints.queue):
				priceList.append(datapoint["price"])
				salesList.append(datapoint["avgSales"])

			priceAxis = np.array(priceList).reshape((-1, 1))
			salesAxis = np.array(salesList)

			#Use linear regression to find demand elasticity
			self.linearModel.fit(priceAxis, salesAxis)
			calcElastitcity = self.linearModel.coef_[0]
			r_sq = self.linearModel.score(priceAxis, salesAxis)
			if (self.demandElasticity):
				elastAlpha = 0.2*(r_sq)
				self.demandElasticity = ((1-elastAlpha)*self.demandElasticity) + (elastAlpha*calcElastitcity)
				self.elasticityCorrelationCoef = ((1-elastAlpha)*self.elasticityCorrelationCoef) + (elastAlpha*r_sq)
			else:
				self.demandElasticity = calcElastitcity
				self.elasticityCorrelationCoef = r_sq

		if (self.demandElasticity):
			self.logger.info("Demand elasticity={}, R2={}".format(round(self.demandElasticity, 3), round(self.elasticityCorrelationCoef, 3)))
	

		########
		# Get new production values
		########

		#Adjust target production rate
		self.logger.info("Old target production rate = {}".format(self.targetProductionRate))
		self.targetProductionRate = self.adjustProductionTarget(inventoryRatio, profitMargin)
		self.logger.info("New target production rate = {}".format(self.targetProductionRate))

		#Adjust sale price 
		self.logger.info("Old sale price = {}".format(self.sellPrice))
		self.sellPrice = self.adjustSalePrice(avgRevenue, avgExpenses, meanPrice, saleRatio)
		self.logger.info("New sale price = {}".format(self.sellPrice))


	def adjustProductionTarget(self, inventoryRatio, profitMargin):
		self.logger.debug("adjustProductionTarget(inventoryRatio={}, profitMargin={}) start".format(inventoryRatio, profitMargin))
		#Adjust target production based on current profit margin and inventory ratio
		prodAlpha = 0.07

		ratioList = []

		profitAdjustmentRatio = 1
		if (profitMargin > 0.05):
			profitAdjustmentRatio = pow((1+profitMargin), 0.6)
			ratioList.append(profitAdjustmentRatio)
			self.logger.debug("adjustProductionTarget() Profit adjustment ratio = {}".format(profitAdjustmentRatio))

		elif (profitMargin < 0):
			profitAdjustmentRatio = pow((1+profitMargin), 1.6)
			productionAdjustmentRatio = profitAdjustmentRatio
			self.logger.debug("adjustProductionTarget() Profit adjustment ratio = {}".format(profitAdjustmentRatio))
			self.logger.debug("adjustProductionTarget() Production adjustment ratio = {}".format(productionAdjustmentRatio))
			targetProductionRate = ((1-prodAlpha)*((self.targetProductionRate+self.currentProductionRateAvg)/2)) + (prodAlpha*self.currentProductionRateAvg*productionAdjustmentRatio)

			return round(targetProductionRate, g_ItemQuantityPercision)

		inventoryAdjustmentRatio = pow(self.targetInventoryDays*inventoryRatio, 0.7)
		self.logger.debug("adjustProductionTarget() Inventory adjustment ratio = {}".format(inventoryAdjustmentRatio))
		ratioList.append(inventoryAdjustmentRatio)

		#productionAdjustmentRatio = sum(ratioList)/len(ratioList)
		productionAdjustmentRatio = inventoryAdjustmentRatio*profitAdjustmentRatio
		self.logger.debug("adjustProductionTarget() Production adjustment ratio = {}".format(productionAdjustmentRatio))
		targetProductionRate = ((1-prodAlpha)*((self.targetProductionRate+self.currentProductionRateAvg)/2)) + (prodAlpha*self.currentProductionRateAvg*productionAdjustmentRatio)

		return round(targetProductionRate, g_ItemQuantityPercision)


	def adjustSalePrice(self, avgRevenue, avgExpenses, meanPrice, saleRatio):
		self.logger.debug("adjustProductionTarget(avgRevenue={}, avgExpenses={}, meanPrice={}, saleRatio={}) start".format(avgRevenue, avgExpenses, meanPrice, saleRatio))
		ratioList = []

		#Make sure sell price covers our costs
		if (self.targetProductionRate > 0):
			if ((self.currentProductionRateAvg > 0) and (avgExpenses > 0)):
				currentUnitCost = (avgExpenses/self.currentProductionRateAvg) * (self.currentProductionRateAvg/self.targetProductionRate)
				self.logger.debug("adjustSalePrice() currentUnitCost = {}".format(currentUnitCost))

				unitCostAlpha = 0.15
				if (self.averageUnitCost):
					self.averageUnitCost = ((1-unitCostAlpha)*self.averageUnitCost) + (unitCostAlpha*currentUnitCost)
				else:
					self.averageUnitCost = currentUnitCost
				self.logger.debug("averageUnitCost = {}".format(self.averageUnitCost))

				#Calculate price that maximizes profit based on demand elasticity
				'''
				#This shit doesn't work. 
				#TODO: Maybe I need to weigh the elasticity measurement towards more recent data? How do you do that with linear regression?
				if (self.demandElasticity):
					if (self.demandElasticity < 0):
						#We have a valid demand elasticity. Calculate price that maximizes profits
						idealPrice = (self.averageUnitCost/2) + (self.sellPrice/2) + (self.currentSalesAvg/(2*self.demandElasticity))  #see Docs/misc/IdealPrice_Derivation for derivation
						if (idealPrice > 0) and (idealPrice > self.averageUnitCost):
							self.logger.debug("Theoretical ideal unit price = {}".format(round(idealPrice, 4)))
							idealRatio = pow(idealPrice/self.sellPrice, self.elasticityCorrelationCoef)
							ratioList.append(idealRatio)
				'''				

				#Make sure we are breaking even
				if (self.sellPrice < self.averageUnitCost):
					costAdjustmentRatio = pow(self.averageUnitCost/self.sellPrice, 1)
					self.logger.debug("adjustSalePrice() Current price too low to cover costs. Cost adjustment ratio = {}".format(costAdjustmentRatio))

					priceAlpha = 0.5
					sellPrice = ((1-priceAlpha)*self.sellPrice) + (priceAlpha*self.sellPrice*costAdjustmentRatio)
					if (sellPrice > 1.3*meanPrice):
						sellPrice = 1.3*meanPrice

					try:
						x = int(sellPrice)
					except:
						self.logger.error("Invalid sell price {}".format(sellPrice))
						self.logger.error("adjustProductionTarget(avgRevenue={}, avgExpenses={}, meanPrice={}, saleRatio={}) start".format(avgRevenue, avgExpenses, meanPrice, saleRatio))
						sellPrice = self.sellPrice

					return sellPrice

		#Adjust target price based on median price
		marketAdjustmentRatio = pow(meanPrice/self.sellPrice, 0.7)
		self.logger.debug("adjustSalePrice() marketAdjustmentRatio = {}".format(marketAdjustmentRatio))
		ratioList.append(marketAdjustmentRatio)

		#Adjust price based on sale ratios
		if (saleRatio < 1):
			saleAdjustmentRatio = pow(saleRatio, 1.4) 
			self.logger.debug("adjustSalePrice() saleAdjustmentRatio = {}".format(saleAdjustmentRatio))
			ratioList.append(saleAdjustmentRatio)
		elif (saleRatio > 1):
			saleAdjustmentRatio = pow(saleRatio, 0.4) 
			self.logger.debug("adjustSalePrice() saleAdjustmentRatio = {}".format(saleAdjustmentRatio))
			ratioList.append(saleAdjustmentRatio)
		

		#Get final price
		priceAdjustmentRatio = sum(ratioList)/len(ratioList)  #take average adjustment ratio
		self.logger.debug("adjustSalePrice() priceAdjustmentRatio = {}".format(priceAdjustmentRatio))
		priceAlpha = 0.1
		sellPrice = ((1-priceAlpha)*self.sellPrice) + (priceAlpha*self.sellPrice*priceAdjustmentRatio)

		try:
			x = int(sellPrice)
		except:
			self.logger.error("Invalid sell price {}".format(sellPrice))
			self.logger.error("adjustProductionTarget(avgRevenue={}, avgExpenses={}, meanPrice={}, saleRatio={}) start".format(avgRevenue, avgExpenses, meanPrice, saleRatio))
			sellPrice = self.sellPrice

		return sellPrice


	def liquidateItem(self, itemContainer):
		#Get volume-adjusted mean market price
		sampledListings = self.agent.sampleItemListings(ItemContainer(self.sellItemId, 0.01), sampleSize=30)
		meanPrice = 100
		if (itemContainer.id in self.liquidationListings):
			meanPrice = self.liquidationListings[itemContainer.id].unitPrice
		totalQuantity = 0
		totalPrice = 0
		if (len(sampledListings) > 0):
			for listing in sampledListings:
				if not (listing.sellerId == self.agentId):
					totalPrice += listing.unitPrice*listing.maxQuantity
					totalQuantity += listing.maxQuantity
			if ((totalQuantity > 0) and (totalPrice > 0)):
				meanPrice = totalPrice/totalQuantity

		#Determine liquidation price
		discountRatio = 0.85 + (0.1/(pow(1+self.agent.stepNum-self.closingStep, 0.2)))
		sellPrice = meanPrice*discountRatio
		self.logger.debug("{} discount ratio = {}".format(itemContainer.id, round(discountRatio, 3)))
		if (sellPrice <= 0):
			sellPrice = 1

		#Post item listing
		liquidationListing = ItemListing(sellerId=self.agentId, itemId=itemContainer.id, unitPrice=sellPrice, maxQuantity=itemContainer.quantity)
		self.liquidationListings[itemContainer.id] = liquidationListing
		listingUpdated = self.agent.updateItemListing(liquidationListing)


	def acquireItem(self, itemContainer):
		#Try to buy item from another seller
		amountAquired = self.agent.acquireItem(itemContainer)

		#If we couldn't buy it, try to make it ourselves
		if (amountAquired < itemContainer.quantity):
			missingQuantity = itemContainer.quantity - amountAquired


	def acquireDeficits(self, deficits):
		#Allocate more land if we don't have enough
		landDeficit = deficits["LandDeficit"] - self.agent.landHoldings["ALLOCATING"]
		if (landDeficit > 0):
			self.agent.allocateLand(self.sellItemId, landDeficit)

		#Acquire fixed item inputs
		for itemId in deficits["FixedItemDeficit"]:
			self.acquireFixedCapital(deficits["FixedItemDeficit"][itemId])

		#Adjust labor requirements
		self.laborLock.acquire()
		for skillLevel in deficits["LaborDeficit"]:
			self.requiredLabor = deficits["LaborDeficit"][skillLevel]
			self.workerDeficit = round(self.requiredLabor/self.maxTicksPerStep, 0)
		self.laborLock.release()

		#Spawn variable item inputs
		for itemId in deficits["VariableItemDeficit"]:
			self.agent.receiveItem(deficits["VariableItemDeficit"][itemId])
			self.agent.receiveItem(deficits["VariableItemDeficit"][itemId])


	def removeSurplus(self, surplusInputs):
		#Deallocate land if we have too much
		landSurplus = surplusInputs["LandSurplus"]
		if (landSurplus > 0):
			self.agent.deallocateLand(self.sellItemId, landSurplus)

		#Adjust labor requirements
		self.laborLock.acquire()
		for skillLevel in surplusInputs["LaborSurplus"]:
			self.requiredLabor = -1*surplusInputs["LaborSurplus"][skillLevel]
			self.workerDeficit = round(self.requiredLabor/self.maxTicksPerStep, 0)
		self.laborLock.release()


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
		productionAmount = maxProductionPossible
		self.logger.debug("targetProductionRate={}, productionAmount={}".format(self.targetProductionRate, productionAmount))

		producedItems = self.agent.produceItem(ItemContainer(self.sellItemId, productionAmount))
		self.logger.debug("Produced {}".format(producedItems))

		#Update production average
		alpha = self.agent.accountingAlpha
		self.currentProductionRateAvg = ((1-alpha)*self.currentProductionRateAvg) + (alpha*productionAmount)


	def updateItemListing(self):
		productInventory = 0	
		if (self.sellItemId in self.agent.inventory):	
			productInventory = self.agent.inventory[self.sellItemId].quantity	
		self.itemListing = ItemListing(sellerId=self.agentId, itemId=self.sellItemId, unitPrice=self.sellPrice, maxQuantity=self.currentProductionRateAvg/3)  #productInventory/(2*self.targetInventoryDays))	
		if (self.itemListing.maxQuantity > 0):	
			self.logger.info("Updating item listing | {}".format(self.itemListing))	
			listingUpdated = self.agent.updateItemListing(self.itemListing)	
		else:	
			self.logger.info("Max quantity = 0. Removing item listing | {}".format(self.itemListing))	
			listingUpdated = self.agent.removeItemListing(self.itemListing)


	#########################
	# Labor management
	#########################
	def manageLabor(self):
		#Lay off employees if required
		if (self.workerDeficit < 0):
			laborContracts = self.agent.getAllLaborContracts()
			wageDict = {}
			for contract in laborContracts:
				wagePerTick = contract.wagePerTick
				if not (contract.wagePerTick in wageDict):
					wageDict[wagePerTick] = []
				wageDict[wagePerTick].append(contract)
	
			sortedWageList = list(wageDict.keys())
			sortedWageList.sort()

			for wage in sortedWageList:
				if (self.workerDeficit >= 0):
					break
				for contract in wageDict[wage]:
					self.agent.cancelLaborContract(contract)
					self.workerDeficit += 1

					if (self.workerDeficit >= 0):
						break

		#Adjust wages
		self.logger.debug("Old wage = {}".format(self.workerWage))
		self.workerWage = self.adjustWorkerWage()
		self.logger.debug("New wage = {}".format(self.workerWage))

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
			if (self.listingActive):
				self.agent.removeLaborListing(self.laborListing)
				self.listingActive = False
				self.applications = 0
				self.openSteps = 0

		#Print stats
		self.logger.debug("HR Stats: employees={}, requiredLabor={}, workerDeficit={}, applications={}, openSteps={}, workerWage={}".format(self.agent.laborContractsTotal, self.requiredLabor, self.workerDeficit, self.applications, self.openSteps, self.workerWage))


	def adjustWorkerWage(self):
		ratioList = []
		
		#Adjust wage  based on market rate
		medianWage = self.workerWage
		sampledListings = self.agent.sampleLaborListings(sampleSize=30)
		sampledWages = SortedList()
		if (len(sampledListings) > 0):
			for listing in sampledListings:
				sampledWages.add(listing.wagePerTick)
			medianWage = sampledWages[int(len(sampledListings)/2)]
		medianRatio = medianWage/self.workerWage
		ratioList.append(medianRatio)

		#Adjust wage based on worker deficit and application number
		divisor = 1
		if (self.workerDeficit < 0):
			divisor = pow(abs(self.workerDeficit)*1.2, 1.1)
		if (self.workerDeficit > 0) and (self.openSteps > 2):
			divisor = 1/pow((self.workerDeficit), 0.15)
		if (self.workerDeficit > 0):
			if (abs(self.applications/self.workerDeficit)>1.5):
				divisor = pow(abs(self.applications/self.workerDeficit), 1.5)

		dividend = 1.0
		if (self.openSteps > 3):
			dividend = (pow(self.openSteps, 0.2))

		deficitRatio = pow(dividend/divisor, 1.2)
		ratioList.append(deficitRatio)

		#Adjust the wage for next time
		adjustmentAlpha = 0.1
		adjustmentRatio = sum(ratioList)/len(ratioList)
		newWage = ((1-adjustmentAlpha)*self.workerWage)+(adjustmentAlpha*adjustmentRatio*self.workerWage)

		return newWage


	def evalJobApplication(self, laborContract):
		self.logger.debug("Recieved job application {}".format(laborContract))

		if (self.closingBusiness):	
			return False

		if (self.openSteps > 0):
			self.applications = 0
		self.openSteps = 0

		self.applications += 1

		#Hire them if we need the labor
		acquired_laborLock = self.laborLock.acquire(timeout=5)
		if (acquired_laborLock):
			if (self.requiredLabor > 0):
				self.logger.info("Accepting job application {}".format(laborContract))

				#Decrease required labor
				self.requiredLabor -= laborContract.ticksPerStep
				self.laborLock.release()

				#Spawn salary if money printer is enabled
				if (self.infiniteCapital):
					totalWages = int((laborContract.wagePerTick * laborContract.ticksPerStep * laborContract.contractLength + 100)*10)
					self.agent.receiveCurrency(totalWages)

				self.logger.debug("Accepted job application {}".format(laborContract))
				return True
			else:
				self.laborLock.release()
				#We don't need more labor. Reject this application
				self.logger.debug("Rejected job application {}".format(laborContract))
				return False
		else:
			self.logger.error("evalJobApplication({}) laborLock acquisition timeout".format(laborContract))
			return False

	
	#########################
	# Business Suicide functions
	#########################
	def closeBusiness(self):
		self.logger.info("### Going out of business ###")
		self.closingStep = self.agent.stepNum

		#Sell all inventory
		self.logger.info("Liquidating inventory")
		for itemId in self.agent.inventory:
			self.liquidateItem(self.agent.inventory[itemId])

		self.closingBusiness = True

		#Fire all employees
		self.logger.info("Firing all employees")
		if (self.listingActive):
			self.agent.removeLaborListing(self.laborListing)
		laborContracts = self.agent.getAllLaborContracts()
		for contract in laborContracts:
			self.agent.cancelLaborContract(contract)

		#Post all land for sale
		pass  #TODO

	#########################
	# Misc functions
	#########################
	def saveCheckpoint(self, filePath=None):
		'''
		Saves current controller state into a checkpoint file. Will determine it's own filepath if filePath is not defined
		'''
		self.logger.info("saveCheckpoint() start")
		checkpointObj = TestFarmCompetetiveV4_Checkpoint(self)

		checkpointFileName = "{}.checkpoint.pickle".format(self.name)
		outputPath = os.path.join(self.outputDir, "CHECKPOINT", checkpointFileName)
		if (filePath):
			outputPath = filePath
		utils.createFolderPath(outputPath)

		self.logger.info("saveCheckpoint() Saving checkpoint to \"{}\"".format(outputPath))
		with open(outputPath, "wb") as pickleFile:
			pickle.dump(checkpointObj, pickleFile)

	def loadCheckpoint(self, filePath=None):
		'''
		Attempts to load controller state from checkpoint file. Returns true if successful, False if not
		Will try to find the checkpoint file if filePath is not specified.
		'''
		self.logger.info("loadCheckpoint(filePath={}) start".format(filePath))

		#Determine checkpoint file path
		checkpointFileName = "{}.checkpoint.pickle".format(self.name)
		checkpointFilePath = os.path.join(self.outputDir, "CHECKPOINT", checkpointFileName)
		if (filePath):
			if (os.path.isdir(filePath)):
				checkpointFilePath = os.path.join(filePath, checkpointFileName)
			else:
				checkpointFilePath = filePath

		if (not os.path.exists(checkpointFilePath)):
			self.logger.error("Could not load checkpoint. \"{}\" does not exist".format(checkpointFilePath))
			return False

		#Load checkpoint
		try:
			self.logger.info("loadCheckpoint() Trying to load checkpoint \"{}\"".format(checkpointFilePath))
			checkpointObj = None
			with open(checkpointFilePath, "rb") as pickleFile:
				checkpointObj = pickle.load(pickleFile)

			if (checkpointObj):
				if (isinstance(checkpointObj, TestFarmCompetetiveV4_Checkpoint)):
					checkpointObj.loadCheckpoint(self)
				else:
					raise ValueError("Loaded pickle was tpye \"{}\"".format(type(checkpointObj)))
			else:
				raise ValueError("Loaded pickle was None")
		except:
			self.logger.error("Error while loading checkpoint\n{}".format(traceback.format_exc()))
			return False

		self.logger.debug("loadCheckpoint() succeeded")
		return True

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