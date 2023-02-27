'''
Standard agent controllers, both AI and rules-based
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
import pickle

import utils
from TradeClasses import *
from NetworkClasses import *


####################
# PeasantFarmWorker
####################
class FrugalWorker:
	'''
	This controller will try to find the highest paying job. Will automatically pruchase and consume food to survive and maximize net utility. Will not purchase anything other than food.
	Will print money the first several days of a new simulation in order to kickstart the economy.
	'''
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO", outputDir="OUTPUT"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_PeasantFarmWorker".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join(outputDir, "LOGS", "Controller_Logs"), fileLevel=fileLevel)

		#Initiate thread kill flag to false
		self.killThreads = False

		#Wage expectations
		self.expectedWage = 0

		#Handle start skews
		self.startStep = 0
		self.skewRate = 0
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

		#Handle incoming load checkpoint commands
		elif ((incommingPacket.msgType == PACKET_TYPE.LOAD_CHECKPOINT) or (incommingPacket.msgType == PACKET_TYPE.LOAD_CHECKPOINT_BROADCAST)):
			self.startStep = 0


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


####################
# BasicItemProducer
####################
class BasicItemProducer_Checkpoint:
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


class BasicItemProducer:
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
		checkpointObj = BasicItemProducer_Checkpoint(self)

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
				if (isinstance(checkpointObj, BasicItemProducer_Checkpoint)):
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


####################
# AIItemProducer
####################
class AIItemProducer_Checkpoint:
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


class AIItemProducer:
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

		#AI Enable
		self.aiEnabled = True
		if ("AIEnabled" in settings):
			self.aiEnabled = bool(settings["AIEnabled"])

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
						if (self.aiEnabled):
							self.manageBusiness_AI()
						else:
							#Adjust production
							self.adjustProduction_RuleBased()

							#Manage worker hiring
							self.manageLabor_RuleBased()

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
	# AI Functions 
	#########################
	def manageBusiness_AI(self):
		########
		# Get AI inputs
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

		#Get volume-adjusted mean market price
		sampledListings = self.agent.sampleItemListings(ItemContainer(self.sellItemId, 0.01), sampleSize=30)
		meanMarketPrice = self.sellPrice
		totalQuantity = 0
		totalPrice = 0
		if (len(sampledListings) > 0):
			for listing in sampledListings:
				totalPrice += listing.unitPrice*listing.maxQuantity
				totalQuantity += listing.maxQuantity
			if ((totalQuantity > 0) and (totalPrice > 0)):
				meanMarketPrice = totalPrice/totalQuantity
		self.logger.info("volume-adjusted average market price = {}".format(meanMarketPrice))

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

		#Get the market worker wage
		medianWage = self.workerWage
		sampledListings = self.agent.sampleLaborListings(sampleSize=30)
		sampledWages = SortedList()
		if (len(sampledListings) > 0):
			for listing in sampledListings:
				sampledWages.add(listing.wagePerTick)
			medianWage = sampledWages[int(len(sampledListings)/2)]
		
		#Get current worker/labor deficit
		requiredLaborTicks = self.requiredLabor
		workerDeficit = round(self.requiredLabor/self.maxTicksPerStep, 0)

		########
		# Run AI
		########
		#TODO: Implement AI
		self.targetProductionRate, self.sellPrice, self.workerWage = self.AI(avgRevenue, avgExpenses, profitMargin, self.currentSalesAvg, productInventory, meanMarketPrice, self.demandElasticity, self.elasticityCorrelationCoef, medianWage, requiredLaborTicks, workerDeficit)

	#########################
	# Production Functions 
	#########################
	def adjustProduction_RuleBased(self):
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
	def manageLabor_RuleBased(self):
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
		checkpointObj = AIItemProducer_Checkpoint(self)

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
				if (isinstance(checkpointObj, AIItemProducer_Checkpoint)):
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

