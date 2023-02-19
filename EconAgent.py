'''
This file contains:
	-Agent class
		The Agent class is a generic class used by all agents running in a simulation.

		The behavior and actions of any given agent instance is decided by it's controller, which handles all decision making.
		The Agent class is instead responsible for the controller's interface to the rest of the simulation.

		The Agent class handles:
			-item transfers
			-item consumption
			-item production
			-currency transfers
			-trade execution
			-land holdings
			-land transfers
			-currency balance management
			-item inventory management
			-ConnectionNetwork interactions
			-item utility calculations
			-marketplace updates and polling

	-UtilityFunction class
		Determines the utility of an object for a given agent

	-ProductionFunction class
		Used to calculate production costs for a given item
'''

import math
import threading
import logging
import time
import os
import random
import multiprocessing
import copy
import queue
import numpy as np
from sortedcontainers import SortedList
import pickle
import traceback

from NetworkClasses import *
from TestControllers import *
from TradeClasses import *
import utils


#######################
# Utility Function
#######################
class UtilityFunction:
	'''
	Determines the utility for an object
	'''
	def __init__(self, baseUtility, baseStdDev, diminishingFactor, diminStdDev):
		self.baseUtility = float(utils.getNormalSample(baseUtility, baseStdDev))
		self.diminishingFactor = float(utils.getNormalSample(diminishingFactor, diminStdDev))

	def getMarginalUtility(self, quantity):
		'''
		Marginal utility can be modeled by the function U' = B/((N+1)^D), where
			N is the current quantity of items.
			B is the base utility of a single item.
			D is the diminishing utility factor. The higher D is, the faster the utility of more items diminishes.
			U' is the marginal utility of 1 additional item

		The marginal utility curve for any given agent can be represented by B and D.
		'''
		marginalUtility = self.baseUtility / (pow(quantity+1, self.diminishingFactor))
		return marginalUtility

	def getTotalUtility(self, quantity):
		'''
		Getting the discrete utility with a for loop is too inefficient, so this uses the continuous integral of marginal utility instead.
		Integral[B/(N^D)] = U(N) = ( B*(x^(1-D)) ) / (1-D) , if D != 1.
		Integral[B/(N^D)] = U(N) = B*ln(N) , if D == 1

		totalUtiliy = U(quantity) - U(1) + U'(0)
			totalUtiliy = U(quantity) - U(1) + U'(0) = B*ln(quantity) - 0 + B  ,  if D == 1

			totalUtiliy = U(quantity) - U(1) + U'(0) 
				= U(quantity) - (B/(1-D)) + B  
				= ( (B*(x^(1-D)) - B) / (1-D) ) + B
				= ( (B*(x^(1-D) - 1)) / (1-D) ) + B  ,  if D != 1
		'''
		if (quantity == 0):
			return 0

		if (self.diminishingFactor == 1):
			totalUtility = (self.baseUtility * math.log(quantity)) + self.baseUtility
		else:
			totalUtility = ((self.baseUtility * (pow(quantity, 1-self.diminishingFactor) - 1)) / (1-self.diminishingFactor)) + self.baseUtility

		return totalUtility

	def __str__(self):
		return "UF(BaseUtility: {}, DiminishingFactor: {})".format(self.baseUtility, self.diminishingFactor)

	def __repr__(self):
		return str(self)


#######################
# Production Function
#######################
class ProductionFunction:
	'''
	Used to calculate production costs for a given item
	'''
	def __init__(self, itemDict):
		self.itemDict = itemDict
		self.itemId = itemDict["id"]
		self.prductionDict = itemDict["ProductionInputs"]

		#Production learning curve
		learningCurveDict = itemDict["ProductionLearningCurve"]
		self.efficiency = learningCurveDict["StartingEfficiency"]
		self.startInnefficiency = 1 - learningCurveDict["StartingEfficiency"]
		self.halfLifeQuant = learningCurveDict["HalfLifeQuant"]
		self.producedItems = 0

		#Fixed costs
		self.fixedLandCosts = {}
		self.fixedItemCosts = {}
		self.fixedLaborCosts = {}

		#Variable costs
		self.variableItemCosts = {}
		self.variableLaborCosts = {}

		#Generate costs
		self.updateCosts()

	def updateCosts(self):
		#Update current production efficiency
		newInnefficiency = 0
		try:
			newInnefficiency = self.startInnefficiency / math.pow(2, (self.producedItems/self.halfLifeQuant))
		except:
			newInnefficiency = (1-self.efficiency)*0.95
		self.efficiency = 1 - newInnefficiency

		#Update fixed costs
		if ("FixedCosts" in self.prductionDict):
			if ("FixedLandCosts" in self.prductionDict["FixedCosts"]):
				if ("MaxYield" in self.prductionDict["FixedCosts"]["FixedLandCosts"]):
					self.fixedLandCosts["MaxYield"] = bool(self.prductionDict["FixedCosts"]["FixedLandCosts"]["MaxYield"])
					if (self.prductionDict["FixedCosts"]["FixedLandCosts"]["MaxYield"]):
						self.fixedLandCosts["MaxYield"] = float(self.efficiency*self.prductionDict["FixedCosts"]["FixedLandCosts"]["MaxYield"])

				if ("MinQuantity" in self.prductionDict["FixedCosts"]["FixedLandCosts"]):
					self.fixedLandCosts["MinQuantity"] = float(self.prductionDict["FixedCosts"]["FixedLandCosts"]["MinQuantity"])

				if ("Quantized" in self.prductionDict["FixedCosts"]["FixedLandCosts"]):
					self.fixedLandCosts["Quantized"] = bool(self.prductionDict["FixedCosts"]["FixedLandCosts"]["Quantized"])
			if ("FixedItemCosts" in self.prductionDict["FixedCosts"]):
				for itemId in self.prductionDict["FixedCosts"]["FixedItemCosts"]:
					self.fixedItemCosts[itemId] = {}
					itemCosts = self.prductionDict["FixedCosts"]["FixedItemCosts"][itemId]
					self.fixedItemCosts[itemId]["MaxYield"] = bool(itemCosts["MaxYield"])
					if (itemCosts["MaxYield"]):
						self.fixedItemCosts[itemId]["MaxYield"] = float(self.efficiency*itemCosts["MaxYield"])

					self.fixedItemCosts[itemId]["MinQuantity"] = float(itemCosts["MinQuantity"])
					self.fixedItemCosts[itemId]["Quantized"] = bool(itemCosts["Quantized"])
			if ("FixedLaborCosts" in self.prductionDict["FixedCosts"]):
				for skillLevel in self.prductionDict["FixedCosts"]["FixedLaborCosts"]:
					self.fixedLaborCosts[float(skillLevel)] = int(self.prductionDict["FixedCosts"]["FixedLaborCosts"][skillLevel])

		#Update variable costs
		if ("VariableCosts" in self.prductionDict):
			if ("VariableItemCosts" in self.prductionDict["VariableCosts"]):
				for itemId in self.prductionDict["VariableCosts"]["VariableItemCosts"]:
					self.variableItemCosts[itemId] = float(self.prductionDict["VariableCosts"]["VariableItemCosts"][itemId]/self.efficiency)

			if ("VariableLaborCosts" in self.prductionDict["VariableCosts"]):
				for skillLevel in self.prductionDict["VariableCosts"]["VariableLaborCosts"]:
					self.variableLaborCosts[float(skillLevel)] = float(self.prductionDict["VariableCosts"]["VariableLaborCosts"][skillLevel]/self.efficiency)

	def getProductionInputDeltas(self, agent, maxStepProduction):
		'''
		Returns a dictionary containing the difference between what is needed to support maxStepProduction and what the agent currently possesses
		'''
		maxTickProduction = (maxStepProduction/agent.ticksPerStep)

		#Calculate land delta
		neededLand = 0
		if ("MaxYield" in self.fixedLandCosts):
			if (self.fixedLandCosts["MaxYield"]):
				maxYield = self.fixedLandCosts["MaxYield"]
				neededLand = maxTickProduction/maxYield
		if ("MinQuantity" in self.fixedLandCosts):
			minQuanta = self.fixedLandCosts["MinQuantity"]
			if (neededLand < minQuanta):
				neededLand = minQuanta
		if ("Quantized" in self.fixedLandCosts):
			if (self.fixedLandCosts["Quantized"]):
				minQuanta = self.fixedLandCosts["MinQuantity"]
				neededQuantas = math.ceil(float(neededLand)/minQuanta)
				neededLand = minQuanta*neededQuantas

		allocatedLand = 0
		if (self.itemId in agent.landHoldings):
			#This agent has allocated land to this item
			allocatedLand = agent.landHoldings[self.itemId]

		landDelta = neededLand - allocatedLand

		#Calculate fixed item deltas
		neededFixedItems = {}
		for itemId in self.fixedItemCosts:
			neededAmount = 0
			itemCosts = self.fixedItemCosts[itemId]
			if ("MaxYield" in itemCosts):
				if (itemCosts["MaxYield"]):
					neededAmount = maxStepProduction/itemCosts["MaxYield"]
			if ("MinQuantity" in itemCosts):
				minQuanta = itemCosts["MinQuantity"]
				if (neededAmount < minQuanta):
					neededAmount = minQuanta
			if ("Quantized" in itemCosts):
				if (itemCosts["Quantized"]):
					minQuanta = itemCosts["MinQuantity"]
					neededQuantas = math.ceil(float(neededAmount)/minQuanta)
					neededAmount = minQuanta*neededQuantas

			if (neededAmount > 0):
				neededFixedItems[itemId] = ItemContainer(itemId, neededAmount)

		fixedItemDeltas = {}
		for itemId in neededFixedItems:
			if (itemId in agent.inventory):
				neededFixedItems[itemId] -= agent.inventory[itemId]

			if (neededFixedItems[itemId].quantity != 0):
				fixedItemDeltas[itemId] = neededFixedItems[itemId]

		#Calculate variable item deltas
		neededVarItems = {}
		for itemId in self.variableItemCosts:
			neededAmount = maxStepProduction * self.variableItemCosts[itemId]
			if (neededAmount > 0):
				neededVarItems[itemId] = ItemContainer(itemId, neededAmount)

		varItemDeltas = {}
		for itemId in neededVarItems:
			if (itemId in agent.inventory):
				neededVarItems[itemId] -= agent.inventory[itemId]

			if (neededVarItems[itemId].quantity != 0):
				varItemDeltas[itemId] = neededVarItems[itemId]

		####
		# Calc labor delta
		####

		#Determine our theoretical labor availability per step
		agent.laborContractsLock.acquire()
		tempLaborContracts = copy.deepcopy(agent.laborContracts)
		agent.laborContractsLock.release()
		laborContractsList =  []
		for endStep in tempLaborContracts:
			for contractHash in tempLaborContracts[endStep]:
				laborContractsList.append(tempLaborContracts[endStep][contractHash])

		theorLaborInventory = {}
		for contract in laborContractsList:
			if not (contract.workerSkillLevel in theorLaborInventory):
				theorLaborInventory[contract.workerSkillLevel] = 0
			theorLaborInventory[contract.workerSkillLevel] += contract.ticksPerStep

		#Calculate fixed labor deficits
		availableSkillLevels = [i for i in theorLaborInventory.keys()]
		availableSkillLevels.sort(reverse=True)

		requiredSkillLevels = [i for i in self.fixedLaborCosts.keys()]
		requiredSkillLevels.sort(reverse=True)

		fixedLaborDeficits = {}
		for reqSkillLevel in requiredSkillLevels:
			requiredLaborTicks = self.fixedLaborCosts[reqSkillLevel]
			while (requiredLaborTicks > 0):
				if (len(availableSkillLevels) > 0):
					highestAvailSkill = availableSkillLevels[0]
					if (highestAvailSkill >= reqSkillLevel):
						availTicks = theorLaborInventory[highestAvailSkill]
						if (availTicks <= requiredLaborTicks):
							requiredLaborTicks -= availTicks
							theorLaborInventory[highestAvailSkill] -= availTicks
							availableSkillLevels.pop(0)
						else:
							theorLaborInventory[highestAvailSkill] -= requiredLaborTicks
							requiredLaborTicks = 0

					else:
						#We don't have skilled enough labor
						break
				else:
					#Do not have enough labor
					break

			fixedLaborDeficits[reqSkillLevel] = requiredLaborTicks

		#Calculate variable labor deficits
		requiredSkillLevels = [i for i in self.variableLaborCosts.keys()]
		requiredSkillLevels.sort(reverse=True)

		variableLaborDeficits = {}
		for reqSkillLevel in requiredSkillLevels:
			requiredLaborTicks = maxStepProduction * self.variableLaborCosts[reqSkillLevel]
			while (requiredLaborTicks > 0):
				if (len(availableSkillLevels) > 0):
					highestAvailSkill = availableSkillLevels[0]
					if (highestAvailSkill >= reqSkillLevel):
						availTicks = theorLaborInventory[highestAvailSkill]
						if (availTicks <= requiredLaborTicks):
							requiredLaborTicks -= availTicks
							theorLaborInventory[highestAvailSkill] -= availTicks
							availableSkillLevels.pop(0)
						else:
							theorLaborInventory[highestAvailSkill] -= requiredLaborTicks
							requiredLaborTicks = 0

					else:
						break
				else:
					break

			variableLaborDeficits[reqSkillLevel] = requiredLaborTicks

		#Caclute labor surplus
		surplusLaborInventory = theorLaborInventory

		#Combine surples and defecits into a single labor delta dict
		tempLaborDeltas = {}
		for skillLevel in fixedLaborDeficits:
			if not (skillLevel in tempLaborDeltas):
				tempLaborDeltas[skillLevel] = 0
			tempLaborDeltas[skillLevel] += fixedLaborDeficits[skillLevel]
		for skillLevel in variableLaborDeficits:
			if not (skillLevel in tempLaborDeltas):
				tempLaborDeltas[skillLevel] = 0
			tempLaborDeltas[skillLevel] += variableLaborDeficits[skillLevel]
		for skillLevel in surplusLaborInventory:
			if not (skillLevel in tempLaborDeltas):
				tempLaborDeltas[skillLevel] = 0
			tempLaborDeltas[skillLevel] -= surplusLaborInventory[skillLevel]

		laborDeltas = {}
		for skillLevel in tempLaborDeltas:
			delta = tempLaborDeltas[skillLevel]
			if (delta != 0):
				laborDeltas[skillLevel] = delta

		####
		# Return deltas
		####
		deltaDict = {
		"LandDelta": landDelta, 
		"FixedItemDeltas": fixedItemDeltas,
		"VariableItemDeltas": varItemDeltas,
		"LaborDeltas": laborDeltas}

		return deltaDict


	def getMaxProduction(self, agent):
		'''
		Returns the maximum amount of this item that can be produced at this time
		'''
		quantityPercision = g_ItemQuantityPercision
		maxQuantity = -1
		maxTickYield = -1  #Maximum amount that can be produced in a single time tick

		#Check land requirements
		if (len(self.fixedLandCosts) > 0):
			#This item requires land to produce
			if (self.itemId in agent.landHoldings):
				#This agent has allocated land to this item
				allocatedLand = agent.landHoldings[self.itemId]
				maxTickYield = allocatedLand * self.fixedLandCosts["MaxYield"]

				if (self.fixedLandCosts["MinQuantity"] > 0):
					#This item has a min land requirement
					if (allocatedLand < self.fixedLandCosts["MinQuantity"]):
						#Agent has not allocated enough land
						maxQuantity = 0
						return maxQuantity
					elif (self.fixedLandCosts["Quantized"]):
						#Land use is quantized
						usableLand = int(allocatedLand / self.fixedLandCosts["MinQuantity"]) * self.fixedLandCosts["MinQuantity"]
						maxTickYieldTemp = usableLand * self.fixedLandCosts["MaxYield"]
						if ((maxTickYield==-1) or (maxTickYieldTemp<maxTickYield)):
							maxTickYield = maxTickYieldTemp
			else:
				#This agent has not allocated land to produce this item
				maxQuantity = 0
				return maxQuantity


		#Check fixed item requriements
		for fixedCostItemId in self.fixedItemCosts:
			if (fixedCostItemId in agent.inventory):
				#This agent has the required item
				itemCost = self.fixedItemCosts[fixedCostItemId]
				currentInventory = agent.inventory[fixedCostItemId].quantity

				if (itemCost["MinQuantity"] > 0):
					if (currentInventory < itemCost["MinQuantity"]):
						#Agent has not have enough of this item to start production
						maxQuantity = 0
						return maxQuantity
					elif (self.fixedLandCosts["Quantized"]):
						#item use is quantized
						usableInventory = int(currentInventory / itemCost["MinQuantity"]) * itemCost["MinQuantity"]
						if (itemCost["MaxYield"]):
							maxTickYieldTemp = usableInventory * itemCost["MaxYield"]
							if ((maxTickYield==-1) or (maxTickYieldTemp<maxTickYield)):
								maxTickYield = maxTickYieldTemp
			else:
				#This agent does not have the required item
				maxQuantity = 0
				return maxQuantity


		#Check fixed labor requirements
		agent.laborInventoryLock.acquire()
		tempLaborInventory =  copy.deepcopy(agent.laborInventory)
		agent.laborInventoryLock.release()
		availableSkillLevels = [i for i in agent.laborInventory.keys()]
		availableSkillLevels.sort(reverse=True)

		if (len(self.fixedLaborCosts) > 0):
			requiredSkillLevels = [i for i in self.fixedLaborCosts.keys()]
			requiredSkillLevels.sort(reverse=True)

			#Check labor requirements in descending skill level
			for reqSkillLevel in requiredSkillLevels:
				requiredLaborTicks = self.fixedLaborCosts[reqSkillLevel]
				while (requiredLaborTicks > 0):
					if (len(availableSkillLevels) > 0):
						highestAvailSkill = availableSkillLevels[0]
						if (highestAvailSkill >= reqSkillLevel):
							availTicks = tempLaborInventory[highestAvailSkill]
							if (availTicks <= requiredLaborTicks):
								requiredLaborTicks -= availTicks
								tempLaborInventory[highestAvailSkill] -= availTicks
								availableSkillLevels.pop(0)
							else:
								tempLaborInventory[highestAvailSkill] -= requiredLaborTicks
								requiredLaborTicks = 0

						else:
							#We don't have skilled enough labor
							maxQuantity = 0
							return maxQuantity
					else:
						#Do not have enough labor
						maxQuantity = 0
						return maxQuantity

		#Initialize max quantity using maxTickYield
		if (maxTickYield > 0):
			maxQuantity = maxTickYield * agent.timeTicks

		#Check variable item costs
		for varCostId in self.variableItemCosts:
			if (varCostId in agent.inventory):
				varUnitCost = self.variableItemCosts[varCostId]
				maxQuantityTemp = agent.inventory[varCostId].quantity / varUnitCost
				if ((maxQuantity==-1) or (maxQuantityTemp<maxQuantity)):
					maxQuantity = maxQuantityTemp
			else:
				#Agent does not have needed variable cost
				maxQuantity = 0
				return maxQuantity

		#Check variable labor costs
		if (len(self.variableLaborCosts) > 0):
			requiredSkillLevels = [i for i in self.variableLaborCosts.keys()]
			requiredSkillLevels.sort(reverse=True)

			#Check labor requirements in descending skill level
			for reqSkillLevel in requiredSkillLevels:
				requiredLaborTicks = maxQuantity * self.variableLaborCosts[reqSkillLevel]
				allocatedLaborTicks = 0
				while (requiredLaborTicks > 0):
					if (len(availableSkillLevels) > 0):
						highestAvailSkill = availableSkillLevels[0]
						if (highestAvailSkill >= reqSkillLevel):
							availTicks = tempLaborInventory[highestAvailSkill]
							if (availTicks <= requiredLaborTicks):
								requiredLaborTicks -= availTicks
								tempLaborInventory[highestAvailSkill] -= availTicks
								allocatedLaborTicks += availTicks
								availableSkillLevels.pop(0)
							else:
								tempLaborInventory[highestAvailSkill] -= requiredLaborTicks
								requiredLaborTicks = 0
								allocatedLaborTicks += availTicks

						else:
							maxQuantityTemp = allocatedLaborTicks / self.variableLaborCosts[reqSkillLevel]
							if (maxQuantityTemp<maxQuantity):
								maxQuantity = maxQuantityTemp
							break
					else:
						maxQuantityTemp = allocatedLaborTicks / self.variableLaborCosts[reqSkillLevel]
						if (maxQuantityTemp<maxQuantity):
							maxQuantity = maxQuantityTemp
						break
		
		
		#maxQuantity = int(maxQuantity*pow(10, quantityPercision))/pow(10, quantityPercision)
		maxQuantity = utils.truncateFloat(maxQuantity, quantityPercision)

		return maxQuantity

	def produceItem(self, agent, productionAmount):
		'''
		Returns an item container if successful. Returns false if not
		'''
		maxQuantity = self.getMaxProduction(agent)
		if (productionAmount > maxQuantity):
			agent.logger.error("Cannot produce {} \"{}\". Max possible production = {}".format(productionAmount, self.itemId, maxQuantity))
			return False

		#Set aside fixed labor
		agent.laborInventoryLock.acquire()  #acquire labor lock

		availableLabor = copy.deepcopy(agent.laborInventory)
		availableSkillLevels = [i for i in agent.laborInventory.keys()]
		availableSkillLevels.sort(reverse=True)

		if (len(self.fixedLaborCosts) > 0):
			requiredSkillLevels = [i for i in self.fixedLaborCosts.keys()]
			requiredSkillLevels.sort(reverse=True)

			#Check labor requirements in descending skill level
			for reqSkillLevel in requiredSkillLevels:
				requiredLaborTicks = self.fixedLaborCosts[reqSkillLevel]
				while (requiredLaborTicks > 0):
					if (len(availableSkillLevels) > 0):
						highestAvailSkill = availableSkillLevels[0]
						if (highestAvailSkill >= reqSkillLevel):
							availTicks = availableLabor[highestAvailSkill]
							if (availTicks <= requiredLaborTicks):
								requiredLaborTicks -= availTicks
								availableLabor[highestAvailSkill] -= availTicks
								availableSkillLevels.pop(0)
							else:
								availableLabor[highestAvailSkill] -= requiredLaborTicks
								requiredLaborTicks = 0

						else:
							#We don't have skilled enough labor
							agent.laborInventoryLock.release()  #release labor lock
							agent.logger.error("Cannot produce {} {} \"{}\". Not enough fixed-cost labor (skillLevel>={})".format(reqSkillLevel, productionAmount, self.itemDict["unit"], self.itemId))
							return False
					else:
						#Do not have enough labor
						agent.laborInventoryLock.release()  #release labor lock
						agent.logger.error("Cannot produce {} {} \"{}\". Not enough fixed-cost labor (skillLevel>={})".format(reqSkillLevel, productionAmount, self.itemDict["unit"], self.itemId))
						return False

		#Calculate labor required
		consumedLabor = {}

		if (len(self.variableLaborCosts) > 0):
			requiredSkillLevels = [i for i in self.variableLaborCosts.keys()]
			requiredSkillLevels.sort(reverse=True)

			#Check labor requirements in descending skill level
			for reqSkillLevel in requiredSkillLevels:
				requiredLaborTicks = productionAmount * self.variableLaborCosts[reqSkillLevel]
				allocatedLaborTicks = 0
				while (requiredLaborTicks > 0):
					if (len(availableSkillLevels) > 0):
						highestAvailSkill = availableSkillLevels[0]
						if (highestAvailSkill >= reqSkillLevel):
							availTicks = availableLabor[highestAvailSkill]
							if (availTicks <= requiredLaborTicks):
								requiredLaborTicks -= availTicks
								availableLabor[highestAvailSkill] -= availTicks
								consumedLabor[highestAvailSkill] = availTicks
								allocatedLaborTicks += availTicks
								availableSkillLevels.pop(0)
							else:
								availableLabor[highestAvailSkill] -= requiredLaborTicks
								consumedLabor[highestAvailSkill] = requiredLaborTicks
								requiredLaborTicks = 0
								allocatedLaborTicks += availTicks

						else:
							#We don't have skilled enough labor
							agent.laborInventoryLock.release()  #release labor lock
							agent.logger.error("Cannot produce {} {} \"{}\". Not enough variable-cost labor (skillLevel>={})".format(productionAmount, self.itemDict["unit"], self.itemId, reqSkillLevel))
							agent.logger.debug("labor inventory = {}".format(agent.laborInventory))
							agent.logger.debug("consumedLabor = {}".format(consumedLabor))
							agent.logger.debug("requiredLaborTicks = {}".format(requiredLaborTicks))
							return False
					else:
						#We don't have skilled enough labor
						agent.laborInventoryLock.release()  #release labor lock
						agent.logger.error("Cannot produce {} {} \"{}\". Not enough variable-cost labor (skillLevel>={})".format(productionAmount, self.itemDict["unit"], self.itemId, reqSkillLevel))
						agent.logger.debug("labor inventory = {}".format(agent.laborInventory))
						agent.logger.debug("consumedLabor = {}".format(consumedLabor))
						agent.logger.debug("requiredLaborTicks = {}".format(requiredLaborTicks))
						return False

		#Calculate variable item inputs required
		consumedItems = {}
		for varCostId in self.variableItemCosts:
			consumedAmount = self.variableItemCosts[varCostId] * productionAmount
			consumedItems[varCostId] = ItemContainer(varCostId, consumedAmount)

		#Ensure we have enough items
		agent.inventoryLock.acquire()

		enoughItems = True
		for itemId in consumedItems:
			if (itemId in agent.inventory):
				if (consumedItems[itemId].quantity > agent.inventory[itemId].quantity):
					enoughItems = False
					agent.logger.error("Cannot produce {} {} \"{}\". Not enough {}".format(productionAmount, self.itemDict["unit"], self.itemId, itemId))
					break
			else:
				enoughItems = False
				break

		#Consume required labor
		if (enoughItems):
			for skillLevel in consumedLabor:
				agent.laborInventory[skillLevel] -= consumedLabor[skillLevel]

			agent.laborInventoryLock.release()  #release labor lock

		#Consume required items
		if (enoughItems):
			for itemId in consumedItems:
				consumedItemContainer = consumedItems[itemId]
				agent.inventory[itemId] -= consumedItemContainer
		else:
			#We do not have enough items
			agent.inventoryLock.release()
			return False

		agent.inventoryLock.release()

		#Generate items
		producedItem = ItemContainer(self.itemId, productionAmount)
		agent.receiveItem(producedItem)

		#Update production costs
		self.producedItems += productionAmount
		self.updateCosts()

		return producedItem


	def __str__(self):
		funcString = "ProductionFunction(itemId={}, fixedLandCosts={}, fixedItemCosts={}, fixedLaborCosts={}, fixedTimeCost={}, variableItemCosts={}, variableLaborCosts={})".format(
			self.itemId, self.fixedLandCosts, self.fixedItemCosts, self.fixedLaborCosts, self.fixedTimeCost, self.variableItemCosts, self.variableLaborCosts)
		return funcString


#######################
# Economic Agent
#######################
class NutritionTracker:
	'''
	Keeps track of an agent's nutritional levels, as well as food consumption
	'''
	def __init__(self, agent):
		self.agent = agent
		self.logger = agent.logger
		self.nutritionalDict = agent.nutritionalDict

		#Daily nutritional targets
		self.targetCalories = 2000
		self.targetCarbs = 250
		self.targetProtein = 110
		self.targetFat = 65
		self.targetWater = 3

		#Keep track of current nutrition
		self.currentCalories = self.targetCalories
		self.currentCarbs = self.targetCarbs
		self.currentProtein = self.targetProtein
		self.currentFat = self.targetFat
		self.currentWater = self.targetWater

		#Keep a moving exponential average of agent nutrition
		self.alpha = 0.2
		self.avgCalories = self.targetCalories
		self.avgCarbs = self.targetCarbs
		self.avgProtein = self.targetProtein
		self.avgFat = self.targetFat
		self.avgWater = self.targetWater

		#Keep track of previous food intake
		self.consumptionAvg = {}
		self.stepConsumption = {}

	def advanceStep(self):
		self.logger.info("Current nutrition levels = ({} calories, {} carbs(g), {} protein(g), {} fat(g), {} water(L))".format(self.currentCalories, self.currentCarbs, self.currentProtein, self.currentFat, self.currentWater))
		self.logger.info("Average nutrition levels = ({} calories, {} carbs(g), {} protein(g), {} fat(g), {} water(L))".format(self.avgCalories, self.avgCarbs, self.avgProtein, self.avgFat, self.avgWater))

		#Update moving exponential averages for nutrition
		self.avgCalories = ((1-self.alpha)*self.avgCalories) + (self.alpha*self.currentCalories)
		self.avgCarbs = ((1-self.alpha)*self.avgCarbs) + (self.alpha*self.currentCarbs)
		self.avgProtein = ((1-self.alpha)*self.avgProtein) + (self.alpha*self.currentProtein)
		self.avgFat = ((1-self.alpha)*self.avgFat) + (self.alpha*self.currentFat)
		self.avgWater = ((1-self.alpha)*self.avgWater) + (self.alpha*self.currentWater)

		#Reset current nutrition
		self.currentCalories = 0
		self.currentCarbs = 0
		self.currentProtein = 0
		self.currentFat = 0
		self.currentWater = 0

		#Add step consumption to moving exponential average
		alpha = 0.1
		for foodId in self.stepConsumption:
			if (foodId in self.consumptionAvg):
				self.consumptionAvg[foodId] = ((1-alpha)*self.consumptionAvg[foodId]) + (alpha*self.stepConsumption[foodId])
			else:
				self.consumptionAvg[foodId] = self.stepConsumption[foodId]

		for foodId in self.consumptionAvg:
			if not (foodId in self.stepConsumption):
				self.consumptionAvg[foodId] = ((1-alpha)*self.consumptionAvg[foodId])

		#Reset step consumption
		self.stepConsumption = {}

	def consumeFood(self, foodId, quantity):
		nutritionFacts = self.nutritionalDict[foodId]

		#Increment current nutrition
		self.currentCalories += quantity * nutritionFacts["kcalories"]
		self.currentCarbs += quantity * nutritionFacts["carbohydrates(g)"]
		self.currentProtein += quantity * nutritionFacts["protein(g)"]
		self.currentFat += quantity * nutritionFacts["fat(g)"]
		self.currentWater += quantity * nutritionFacts["water(L)"]

		#Add this to our consumption for this step
		if not (foodId in self.stepConsumption):
			self.stepConsumption[foodId] = 0
		self.stepConsumption[foodId] += quantity

		#Add this to our consumption average
		if not (foodId in self.consumptionAvg):
			self.consumptionAvg[foodId] = quantity

	def getAutoMeal(self):
		'''
		Automatically calculates a meal plan for this step based on agent preference and nutrition.
		Will attempt to maximize agent net agent utility for the meal.

		Returns a dictionary
		'''
		#Get dictionary of average food prices
		foodUnitPrices = {}
		for foodId in self.nutritionalDict:
			#Get average market price of this food item
			sampleSize = 5
			itemContainer = ItemContainer(foodId, 1)
			sampledListings = self.agent.sampleItemListings(itemContainer, sampleSize=sampleSize)
			sampledPrices = SortedList()
			sampleSize = len(sampledListings)
			if (sampleSize > 0):
				for listing in sampledListings:
					sampledPrices.add(listing.unitPrice)
				medianUnitPrice = sampledPrices[int(sampleSize/2)]

				foodUnitPrices[foodId] = medianUnitPrice

		#Calculate current and historical nutritional defecits
		currentDeficit = np.array([self.targetCalories-self.currentCalories, self.targetCarbs-self.currentCarbs, self.targetProtein-self.currentProtein, self.targetFat-self.currentFat])
		historicalDeficitRatios = np.array([
			((self.targetCalories-self.avgCalories)/self.targetCalories)+1, 
			((self.targetCarbs-self.avgCarbs)/self.targetCarbs)+1, 
			((self.targetProtein-self.avgProtein)/self.targetProtein)+1, 
			((self.targetFat-self.avgFat)/self.targetFat)+1])

		#Get dictionary of food marginal utility
		foodMarginalUtil = {}
		for foodId in self.nutritionalDict:
			marginalUtility = self.agent.getMarginalUtility(foodId)
			foodMarginalUtil[foodId] = marginalUtility * pow((self.targetCalories/self.avgCalories), 3)  #Sale the utility of food with hunger level

		#Iteratively approach meal plan that closely meets deficits while maximizing net utility
		mealPlan = {}
		iterationSteps = 10
		planNutritionVec = np.array([0, 0, 0, 0])
		for i in range(iterationSteps):
			foodReqAverages = {}
			foodNetUtils = {}
			for foodId in self.nutritionalDict:
				#Skip unavailable food
				if not (foodId in foodUnitPrices):
					continue

				#Skip water
				if (foodId == "water"):
					continue

				# #If current price is more than marginalUtility, exclude this food type
				# avgUnitPrice = foodUnitPrices[foodId]
				# marginalUtility = foodMarginalUtil[foodId]
				# if (avgUnitPrice > marginalUtility):
				# 	continue

				#Calculate roughly how much of this food we need to meed our nutritional deficit
				foodVec = self.nutritionalDict[foodId]["vector"]
				reqVec = np.divide(currentDeficit, foodVec)
				reqAdjusted = np.multiply(reqVec, historicalDeficitRatios)
				reqAverage = np.amin(reqAdjusted)
				
				foodReqAverages[foodId] = reqAverage

				#Get net utility of this food
				unitPrice = foodUnitPrices[foodId]
				netUtil = marginalUtility-unitPrice
				if (netUtil <= 0):
					netUtil = (marginalUtility/unitPrice)
				foodNetUtils[foodId] = netUtil

			#Scale required amounts by net utility distribution
			totalNetUtil = sum(foodNetUtils.values())
			scaledQuantities = {}
			for foodId in foodReqAverages:
				scaledQuantities[foodId] = (foodReqAverages[foodId] * (foodNetUtils[foodId] / totalNetUtil)) / ((i/4)+1)

			#Add amounts to meal plan
			for foodId in scaledQuantities:
				if not (foodId in mealPlan):
					mealPlan[foodId] = 0
				mealPlan[foodId] += scaledQuantities[foodId]

			#Get nutrition of current meal plan
			planNutritionVec =  np.array([0, 0, 0, 0])
			for foodId in mealPlan:
				foodVec = self.nutritionalDict[foodId]["vector"]
				quantity = mealPlan[foodId]
				if (quantity > 0):
					nutritionVec = np.multiply(foodVec, quantity)
					planNutritionVec = np.add(planNutritionVec, nutritionVec)

			#Update current deficit
			currentDeficit = np.array([self.targetCalories-planNutritionVec[0], self.targetCarbs-planNutritionVec[1], self.targetProtein-planNutritionVec[2], self.targetFat-planNutritionVec[3]])


		#Remove all negative quantities from meal plan
		foodList = list(mealPlan.keys())
		for foodId in foodList:
			quantity = mealPlan[foodId]
			if (quantity <= 0):
				del mealPlan[foodId]

		#Recalculate plan nutrition
		planNutritionVec =  np.array([0, 0, 0, 0])
		for foodId in mealPlan:
			foodVec = self.nutritionalDict[foodId]["vector"]
			quantity = mealPlan[foodId]
			nutritionVec = np.multiply(foodVec, quantity)
			planNutritionVec = np.add(planNutritionVec, nutritionVec)

		#Scale meal plan by calories
		#self.logger.debug("getAutoMeal() nutrition vector = {}".format(planNutritionVec))
		quantityPercision = g_ItemQuantityPercision
		totalCost = 0
		if (planNutritionVec[0] > 0):
			calorieScale = self.targetCalories/planNutritionVec[0]
			#self.logger.debug("getAutoMeal() calorie scale = {}".format(calorieScale))
			for foodId in mealPlan:
				quantity = mealPlan[foodId]*calorieScale
				mealPlan[foodId] = utils.truncateFloat(quantity, quantityPercision)
				totalCost += foodUnitPrices[foodId]*quantity

		#Make sure we have enough money for this meal plan
		currencyBalance = self.agent.currencyBalance
		if (currencyBalance < totalCost):
			#We don't have enough money for this meal. Scale down the meal
			povertyScale = currencyBalance / totalCost
			self.logger.debug("getAutoMeal() Don't have enough money to eat a full meal. Scaling down to meal by {}".format(povertyScale))
			for foodId in mealPlan:
				quantity = mealPlan[foodId]*povertyScale
				mealPlan[foodId] = quantity

		#Calculate water shortage
		netWater = 0
		for foodId in mealPlan:
			quantity = mealPlan[foodId]
			netWater += quantity*self.nutritionalDict[foodId]["water(L)"]

		waterDeficit = self.targetWater - netWater
		if (waterDeficit > 0):
			if ("water" in foodUnitPrices):
				mealPlan["water"] = waterDeficit

		return mealPlan


	def getQuantityConsumed(self, agent, foodId):
		# if (foodId in self.consumptionTotal):
		# 	if (agent.stepNum < (self.historyWindow-1)):
		# 		quantity = self.consumptionTotal[foodId]
		# 		extrapolatedQuantity = quantity * (self.historyWindow/(agent.stepNum+1))
		# 		return extrapolatedQuantity
		# 	else:
		# 		return self.consumptionTotal[foodId]

		if (foodId in self.consumptionAvg):
				return self.consumptionAvg[foodId]

		return 0


class LandAllocationQueue:
	'''
	Keeps track of land that is currently being allocated
	'''
	def __init__(self, agent):
		self.itemDict = agent.itemDict
		self.queue = []
		self.agent = agent
		self.logger = agent.logger

	def startAllocation(self, allocationType, hectares):
		'''
		Returns True if successful, False if not
		'''
		landAllocated = False

		if not (allocationType in self.itemDict):
			self.logger.error("Cannot allocate land. {} missing from item dictionary".format(allocationType))
			return False

		acquired_landHoldingsLock = self.agent.landHoldingsLock.acquire(timeout=self.agent.lockTimeout)
		if (acquired_landHoldingsLock):
			if (hectares <= self.agent.landHoldings["UNALLOCATED"]):
				ticksNeeded = 0
				try:
					ticksNeeded = int(self.itemDict[allocationType]["ProductionInputs"]["FixedCosts"]["FixedLandCosts"]["AllocationTime"])
				except:
					self.logger.debug("\"AllocationTime\" missing from itemDict for \"{}\". Using an allocation time of 0".format(allocationType))

				allocationEntry = {"allocationType": allocationType, "hectares": hectares, "ticksNeeded": ticksNeeded}
				self.queue.append(allocationEntry)
				self.logger.debug("{} added t0 LandAllocationQueue".format(allocationEntry))

				self.agent.landHoldings["ALLOCATING"] += hectares
				self.agent.landHoldings["UNALLOCATED"] -= hectares

				landAllocated = True

			else:
				self.logger.error("LandAllocationQueue.startAllocation({}, {}) Not enough land in landHoldings {}".format(allocationType, hectares, self.agent.landHoldings))
				landAllocated = False

			self.agent.landHoldingsLock.release()
		else:
			self.logger.error("LandAllocationQueue.startAllocation({}, {}) Lock landHoldingsLock acquisition timout".format(allocationType, hectares))
			landAllocated = False

		return landAllocated

	def useTimeTicks(self, ticks):
		'''
		Will decrement the waiting time for each allocation entry.
		When an entry is done, it will be removed from the queue and allocated in the agent's land holdings
		'''
		newQueue = []

		while (len(self.queue) > 0):
			allocationEntry = self.queue.pop(0)
			allocationEntry["ticksNeeded"] -= ticks

			if (allocationEntry["ticksNeeded"] <= 0):
				#This land is ready to be fully allocated
				acquired_landHoldingsLock = self.agent.landHoldingsLock.acquire(timeout=self.agent.lockTimeout)
				if (acquired_landHoldingsLock):
					self.logger.debug("{} has finished allocating".format(allocationEntry))

					hectares = allocationEntry["hectares"]
					self.agent.landHoldings["ALLOCATING"] -= hectares

					allocationType = allocationEntry["allocationType"]
					if not (allocationType in self.agent.landHoldings):
						self.agent.landHoldings[allocationType] = 0
					self.agent.landHoldings[allocationType] += hectares

					self.agent.landHoldingsLock.release()
				else:
					self.logger.error("LandAllocationQueue.useTimeTicks({}) Lock landHoldingsLock acquisition timout".format(ticks))
			else:
				#This land is not yet ready to be fully allocated
				newQueue.append(allocationEntry)

		self.queue = newQueue


class AgentInfo:
	def __init__(self, agentId, agentType):
		self.agentId = agentId
		self.agentType = agentType

	def __str__(self):
		return "AgentInfo(ID={}, Type={})".format(self.agentId, self.agentType)


def getAgentController(agent, settings={}, logFile=True, fileLevel="INFO", outputDir="OUTPUT"):
	'''
	Instantiates an agent controller, dependant on the agentType
	'''
	agentInfo = agent.info

	#Test controllers
	if (agentInfo.agentType == "PushoverController"):
		return PushoverController(agent, settings=settings, logFile=logFile, fileLevel=fileLevel, outputDir=outputDir)
	if (agentInfo.agentType == "TestSnooper"):
		return TestSnooper(agent, settings=settings, logFile=logFile, fileLevel=fileLevel, outputDir=outputDir)
	if (agentInfo.agentType == "TestSeller"):
		return TestSeller(agent, settings=settings, logFile=logFile, fileLevel=fileLevel, outputDir=outputDir)
	if (agentInfo.agentType == "TestBuyer"):
		return TestBuyer(agent, settings=settings, logFile=logFile, fileLevel=fileLevel, outputDir=outputDir)
	if (agentInfo.agentType == "TestEmployer"):
		return TestEmployer(agent, settings=settings, logFile=logFile, fileLevel=fileLevel, outputDir=outputDir)
	if (agentInfo.agentType == "TestWorker"):
		return TestWorker(agent, settings=settings, logFile=logFile, fileLevel=fileLevel, outputDir=outputDir)
	if (agentInfo.agentType == "TestLandSeller"):
		return TestLandSeller(agent, settings=settings, logFile=logFile, fileLevel=fileLevel, outputDir=outputDir)
	if (agentInfo.agentType == "TestLandBuyer"):
		return TestLandBuyer(agent, settings=settings, logFile=logFile, fileLevel=fileLevel, outputDir=outputDir)
	if (agentInfo.agentType == "TestEater"):
		return TestEater(agent, settings=settings, logFile=logFile, fileLevel=fileLevel, outputDir=outputDir)
	if (agentInfo.agentType == "TestSpawner"):
		return TestSpawner(agent, settings=settings, logFile=logFile, fileLevel=fileLevel, outputDir=outputDir)
	if (agentInfo.agentType == "TestEmployerCompetetive"):
		return TestEmployerCompetetive(agent, settings=settings, logFile=logFile, fileLevel=fileLevel, outputDir=outputDir)
	if (agentInfo.agentType == "TestFarmWorker"):
		return TestFarmWorker(agent, settings=settings, logFile=logFile, fileLevel=fileLevel, outputDir=outputDir)
	if (agentInfo.agentType == "TestFarmWorkerV2"):
		return TestFarmWorkerV2(agent, settings=settings, logFile=logFile, fileLevel=fileLevel, outputDir=outputDir)
	if (agentInfo.agentType == "TestFarmCompetetive"):
		return TestFarmCompetetive(agent, settings=settings, logFile=logFile, fileLevel=fileLevel, outputDir=outputDir)
	if (agentInfo.agentType == "TestFarmCompetetiveV2"):
		return TestFarmCompetetiveV2(agent, settings=settings, logFile=logFile, fileLevel=fileLevel, outputDir=outputDir)
	if (agentInfo.agentType == "TestFarmCompetetiveV3"):
		return TestFarmCompetetiveV3(agent, settings=settings, logFile=logFile, fileLevel=fileLevel, outputDir=outputDir)

	#Unhandled agent type. Return default controller
	return None


class AgentSeed:
	'''
	Because thread locks cannot be pickled, you can't pass Agent instances to other processes.

	So the AgentSeed class is a pickle-safe info container that can be passed to child processes.
	The process can then call AgentSeed.spawnAgent() to instantiate an Agent obj.
	'''
	def __init__(self, agentId, agentType=None, ticksPerStep=24, settings={}, simManagerId=None, itemDict=None, allAgentDict=None, logFile=True, fileLevel="INFO", outputDir="OUTPUT", disableNetworkLink=False):
		self.agentInfo = AgentInfo(agentId, agentType)
		self.ticksPerStep = ticksPerStep
		self.settings = settings
		self.simManagerId = simManagerId
		self.itemDict = itemDict
		self.allAgentDict = allAgentDict
		self.logFile = logFile
		self.fileLevel = fileLevel
		self.outputDir = outputDir

		if (disableNetworkLink):
			self.networkLink = None
			self.agentLink = None
		else:
			networkPipeRecv, agentPipeSend = multiprocessing.Pipe()
			agentPipeRecv, networkPipeSend = multiprocessing.Pipe()

			self.networkLink = Link(sendPipe=networkPipeSend, recvPipe=networkPipeRecv)
			self.agentLink = Link(sendPipe=agentPipeSend, recvPipe=agentPipeRecv)

	def spawnAgent(self):
		return Agent(self.agentInfo, simManagerId=self.simManagerId, ticksPerStep=self.ticksPerStep, settings=self.settings, itemDict=self.itemDict, allAgentDict=self.allAgentDict, networkLink=self.agentLink, logFile=self.logFile, fileLevel=self.fileLevel, outputDir=self.outputDir)

	def __str__(self):
		return "AgentSeed({})".format(self.agentInfo)


class AgentCheckpoint:
	'''
	This class stores information on current agent state for saving to and loading from simulation checkpoints.
	All class variables must be pickle-safe (that means no thread locks).
	'''
	def __init__(self, agentObj):
		'''
		Stores the class variables of agentObj in this checkpoint obj
		'''
		self.info = agentObj.info
		self.agentId = agentObj.agentId
		self.agentType = agentObj.agentType
		
		self.simManagerId = agentObj.simManagerId
		self.outputDir = agentObj.outputDir

		#Keep track of other agents
		self.allAgentDict = agentObj.allAgentDict

		#Keep track of agent assets
		self.currencyBalance = agentObj.currencyBalance
		self.inventory = agentObj.inventory
		self.debtBalance = agentObj.debtBalance
		self.landHoldings = agentObj.landHoldings
		self.landAllocationQueue__quueu = agentObj.landAllocationQueue.queue

		#Keep track of labor stuff
		self.skillLevel = agentObj.skillLevel

		self.laborContracts = agentObj.laborContracts
		self.laborContractsTotal = agentObj.laborContractsTotal
		self.laborInventory = agentObj.laborInventory
		self.nextLaborInventory = agentObj.nextLaborInventory
		self.commitedTicks = agentObj.commitedTicks
		self.commitedTicks_nextStep = agentObj.commitedTicks_nextStep

		#Keep track of time ticks
		self.timeTicks = agentObj.timeTicks
		self.tickBlockFlag = agentObj.tickBlockFlag
		self.stepNum = agentObj.stepNum
		self.ticksPerStep = agentObj.ticksPerStep
		
		#Instantiate agent preferences (utility functions)
		self.nutritionalDict = agentObj.nutritionalDict
		self.utilityFunctions = agentObj.utilityFunctions
		self.eating = agentObj.eating
		self.autoEatFlag = agentObj.autoEatFlag

		#Keep track of agent nutrition
		self.enableNutrition = agentObj.enableNutrition
		self.nutritionTracker__consumptionAvg = None
		self.nutritionTracker__stepConsumption = None
		if (agentObj.nutritionTracker):
			self.nutritionTracker__consumptionAvg = agentObj.nutritionTracker.consumptionAvg
			self.nutritionTracker__stepConsumption = agentObj.nutritionTracker.stepConsumption

		#####
		# Keep track of accounting stats
		#####
		#Labor income
		self.laborIncomeTracking = agentObj.laborIncomeTracking
		self.totalLaborIncome = agentObj.totalLaborIncome
		self.prevTotalLaborIncome = agentObj.prevTotalLaborIncome
		self.avgLaborIncome = agentObj.avgLaborIncome
		self.stepLaborIncome = agentObj.stepLaborIncome
		self.prevStepLaborIncome = agentObj.prevStepLaborIncome
		#Labor expenses
		self.laborExpenseTracking = agentObj.laborExpenseTracking
		self.totalLaborExpense = agentObj.totalLandExpenses
		self.prevTotalLaborExpense = agentObj.prevTotalLaborExpense
		self.avgLaborExpense = agentObj.avgLaborExpense
		self.stepLaborExpense = agentObj.stepLaborExpense
		self.prevStepLaborExpense = agentObj.prevStepLaborExpense
		#Trading revenue
		self.tradeRevenueTracking = agentObj.tradeRevenueTracking
		self.totalTradeRevenue = agentObj.totalTradeRevenue
		self.prevTotalTradeRevenue = agentObj.prevTotalTradeRevenue
		self.avgTradeRevenue = agentObj.avgTradeRevenue
		self.stepTradeRevenue = agentObj.stepTradeRevenue
		self.prevStepTradeRevenue = agentObj.prevStepTradeRevenue
		#Item expenses
		self.itemExpensesTracking = agentObj.itemExpensesTracking
		self.totalItemExpenses = agentObj.totalItemExpenses
		self.prevTotalItemExpenses = agentObj.prevTotalItemExpenses
		self.avgItemExpenses = agentObj.avgItemExpenses
		self.stepItemExpenses = agentObj.stepItemExpenses
		self.prevStepItemExpenses = agentObj.prevStepItemExpenses
		#Land revenue
		self.landRevenueTracking = agentObj.landRevenueTracking
		self.totalLandRevenue = agentObj.totalLandRevenue
		self.prevTotalLandRevenue = agentObj.prevTotalLandRevenue
		#Land expenses
		self.landExpensesTracking = agentObj.landExpensesTracking
		self.totalLandExpenses = agentObj.totalLandExpenses
		self.prevTotalLandExpenses = agentObj.prevTotalLandExpenses
		#Currency inflows
		self.currencyInflowTracking = agentObj.currencyInflowTracking
		self.totalCurrencyInflow = agentObj.totalCurrencyInflow
		self.prevTotalCurrencyInflow = agentObj.prevTotalCurrencyInflow
		self.avgCurrencyInflow = agentObj.avgCurrencyInflow
		self.stepCurrencyInflow = agentObj.stepCurrencyInflow
		self.prevStepCurrencyInflow = agentObj.prevStepCurrencyInflow
		#Currency outflows
		self.currencyOutflowTracking = agentObj.currencyOutflowTracking
		self.totalCurrencyOutflow = agentObj.totalCurrencyOutflow
		self.prevTotalCurrencyOutflow = agentObj.prevTotalCurrencyOutflow
		self.avgCurrencyOutflow = agentObj.avgCurrencyOutflow
		self.stepCurrencyOutflow = agentObj.stepCurrencyOutflow
		self.prevStepCurrencyOutflow = agentObj.prevStepCurrencyOutflow
		#Production functions
		self.productionFunctions = agentObj.productionFunctions


	def loadCheckpoint(self, agentObj):
		'''
		Overwrites the class variables of agentObj with the values stored in this checkpoint obj
		'''
		agentObj.info = self.info
		agentObj.agentId = self.agentId
		agentObj.agentType = self.agentType
		
		agentObj.simManagerId = self.simManagerId
		agentObj.outputDir = self.outputDir

		#Keep track of other agents
		agentObj.allAgentDict = self.allAgentDict

		#Keep track of agent assets
		agentObj.currencyBalance = self.currencyBalance
		agentObj.inventory = self.inventory
		agentObj.debtBalance = self.debtBalance
		agentObj.landHoldings = self.landHoldings

		agentLandAllocationQueue = LandAllocationQueue(agentObj)
		agentLandAllocationQueue.queue = self.landAllocationQueue__quueu
		agentObj.landAllocationQueue = agentLandAllocationQueue

		#Keep track of labor stuff
		agentObj.skillLevel = self.skillLevel

		shiftedLaborContracts = {}  #Shift labor contract start and end times by checkpoint step time
		for endStep in self.laborContracts:
			shiftedEndStep = endStep - self.stepNum
			shiftedLaborContracts[shiftedEndStep] = {}
			for contractHash in self.laborContracts[endStep]:
				laborContract = self.laborContracts[endStep][contractHash]
				laborContract.startStep = laborContract.startStep - self.stepNum
				laborContract.endStep = laborContract.endStep - self.stepNum

				shiftedLaborContracts[shiftedEndStep][contractHash] = laborContract

		agentObj.laborContracts = shiftedLaborContracts

		agentObj.laborContractsTotal = self.laborContractsTotal
		agentObj.laborInventory = self.laborInventory
		agentObj.nextLaborInventory = self.nextLaborInventory
		agentObj.commitedTicks = self.commitedTicks
		agentObj.commitedTicks_nextStep = self.commitedTicks_nextStep

		#Keep track of time ticks
		agentObj.timeTicks = self.timeTicks
		agentObj.tickBlockFlag = self.tickBlockFlag
		agentObj.ticksPerStep = self.ticksPerStep
		
		#Instantiate agent preferences (utility functions)
		agentObj.nutritionalDict = self.nutritionalDict
		agentObj.utilityFunctions = self.utilityFunctions
		agentObj.eating = self.eating
		agentObj.autoEatFlag = self.autoEatFlag

		#Keep track of agent nutrition
		agentObj.enableNutrition = self.enableNutrition
		if (self.nutritionTracker__consumptionAvg):
			agentNutritionTracker = NutritionTracker(agentObj)
			agentNutritionTracker.consumptionAvg = self.nutritionTracker__consumptionAvg
			agentNutritionTracker.stepConsumption = self.nutritionTracker__stepConsumption
			agentObj.nutritionTracker = agentNutritionTracker

		#####
		# Keep track of accounting stats
		#####
		#Labor income
		agentObj.laborIncomeTracking = self.laborIncomeTracking
		agentObj.totalLaborIncome = self.totalLaborIncome
		agentObj.prevTotalLaborIncome = self.prevTotalLaborIncome
		agentObj.avgLaborIncome = self.avgLaborIncome
		agentObj.stepLaborIncome = self.stepLaborIncome
		agentObj.prevStepLaborIncome = self.prevStepLaborIncome
		#Labor expenses
		agentObj.laborExpenseTracking = self.laborExpenseTracking
		agentObj.totalLaborExpense = self.totalLandExpenses
		agentObj.prevTotalLaborExpense = self.prevTotalLaborExpense
		agentObj.avgLaborExpense = self.avgLaborExpense
		agentObj.stepLaborExpense = self.stepLaborExpense
		agentObj.prevStepLaborExpense = self.prevStepLaborExpense
		#Trading revenue
		agentObj.tradeRevenueTracking = self.tradeRevenueTracking
		agentObj.totalTradeRevenue = self.totalTradeRevenue
		agentObj.prevTotalTradeRevenue = self.prevTotalTradeRevenue
		agentObj.avgTradeRevenue = self.avgTradeRevenue
		agentObj.stepTradeRevenue = self.stepTradeRevenue
		agentObj.prevStepTradeRevenue = self.prevStepTradeRevenue
		#Item expenses
		agentObj.itemExpensesTracking = self.itemExpensesTracking
		agentObj.totalItemExpenses = self.totalItemExpenses
		agentObj.prevTotalItemExpenses = self.prevTotalItemExpenses
		agentObj.avgItemExpenses = self.avgItemExpenses
		agentObj.stepItemExpenses = self.stepItemExpenses
		agentObj.prevStepItemExpenses = self.prevStepItemExpenses
		#Land revenue
		agentObj.landRevenueTracking = self.landRevenueTracking
		agentObj.totalLandRevenue = self.totalLandRevenue
		agentObj.prevTotalLandRevenue = self.prevTotalLandRevenue
		#Land expenses
		agentObj.landExpensesTracking = self.landExpensesTracking
		agentObj.totalLandExpenses = self.totalLandExpenses
		agentObj.prevTotalLandExpenses = self.prevTotalLandExpenses
		#Currency inflows
		agentObj.currencyInflowTracking = self.currencyInflowTracking
		agentObj.totalCurrencyInflow = self.totalCurrencyInflow
		agentObj.prevTotalCurrencyInflow = self.prevTotalCurrencyInflow
		agentObj.avgCurrencyInflow = self.avgCurrencyInflow
		agentObj.stepCurrencyInflow = self.stepCurrencyInflow
		agentObj.prevStepCurrencyInflow = self.prevStepCurrencyInflow
		#Currency outflows
		agentObj.currencyOutflowTracking = self.currencyOutflowTracking
		agentObj.totalCurrencyOutflow = self.totalCurrencyOutflow
		agentObj.prevTotalCurrencyOutflow = self.prevTotalCurrencyOutflow
		agentObj.avgCurrencyOutflow = self.avgCurrencyOutflow
		agentObj.stepCurrencyOutflow = self.stepCurrencyOutflow
		agentObj.prevStepCurrencyOutflow = self.prevStepCurrencyOutflow
		#Production functions
		agentObj.productionFunctions = self.productionFunctions


	def __str__(self):
		return "AgentCheckpoint({})".format(self.info)



class Agent:
	'''
	The Agent class is a generic class used by all agents running in a simulation.

	The behavior of any given agent instance is determined by it's controller, which handles all decision making.
	The Agent class is instead responsible for the controller's interface to the rest of the simulation.

	The Agent class handles:
		-item transfers
		-item consumption
		-item production
		-currency transfers
		-trade execution
		-currency balance
		-item inventory
		-land holdings
		-land transfers
		-ConnectionNetwork interactions
		-item utility calculations
		-marketplace updates and polling

	'''
	def __init__(self, agentInfo, simManagerId=None, ticksPerStep=24, settings={}, itemDict=None, allAgentDict=None, networkLink=None, logFile=True, fileLevel="INFO", outputDir="OUTPUT", controller=None):
		self.info = agentInfo
		self.agentId = agentInfo.agentId
		self.agentType = agentInfo.agentType
		
		self.simManagerId = simManagerId
		self.outputDir = outputDir

		self.logger = utils.getLogger("{}:{}".format(__name__, self.agentId), console="ERROR", logFile=logFile, outputdir=os.path.join(outputDir, "LOGS", "Agent_Logs"), fileLevel=fileLevel)
		self.logger.info("{} instantiated".format(self.info))

		self.lockTimeout = 5
		self.responsePollTime = 0.0001
		self.agentKillFlag = False

		self.itemDict = itemDict

		#Pipe connections to the connection network
		self.networkLink = networkLink
		self.networkSendLock = threading.Lock()
		self.responseBuffer = {}
		self.responseBufferLock = threading.Lock()
		self.outstandingTrades = {}
		self.outstandingTradesLock = threading.Lock()

		#ACK requirement settings
		self.needCurrencyTransferAck = False
		self.needItemTransferAck = False
		self.needLandTransferAck = False
		self.needLaborCancellationAck = False
		self.needTickBlockAck = False

		#Keep track of other agents
		self.allAgentDict = allAgentDict

		#Keep track of agent assets
		self.currencyBalance = 0  #(int) cents  #This prevents accounting errors due to float arithmetic (plus it's faster)
		self.currencyBalanceLock = threading.Lock()
		self.inventory = {}
		self.inventoryLock = threading.Lock()
		self.debtBalance = 0
		self.debtBalanceLock = threading.Lock()
		self.tradeRequestLock = threading.Lock()
		self.landHoldings = {"UNALLOCATED": 0, "ALLOCATING": 0}
		self.landHoldingsLock = threading.Lock()
		self.landTradeRequestLock = threading.Lock()
		self.landAllocationQueue = LandAllocationQueue(self)

		#Keep track of labor stuff
		alpha = 2  #Default alpha
		beta = 5   #Default beta
		if ("skillDistribution" in settings):
			if ("alpha" in settings["skillDistribution"]):
				alpha = settings["skillDistribution"]["alpha"]

			if ("beta" in settings["skillDistribution"]):
				beta = settings["skillDistribution"]["beta"]

		self.skillLevel = random.betavariate(alpha, beta)

		self.laborContracts = {}
		self.laborContractsTotal = 0
		self.laborContractsLock = threading.Lock()
		self.fullfilledContracts = False
		self.laborInventory = {}  #Keep track of all the labor available to a firm for this step
		self.laborInventoryLock = threading.Lock()
		self.nextLaborInventory = {}  #Keep track of all the labor supplied to a firm for this step
		self.nextLaborInventoryLock = threading.Lock()
		self.commitedTicks = 0
		self.commitedTicksLock = threading.Lock()
		self.commitedTicks_nextStep = 0
		self.commitedTicks_nextStepLock = threading.Lock()

		#Keep track of time ticks
		self.timeTicks = 0
		self.timeTickLock = threading.Lock()
		self.tickBlockFlag = False
		self.tickBlockFlag_Lock = threading.Lock()
		self.stepNum = -1
		self.ticksPerStep = ticksPerStep
		
		#Instantiate agent preferences (utility functions)
		self.nutritionalDict = {}
		self.utilityFunctions = {}
		self.eating = False
		self.autoEatFlag = False
		if (itemDict):
			for itemName in itemDict:
				itemFunctionParams = itemDict[itemName]["UtilityFunctions"]
				self.utilityFunctions[itemName] = UtilityFunction(itemFunctionParams["BaseUtility"]["mean"], itemFunctionParams["BaseUtility"]["stdDev"], itemFunctionParams["DiminishingFactor"]["mean"], itemFunctionParams["DiminishingFactor"]["stdDev"])
				if ("NutritionalFacts" in itemDict[itemName]):
					nutrition = itemDict[itemName]["NutritionalFacts"]
					nutrition["vector"] = np.array([nutrition["kcalories"], nutrition["carbohydrates(g)"], nutrition["protein(g)"], nutrition["fat(g)"]])
					self.nutritionalDict[itemName] = nutrition

		#Keep track of agent nutrition
		self.enableNutrition = False
		self.nutritionTracker = None

		#####
		# Keep track of accounting stats
		#####
		self.accountingAlpha = 0.2
		#Labor income
		self.laborIncomeTracking = False
		self.totalLaborIncome = 0
		self.prevTotalLaborIncome = 0
		self.avgLaborIncome = 0
		self.stepLaborIncome = 0
		self.prevStepLaborIncome = 0
		self.laborIncomeLock = threading.Lock()
		#Labor expenses
		self.laborExpenseTracking = False
		self.totalLaborExpense = 0
		self.prevTotalLaborExpense = 0
		self.avgLaborExpense = 0
		self.stepLaborExpense = 0
		self.prevStepLaborExpense = 0
		self.laborExpenseLock = threading.Lock()
		#Trading revenue
		self.tradeRevenueTracking = False
		self.totalTradeRevenue = 0
		self.prevTotalTradeRevenue = 0
		self.avgTradeRevenue = 0
		self.stepTradeRevenue = 0
		self.prevStepTradeRevenue = 0
		self.tradeRevenueLock = threading.Lock()
		#Item expenses
		self.itemExpensesTracking = False
		self.totalItemExpenses = 0
		self.prevTotalItemExpenses = 0
		self.avgItemExpenses = 0
		self.stepItemExpenses = 0
		self.prevStepItemExpenses = 0
		self.itemExpensesLock = threading.Lock()
		#Land revenue
		self.landRevenueTracking = False
		self.totalLandRevenue = 0
		self.prevTotalLandRevenue = 0
		self.landRevenueLock = threading.Lock()
		#Land expenses
		self.landExpensesTracking = False
		self.totalLandExpenses = 0
		self.prevTotalLandExpenses = 0
		self.landExpensesLock = threading.Lock()
		#Currency inflows
		self.currencyInflowTracking = False
		self.totalCurrencyInflow = 0
		self.prevTotalCurrencyInflow = 0
		self.avgCurrencyInflow = 0
		self.stepCurrencyInflow = 0
		self.prevStepCurrencyInflow = 0
		self.currencyInflowLock = threading.Lock()
		#Currency outflows
		self.currencyOutflowTracking = False
		self.totalCurrencyOutflow = 0
		self.prevTotalCurrencyOutflow = 0
		self.avgCurrencyOutflow = 0
		self.stepCurrencyOutflow = 0
		self.prevStepCurrencyOutflow = 0
		self.currencyOutflowLock = threading.Lock()


		#Production functions
		self.productionFunctions = {}
		self.productionFunctionsLock = threading.Lock()

		#Instantiate AI agent controller
		if (controller):
			self.controller = controller
		else:	
			self.controller = getAgentController(self, settings=settings, logFile=logFile, fileLevel=fileLevel, outputDir=outputDir)
			if (not self.controller):
				self.logger.error("No controller was instantiated. \"{}\" is not a valid controller type".format(self.agentType))
		self.controllerStart = False

		#Keep track of spawned threads
		self.spawnedThreads = []

		#Launch network link monitor
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
			self.logger.debug("Monitoring networkLink {}".format(self.networkLink))
			incommingPacket = self.networkLink.recvPipe.recv()
			self.logger.info("INBOUND {}".format(incommingPacket))
			if ((incommingPacket.msgType == PACKET_TYPE.KILL_PIPE_AGENT) or (incommingPacket.msgType == PACKET_TYPE.KILL_ALL_BROADCAST)):
				#Kill the network pipe before exiting monitor
				killPacket = NetworkPacket(senderId=self.agentId, destinationId=self.agentId, msgType=PACKET_TYPE.KILL_PIPE_NETWORK)
				self.sendPacket(killPacket)
				self.logger.info("Killing networkLink {}".format(self.networkLink))
				self.agentKillFlag = True

				#Foward packet to controller
				if (self.controller):
					self.logger.debug("Fowarding msg to controller {}".format(incommingPacket))
					controllerThread =  threading.Thread(target=self.controller.receiveMsg, args=(incommingPacket, ))
					controllerThread.start()
					self.spawnedThreads.append(controllerThread)
				break

			#Handle incoming acks
			elif ((incommingPacket.msgType == PACKET_TYPE.CURRENCY_TRANSFER_ACK) or (incommingPacket.msgType == PACKET_TYPE.ITEM_TRANSFER_ACK) or (incommingPacket.msgType == PACKET_TYPE.LAND_TRANSFER_ACK) or	
				(incommingPacket.msgType == PACKET_TYPE.TRADE_REQ_ACK) or (incommingPacket.msgType == PACKET_TYPE.LAND_TRADE_REQ_ACK) or (incommingPacket.msgType == PACKET_TYPE.LABOR_APPLICATION_ACK) or (incommingPacket.msgType == PACKET_TYPE.LABOR_CONTRACT_CANCEL_ACK) or
				(incommingPacket.msgType == PACKET_TYPE.ITEM_MARKET_SAMPLE_ACK) or (incommingPacket.msgType == PACKET_TYPE.LABOR_MARKET_SAMPLE_ACK) or (incommingPacket.msgType == PACKET_TYPE.LAND_MARKET_SAMPLE_ACK) or 
				(incommingPacket.msgType == PACKET_TYPE.TICK_BLOCKED_ACK)):
				#Determine whether to handle this ack
				handleAck = True
				if (incommingPacket.msgType == PACKET_TYPE.CURRENCY_TRANSFER_ACK):
					handleAck = self.needCurrencyTransferAck
				elif (incommingPacket.msgType == PACKET_TYPE.ITEM_TRANSFER_ACK):
					handleAck = self.needItemTransferAck
				elif (incommingPacket.msgType == PACKET_TYPE.LAND_TRANSFER_ACK):
					handleAck = self.needLandTransferAck
				elif (incommingPacket.msgType == PACKET_TYPE.LABOR_CONTRACT_CANCEL_ACK):
					handleAck = self.needLaborCancellationAck
				elif (incommingPacket.msgType == PACKET_TYPE.TICK_BLOCKED_ACK):
					handleAck = self.needTickBlockAck
		
				if (handleAck):
					#Place incoming acks into the response buffer
					acquired_responseBufferLock = self.responseBufferLock.acquire(timeout=self.lockTimeout)  #<== acquire responseBufferLock
					if (acquired_responseBufferLock):
						self.responseBuffer[incommingPacket.transactionId] = incommingPacket
						self.responseBufferLock.release()  #<== release responseBufferLock
					else:
						self.logger.error("monitorNetworkLink() Lock \"responseBufferLock\" acquisition timeout")
						break

			#Handle errors
			elif (incommingPacket.msgType == PACKET_TYPE.ERROR) or (incommingPacket.msgType == PACKET_TYPE.ERROR_CONTROLLER_START):
				self.logger.error("{} {}".format(incommingPacket, incommingPacket.payload))

			#Handle controller messages
			elif ((incommingPacket.msgType == PACKET_TYPE.CONTROLLER_START) or (incommingPacket.msgType == PACKET_TYPE.CONTROLLER_START_BROADCAST)):
				if (self.controller):
					if (not self.controllerStart):
						self.controllerStart = True
						controllerThread =  threading.Thread(target=self.controller.controllerStart, args=(incommingPacket, ))
						controllerThread.start()
						self.spawnedThreads.append(controllerThread)
				else:
					warning = "Agent does not have controller to start"
					self.logger.warning(warning)
					responsePacket = NetworkPacket(senderId=self.agentId, destinationId=incommingPacket.senderId, msgType=PACKET_TYPE.ERROR_CONTROLLER_START, payload=warning)

			
			elif ((incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG) or (incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG_BROADCAST)):
				#Foward packet to controller
				if (self.controller):
					self.logger.debug("Fowarding msg to controller {}".format(incommingPacket))
					controllerThread =  threading.Thread(target=self.controller.receiveMsg, args=(incommingPacket, ))
					controllerThread.start()
					self.spawnedThreads.append(controllerThread)
				else:
					self.logger.error("Agent {} does not have a controller. Ignoring {}".format(self.agentId, incommingPacket))


			#Handle incoming payments
			elif (incommingPacket.msgType == PACKET_TYPE.CURRENCY_TRANSFER):
				amount = incommingPacket.payload["cents"]
				self.receiveCurrency(amount, incommingPacket)
				if (incommingPacket.transactionId in self.outstandingTrades):
					self.outstandingTradesLock.acquire()
					del self.outstandingTrades[incommingPacket.transactionId]
					self.outstandingTradesLock.release()

			#Handle incoming items
			elif (incommingPacket.msgType == PACKET_TYPE.ITEM_TRANSFER):
				itemPackage = incommingPacket.payload["item"]
				self.receiveItem(itemPackage, incommingPacket)
				if (incommingPacket.transactionId in self.outstandingTrades):
					self.outstandingTradesLock.acquire()
					del self.outstandingTrades[incommingPacket.transactionId]
					self.outstandingTradesLock.release()

			#Handle incoming land
			elif (incommingPacket.msgType == PACKET_TYPE.LAND_TRANSFER):
				allocation = incommingPacket.payload["allocation"]
				hectares = incommingPacket.payload["hectares"]
				self.receiveLand(allocation, hectares, incommingPacket)
				if (incommingPacket.transactionId in self.outstandingTrades):
					self.outstandingTradesLock.acquire()
					del self.outstandingTrades[incommingPacket.transactionId]
					self.outstandingTradesLock.release()

			#Handle incoming trade requests
			elif (incommingPacket.msgType == PACKET_TYPE.TRADE_REQ):
				tradeRequest = incommingPacket.payload
				tradeReqThread =  threading.Thread(target=self.receiveTradeRequest, args=(tradeRequest, incommingPacket.senderId))
				tradeReqThread.start()
				self.spawnedThreads.append(tradeReqThread)
				#self.receiveTradeRequest(tradeRequest, incommingPacket.senderId)

			#Handle incoming land trade requests
			elif (incommingPacket.msgType == PACKET_TYPE.LAND_TRADE_REQ):
				tradeRequest = incommingPacket.payload
				landTradeThread =  threading.Thread(target=self.receiveLandTradeRequest, args=(tradeRequest, incommingPacket.senderId))
				landTradeThread.start()
				self.spawnedThreads.append(landTradeThread)
				#self.receiveLandTradeRequest(tradeRequest, incommingPacket.senderId)

			#Handle incoming job applications
			elif (incommingPacket.msgType == PACKET_TYPE.LABOR_APPLICATION):
				applicationPayload = incommingPacket.payload
				laborAppThread =  threading.Thread(target=self.receiveJobApplication, args=(applicationPayload, incommingPacket.senderId))
				laborAppThread.start()
				self.spawnedThreads.append(laborAppThread)
				#self.receiveJobApplication(applicationPayload, incommingPacket.senderId)

			#Handle incoming labor
			elif (incommingPacket.msgType == PACKET_TYPE.LABOR_TIME_SEND):
				laborTicks = incommingPacket.payload["ticks"]
				skillLevel = incommingPacket.payload["skillLevel"]
				self.nextLaborInventoryLock.acquire()
				if not (skillLevel in self.nextLaborInventory):
					self.nextLaborInventory[skillLevel] = 0
				self.nextLaborInventory[skillLevel] += laborTicks
				self.logger.debug("nextLaborInventory[{}] += {}".format(skillLevel, laborTicks))
				self.nextLaborInventoryLock.release()

			#Handle incoming labor contract cancellations
			elif (incommingPacket.msgType == PACKET_TYPE.LABOR_CONTRACT_CANCEL):
				laborContract = incommingPacket.payload
				self.removeLaborContract(laborContract, incommingPacket)

			#Handle incoming information requests
			elif ((incommingPacket.msgType == PACKET_TYPE.INFO_REQ) or (incommingPacket.msgType == PACKET_TYPE.INFO_REQ_BROADCAST)):
				infoRequest = incommingPacket.payload
				#infoThread =  threading.Thread(target=self.handleInfoRequest, args=(infoRequest, ))
				#infoThread.start()
				self.handleInfoRequest(infoRequest)

			#Handle incoming save checkpoint commands
			elif ((incommingPacket.msgType == PACKET_TYPE.SAVE_CHECKPOINT) or (incommingPacket.msgType == PACKET_TYPE.SAVE_CHECKPOINT_BROADCAST)):
				#Save agent checkpoint
				self.saveCheckpoint()
				#Foward to controller
				if (self.controller):
					controllerThread =  threading.Thread(target=self.controller.receiveMsg, args=(incommingPacket, ))
					controllerThread.start()
				self.spawnedThreads.append(controllerThread)

			#Handle incoming load checkpoint commands
			elif ((incommingPacket.msgType == PACKET_TYPE.LOAD_CHECKPOINT) or (incommingPacket.msgType == PACKET_TYPE.LOAD_CHECKPOINT_BROADCAST)):
				#Load agent checkpoint
				filePath = incommingPacket.payload
				self.loadCheckpoint(filePath=filePath)
				#Foward to controller
				if (self.controller):
					controllerThread =  threading.Thread(target=self.controller.receiveMsg, args=(incommingPacket, ))
					controllerThread.start()
				self.spawnedThreads.append(controllerThread)

			#Hanle incoming tick grants
			elif ((incommingPacket.msgType == PACKET_TYPE.TICK_GRANT) or (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT_BROADCAST)):
				#Mark all previously spawned threads as elgible for garbage collection
				self.logger.debug("Joining spawned threads")
				for thread in self.spawnedThreads:
					thread.join()
				self.spawnedThreads.clear()

				#This is the start of a new step
				self.fullfilledContracts = False

				ticksGranted = incommingPacket.payload
				acquired_timeTickLock = self.timeTickLock.acquire(timeout=self.lockTimeout)  #<== timeTickLock acquire
				if (acquired_timeTickLock):
					self.timeTicks += ticksGranted
					self.timeTickLock.release()  #<== timeTickLock release
					self.stepNum += 1
					self.logger.info("### Step Number = {} ###".format(self.stepNum))

					acquired_tickBlockFlag_Lock = self.tickBlockFlag_Lock.acquire(timeout=self.lockTimeout)  #<== tickBlockFlag_Lock acquire
					if (acquired_tickBlockFlag_Lock):
						self.tickBlockFlag = False
						self.tickBlockFlag_Lock.release()  #<== tickBlockFlag_Lock release
					else:
						self.logger.critical("TICK_GRANT tickBlockFlag_Lock acquire timeout")

				else:
					self.logger.critical("TICK_GRANT timeTickLock acquire timeout")

				#Update accounting
				self.updateAcountingAverages()

				#Daily nutritional stuff
				if (self.enableNutrition):
					self.nutritionTracker.advanceStep()
					if (self.autoEatFlag):
						self.useTimeTicks(1)
						self.eating = True
						eatThread = threading.Thread(target=self.autoEat)
						eatThread.start()
						self.spawnedThreads.append(eatThread)

				#Update time tick commitments
				self.commitedTicks_nextStepLock.acquire()
				self.commitedTicksLock.acquire()
				self.commitedTicks = self.commitedTicks_nextStep
				self.commitedTicksLock.release()
				self.commitedTicks_nextStepLock.release()

				#Fulfill labor contracts
				contractThread = threading.Thread(target=self.fulfillAllLaborContracts)
				contractThread.start()
				self.spawnedThreads.append(contractThread)

				#Foward tick grant to controller
				if (self.controller):
					controllerGrantThread = threading.Thread(target=self.controller.receiveMsg, args=(incommingPacket, ))
					controllerGrantThread.start()
					self.spawnedThreads.append(controllerGrantThread)
				else:
					#We don't have a controller. Relinquish all time ticks
					self.relinquishTimeTicks()

			#Unhandled packet type
			else:
				self.logger.error("Received packet type {}. Ignoring packet {}".format(incommingPacket.msgType, incommingPacket))

		self.logger.info("Ending networkLink monitor".format(self.networkLink))


	def sendPacket(self, packet):
		if (self.agentKillFlag):
			return

		if (self.networkLink):
			self.logger.debug("Waiting for networkSendLock to send {}".format(packet))
			#acquired_networkSendLock = self.networkSendLock.acquire(timeout=self.lockTimeout)
			acquired_networkSendLock = self.networkSendLock.acquire()
			if (acquired_networkSendLock):
				self.logger.info("OUTBOUND {}".format(packet))
				self.networkLink.sendPipe.send(packet)
				self.networkSendLock.release()
			else:
				self.logger.error("{}.sendPacket() Lock networkSendLock acquire timeout | {}".format(self.agentId, packet))
		else:
			self.logger.error("This agent is missing a networkLink. Cannot send packet {}".format(packet))


	#########################
	# Accounting Methods
	#########################
	def updateAcountingAverages(self):
		#Labor income
		if (self.laborIncomeTracking):
			self.laborIncomeLock.acquire()
			self.avgLaborIncome = ((1-self.accountingAlpha)*self.avgLaborIncome) + (self.accountingAlpha*self.stepLaborIncome)
			self.prevStepLaborIncome = self.stepLaborIncome
			self.prevTotalLaborIncome = self.totalLaborIncome
			self.stepLaborIncome = 0
			self.laborIncomeLock.release()
		#Labor expenses
		if (self.laborExpenseTracking):
			self.laborExpenseLock.acquire()
			self.avgLaborExpense = ((1-self.accountingAlpha)*self.avgLaborExpense) + (self.accountingAlpha*self.stepLaborExpense)
			self.prevStepLaborExpense = self.stepLaborExpense
			self.prevTotalLaborExpense = self.totalLaborExpense
			self.stepLaborExpense = 0
			self.laborExpenseLock.release()
		#Trading revenue
		if (self.tradeRevenueTracking):
			self.tradeRevenueLock.acquire()
			self.avgTradeRevenue = ((1-self.accountingAlpha)*self.avgTradeRevenue) + (self.accountingAlpha*self.stepTradeRevenue)
			self.prevStepTradeRevenue = self.stepTradeRevenue
			self.prevTotalTradeRevenue = self.totalTradeRevenue
			self.stepTradeRevenue = 0
			self.tradeRevenueLock.release()
		#Item expenses
		if (self.itemExpensesTracking):
			self.itemExpensesLock.acquire()
			self.avgItemExpenses = ((1-self.accountingAlpha)*self.avgItemExpenses) + (self.accountingAlpha*self.stepItemExpenses)
			self.prevStepItemExpenses = self.stepItemExpenses
			self.prevTotalItemExpenses = self.totalItemExpenses
			self.stepItemExpenses = 0
			self.itemExpensesLock.release()
		#Currency inflow
		if (self.currencyInflowTracking):
			self.currencyInflowLock.acquire()
			self.avgCurrencyInflow = ((1-self.accountingAlpha)*self.avgCurrencyInflow) + (self.accountingAlpha*self.stepCurrencyInflow)
			self.prevStepCurrencyInflow = self.stepCurrencyInflow
			self.prevTotalCurrencyInflow = self.totalCurrencyInflow
			self.stepCurrencyInflow = 0
			self.currencyInflowLock.release()
		#Currency outflow
		if (self.currencyOutflowTracking):
			self.currencyOutflowLock.acquire()
			self.avgCurrencyOutflow = ((1-self.accountingAlpha)*self.avgCurrencyOutflow) + (self.accountingAlpha*self.stepCurrencyOutflow)
			self.prevStepCurrencyOutflow = self.stepCurrencyOutflow
			self.prevTotalCurrencyOutflow = self.totalCurrencyOutflow
			self.stepCurrencyOutflow = 0
			self.currencyOutflowLock.release()
		#Land revenue
		if (self.landRevenueTracking):
			self.landRevenueLock.acquire()
			self.prevTotalLandRevenue = self.totalLandRevenue
			self.landRevenueLock.release()
		#Land expenses
		if (self.landExpensesTracking):
			self.landExpensesLock.acquire()
			self.prevTotalLandExpenses = self.totalLandExpenses
			self.landExpensesLock.release()


	#Labor income
	def enableLaborIncomeTracking(self):
		self.laborIncomeTracking = True
	def getTotalLaborIncome(self):
		return self.totalLaborIncome
	def getAvgLaborIncome(self):
		return self.avgLaborIncome
	def resetLaborIncome(self):
		self.totalLaborIncome = 0

	#Labor expenses
	def enableLaborExpenseTracking(self):
		self.laborExpenseTracking = True
	def getTotalLaborExpense(self):
		return self.totalLaborExpense
	def getAvgLaborExpense(self):
		return self.avgLaborExpense
	def resetLaborExpense(self):
		self.totalLaborExpense = 0

	#Trading revenue
	def enableTradeRevenueTracking(self):
		self.tradeRevenueTracking = True
	def getTotalTradeRevenue(self):
		return self.totalTradeRevenue
	def getAvgTradeRevenue(self):
		return self.avgTradeRevenue
	def resetTradeRevenue(self):
		self.totalTradeRevenue = 0

	#Item expenses
	def enableItemExpensesTracking(self):
		self.itemExpensesTracking = True
	def getTotalItemExpenses(self):
		return self.totalItemExpenses
	def getAvgItemExpenses(self):
		return self.avgItemExpenses
	def resetItemExpenses(self):
		self.totalItemExpenses = 0

	#Land revenue
	def enableLandRevenueTracking(self):
		self.landRevenueTracking = True
	def getTotalLandRevenue(self):
		return self.totalLandRevenue
	def resetLandRevenue(self):
		self.totalLandRevenue = 0

	#Land expenses
	def enableLandExpensesTracking(self):
		self.landExpensesTracking = True
	def getTotalLandExpenses(self):
		return self.totalLandExpenses
	def resetLandExpenses(self):
		self.totalLandExpenses = 0

	#Currency inflows
	def enableCurrencyInflowTracking(self):
		self.currencyInflowTracking = True
	def getTotalCurrencyInflow(self):
		return self.totalCurrencyInflow
	def getAvgCurrencyInflow(self):
		return self.avgCurrencyInflow
	def getStepCurrencyInflow(self):
		return self.prevStepCurrencyInflow
	def resetCurrencyInflow(self):
		self.totalCurrencyInflow = 0

	#Currency outflows
	def enableCurrencyOutflowTracking(self):
		self.currencyOutflowTracking = True
	def getTotalCurrencyOutflow(self):
		return self.totalCurrencyOutflow
	def getAvgCurrencyOutflow(self):
		return self.avgCurrencyOutflow
	def getStepCurrencyOutflow(self):
		return self.prevStepCurrencyOutflow
	def resetCurrencyOutflow(self):
		self.totalCurrencyOutflow = 0

	def getAccountingStats(self):
		'''
		Returns a dictionary of accounting stats for the previous step
		'''
		statsDict = {}

		#Labor income
		statsDict["totalLaborIncome"] = self.prevTotalLaborIncome
		statsDict["avgLaborIncome"] = self.avgLaborIncome
		statsDict["stepLaborIncome"] = self.prevStepLaborIncome
		#Labor expenses
		statsDict["totalLaborExpense"] = self.prevTotalLaborExpense
		statsDict["avgLaborExpense"] = self.avgLaborExpense
		statsDict["stepLaborExpense"] = self.prevStepLaborExpense
		#Trading revenue
		statsDict["totalTradeRevenue"] = self.prevTotalTradeRevenue
		statsDict["avgTradeRevenue"] = self.avgTradeRevenue
		statsDict["stepTradeRevenue"] = self.prevStepTradeRevenue
		#Item expenses
		statsDict["totalItemExpenses"] = self.prevTotalItemExpenses
		statsDict["avgItemExpenses"] = self.avgItemExpenses
		statsDict["stepItemExpenses"] = self.prevStepItemExpenses
		#Land revenue
		statsDict["totalLandRevenue"] = self.prevTotalLandRevenue
		#Land expenses
		statsDict["totalLandExpenses"] = self.prevTotalLandExpenses
		#Currency inflows
		statsDict["totalCurrencyInflow"] = self.prevTotalCurrencyInflow
		statsDict["avgCurrencyInflow"] = self.avgCurrencyInflow
		statsDict["stepCurrencyInflow"] = self.prevStepCurrencyInflow
		#Currency outflows
		statsDict["totalCurrencyOutflow"] = self.prevTotalCurrencyOutflow
		statsDict["avgCurrencyOutflow"] = self.avgCurrencyOutflow
		statsDict["stepCurrencyOutflow"] = self.prevStepCurrencyOutflow

		return statsDict


	#########################
	# Currency transfer functions
	#########################
	def getCurrencyBalance(self):
		return self.currencyBalance

	def receiveCurrency(self, cents, incommingPacket=None):
		'''
		Returns True if transfer was succesful, False if not
		'''
		try:
			self.logger.debug("{}.receiveCurrency({}) start".format(self.agentId, cents))

			#Check if transfer is valid
			transferSuccess = False
			transferComplete = False
			if (cents < 0):
				transferSuccess =  False
				transferComplete = True
			if (cents == 0):
				transferSuccess =  True
				transferComplete = True

			#If transfer is valid, handle transfer
			if (not transferComplete):
				acquired_currencyBalanceLock = self.currencyBalanceLock.acquire(timeout=self.lockTimeout)  #<== acquire currencyBalanceLock
				if (acquired_currencyBalanceLock):
					#Lock acquired. Increment balance
					self.currencyBalance = self.currencyBalance + int(cents)
					self.logger.debug("New balance = ${}".format(self.currencyBalance/100))
					self.currencyBalanceLock.release()  #<== release currencyBalanceLock

					transferSuccess = True
				else:
					#Lock timeout
					self.logger.error("receiveCurrency() Lock \"currencyBalanceLock\" acquisition timeout")
					transferSuccess = False

			#Send CURRENCY_TRANSFER_ACK
			if (self.needCurrencyTransferAck):
				if (incommingPacket):
					respPayload = {"paymentId": incommingPacket.payload["paymentId"], "transferSuccess": transferSuccess}
					responsePacket = NetworkPacket(senderId=self.agentId, destinationId=incommingPacket.senderId, msgType=PACKET_TYPE.CURRENCY_TRANSFER_ACK, payload=respPayload, transactionId=incommingPacket.transactionId)
					self.sendPacket(responsePacket)

			#Update accounting
			if (transferSuccess and self.currencyInflowTracking):
				self.currencyInflowLock.acquire()
				self.stepCurrencyInflow += int(cents)
				self.totalCurrencyInflow += int(cents)
				self.currencyInflowLock.release()

			if (transferSuccess and self.laborIncomeTracking):
				if (incommingPacket):
					paymentId = incommingPacket.payload["paymentId"]
					if ("LaborPayment_" in paymentId):
						self.laborIncomeLock.acquire()
						self.stepLaborIncome += int(cents)
						self.totalLaborIncome += int(cents)
						self.laborIncomeLock.release()

			#Return transfer status
			self.logger.debug("{}.receiveCurrency({}) return {}".format(self.agentId, cents, transferSuccess))
			return transferSuccess

		except Exception as e:
			self.logger.critical("receiveCurrency() Exception")
			self.logger.critical("selg.agentId={}, cents={}, incommingPacket={}".format(self.agentId, cents, incommingPacket))
			raise ValueError("receiveCurrency() Exception")


	def sendCurrency(self, cents, recipientId, transactionId=None, delResponse=True):
		'''
		Send currency to another agent. 
		Returns True if transfer was succesful, False if not
		'''
		try:
			self.logger.debug("{}.sendCurrency({}, {}) start".format(self.agentId, cents, recipientId))

			#Check for valid transfers
			if (cents == 0):
				self.logger.debug("{}.sendCurrency({}, {}) return {}".format(self.agentId, cents, recipientId, False))
				return True
			if (recipientId == self.agentId):
				self.logger.debug("{}.sendCurrency({}, {}) return {}".format(self.agentId, cents, recipientId, True))
				return True
			if (cents > self.currencyBalance):
				self.logger.error("Balance too small ({}). Cannot send {}".format(self.currencyBalance, cents))
				self.logger.debug("{}.sendCurrency({}, {}) return {}".format(self.agentId, cents, recipientId, False))
				return False

			#Start transfer
			transferSuccess = False

			acquired_currencyBalanceLock = self.currencyBalanceLock.acquire(timeout=self.lockTimeout)  #<== acquire currencyBalanceLock
			if (acquired_currencyBalanceLock):
				#Decrement balance
				self.currencyBalance -= int(cents)
				self.logger.debug("New balance = ${}".format(self.currencyBalance/100))
				self.currencyBalanceLock.release()  #<== release currencyBalanceLock

				#Send payment packet
				paymentId = "{}_CURRENCY".format(transactionId)
				if (not transactionId):
					paymentId = "{}_{}_{}".format(self.agentId, recipientId, cents)
				transferPayload = {"paymentId": paymentId, "cents": cents}
				transferPacket = NetworkPacket(senderId=self.agentId, destinationId=recipientId, msgType=PACKET_TYPE.CURRENCY_TRANSFER, payload=transferPayload, transactionId=paymentId)
				self.sendPacket(transferPacket)

				if (self.needCurrencyTransferAck):
					#Wait for transaction response
					while not (paymentId in self.responseBuffer):
						time.sleep(self.responsePollTime)
						if (self.agentKillFlag):
							return False
						
					responsePacket = self.responseBuffer[paymentId]

					#Undo balance change if not successful
					transferSuccess = bool(responsePacket.payload["transferSuccess"])
					if (not transferSuccess):
						self.logger.error("{} {}".format(responsePacket, responsePacket.payload))
						self.logger.error("Undoing balance change of -{}".format(cents))
						self.currencyBalanceLock.acquire()  #<== acquire currencyBalanceLock
						self.currencyBalance += cents
						self.currencyBalanceLock.release()  #<== acquire currencyBalanceLock

					#Remove transaction from response buffer
					if (delResponse):
						acquired_responseBufferLock = self.responseBufferLock.acquire(timeout=self.lockTimeout)  #<== acquire responseBufferLock
						if (acquired_responseBufferLock):
							del self.responseBuffer[paymentId]
							self.responseBufferLock.release()  #<== release responseBufferLock
						else:
							self.logger.error("sendCurrency() Lock \"responseBufferLock\" acquisition timeout")
							transferSuccess = False
				else:
					transferSuccess = True

				#Update accounting
				if (transferSuccess and self.currencyOutflowTracking):
					self.currencyOutflowLock.acquire()
					self.stepCurrencyOutflow += int(cents)
					self.totalCurrencyOutflow += int(cents)
					self.currencyOutflowLock.release()
				
			else:
				#Lock acquisition timout
				self.logger.error("sendCurrency() Lock \"currencyBalanceLock\" acquisition timeout")
				transferSuccess = False

			self.logger.debug("{}.sendCurrency({}, {}) return {}".format(self.agentId, cents, recipientId, transferSuccess))
			return transferSuccess

		except Exception as e:
			self.logger.critical("sendCurrency() Exception")
			self.logger.critical("selg.agentId={}, cents={}, recipientId={}, transactionId={}, delResponse={}".format(self.agentId, cents, recipientId, transactionId, delResponse))
			raise ValueError("sendCurrency() Exception")

	#########################
	# Item functions
	#########################
	def receiveItem(self, itemPackage, incommingPacket=None):
		'''
		Add an item to agent inventory.
		Returns True if item was successfully added, False if not
		'''
		try:
			self.logger.debug("{}.receiveItem({}) start".format(self.agentId, itemPackage))
			received = False

			acquired_inventoryLock = self.inventoryLock.acquire(timeout=self.lockTimeout)  #<== acquire inventoryLock
			if (acquired_inventoryLock):
				itemId = itemPackage.id
				if not (itemId in self.inventory):
					self.inventory[itemId] = itemPackage
					self.logger.debug("old {}.inventory[{}]=None".format(self.agentId, itemId))
				else:
					self.logger.debug("old {}.inventory[{}]={}".format(self.agentId, itemId, self.inventory[itemId]))
					self.inventory[itemId] += itemPackage

				self.logger.debug("new {}.inventory[{}]={}".format(self.agentId, itemId, self.inventory[itemId]))
				self.inventoryLock.release()  #<== release inventoryLock

				received = True

				if (self.needItemTransferAck):
					#Send ITEM_TRANSFER_ACK
					if (incommingPacket):
						respPayload = {"transferId": incommingPacket.payload["transferId"], "transferSuccess": received}
						responsePacket = NetworkPacket(senderId=self.agentId, destinationId=incommingPacket.senderId, msgType=PACKET_TYPE.ITEM_TRANSFER_ACK, payload=respPayload, transactionId=incommingPacket.transactionId)
						self.sendPacket(responsePacket)
			else:
				self.logger.error("receiveItem() Lock \"inventoryLock\" acquisition timeout")
				received = False

			#Return status
			self.logger.debug("{}.receiveItem({}) return {}".format(self.agentId, itemPackage, received))
			return received

		except Exception as e:
			self.logger.critical("receiveItem() Exception")
			self.logger.critical("self.agentId={}, itemPackage={}, incommingPacket={}".format(self.agentId, itemPackage, incommingPacket))
			raise ValueError("receiveItem() Exception")


	def sendItem(self, itemPackage, recipientId, transactionId=None, delResponse=True):
		'''
		Send an item to another agent.
		Returns True if item was successfully sent, False if not
		'''
		try:
			self.logger.debug("{}.sendItem({}, {}) start".format(self.agentId, itemPackage, recipientId))

			transferSuccess = False
			transferValid = False

			acquired_inventoryLock = self.inventoryLock.acquire(timeout=self.lockTimeout)  #<== acquire inventoryLock
			if (acquired_inventoryLock):
				#Ensure we have enough stock to send item
				itemId = itemPackage.id
				if not (itemId in self.inventory):
					self.logger.error("sendItem() {} not in agent inventory".format(itemId))
					transferSuccess = False
					transferValid = False
				else:
					currentStock = self.inventory[itemId]
					if(currentStock.quantity < itemPackage.quantity):
						self.logger.error("sendItem() Current stock {} not sufficient to send {}".format(currentStock, itemPackage))
						transferSuccess = False
						transferValid = False
					else:
						#We have enough stock. Subtract transfer amount from inventory
						self.inventory[itemId] -= itemPackage
						transferValid = True

				self.inventoryLock.release()  #<== release inventoryLock

				#Send items to recipient if transfer valid
				transferId = "{}_ITEM".format(transactionId)
				if (not transactionId):
					transferId = "{}_{}_{}_{}".format(self.agentId, recipientId, itemPackage, time.time())

				if (transferValid):
					transferPayload = {"transferId": transferId, "item": itemPackage}
					transferPacket = NetworkPacket(senderId=self.agentId, destinationId=recipientId, msgType=PACKET_TYPE.ITEM_TRANSFER, payload=transferPayload, transactionId=transferId)
					self.sendPacket(transferPacket)

				if (self.needItemTransferAck):
					#Wait for transaction response
					while not (transferId in self.responseBuffer):
						time.sleep(self.responsePollTime)
						if (self.agentKillFlag):
							return False
						
					responsePacket = self.responseBuffer[transferId]

					#Undo inventory change if not successful
					transferSuccess = bool(responsePacket.payload["transferSuccess"])
					if (not transferSuccess):
						self.logger.error("{} {}".format(responsePacket, responsePacket.payload))
						self.logger.error("Undoing inventory change ({},{})".format(itemPackage.id, -1*itemPackage.quantity))
						self.inventoryLock.acquire()  #<== acquire currencyBalanceLock
						self.inventory[itemId] += itemPackage
						self.inventoryLock.release()  #<== acquire currencyBalanceLock

					#Remove transaction from response buffer
					if (delResponse):
						acquired_responseBufferLock = self.responseBufferLock.acquire(timeout=self.lockTimeout)  #<== acquire responseBufferLock
						if (acquired_responseBufferLock):
							del self.responseBuffer[transferId]
							self.responseBufferLock.release()  #<== release responseBufferLock
						else:
							self.logger.error("sendItem() Lock \"responseBufferLock\" acquisition timeout")
							transferSuccess = False
				else:
					transferSuccess = True

			else:
				#Lock acquisition timout
				self.logger.error("sendItem() Lock \"inventoryLock\" acquisition timeout")
				transferSuccess = False

			#Return status
			self.logger.debug("{}.sendItem({}, {}) return {}".format(self.agentId, itemPackage, recipientId, transferSuccess))
			return transferSuccess

		except Exception as e:
			self.logger.critical("sendItem() Exception")
			self.logger.critical("selg.agentId={}, itemPackage={}, recipientId={}, transactionId={}, delResponse={}".format(self.agentId, itemPackage, recipientId, transactionId, delResponse))
			raise ValueError("sendItem() Exception")


	def consumeItem(self, itemContainer):
		'''
		Consumes an item. Returns True if successful, False if not
		'''
		self.logger.debug("consumeItem({}) start".format(itemContainer))

		consumeSuccess = False

		#Make sure we have the item in our inventory
		if (itemContainer.id in self.inventory):
			acquired_inventoryLock = self.inventoryLock.acquire(timeout=self.lockTimeout)  #<== acquire inventoryLock
			if (acquired_inventoryLock):
				#Make sure we have enough of the item
				if ((itemContainer.quantity-(2/pow(10,g_ItemQuantityPercision))) > self.inventory[itemContainer.id].quantity):
					self.logger.error("Cannot consume {}. Current inventory of {}".format(itemContainer, self.inventory[itemContainer.id]))
					consumeSuccess = False
				else:
					#Consume the item
					if (itemContainer.quantity > self.inventory[itemContainer.id].quantity):
						self.inventory[itemContainer.id].quantity = 0
					else:
						self.inventory[itemContainer.id] -= itemContainer

					#Check if this item was food
					if (self.enableNutrition):
						if (itemContainer.id in self.nutritionalDict):
							self.nutritionTracker.consumeFood(itemContainer.id, itemContainer.quantity)

				self.inventoryLock.release()

				consumeSuccess = True
			else:
				#Lock acquisition timout
				self.logger.error("consumeItem() Lock \"inventoryLock\" acquisition timeout")
				consumeSuccess = False
		else:
			self.logger.error("Cannot consume {}. Item missing from inventory".format(itemContainer))
			consumeSuccess = False

		self.logger.debug("consumeItem({}) return {}".format(itemContainer, consumeSuccess))
		return consumeSuccess


	def produceItem(self, itemContainer):
		'''
		Returns an item container of produced items if successful, False if not.
		'''
		self.logger.debug("produceItem({}) start".format(itemContainer))

		#Make sure we can produce this item
		itemId = itemContainer.id
		if not (self.itemDict):
			self.logger.error("Cannot produce {}. No global item dictionary set for this agent".format(itemContainer, itemId))
			self.logger.debug("produceItem({}) end".format(itemContainer))
			return False

		if not (itemId in self.itemDict):
			self.logger.error("Cannot produce {}. \"{}\" missing from global item dictionary".format(itemContainer, itemId))
			self.logger.debug("produceItem({}) end".format(itemContainer))
			return False

		#Produce item
		productionFunction = self.getProductionFunction(itemId)
		producedItems = productionFunction.produceItem(self, itemContainer.quantity)

		#Send out production notification
		if (producedItems):
			productionNotification = NetworkPacket(senderId=self.agentId, msgType=PACKET_TYPE.PRODUCTION_NOTIFICATION, payload=producedItems)
			self.sendPacket(productionNotification)

		self.logger.debug("produceItem({}) end".format(itemContainer))
		return producedItems


	def getMaxProduction(self, itemId):
		'''
		Returns the max amount of itemId this agent can produce at this time
		'''
		self.logger.debug("getMaxProduction({}) start".format(itemId))

		if not (self.itemDict):
			self.logger.error("Cannot produce {}. No global item dictionary set for this agent".format(itemId))
			return False

		if not (itemId in self.itemDict):
			self.logger.error("Cannot produce {}. \"{}\" missing from global item dictionary".format(itemId, itemId))
			return False

		productionFunction = self.getProductionFunction(itemId)
		maxQuantity = productionFunction.getMaxProduction(self)
		
		self.logger.debug("getMaxProduction({}) return {}".format(itemId, maxQuantity))

		return maxQuantity


	def getProductionFunction(self, itemId):
		if not (itemId in self.productionFunctions):
			#Have not produced this item before. Create new production function
			newProductionFunction = ProductionFunction(self.itemDict[itemId])
			self.productionFunctionsLock.acquire()
			self.productionFunctions[itemId] = newProductionFunction
			self.productionFunctionsLock.release()

		productionFunction = self.productionFunctions[itemId]
		return productionFunction


	def getProductionInputDeltas(self, itemId, stepProductionQuantity):
		productionFunction = self.getProductionFunction(itemId)
		deltas = productionFunction.getProductionInputDeltas(self, stepProductionQuantity)
		return deltas


	def getProductionInputDeficit(self, itemId, stepProductionQuantity):
		'''
		Returns a dictionary of what this agent is missing to produce this item at the specified quantity
		'''
		self.logger.debug("getProductionInputDeficit({},{}) start".format(itemId, stepProductionQuantity))

		productionFunction = self.getProductionFunction(itemId)
		deltas = productionFunction.getProductionInputDeltas(self, stepProductionQuantity)

		deficitDict = {
		"LandDeficit": 0, 
		"FixedItemDeficit": {},
		"VariableItemDeficit": {},
		"LaborDeficit": {}}

		landDelta = deltas["LandDelta"]
		if (landDelta > 0):
			deficitDict["LandDeficit"] = landDelta

		for itemId in deltas["FixedItemDeltas"]:
			if (deltas["FixedItemDeltas"][itemId].quantity > 0):
				deficitDict["FixedItemDeficit"][itemId] = deltas["FixedItemDeltas"][itemId]

		for itemId in deltas["VariableItemDeltas"]:
			if (deltas["VariableItemDeltas"][itemId].quantity > 0):
				deficitDict["VariableItemDeficit"][itemId] = deltas["VariableItemDeltas"][itemId]

		for skillLevel in deltas["LaborDeltas"]:
			if (deltas["LaborDeltas"][skillLevel] > 0):
				deficitDict["LaborDeficit"][skillLevel] = deltas["LaborDeltas"][skillLevel]


		self.logger.debug("getProductionInputDeficit({},{}) end".format(itemId, stepProductionQuantity))
		return deficitDict


	def getProductionInputSurplus(self, itemId, stepProductionQuantity):
		'''
		Returns a dictionary of what this agent has but does not need to produce this item at the specified quantity
		'''
		self.logger.debug("getProductionInputDeficit({},{}) start".format(itemId, stepProductionQuantity))

		productionFunction = self.getProductionFunction(itemId)
		deltas = productionFunction.getProductionInputDeltas(self, stepProductionQuantity)

		surplusDict = {
		"LandSurplus": 0, 
		"FixedItemSurplus": {},
		"VariableItemSurplus": {},
		"LaborSurplus": {}}

		landDelta = deltas["LandDelta"]
		if (landDelta < 0):
			surplusDict["LandSurplus"] = abs(landDelta)

		for itemId in deltas["FixedItemDeltas"]:
			if (deltas["FixedItemDeltas"][itemId].quantity < 0):
				surplusContainer = deltas["FixedItemDeltas"][itemId]
				surplusContainer.quantity = abs(surplusContainer.quantity)
				surplusDict["FixedItemSurplus"][itemId] = surplusContainer

		for itemId in deltas["VariableItemDeltas"]:
			if (deltas["VariableItemDeltas"][itemId].quantity < 0):
				surplusContainer = deltas["VariableItemDeltas"][itemId]
				surplusContainer.quantity = abs(surplusContainer.quantity)
				surplusDict["VariableItemSurplus"][itemId] = surplusContainer

		for skillLevel in deltas["LaborDeltas"]:
			if (deltas["LaborDeltas"][skillLevel] < 0):
				surplusDict["LaborSurplus"][skillLevel] = abs(deltas["LaborDeltas"][skillLevel])

		self.logger.debug("getProductionInputDeficit({},{}) end".format(itemId, stepProductionQuantity))
		return surplusDict

	#########################
	# Item Trading functions
	#########################
	def executeTrade(self, request):
		'''
		Execute a trade request.
		Returns True if trade is completed, False if not
		'''
		try:
			self.logger.debug("Executing {}".format(request))
			tradeCompleted = False

			if (self.agentId == request.buyerId):
				#We are the buyer. Send money
				moneySent = self.sendCurrency(request.currencyAmount, request.sellerId, transactionId=request.reqId)
				if (not moneySent):
					self.logger.error("Money transfer failed {}".format(request))
					
				tradeCompleted = moneySent

				#Update accounting
				if (tradeCompleted and self.itemExpensesTracking):
					self.itemExpensesLock.acquire()
					self.stepItemExpenses += request.currencyAmount
					self.totalItemExpenses += request.currencyAmount
					self.itemExpensesLock.release()

			if (self.agentId == request.sellerId):
				#We are the seller. Send item package
				itemSent = self.sendItem(request.itemPackage, request.buyerId, transactionId=request.reqId)
				if (not itemSent):
					self.logger.error("Item transfer failed {}".format(request))
					
				tradeCompleted = itemSent

				#Update accounting
				if (tradeCompleted and self.tradeRevenueTracking):
					self.tradeRevenueLock.acquire()
					self.stepTradeRevenue += request.currencyAmount
					self.totalTradeRevenue += request.currencyAmount
					self.tradeRevenueLock.release()

			self.logger.debug("Completed {}".format(request))
			return tradeCompleted

		except Exception as e:
			self.logger.critical("executeTrade() Exception")
			self.logger.critical("selg.agentId={}, request={}".format(self.agentId, request))
			raise ValueError("executeTrade() Exception")


	def receiveTradeRequest(self, request, senderId):
		'''
		Will pass along trade request to agent controller for approval. Will execute trade if approved.
		Returns True if trade is completed, False if not
		'''
		self.logger.debug("receiveTradeRequest({}) start".format(request))
		try:
			self.tradeRequestLock.acquire()  #<== acquire tradeRequestLock

			tradeCompleted = False

			#Evaluate offer
			offerAccepted = False
			if (senderId != request.sellerId) and (senderId != request.buyerId):
				#This request was sent by a third party. Reject it
				self.logger.debug("{} was sent by a third party. Rejecting it".format(request))
				offerAccepted = False
			else:
				#Offer is valid. Evaluate offer
				if (self.controller):
					self.logger.debug("Fowarding {} to controller {}".format(request, self.controller.name))
					offerAccepted = self.controller.evalTradeRequest(request)
				else:
					self.logger.debug("{} does not have a controller. Rejecting {}".format(self.agentId, request))
					offerAccepted = False

			#Add this trade offer to the outstanding trade dict
			if (offerAccepted):
				completedTransactionId = request.reqId
				if (self.agentId == request.buyerId):
					#We are the buyer. We need the item
					completedTransactionId = "{}_ITEM".format(request.reqId)

				if (self.agentId == request.sellerId):
					#We are the seller. We need the money
					completedTransactionId = "{}_CURRENCY".format(request.reqId)


				self.outstandingTradesLock.acquire()
				self.outstandingTrades[completedTransactionId] = True
				self.outstandingTradesLock.release()

			#Execute trade if offer accepted
			if (offerAccepted):
				self.logger.debug("{} accepted".format(request))
				tradeCompleted = self.executeTrade(request)
			else:
				self.logger.debug("{} rejected".format(request))

			#Notify counter party of response
			respPayload = {"tradeRequest": request, "accepted": offerAccepted}
			responsePacket = NetworkPacket(senderId=self.agentId, destinationId=senderId, msgType=PACKET_TYPE.TRADE_REQ_ACK, payload=respPayload, transactionId=request.reqId)
			self.sendPacket(responsePacket)

			#Wait for counter party to fullfill their end of the trade
			if (offerAccepted):
				self.logger.debug("Waiting for counterparty to complete trade {}".format(request))
				while (request.reqId in self.outstandingTrades):
					time.sleep(self.responsePollTime)
					if (self.agentKillFlag):
						return False
					
				self.logger.debug("Counterparty completed trade {}".format(request))

			self.tradeRequestLock.release()  #<== release tradeRequestLock
			return tradeCompleted

		except Exception as e:
			self.logger.critical("receiveTradeRequest() Exception")
			self.logger.critical("selg.agentId={}, request={}, senderId={}".format(self.agentId, request, senderId))
			raise ValueError("receiveTradeRequest() Exception")
		

	def sendTradeRequest(self, request, recipientId):
		'''
		Send a trade request to another agent. Will execute trade if accepted by recipient.
		Returns True if the trade completed. Returns False if not
		'''
		try:
			#Make sure this request is valid
			quantity = request.itemPackage.quantity
			if (quantity <= 0):
				return False

			if (self.agentId == request.buyerId):
				#We are the buyer. Make sure we have enough money
				if (self.currencyBalance < request.currencyAmount):
					self.logger.error("Current balance {} not enough for {}".format(self.currencyBalance, request))
					return False

			self.tradeRequestLock.acquire()  #<== acquire tradeRequestLock

			self.logger.debug("{}.sendTradeRequest({}, {}) start".format(self.agentId, request, recipientId))
			tradeCompleted = False

			#Send trade offer
			tradeId = request.reqId
			tradePacket = NetworkPacket(senderId=self.agentId, destinationId=recipientId, msgType=PACKET_TYPE.TRADE_REQ, payload=request, transactionId=tradeId)
			self.sendPacket(tradePacket)
			
			#Wait for trade response
			while not (tradeId in self.responseBuffer):
				time.sleep(self.responsePollTime)
				if (self.agentKillFlag):
					return False
				
			responsePacket = self.responseBuffer[tradeId]

			#Execute trade if request accepted
			offerAccepted = bool(responsePacket.payload["accepted"])
			if (offerAccepted):
				#Execute trade
				tradeCompleted = self.executeTrade(request)
			else:
				self.logger.info("{} was rejected".format(request))
				tradeCompleted = offerAccepted

			#Remove transaction from response buffer
			acquired_responseBufferLock = self.responseBufferLock.acquire(timeout=self.lockTimeout)  #<== acquire responseBufferLock
			if (acquired_responseBufferLock):
				del self.responseBuffer[tradeId]
				self.responseBufferLock.release()  #<== release responseBufferLock
			else:
				self.logger.error("sendTradeRequest({}) Lock \"responseBufferLock\" acquisition timeout".format(request))
				transferSuccess = False

			self.tradeRequestLock.release()  #<== release tradeRequestLock
			self.logger.debug("{}.sendTradeRequest({}, {}) return {}".format(self.agentId, request, recipientId, tradeCompleted))
			return tradeCompleted

		except Exception as e:
			self.logger.critical("sendTradeRequest() Exception")
			self.logger.critical("selg.agentId={}, request={}, recipientId={}".format(self.agentId, request, recipientId))
			raise ValueError("sendTradeRequest() Exception")

	#########################
	# Land functions
	#########################
	def deallocateLand(self, allocationType, hectares):
		'''
		Returns True if successful, False if not
		'''
		self.logger.info("deallocateLand({}, {}) start".format(allocationType, hectares))
		landDeallocated = False

		acquired_landHoldingsLock = self.landHoldingsLock.acquire(timeout=self.lockTimeout)
		if (acquired_landHoldingsLock):
			if (allocationType in self.landHoldings):
				if (allocationType == "ALLOCATING"):
					self.logger.error("deallocateLand({}, {}) Cannot deallocate land that is currently being allocated".format(allocationType, hectares))
					landDeallocated = False
					return landDeallocated

				if (hectares <= self.landHoldings[allocationType]):
					self.landHoldings[allocationType] -= hectares
					if (self.landHoldings[allocationType] == 0):
						del self.landHoldings[allocationType]

					self.landHoldings["UNALLOCATED"] += hectares
					landDeallocated = True
				else:
					self.logger.error("deallocateLand({}, {}) Not enough land in landHoldings {}".format(allocationType, hectares, self.landHoldings))
					landDeallocated = False
			else:
				self.logger.error("deallocateLand({}, {}) \"{}\" not in landHoldings {}".format(allocationType, hectares, allocationType, self.landHoldings))
				landDeallocated = False

			self.landHoldingsLock.release()
		else:
			self.logger.error("deallocateLand({}, {}) Lock landHoldingsLock acquisition timout".format(allocationType, hectares))
			landDeallocated = False

		return landDeallocated


	def allocateLand(self, allocationType, hectares):
		'''
		Changes "UNALLOCATED" land into allocated land.
		Transition does not happen instantly; the allocation is delayed by "AllocationTime", which is a field in the ProductionInputs for a given item.
		During this transition time, the land is counted as "ALLOCATING", and cannot be used for anything.

		Returns True if successful, False if not
		'''
		self.logger.info("allocateLand({}, {}) start".format(allocationType, hectares))
		landAllocated = self.landAllocationQueue.startAllocation(allocationType, hectares)
		return landAllocated


	def receiveLand(self, allocation, hectares, incommingPacket=None):
		'''
		Add land to agent land holdings.
		Returns True if land was successfully added, False if not
		'''
		try:
			self.logger.debug("{}.receiveLand({},{}) start".format(self.agentId, allocation, hectares))
			received = False

			acquired_landHoldingsLock = self.landHoldingsLock.acquire(timeout=self.lockTimeout)  #<== acquire landHoldingsLock
			if (acquired_landHoldingsLock):
				if not (allocation in self.landHoldings):
					self.landHoldings[allocation] = hectares
				else:
					self.landHoldings[allocation] += hectares

				self.landHoldingsLock.release()  #<== release landHoldingsLock

				received = True

				if (self.needLandTransferAck):
					#Send ITEM_TRANSFER_ACK
					if (incommingPacket):
						respPayload = {"transferId": incommingPacket.payload["transferId"], "transferSuccess": received}
						responsePacket = NetworkPacket(senderId=self.agentId, destinationId=incommingPacket.senderId, msgType=PACKET_TYPE.LAND_TRANSFER_ACK, payload=respPayload, transactionId=incommingPacket.transactionId)
						self.sendPacket(responsePacket)
			else:
				self.logger.error("receiveLand() Lock \"landHoldingsLock\" acquisition timeout")
				received = False

			#Return status
			self.logger.debug("{}.receiveLand({},{}) return {}".format(self.agentId, allocation, hectares, received))
			return received

		except Exception as e:
			self.logger.critical("receiveLand() Exception")
			self.logger.critical("self.agentId={}, allocation={}, hectares={}, incommingPacket={}".format(self.agentId, allocation, hectares, incommingPacket))
			raise ValueError("receiveLand() Exception")


	def sendLand(self, allocation, hectares, recipientId, transactionId=None, delResponse=True):
		'''
		Send land to another agent.
		Returns True if land was successfully sent, False if not
		'''
		try:
			self.logger.debug("{}.sendLand({}, {}, {}) start".format(self.agentId, allocation, hectares, recipientId))

			transferSuccess = False
			transferValid = False

			acquired_landHoldingsLock = self.landHoldingsLock.acquire(timeout=self.lockTimeout)  #<== acquire landHoldingsLock
			if (acquired_landHoldingsLock):
				#Ensure we have enough land to send
				if not (allocation in self.landHoldings):
					self.logger.error("sendLand() Land type {} not in land holdings".format(allocation))
					transferSuccess = False
					transferValid = False
				else:
					currentAcres = self.landHoldings[allocation]
					if(currentAcres < hectares):
						self.logger.error("sendLand() Current land allocation={}, hectares={} not sufficient to send {} hectares".format(allocation, currentAcres, hectares))
						transferSuccess = False
						transferValid = False
					else:
						#We have enough stock. Subtract transfer amount from inventory
						self.landHoldings[allocation] -= hectares
						transferValid = True

				self.landHoldingsLock.release()  #<== release landHoldingsLock

				#Send items to recipient if transfer valid
				transferId = "{}_LAND".format(transactionId)
				if (not transactionId):
					transferId = "{}_{}_LAND_{}_{}_{}".format(self.agentId, recipientId, allocation, hectares, time.time())

				if (transferValid):
					transferPayload = {"transferId": transferId, "allocation": allocation, "hectares": hectares}
					transferPacket = NetworkPacket(senderId=self.agentId, destinationId=recipientId, msgType=PACKET_TYPE.LAND_TRANSFER, payload=transferPayload, transactionId=transferId)
					self.sendPacket(transferPacket)

				if (self.needLandTransferAck):
					#Wait for transaction response
					while not (transferId in self.responseBuffer):
						time.sleep(self.responsePollTime)
						if (self.agentKillFlag):
							return False
						
					responsePacket = self.responseBuffer[transferId]

					#Undo inventory change if not successful
					transferSuccess = bool(responsePacket.payload["transferSuccess"])
					if (not transferSuccess):
						self.logger.error("{} {}".format(responsePacket, responsePacket.payload))
						self.logger.error("Undoing land holdings change ({},{})".format(allocation, -1*hectares))
						self.landHoldingsLock.acquire()  #<== acquire currencyBalanceLock
						self.landHoldings[allocation] += hectares
						self.landHoldingsLock.release()  #<== acquire currencyBalanceLock

					#Remove transaction from response buffer
					if (delResponse):
						acquired_responseBufferLock = self.responseBufferLock.acquire(timeout=self.lockTimeout)  #<== acquire responseBufferLock
						if (acquired_responseBufferLock):
							del self.responseBuffer[transferId]
							self.responseBufferLock.release()  #<== release responseBufferLock
						else:
							self.logger.error("sendLand() Lock \"responseBufferLock\" acquisition timeout")
							transferSuccess = False
				else:
					transferSuccess = True

			else:
				#Lock acquisition timout
				self.logger.error("sendLand() Lock \"inventoryLock\" acquisition timeout")
				transferSuccess = False

			#Return status
			self.logger.debug("{}.sendLand({}, {}, {}) return {}".format(self.agentId, allocation, hectares, recipientId, transferSuccess))
			return transferSuccess

		except Exception as e:
			self.logger.critical("sendLand() Exception")
			self.logger.critical("self.agentId={}, allocation={}, hectares={}, recipientId={}, transactionId={}, delResponse={}".format(self.agentId, allocation, hectares, recipientId, transactionId, delResponse))
			raise ValueError("sendLand() Exception")


	def executeLandTrade(self, request):
		'''
		Execute a land trade request.
		Returns True if trade is completed, False if not
		'''
		try:
			self.logger.debug("Executing {}".format(request))
			tradeCompleted = False

			if (self.agentId == request.buyerId):
				#We are the buyer. Send money
				moneySent = self.sendCurrency(request.currencyAmount, request.sellerId, transactionId=request.reqId)
				if (not moneySent):
					self.logger.error("Money transfer failed {}".format(request))
					
				tradeCompleted = moneySent

				#Update accounting
				if (tradeCompleted and self.landExpensesTracking):
					self.landExpensesLock.acquire()
					self.totalLandExpenses += request.currencyAmount
					self.landExpensesLock.release()

			if (self.agentId == request.sellerId):
				#We are the seller. Send item package
				landSent = self.sendLand(request.allocation, request.hectares, request.buyerId, transactionId=request.reqId)
				if (not landSent):
					self.logger.error("Land transfer failed {}".format(request))
					
				tradeCompleted = landSent

				#Update accounting
				if (tradeCompleted and self.landRevenueTracking):
					self.landRevenueLock.acquire()
					self.totalLandRevenue += request.currencyAmount
					self.landRevenueLock.release()

			return tradeCompleted

		except Exception as e:
			self.logger.critical("executeLandTrade() Exception")
			self.logger.critical("selg.agentId={}, request={}".format(self.agentId, request))
			raise ValueError("executeLandTrade() Exception")


	def receiveLandTradeRequest(self, request, senderId):
		'''
		Will pass along land trade request to agent controller for approval. Will execute land trade if approved.
		Returns True if trade is completed, False if not
		'''
		try:
			self.landTradeRequestLock.acquire()  #<== acquire landTradeRequestLock

			tradeCompleted = False

			#Evaluate offer
			offerAccepted = False
			if (senderId != request.sellerId) and (senderId != request.buyerId):
				#This request was sent by a third party. Reject it
				offerAccepted = False
			else:
				#Offer is valid. Evaluate offer
				if (self.controller):
					self.logger.debug("Fowarding {} to controller {}".format(request, self.controller.name))
					offerAccepted = self.controller.evalLandTradeRequest(request)
				else:
					self.logger.debug("{} does not have a controller. Rejecting {}".format(self.agentId, request))
					offerAccepted = False

			#Add this trade offer to the outstanding trade dict
			if (offerAccepted):
				completedTransactionId = request.reqId
				if (self.agentId == request.buyerId):
					#We are the buyer. We need the land
					completedTransactionId = "{}_LAND".format(request.reqId)

				if (self.agentId == request.sellerId):
					#We are the seller. We need the money
					completedTransactionId = "{}_CURRENCY".format(request.reqId)


				self.outstandingTradesLock.acquire()
				self.outstandingTrades[completedTransactionId] = True
				self.outstandingTradesLock.release()

			#Execute trade if offer accepted
			if (offerAccepted):
				self.logger.debug("{} accepted".format(request))
				tradeCompleted = self.executeLandTrade(request)
			else:
				self.logger.debug("{} rejected".format(request))

			#Notify counter party of response
			respPayload = {"tradeRequest": request, "accepted": offerAccepted}
			responsePacket = NetworkPacket(senderId=self.agentId, destinationId=senderId, msgType=PACKET_TYPE.LAND_TRADE_REQ_ACK, payload=respPayload, transactionId=request.reqId)
			self.sendPacket(responsePacket)

			#Wait for counter party to fullfill their end of the trade
			if (offerAccepted):
				self.logger.debug("Waiting for counterparty to complete trade {}".format(request))
				while (request.reqId in self.outstandingTrades):
					time.sleep(self.responsePollTime)
					if (self.agentKillFlag):
						return False
					
				self.logger.debug("Counterparty completed trade {}".format(request))

			self.landTradeRequestLock.release()  #<== release landTradeRequestLock
			return tradeCompleted

		except Exception as e:
			self.logger.critical("receiveLandTradeRequest() Exception")
			self.logger.critical("selg.agentId={}, request={}, senderId={}".format(self.agentId, request, senderId))
			raise ValueError("receiveLandTradeRequest() Exception")
		

	def sendLandTradeRequest(self, request, recipientId):
		'''
		Send a land trade request to another agent. Will execute trade if accepted by recipient.
		Returns True if the trade completed. Returns False if not
		'''
		try:
			#Make sure this request is valid
			if (self.agentId == request.buyerId):
				#We are the buyer. Make sure we have enough money
				if (self.currencyBalance < request.currencyAmount):
					self.logger.error("Current balance {} not enough for {}".format(self.currencyBalance, request))
					return False

			self.landTradeRequestLock.acquire()  #<== acquire landTradeRequestLock

			self.logger.debug("{}.sendLandTradeRequest({}, {}) start".format(self.agentId, request, recipientId))
			tradeCompleted = False

			#Send trade offer
			tradeId = request.reqId
			tradePacket = NetworkPacket(senderId=self.agentId, destinationId=recipientId, msgType=PACKET_TYPE.LAND_TRADE_REQ, payload=request, transactionId=tradeId)
			self.sendPacket(tradePacket)
			
			#Wait for trade response
			while not (tradeId in self.responseBuffer):
				time.sleep(self.responsePollTime)
				if (self.agentKillFlag):
					return False
				
			responsePacket = self.responseBuffer[tradeId]

			#Execute trade if request accepted
			offerAccepted = bool(responsePacket.payload["accepted"])
			if (offerAccepted):
				#Execute trade
				tradeCompleted = self.executeLandTrade(request)
			else:
				self.logger.info("{} was rejected".format(request))
				tradeCompleted = offerAccepted

			#Remove transaction from response buffer
			acquired_responseBufferLock = self.responseBufferLock.acquire(timeout=self.lockTimeout)  #<== acquire responseBufferLock
			if (acquired_responseBufferLock):
				del self.responseBuffer[tradeId]
				self.responseBufferLock.release()  #<== release responseBufferLock
			else:
				self.logger.error("sendLandTradeRequest({}) Lock \"responseBufferLock\" acquisition timeout".format(request))
				transferSuccess = False

			self.landTradeRequestLock.release()  #<== release landTradeRequestLock
			self.logger.debug("{}.sendLandTradeRequest({}, {}) return {}".format(self.agentId, request, recipientId, tradeCompleted))
			return tradeCompleted

		except Exception as e:
			self.logger.critical("sendLandTradeRequest() Exception")
			self.logger.critical("selg.agentId={}, request={}, recipientId={}".format(self.agentId, request, recipientId))
			raise ValueError("sendLandTradeRequest() Exception")

	#########################
	# Labor functions
	#########################
	def fulfillAllLaborContracts(self):
		'''
		Fulfills all non-expired labor contracts
		'''
		self.laborContractsLock.acquire()
		laborContractsTemp = copy.deepcopy(self.laborContracts)
		self.laborContractsLock.release()
		for endStep in list(laborContractsTemp.keys()):
			if (self.stepNum > endStep):
				self.logger.debug("Removing all contracts that expire on step {}".format(endStep))

				self.commitedTicks_nextStepLock.acquire()
				for laborContractHash in laborContractsTemp[endStep]:
					self.commitedTicks_nextStep -= laborContractsTemp[endStep][laborContractHash].ticksPerStep
				self.commitedTicks_nextStepLock.release()

				self.laborContractsLock.acquire()
				self.laborContractsTotal -= len(laborContractsTemp[endStep])
				del self.laborContracts[endStep]
				self.laborContractsLock.release()
			else:
				for laborContractHash in laborContractsTemp[endStep]:
					self.fulfillLaborContract(laborContractsTemp[endStep][laborContractHash])

		self.fullfilledContracts = True


	def fulfillLaborContract(self, laborContract):
		'''
		Fulfills an existing laborContract
		'''
		contractFulfilled = False
		self.logger.info("Fulfilling {}".format(laborContract))

		if (self.stepNum <= laborContract.endStep):
			if (self.agentId == laborContract.workerId):
				#We are the worker. Send labor to employer
				ticks = laborContract.ticksPerStep
				employerId = laborContract.employerId
				contractHash = laborContract.hash

				if (ticks > self.timeTicks):
					self.logger.error("{}.sendLaborTime({}, {}) failed. Not enough time ticks ({})".format(self.agentId, ticks, employerId, self.timeTicks))
					contractFulfilled = False
				else:
					laborId = "LaborSend_{}(agentId={}, employerId={}, ticks={})".format(contractHash, self.agentId, employerId, ticks, contractHash)
					ticksSpent = self.useTimeTicks(ticks)
					if (ticksSpent):
						payload = {"ticks": ticks, "skillLevel": self.skillLevel}
						laborPacket = NetworkPacket(senderId=self.agentId, destinationId=laborContract.employerId, transactionId=laborId, payload=payload, msgType=PACKET_TYPE.LABOR_TIME_SEND)
						self.sendPacket(laborPacket)
						contractFulfilled = True
					else:
						self.logger.error("{} failed".format(laborId))
						contractFulfilled = False

			if (self.agentId == laborContract.employerId):
				#We are the employer. Send wages
				ticks = laborContract.ticksPerStep
				wage = laborContract.wagePerTick
				netPayment = ticks*wage
				if (self.currencyBalance < netPayment):
					#We don't have enough money to pay this employee. Fire them
					self.logger.warning("Current balance ${} not enough to honor {}. Cancelling this labor contract".format(round(float(self.currencyBalance)/100, 2), laborContract))
					self.cancelLaborContract(laborContract)
					return False

				paymentId = "LaborPayment_{}".format(laborContract.hash)
				paymentSent = self.sendCurrency(netPayment, laborContract.workerId, transactionId=paymentId)
				if not (paymentSent):
					self.logger.error("{} failed".format(paymentId))

				contractFulfilled = paymentSent

				#Update accounting
				if (self.laborExpenseTracking):
					self.laborExpenseLock.acquire()
					self.stepLaborExpense += netPayment
					self.totalLaborExpense += netPayment
					self.laborExpenseLock.release()
		else:
			self.logger.error("{} already expired".format(laborContract))
			contractFulfilled = False

		return contractFulfilled
		

	def receiveJobApplication(self, applicationPayload, senderId):
		'''
		Will pass along job application to agent controller for approval. Will finalizae labor contract if approved.
		Returns True if contract is completed, False if not
		'''
		try:
			laborContract = applicationPayload["laborContract"]
			applicationId = applicationPayload["applicationId"]

			#Evaluate offer
			applicationAccepted = False
			if (self.agentId != laborContract.employerId):
				#This application is for a different employer. Reject it
				applicationAccepted = False
			elif (senderId != laborContract.workerId):
				#This was sent by a third party. Reject it
				applicationAccepted = False
			else:
				#Offer is valid. Evaluate offer
				if (self.controller):
					self.logger.debug("Fowarding {} to controller {}".format(laborContract, self.controller.name))
					applicationAccepted = self.controller.evalJobApplication(laborContract)
				else:
					self.logger.debug("{} does not have a controller. Rejecting {}".format(self.agentId, laborContract))
					applicationAccepted = False

			#Notify counter party of response
			respPayload = {"laborContract": laborContract, "accepted": applicationAccepted}
			responsePacket = NetworkPacket(senderId=self.agentId, destinationId=senderId, msgType=PACKET_TYPE.LABOR_APPLICATION_ACK, payload=respPayload, transactionId=applicationId)
			self.sendPacket(responsePacket)

			#If accepted, add to existing labor contracts
			if (applicationAccepted):
				self.logger.debug("{} accepted".format(laborContract))
				self.laborContractsLock.acquire()
				
				if not (laborContract.endStep in self.laborContracts):
					self.laborContracts[laborContract.endStep] = {}
				self.laborContracts[laborContract.endStep][laborContract.hash] = laborContract
				self.laborContractsTotal += 1

				self.laborContractsLock.release()
			else:
				self.logger.debug("{} rejected".format(laborContract))

			return applicationAccepted

		except Exception as e:
			self.logger.critical("receiveJobApplication() Exception")
			self.logger.critical("selg.agentId={}, applicationPayload={}, senderId={}".format(self.agentId, applicationPayload, senderId))
			raise ValueError("receiveJobApplication() Exception")
		

	def sendJobApplication(self, laborListing):
		'''
		Send a job application to an employer.
		Returns True if the application accepted. Returns False if not
		'''
		if (laborListing.ticksPerStep > (self.ticksPerStep - self.commitedTicks)):
			#This agent does not have the time for the job
			self.logger.error("{} cannot apply for {}. {}/{} ticks per day are already commited".format(self.agentId, laborListing, self.commitedTicks, self.ticksPerStep))
			return False

		try:
			self.logger.debug("{}.sendJobApplication({}) start".format(self.agentId, laborListing))
			applicationAccepted = False

			#Send job application
			laborContract = laborListing.generateLaborContract(workerId=self.agentId, workerSkillLevel=self.skillLevel, startStep=self.stepNum+1)
			applicationId = "LaborApplication_{}(contract={})".format(laborContract.hash, laborContract)
			applicationPayload = {"laborContract": laborContract, "applicationId": applicationId}
			applicationPacket = NetworkPacket(senderId=self.agentId, destinationId=laborListing.employerId, msgType=PACKET_TYPE.LABOR_APPLICATION, payload=applicationPayload, transactionId=applicationId)
			self.sendPacket(applicationPacket)
			
			#Wait for application response
			while not (applicationId in self.responseBuffer):
				time.sleep(self.responsePollTime)
				if (self.agentKillFlag):
					return False
				
			responsePacket = self.responseBuffer[applicationId]

			#Execute trade if request accepted
			employerAccepted = bool(responsePacket.payload["accepted"])
			if (employerAccepted):
				self.logger.info("{} was accepted".format(applicationId))
				#Add contract to contract dict
				self.laborContractsLock.acquire()

				if not (laborContract.endStep in self.laborContracts):
					self.laborContracts[laborContract.endStep] = {}
				self.laborContracts[laborContract.endStep][laborContract.hash] = laborContract
				self.laborContractsTotal += 1
				applicationAccepted = True

				self.laborContractsLock.release()
				
				#Reserve ticks for this job
				self.commitedTicks_nextStepLock.acquire()
				self.commitedTicks_nextStep += laborContract.ticksPerStep
				self.commitedTicks_nextStepLock.release()
			else:
				self.logger.info("{} was rejected".format(applicationId))
				applicationAccepted = False

			#Remove transaction from response buffer
			acquired_responseBufferLock = self.responseBufferLock.acquire(timeout=self.lockTimeout)  #<== acquire responseBufferLock
			if (acquired_responseBufferLock):
				del self.responseBuffer[applicationId]
				self.responseBufferLock.release()  #<== release responseBufferLock
			else:
				self.logger.error("sendJobApplication({}) Lock \"responseBufferLock\" acquisition timeout".format(request))
				transferSuccess = False

			self.logger.debug("{}.sendJobApplication({}) return {}".format(self.agentId, laborListing, applicationAccepted))
			return applicationAccepted

		except Exception as e:
			self.logger.critical("sendJobApplication() Exception")
			self.logger.critical("selg.agentId={}, listing={}".format(self.agentId, laborListing))
			raise ValueError("sendJobApplication() Exception")


	def removeLaborContract(self, laborContract, incommingPacket=None):
		'''
		Remove an existing labor contract
		'''
		self.logger.debug("removeLaborContract({}, incommingPacket={}) start".format(laborContract, incommingPacket))
		
		removalSuccess = True

		endStep = laborContract.endStep
		if (endStep > self.stepNum):
			self.laborContractsLock.acquire()
			if (endStep in self.laborContracts):
				if (laborContract.hash in self.laborContracts[endStep]):
					#Remove contract from contract dict
					del self.laborContracts[laborContract.endStep][laborContract.hash]
					self.laborContractsTotal -= 1

					self.commitedTicks_nextStepLock.acquire()
					self.commitedTicks_nextStep -= laborContract.ticksPerStep
					self.commitedTicks_nextStepLock.release()

					self.laborContractsLock.release()

					removalSuccess = True
				else:
					self.laborContractsLock.release()
					self.logger.error("removeLaborContract() {} not found".format(laborContract))
					removalSuccess = False
			else:
				self.laborContractsLock.release()
				self.logger.error("removeLaborContract() {} not found".format(laborContract))
				removalSuccess = True


		if (incommingPacket):
			if (self.needLaborCancellationAck):
				ackPayload = {"cancellationSuccess": removalSuccess, "laborContract": laborContract}
				cancellationAckPacket = NetworkPacket(senderId=self.agentId, destinationId=incommingPacket.senderId, msgType=PACKET_TYPE.LABOR_CONTRACT_CANCEL_ACK, payload=ackPayload, transactionId=incommingPacket.transactionId)
				self.sendPacket(cancellationAckPacket)

		self.logger.debug("removeLaborContract({}) returned {}".format(laborContract, removalSuccess))
		return removalSuccess


	def cancelLaborContract(self, laborContract):
		'''
		Cancels an existing labor contract. Returns True if successful, false if not
		'''
		self.logger.debug("cancelLaborContract({}) start".format(laborContract))

		endStep = laborContract.endStep
		if (endStep > self.stepNum):
			self.laborContractsLock.acquire()
			if (endStep in self.laborContracts):
				if (laborContract.hash in self.laborContracts[endStep]):
					counterParty = None
					if (laborContract.employerId == self.agentId):
						#We are the employer
						counterParty = laborContract.workerId
					elif (laborContract.workerId == self.agentId):
						#We are the employee
						counterParty = laborContract.employerId
					else:
						self.laborContractsLock.release()
						self.logger.error("cancelLaborContract({}) We are a third party to this contract. We cannot cancel it".format(laborContract))
						return False

					if (counterParty):
						transactionId = "CANCEL_{}".format(laborContract.hash)
						cancelPacket = NetworkPacket(senderId=self.agentId, destinationId=counterParty, msgType=PACKET_TYPE.LABOR_CONTRACT_CANCEL, payload=laborContract, transactionId=transactionId)
						self.sendPacket(cancelPacket)

						cancellationSuccess = True
						if (self.needLaborCancellationAck):
							#Wait for transaction response
							while not (transactionId in self.responseBuffer):
								time.sleep(self.responsePollTime)
								if (self.agentKillFlag):
									self.laborContractsLock.release()
									return False
								
							responsePacket = self.responseBuffer[transactionId]
							cancellationSuccess = bool(responsePacket.payload["cancellationSuccess"])

							#Remove transaction from response buffer
							acquired_responseBufferLock = self.responseBufferLock.acquire(timeout=self.lockTimeout)  #<== acquire responseBufferLock
							if (acquired_responseBufferLock):
								del self.responseBuffer[transactionId]
								self.responseBufferLock.release()  #<== release responseBufferLock
							else:
								self.logger.error("cancelLaborContract({}) Lock \"responseBufferLock\" acquisition timeout".format(laborContract))
								
						self.laborContractsLock.release()
						if (cancellationSuccess):
							self.removeLaborContract(laborContract)
						else:
							self.logger.error("cancelLaborContract({}) Ack from counterpart returned False".format(laborContract))
							return False

					else:
						self.laborContractsLock.release()
						self.logger.error("cancelLaborContract() Could not determine counterParty of {}".format(laborContract))
						return False
				else:
					self.laborContractsLock.release()
					self.logger.warning("cancelLaborContract() {} not found".format(laborContract))
					return False
			else:
				self.laborContractsLock.release()
				self.logger.warning("cancelLaborContract() {} not found".format(laborContract))
				return False


		self.logger.debug("cancelLaborContract({}) completed".format(laborContract))
		return True

	def getNetContractedEmployeeLabor(self):
		'''
		Returns a dictionary of all current labor contracts in which this agent is the employer, organized by skill level
		'''
		self.laborContractsLock.acquire()
		tempLaborContracts = copy.deepcopy(self.laborContracts)
		self.laborContractsLock.release()
		laborContractsList =  []
		for endStep in tempLaborContracts:
			for contractHash in tempLaborContracts[endStep]:
				laborContractsList.append(tempLaborContracts[endStep][contractHash])

		employeeLaborInventory = {}
		for contract in laborContractsList:
			if (contract.employerId == self.agentId):
				if not (contract.workerSkillLevel in employeeLaborInventory):
					employeeLaborInventory[contract.workerSkillLevel] = 0
				employeeLaborInventory[contract.workerSkillLevel] += contract.ticksPerStep

		return employeeLaborInventory

	def getAllLaborContracts(self):
		'''
		Returns a list of all labor contracts
		'''
		self.laborContractsLock.acquire()
		tempLaborContracts = copy.deepcopy(self.laborContracts)
		self.laborContractsLock.release()
		laborContractsList =  []
		for endStep in tempLaborContracts:
			for contractHash in tempLaborContracts[endStep]:
				laborContractsList.append(tempLaborContracts[endStep][contractHash])

		return laborContractsList


	#########################
	# Item Market functions
	#########################
	def updateItemListing(self, itemListing):
		'''
		Update the item marketplace.
		Returns True if succesful, False otherwise
		'''
		self.logger.debug("{}.updateItemListing({}) start".format(self.agentId, itemListing))

		updateSuccess = False
		
		#If we're the seller, send out update to item market
		if (itemListing.sellerId == self.agentId):
			transactionId = itemListing.listingStr
			updatePacket = NetworkPacket(senderId=self.agentId, transactionId=transactionId, msgType=PACKET_TYPE.ITEM_MARKET_UPDATE, payload=itemListing)
			self.sendPacket(updatePacket)
			updateSuccess = True

		else:
			#We are not the item seller
			self.logger.error("{}.updateItemListing({}) failed. {} is not the seller".format(self.agentId, itemListing, self.agentId))
			updateSuccess = False

		#Return status
		self.logger.debug("{}.updateItemListing({}) return {}".format(self.agentId, itemListing, updateSuccess))
		return updateSuccess

	def removeItemListing(self, itemListing):
		'''
		Remove a listing from the item marketplace
		Returns True if succesful, False otherwise
		'''
		self.logger.debug("{}.removeItemListing({}) start".format(self.agentId, itemListing))

		updateSuccess = False

		#If we're the seller, send out update to item market
		if (itemListing.sellerId == self.agentId):
			transactionId = itemListing.listingStr
			updatePacket = NetworkPacket(senderId=self.agentId, transactionId=transactionId, msgType=PACKET_TYPE.ITEM_MARKET_REMOVE, payload=itemListing)
			self.sendPacket(updatePacket)
			updateSuccess = True

		else:
			#We are not the item market or the seller
			self.logger.error("{}.removeItemListing({}) failed. {} is not the itemMarket or the seller".format(self.agentId, itemListing, self.agentId))
			updateSuccess = False

		#Return status
		self.logger.debug("{}.removeItemListing({}) return {}".format(self.agentId, itemListing, updateSuccess))
		return updateSuccess

	def sampleItemListings(self, itemContainer, sampleSize=3, delResponse=True):
		'''
		Returns a list of randomly sampled item listings that match itemContainer
			ItemListing.itemId == itemContainer.id

		List length can be 0 if none are found, or up to sampleSize.
		Returns False if there was an error
		'''
		sampledListings = []
		
		#Send request to itemMarketAgent
		transactionId = "ITEM_MARKET_SAMPLE_{}_{}".format(itemContainer, time.time())
		requestPayload = {"itemContainer": itemContainer, "sampleSize": sampleSize}
		requestPacket = NetworkPacket(senderId=self.agentId, transactionId=transactionId, msgType=PACKET_TYPE.ITEM_MARKET_SAMPLE, payload=requestPayload)
		self.sendPacket(requestPacket)

		#Wait for response from itemMarket
		while not (transactionId in self.responseBuffer):
			time.sleep(self.responsePollTime)
			if (self.agentKillFlag):
				return False
			
		responsePacket = self.responseBuffer[transactionId]
		sampledListings = responsePacket.payload

		#Remove response from response buffer
		if (delResponse):
			acquired_responseBufferLock = self.responseBufferLock.acquire(timeout=self.lockTimeout)  #<== acquire responseBufferLock
			if (acquired_responseBufferLock):
				del self.responseBuffer[transactionId]
				self.responseBufferLock.release()  #<== release responseBufferLock
			else:
				self.logger.error("sampleItemListings() Lock \"responseBufferLock\" acquisition timeout")

		return sampledListings


	def acquireItem(self, itemContainer, sampleSize=5):
		'''
		Will sample the market and acquire the item at the lowest price, if we have enough money.
		Returns the amount of the item that is acquired
		'''
		itemAcquired = 0

		#Sample market
		listingDict = {}
		sampledListings = self.sampleItemListings(itemContainer, sampleSize=sampleSize)
		for itemListing in sampledListings:
			if not (itemListing.unitPrice in listingDict):
				listingDict[itemListing.unitPrice] = []
			listingDict[itemListing.unitPrice].append(itemListing)
		
		if (len(listingDict) > 0):
			priceKeys = list(listingDict.keys())
			priceKeys.sort()
			desiredAmount = itemContainer.quantity
			itemId = itemContainer.id
			while (desiredAmount > 0):
				if (len(priceKeys) > 0):
					price = priceKeys.pop(0)
					for itemListing in listingDict[price]:
						#Stop if we have enough of the item
						if (utils.truncateFloat(desiredAmount, g_ItemQuantityPercision) <= 0):
							break

						#Determine how much we can buy from this seller
						requestedQuantity = utils.truncateFloat(desiredAmount, g_ItemQuantityPercision)
						if (desiredAmount > itemListing.maxQuantity):
							requestedQuantity = itemListing.maxQuantity

						#Send trade request
						totalCost = int(price*requestedQuantity)+2
						if (totalCost <= self.currencyBalance):
							tradeRequest = TradeRequest(sellerId=itemListing.sellerId, buyerId=self.agentId, currencyAmount=totalCost, itemPackage=ItemContainer(itemId, requestedQuantity))
							self.logger.debug("Acquiring item | {}".format(tradeRequest))
							tradeCompleted = self.sendTradeRequest(request=tradeRequest, recipientId=itemListing.sellerId)
							if (tradeCompleted):
								desiredAmount -= requestedQuantity
								itemAcquired += requestedQuantity
						else:
							self.logger.warning("Could not acquire {} {}. Current balance ${} not enough at current unit price ${}".format(requestedQuantity, itemId, self.currencyBalance/100, price/100))
							return itemAcquired
				else:
					if (desiredAmount > 0):
						self.logger.warning("Could not acquire enough {}. Could only get {}".format(itemId, itemAcquired))
						self.logger.debug("listingDict = {}".format(listingDict))
						return itemAcquired

		else:
			self.logger.warning("Could not acquire {}. No sellers found".format(itemContainer))
			itemAcquired = 0
			return itemAcquired

		if not (itemAcquired):
			self.logger.warning("Could not acquire {}".format(itemContainer))
			self.logger.debug("listingDict = {}".format(listingDict))

		return itemAcquired


	#########################
	# Labor Market functions
	#########################
	def updateLaborListing(self, laborListing):
		'''
		Update the labor marketplace.
		Returns True if succesful, False otherwise
		'''
		self.logger.debug("{}.updateLaborListing({}) start".format(self.agentId, laborListing))

		updateSuccess = False
		
		#If we're the employer, send out update to labor market
		if (laborListing.employerId == self.agentId):
			transactionId = laborListing.listingStr
			updatePacket = NetworkPacket(senderId=self.agentId, transactionId=transactionId, msgType=PACKET_TYPE.LABOR_MARKET_UPDATE, payload=laborListing)
			self.sendPacket(updatePacket)
			updateSuccess = True

		else:
			#We are not the employer
			self.logger.error("{}.updateLaborListing({}) failed. {} is not the employer".format(self.agentId, itemListing, self.agentId))
			updateSuccess = False

		#Return status
		self.logger.debug("{}.updateLaborListing({}) return {}".format(self.agentId, laborListing, updateSuccess))
		return updateSuccess

	def removeLaborListing(self, laborListing):
		'''
		Remove a listing from the labor marketplace
		Returns True if succesful, False otherwise
		'''
		self.logger.debug("{}.removeLaborListing({}) start".format(self.agentId, laborListing))

		updateSuccess = False

		#If we're the seller, send out update to item market
		if (laborListing.employerId == self.agentId):
			transactionId = laborListing.listingStr
			updatePacket = NetworkPacket(senderId=self.agentId, transactionId=transactionId, msgType=PACKET_TYPE.LABOR_MARKET_REMOVE, payload=laborListing)
			self.sendPacket(updatePacket)
			updateSuccess = True

		else:
			#We are not the employer
			self.logger.error("{}.removeLaborListing({}) failed. {} is not the itemMarket or the seller".format(self.agentId, laborListing, self.agentId))
			updateSuccess = False

		#Return status
		self.logger.debug("{}.removeLaborListing({}) return {}".format(self.agentId, laborListing, updateSuccess))
		return updateSuccess

	def sampleLaborListings(self, sampleSize=3, maxSkillLevel=-1, minSkillLevel=0, delResponse=True):
		'''
		Returns a list of sampled labor listings that agent qualifies for (listing.minSkillLevel <= agent.skillLevel).
		Will sample listings in order of decreasing skill level, returning the highest possible skill-level listings. Samples are randomized within skill levels.
		'''
		sampledListings = []
		
		tempMaxSkillLevel = self.skillLevel
		if (maxSkillLevel != -1):
			#Has been set explicitly. Override agent skill level
			tempMaxSkillLevel = maxSkillLevel

		#Send request to itemMarketAgent
		transactionId = "LABOR_MARKET_SAMPLE_{}_{}".format(self.agentId, time.time())
		requestPayload = {"maxSkillLevel": tempMaxSkillLevel, "minSkillLevel": minSkillLevel, "sampleSize": sampleSize}
		requestPacket = NetworkPacket(senderId=self.agentId, transactionId=transactionId, msgType=PACKET_TYPE.LABOR_MARKET_SAMPLE, payload=requestPayload)
		self.sendPacket(requestPacket)

		#Wait for response from itemMarket
		while not (transactionId in self.responseBuffer):
			time.sleep(self.responsePollTime)
			if (self.agentKillFlag):
				return []
			
		responsePacket = self.responseBuffer[transactionId]
		sampledListings = responsePacket.payload

		#Remove response from response buffer
		if (delResponse):
			acquired_responseBufferLock = self.responseBufferLock.acquire(timeout=self.lockTimeout)  #<== acquire responseBufferLock
			if (acquired_responseBufferLock):
				del self.responseBuffer[transactionId]
				self.responseBufferLock.release()  #<== release responseBufferLock
			else:
				self.logger.error("sampleLaborListings() Lock \"responseBufferLock\" acquisition timeout")

		return sampledListings

	#########################
	# Land Market functions
	#########################
	def updateLandListing(self, landListing):
		'''
		Update the land marketplace.
		Returns True if succesful, False otherwise
		'''
		self.logger.debug("{}.updateLandListing({}) start".format(self.agentId, landListing))

		updateSuccess = False
		
		#If we're the seller, send out update to land market
		if (landListing.sellerId == self.agentId):
			transactionId = landListing.listingStr
			updatePacket = NetworkPacket(senderId=self.agentId, transactionId=transactionId, msgType=PACKET_TYPE.LAND_MARKET_UPDATE, payload=landListing)
			self.sendPacket(updatePacket)
			updateSuccess = True

		else:
			#We are not the land seller
			self.logger.error("{}.updateLandListing({}) failed. {} is not the seller".format(self.agentId, landListing, self.agentId))
			updateSuccess = False

		#Return status
		self.logger.debug("{}.updateLandListing({}) return {}".format(self.agentId, landListing, updateSuccess))
		return updateSuccess

	def removeLandListing(self, landListing):
		'''
		Remove a listing from the land marketplace
		Returns True if succesful, False otherwise
		'''
		self.logger.debug("{}.removeLandListing({}) start".format(self.agentId, landListing))

		updateSuccess = False

		#If we're the seller, send out update to land market
		if (landListing.sellerId == self.agentId):
			transactionId = landListing.listingStr
			updatePacket = NetworkPacket(senderId=self.agentId, transactionId=transactionId, msgType=PACKET_TYPE.ITEM_MARKET_REMOVE, payload=landListing)
			self.sendPacket(updatePacket)
			updateSuccess = True

		else:
			#We are not the land market or the seller
			self.logger.error("{}.removeLandListing({}) failed. {} is not the itemMarket or the seller".format(self.agentId, landListing, self.agentId))
			updateSuccess = False

		#Return status
		self.logger.debug("{}.removeLandListing({}) return {}".format(self.agentId, landListing, updateSuccess))
		return updateSuccess

	def sampleLandListings(self, allocation, hectares, sampleSize=3, delResponse=True):
		'''
		Returns a list of randomly sampled item listings where
			LandListing.allocation == allocation
			LandListing.hectares >= hectares

		List length can be 0 if none are found, or up to sampleSize.
		Returns False if there was an error
		'''
		sampledListings = []
		
		#Send request to itemMarketAgent
		transactionId = "LAND_MARKET_SAMPLE_{}_{}_{}".format(allocation, hectares, time.time())
		requestPayload = {"allocation": allocation, "hectares": hectares, "sampleSize": sampleSize}
		requestPacket = NetworkPacket(senderId=self.agentId, transactionId=transactionId, msgType=PACKET_TYPE.LAND_MARKET_SAMPLE, payload=requestPayload)
		self.sendPacket(requestPacket)

		#Wait for response from itemMarket
		while not (transactionId in self.responseBuffer):
			time.sleep(self.responsePollTime)
			if (self.agentKillFlag):
				return []
			
		responsePacket = self.responseBuffer[transactionId]
		sampledListings = responsePacket.payload

		#Remove response from response buffer
		if (delResponse):
			acquired_responseBufferLock = self.responseBufferLock.acquire(timeout=self.lockTimeout)  #<== acquire responseBufferLock
			if (acquired_responseBufferLock):
				del self.responseBuffer[transactionId]
				self.responseBufferLock.release()  #<== release responseBufferLock
			else:
				self.logger.error("sampleLandListings() Lock \"responseBufferLock\" acquisition timeout")

		return sampledListings

	#########################
	# Utility functions
	#########################
	def getMarginalUtility(self, itemId):
		'''
		Returns the current marginal utility of an itemId
		'''
		quantity = 1
		if (itemId in self.inventory):
			quantity = self.inventory[itemId].quantity

		#Override quantity if this item is food and nutrition tracking is enabled
		if (self.enableNutrition):
			if (itemId in self.nutritionalDict):
				quantity += self.nutritionTracker.getQuantityConsumed(self, itemId)

		utilityFunction = self.utilityFunctions[itemId]
		try:
			marginalUtility = utilityFunction.getMarginalUtility(quantity)
		except:
			self.logger.critical("getMarginalUtility({}) quantity={}".format(itemId, quantity))

		return utilityFunction.getMarginalUtility(quantity)

	#########################
	# Time functions
	#########################
	def useTimeTicks(self, amount):
		'''
		Consume the specified amount of time ticks. 
		If we run out in the process, set the tickBlocked flag and send a TICK_BLOCKED packet to sim manager.

		Returns True if successful, False if not
		'''
		self.logger.debug("{}.useTimeTicks({}) start".format(self.agentId, amount))
		useSuccess = False

		if (amount > 0):
			acquired_timeTickLock = self.timeTickLock.acquire(timeout=self.lockTimeout)  #<== timeTickLock acquire
			if (acquired_timeTickLock):
				if (self.timeTicks >= amount):
					#We have enough ticks. Decrement tick counter
					self.logger.debug("Using {} time ticks".format(amount))
					self.timeTicks -= amount
					self.logger.debug("Time tick balance = {}".format(self.timeTicks))
					useSuccess = True

					self.timeTickLock.release()  #<== timeTickLock release

					#Advance land allocation queue
					self.landAllocationQueue.useTimeTicks(amount)

					if (self.timeTicks <= 0):
						#We are out of time ticks. Set blocked flag
						acquired_tickBlockFlag_Lock = self.tickBlockFlag_Lock.acquire(timeout=self.lockTimeout)  #<== tickBlockFlag_Lock acquire
						if (acquired_tickBlockFlag_Lock):
							self.tickBlockFlag = True
							self.tickBlockFlag_Lock.release()  #<== tickBlockFlag_Lock release
						else:
							self.logger.error("TICK_GRANT tickBlockFlag_Lock acquire timeout")

						#Move labor received in this step into the available labor for next step
						self.laborInventoryLock.acquire()
						self.nextLaborInventoryLock.acquire()

						self.laborInventory = self.nextLaborInventory.copy()
						self.nextLaborInventory = {}
						self.logger.debug("laborInventory = {}".format(self.laborInventory))

						self.laborInventoryLock.release()
						self.nextLaborInventoryLock.release()

						#Send blocked signal to sim manager
						self.logger.debug("We're tick blocked. Sending TICK_BLOCKED to simManager")
						if (self.needTickBlockAck):
							tickBlockedId = "TickBlocked.{}.{}".format(self.agentId, self.stepNum)
							while not (tickBlockedId in self.responseBuffer):
								tickBlockPacket = NetworkPacket(senderId=self.agentId, msgType=PACKET_TYPE.TICK_BLOCKED, transactionId=tickBlockedId)
								self.sendPacket(tickBlockPacket)
								time.sleep(self.responsePollTime)

							self.responseBufferLock.acquire()
							del self.responseBuffer[tickBlockedId]
							self.responseBufferLock.release()
						else:
							tickBlockPacket = NetworkPacket(senderId=self.agentId, msgType=PACKET_TYPE.TICK_BLOCKED)
							self.sendPacket(tickBlockPacket)

				else:
					#We do not have enought time ticks
					self.logger.error("Cannot use {} time ticks. Only have {} available".format(amount, self.timeTicks))
					useSuccess = False

					self.timeTickLock.release()  #<== timeTickLock release
			else:
				#Lock timout
				self.logger.error("{}.useTimeTicks({}) timeTickLock acquire timeout".format(self.agentId, amount))
				useSuccess = False
		else:
			useSuccess = False

		self.logger.debug("{}.useTimeTicks({}) return {}".format(self.agentId, amount, useSuccess))
		return useSuccess


	def relinquishTimeTicks(self):
		'''
		Relinquish all time ticks for this sim step.
		Returns True if successful, False if not
		'''
		self.logger.debug("{}.relinquishTimeTicks() start".format(self.agentId))

		self.logger.debug("{}.relinquishTimeTicks() waiting for time commitments to complete".format(self.agentId))
		#Wait for labor contracts to be fullfilled
		while not (self.fullfilledContracts):
			time.sleep(self.responsePollTime)
			if (self.agentKillFlag):
				return False

		#Wait for agent to finish eating
		while (self.eating):
			time.sleep(self.responsePollTime)
			if (self.agentKillFlag):
				return False

		self.logger.debug("{}.relinquishTimeTicks() time commitments completed".format(self.agentId))

		#Use all remaining time ticks
		acquired_timeTickLock = self.timeTickLock.acquire(timeout=self.lockTimeout)  #<== timeTickLock acquire
		amount = self.timeTicks
		if (amount > 0):
			if (acquired_timeTickLock):
				self.logger.debug("Using {} time ticks".format(amount))
				self.timeTicks -= amount
				self.logger.debug("Time tick balance = {}".format(self.timeTicks))
				useSuccess = True

				self.timeTickLock.release()  #<== timeTickLock release

				#Advance land allocation queue
				self.landAllocationQueue.useTimeTicks(amount)

				if (self.timeTicks <= 0):
					self.logger.debug("We're tick blocked. Setting tickBlockFlag to True")
					#We are out of time ticks. Set blocked flag
					acquired_tickBlockFlag_Lock = self.tickBlockFlag_Lock.acquire(timeout=self.lockTimeout)  #<== tickBlockFlag_Lock acquire
					if (acquired_tickBlockFlag_Lock):
						self.tickBlockFlag = True
						self.tickBlockFlag_Lock.release()  #<== tickBlockFlag_Lock release
					else:
						self.logger.error("relinquishTimeTicks() tickBlockFlag_Lock acquire timeout")

					#Move labor received in this step into the available labor for next step
					self.laborInventoryLock.acquire()
					self.nextLaborInventoryLock.acquire()

					self.laborInventory = self.nextLaborInventory.copy()
					self.nextLaborInventory = {}
					self.logger.debug("laborInventory = {}".format(self.laborInventory))

					self.laborInventoryLock.release()
					self.nextLaborInventoryLock.release()

					#Send blocked signal to sim manager
					self.logger.debug("We're tick blocked. Sending TICK_BLOCKED to simManager")
					if (self.needTickBlockAck):
						tickBlockedId = "TickBlocked.{}.{}".format(self.agentId, self.stepNum)
						while not (tickBlockedId in self.responseBuffer):
							tickBlockPacket = NetworkPacket(senderId=self.agentId, msgType=PACKET_TYPE.TICK_BLOCKED, transactionId=tickBlockedId)
							self.sendPacket(tickBlockPacket)
							time.sleep(self.responsePollTime)

						self.responseBufferLock.acquire()
						del self.responseBuffer[tickBlockedId]
						self.responseBufferLock.release()
					else:
						tickBlockPacket = NetworkPacket(senderId=self.agentId, msgType=PACKET_TYPE.TICK_BLOCKED)
						self.sendPacket(tickBlockPacket)


			else:
				#Lock timout
				self.logger.error("{}.relinquishTimeTicks({}) timeTickLock acquire timeout".format(self.agentId, amount))
				useSuccess = False
		else:
			self.timeTickLock.release()  #<== timeTickLock release

		return self.useTimeTicks(self.timeTicks)


	def subcribeTickBlocking(self):
		'''
		Subscribes this agent as a tick blocker with the sim manager
		'''
		self.logger.info("Subscribing as a tick blocker")
		tickBlockPacket = NetworkPacket(senderId=self.agentId, msgType=PACKET_TYPE.TICK_BLOCK_SUBSCRIBE)
		self.sendPacket(tickBlockPacket)


	#########################
	# Food functions
	#########################
	def enableHunger(self, autoEat=True):
		'''
		Sets the enableNutrition flag to True, which means this agent now has to consume food.

		If autoEat is set to True, agent will automatically feed itself at the beginning of each step
		'''
		self.enableNutrition = True
		self.nutritionTracker = NutritionTracker(self)
		self.autoEatFlag = autoEat


	def autoEat(self):
		'''
		Will create a meal plan, acquire the needed food, then consume the food.
		Returns True if successful, False if not
		'''
		self.logger.debug("autoEat() start")

		mealPlan = self.nutritionTracker.getAutoMeal()
		self.logger.debug("autoEat() mealPlan = {}".format(mealPlan))

		#Acquire needed food
		acquisitionSuccess = True
		for foodId in mealPlan:
			foodContainer = ItemContainer(foodId, mealPlan[foodId])
			foodAcquired = self.acquireItem(foodContainer, sampleSize=5)
			if (foodAcquired > 0):
				self.consumeItem(ItemContainer(foodId, foodAcquired))

		if not (acquisitionSuccess):
			self.logger.warning("autoEat() Could not acquire all ingredients for meal plan {}".format(mealPlan))

		self.eating = False

		return acquisitionSuccess

	#########################
	# Misc functions
	#########################
	def handleInfoRequest(self, infoRequest):
		if (infoRequest.agentFilter in self.agentId) or (len(infoRequest.agentFilter) == 0):
			infoKey = infoRequest.infoKey
			if (infoKey == "currencyBalance"):
				infoRequest.info = self.currencyBalance
			if (infoKey == "inventory"):
				infoRequest.info = self.inventory
			if (infoKey == "debtBalance"):
				infoRequest.info = self.debtBalance
			if (infoKey == "acountingStats"):
				infoRequest.info = self.getAccountingStats()
			if (infoKey == "laborContracts"):
				infoRequest.info = self.laborContracts
			
			infoRespPacket = NetworkPacket(senderId=self.agentId, destinationId=infoRequest.requesterId, msgType=PACKET_TYPE.INFO_RESP, payload=infoRequest)
			self.sendPacket(infoRespPacket)
		else:
			self.logger.warning("Received infoRequest for another agent {}. Ignoring it".format(infoRequest))

	def saveCheckpoint(self, filePath=None):
		'''
		Saves current agent state into a checkpoint file. Will determine it's own filepath if filePath is not defined
		'''
		self.logger.info("saveCheckpoint() start")
		checkpointObj = AgentCheckpoint(self)

		checkpointFileName = "{}.{}.checkpoint.pickle".format(self.agentId, self.agentType)
		outputPath = os.path.join(self.outputDir, "CHECKPOINT", checkpointFileName)
		if (filePath):
			outputPath = filePath
		utils.createFolderPath(outputPath)

		self.logger.info("saveCheckpoint() Saving checkpoint to \"{}\"".format(outputPath))
		with open(outputPath, "wb") as pickleFile:
			pickle.dump(checkpointObj, pickleFile)

	def loadCheckpoint(self, filePath=None):
		'''
		Attempts to load agent state from checkpoint file. Returns true if successful, False if not
		Will try to find the checkpoint file if filePath is not specified.
		'''
		self.logger.info("loadCheckpoint(filePath={}) start".format(filePath))

		#Determine checkpoint file path
		checkpointFileName = "{}.{}.checkpoint.pickle".format(self.agentId, self.agentType)
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
				if (isinstance(checkpointObj, AgentCheckpoint)):
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


	def commitSuicide(self):
		'''
		Agent will send a KILL_AGENT packet to itself and it's controller
		'''
		killPacket = NetworkPacket(senderId=self.agentId, destinationId=self.agentId, msgType=PACKET_TYPE.KILL_PIPE_AGENT)
		self.sendPacket(killPacket)


	def startController(self):
		'''
		Agent will send a CONTROLLER_START packet to it's controller
		'''
		controllerStartPacket = NetworkPacket(senderId=self.agentId, destinationId=self.agentId, msgType=PACKET_TYPE.CONTROLLER_START)
		if (self.controller):
			if (not self.controllerStart):
				self.controllerStart = True
				controllerThread =  threading.Thread(target=self.controller.controllerStart, args=(controllerStartPacket, ))
				controllerThread.start()
				self.spawnedThreads.append(controllerThread)
				return True
			return True
		else:
			warning = "Agent does not have controller to start"
			self.logger.error(warning)
			return False			


	def __str__(self):
		return str(self.info)

'''
Item Json format
{
	"id": <str> itemId,
	"unit": <str> itemUnit,
	"category": <str> itemCategory,
	"ProductionLearningCurve": {   #How quickly do new firms approach perfect production efficiency
		"StartingEfficiency": <float>,  #What is the starting efficiency for new firms producing this item
		"HalfLifeQuant": <float> or <int>   #How many units of this item does a firm have to produce to cut their current production innefficiency in half
	},
	"ProductionInputs": {   #What is required to produce this item, assuming perfect production efficiency
		"FixedCosts": {
			"FixedLandCosts": {
				"MaxYield": <float> or <bool>, #How many units of itemId can 1 unit of land (1 hectare) produce in 1 time tick (1 hour). Can be set to <bool> false if it does not apply.
				"MinQuantity": <float>,        #What is the smallest amount of land you need before you can start production.
				"Quantized": <bool>,           #If True, land can only be productive in increments of MinQuantity
				"AllocationTime": <int>        #How many ticks of time must you wait before you can allocate the land to start producting itemId. Basically production setup time
			},
			"FixedItemCosts": {
				<str> costItemId_f0: {
					"MaxYield": <float> or <bool>, #How many units of itemId can 1 unit of costItemId_f0 produce in 1 time tick (1 hour). Can be set to <bool> false if it does not apply.
					"MinQuantity": <float>,        #What is the smallest amount of costItemId_f0 you need before you can start production. (ex. 1/2 of a tractor is not particularly useful)
					"Quantized": <bool>            #If True, costItemId_f0 can only be productive in increments of MinQuantity (ex. After buying 1 whole tractor, buying 0.5 more tractors does not help you)
				},
				...
			},
			"FixedLaborCosts": {
				<float> MinSkillLevel_a: <int> ticks, #How many ticks per step of labor with skill >= MinSkillLevel_a it takes to enable production of itemId
				<float> MinSkillLevel_b: <int> ticks, #How many ticks per step of labor with skill >= MinSkillLevel_b it takes to enable production of itemId
				...
			}
		},
		"VariableCosts": {
			"VariableItemCosts": {
				<str> costItemId_v0: <float>, #How many units of costItemId_v0 does it take to produce 1 unit of itemId
				<str> costItemId_v1: <float>, #How many units of costItemId_v1 does it take to produce 1 unit of itemId
				...
			},
			"VariableLaborCosts": {
				<float> MinSkillLevel_a: <float> ticks, #How many ticks of labor with skill >= MinSkillLevel_a it takes to produce 1 unit of itemId
				<float> MinSkillLevel_b: <float> ticks, #How many ticks of labor with skill >= MinSkillLevel_b it takes to produce 1 unit of itemId
				...
			}
		}
	},
	"UtilityFunctions": {   #How much utility do household get from one unit of this item
		"BaseUtility": {
			"mean": <float>,
			"stdDev": <float>
		},
		"DiminishingFactor": {
			"mean": <float>,
			"stdDev": <float>
		}
	}
}
'''