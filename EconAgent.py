'''
This file contains:
	-Generic Agent class
	-item UtilityFunction class
	-item ProductionFunction class
'''

import math
import threading
import logging
import time
import os
import random
import multiprocessing

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
	Used to calculate production costs for items
	'''
	def __init__(self):
		pass


#######################
# Economic Agent
#######################

class AgentInfo:
	def __init__(self, agentId, agentType):
		self.agentId = agentId
		self.agentType = agentType

	def __str__(self):
		return "AgentInfo(ID={}, Type={})".format(self.agentId, self.agentType)


def getAgentController(agent, logFile=True, fileLevel="INFO"):
	'''
	Instantiates an agent controller, dependant on the agentType
	'''
	agentInfo = agent.info

	#Test controllers
	if (agentInfo.agentType == "PushoverController"):
		#Return pushover controller
		return PushoverController(agent, logFile=logFile, fileLevel=fileLevel)
	if (agentInfo.agentType == "TestSnooper"):
		#Return TestSnooper controller
		return TestSnooper(agent, logFile=logFile, fileLevel=fileLevel)
	if (agentInfo.agentType == "TestSeller"):
		#Return TestSeller controller
		return TestSeller(agent, logFile=logFile, fileLevel=fileLevel)
	if (agentInfo.agentType == "TestBuyer"):
		#Return TestBuyer controller
		return TestBuyer(agent, logFile=logFile, fileLevel=fileLevel)
	if (agentInfo.agentType == "TestEmployer"):
		#Return TestEmployer controller
		return TestEmployer(agent, logFile=logFile, fileLevel=fileLevel)
	if (agentInfo.agentType == "TestWorker"):
		#Return TestWorker controller
		return TestWorker(agent, logFile=logFile, fileLevel=fileLevel)

	#Unhandled agent type. Return default controller
	return None


class AgentSeed:
	'''
	Because thread locks cannot be pickled, you can't pass Agent instances to other processes.

	So the AgentSeed class is a pickle-safe info container that can be passed to child processes.
	The process can then call AgentSeed.spawnAgent() to instantiate an Agent obj.
	'''
	def __init__(self, agentId, agentType, ticksPerStep=24, settings={}, simManagerId=None, itemDict=None, allAgentDict=None, logFile=True, fileLevel="INFO"):
		self.agentInfo = AgentInfo(agentId, agentType)
		self.ticksPerStep = ticksPerStep
		self.settings = settings
		self.simManagerId = simManagerId
		self.itemDict = itemDict
		self.allAgentDict = allAgentDict
		self.logFile = logFile
		self.fileLevel = fileLevel

		networkPipeRecv, agentPipeSend = multiprocessing.Pipe()
		agentPipeRecv, networkPipeSend = multiprocessing.Pipe()

		self.networkLink = Link(sendPipe=networkPipeSend, recvPipe=networkPipeRecv)
		self.agentLink = Link(sendPipe=agentPipeSend, recvPipe=agentPipeRecv)

	def spawnAgent(self):
		return Agent(self.agentInfo, simManagerId=self.simManagerId, ticksPerStep=self.ticksPerStep, settings=self.settings, itemDict=self.itemDict, allAgentDict=self.allAgentDict, networkLink=self.agentLink, logFile=self.logFile, fileLevel=self.fileLevel)

	def __str__(self):
		return "AgentSeed({})".format(self.agentInfo)


class Agent:
	'''
	The Agent class is a generic class used by all agents running in a simulation.

	The behavior of any given agent instance is determined by it's controller, which handles all decision making.
	The Agent class is instead mostly responsible for the controller's interface to the rest of the simulation.

	The Agent class handles:
		-item transfers
		-currency transfers
		-trade execution
		-currency balance
		-item inventory
		-ConnectionNetwork interactions
		-item utility calculations
		-marketplace updates and polling

	'''
	def __init__(self, agentInfo, simManagerId=None, ticksPerStep=24, settings={}, itemDict=None, allAgentDict=None, networkLink=None, logFile=True, fileLevel="INFO", controller=None):
		self.info = agentInfo
		self.agentId = agentInfo.agentId
		self.agentType = agentInfo.agentType
		
		self.simManagerId = simManagerId

		self.logger = utils.getLogger("{}:{}".format(__name__, self.agentId), logFile=logFile, outputdir=os.path.join("LOGS", "Agent_Logs"), fileLevel=fileLevel)
		self.logger.info("{} instantiated".format(self.info))

		self.lockTimeout = 5

		#Pipe connections to the connection network
		self.networkLink = networkLink
		self.networkSendLock = threading.Lock()
		self.responseBuffer = {}
		self.responseBufferLock = threading.Lock()

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
		self.laborContractsLock = threading.Lock()
		self.laborInventory = {}  #Keep track of all the labor supplied to a firm for this step
		self.laborInventoryLock = threading.Lock()
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
		self.utilityFunctions = {}
		if (itemDict):
			for itemName in itemDict:
				itemFunctionParams = itemDict[itemName]["UtilityFunctions"]
				self.utilityFunctions[itemName] = UtilityFunction(itemFunctionParams["BaseUtility"]["mean"], itemFunctionParams["BaseUtility"]["stdDev"], itemFunctionParams["DiminishingFactor"]["mean"], itemFunctionParams["DiminishingFactor"]["stdDev"])

		#Instantiate AI agent controller
		if (controller):
			self.controller = controller
		else:	
			self.controller = getAgentController(self, logFile=logFile, fileLevel=fileLevel)
			if (not self.controller):
				self.logger.warning("No controller was instantiated")
		self.controllerStart = False

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
			incommingPacket = self.networkLink.recvPipe.recv()
			self.logger.info("INBOUND {}".format(incommingPacket))
			if ((incommingPacket.msgType == "KILL_PIPE_AGENT") or (incommingPacket.msgType == "KILL_ALL_BROADCAST")):
				#Kill the network pipe before exiting monitor
				killPacket = NetworkPacket(senderId=self.agentId, destinationId=self.agentId, msgType="KILL_PIPE_NETWORK")
				self.sendPacket(killPacket)
				self.logger.info("Killing networkLink {}".format(self.networkLink))
				break

			#Handle incoming acks
			elif ("_ACK" in incommingPacket.msgType):
				#Place incoming acks into the response buffer
				acquired_responseBufferLock = self.responseBufferLock.acquire(timeout=self.lockTimeout)  #<== acquire responseBufferLock
				if (acquired_responseBufferLock):
					self.responseBuffer[incommingPacket.transactionId] = incommingPacket
					self.responseBufferLock.release()  #<== release responseBufferLock
				else:
					self.logger.error("monitorNetworkLink() Lock \"responseBufferLock\" acquisition timeout")
					break

			#Handle errors
			elif ("ERROR" in incommingPacket.msgType):
				self.logger.error("{} {}".format(incommingPacket, incommingPacket.payload))

			#Handle controller messages
			elif ((incommingPacket.msgType == "CONTROLLER_START") or (incommingPacket.msgType == "CONTROLLER_START_BROADCAST")):
				if (self.controller):
					if (not self.controllerStart):
						self.controllerStart = True
						controllerThread =  threading.Thread(target=self.controller.controllerStart, args=(incommingPacket, ))
						controllerThread.start()
				else:
					warning = "Agent does not have controller to start"
					self.logger.warning(warning)
					responsePacket = NetworkPacket(senderId=self.agentId, destinationId=incommingPacket.senderId, msgType="ERROR_CONTROLLER_START", payload=warning)

			elif ((incommingPacket.msgType == "CONTROLLER_MSG") or (incommingPacket.msgType == "CONTROLLER_MSG_BROADCAST") or (incommingPacket.msgType == "SNOOP") or (incommingPacket.msgType == "INFO_RESP")):
				#Foward packet to controller
				if (self.controller):
					self.logger.debug("Fowarding msg to controller {}".format(incommingPacket))
					controllerThread =  threading.Thread(target=self.controller.receiveMsg, args=(incommingPacket, ))
					controllerThread.start()
				else:
					self.logger.error("Agent {} does not have a controller. Ignoring {}".format(self.agentId, incommingPacket))

			#Handle incoming payments
			elif (incommingPacket.msgType == "CURRENCY_TRANSFER"):
				amount = incommingPacket.payload["cents"]
				transferThread =  threading.Thread(target=self.receiveCurrency, args=(amount, incommingPacket))
				transferThread.start()

			#Handle incoming items
			elif (incommingPacket.msgType == "ITEM_TRANSFER"):
				itemPackage = incommingPacket.payload["item"]
				transferThread =  threading.Thread(target=self.receiveItem, args=(itemPackage, incommingPacket))
				transferThread.start()

			#Handle incoming trade requests
			elif (incommingPacket.msgType == "TRADE_REQ"):
				tradeRequest = incommingPacket.payload
				transferThread =  threading.Thread(target=self.receiveTradeRequest, args=(tradeRequest, incommingPacket.senderId))
				transferThread.start()

			#Handle incoming job applications
			elif (incommingPacket.msgType == "LABOR_APPLICATION"):
				applicationPayload = incommingPacket.payload
				contractThread =  threading.Thread(target=self.receiveJobApplication, args=(applicationPayload, incommingPacket.senderId))
				contractThread.start()

			#Handle incoming labor
			elif (incommingPacket.msgType == "LABOR_TIME_SEND"):
				laborTicks = incommingPacket.payload["ticks"]
				skillLevel = incommingPacket.payload["skillLevel"]
				self.laborInventoryLock.acquire()
				if not (skillLevel in self.laborInventory):
					self.laborInventory[skillLevel] = 0
				self.laborInventory[skillLevel] += laborTicks
				self.laborInventoryLock.release()

			#Handle incoming information requests
			elif (incommingPacket.msgType == "INFO_REQ"):
				infoRequest = incommingPacket.payload
				infoThread =  threading.Thread(target=self.handleInfoRequest, args=(infoRequest, ))
				infoThread.start()

			#Hanle incoming tick grants
			elif ((incommingPacket.msgType == "TICK_GRANT") or (incommingPacket.msgType == "TICK_GRANT_BROADCAST")):
				ticksGranted = incommingPacket.payload
				acquired_timeTickLock = self.timeTickLock.acquire(timeout=self.lockTimeout)  #<== timeTickLock acquire
				if (acquired_timeTickLock):
					self.timeTicks += ticksGranted
					self.timeTickLock.release()  #<== timeTickLock release
					self.stepNum += 1

					acquired_tickBlockFlag_Lock = self.tickBlockFlag_Lock.acquire(timeout=self.lockTimeout)  #<== tickBlockFlag_Lock acquire
					if (acquired_tickBlockFlag_Lock):
						self.tickBlockFlag = False
						self.tickBlockFlag_Lock.release()  #<== tickBlockFlag_Lock release
					else:
						self.logger.error("TICK_GRANT tickBlockFlag_Lock acquire timeout")

				else:
					self.logger.error("TICK_GRANT timeTickLock acquire timeout")

				#Update time tick commitments
				self.commitedTicks_nextStepLock.acquire()
				self.commitedTicksLock.acquire()
				self.commitedTicks += self.commitedTicks_nextStep
				self.commitedTicks_nextStep = 0
				self.commitedTicksLock.release()
				self.commitedTicks_nextStepLock.release()

				#Fulfill labor contracts
				contractThread = threading.Thread(target=self.fulfillAllLaborContracts)
				contractThread.start()

				#Foward tick grant to controller
				if (self.controller):
					controllerGrantThread = threading.Thread(target=self.controller.receiveMsg, args=(incommingPacket, ))
					controllerGrantThread.start()

			#Unhandled packet type
			else:
				self.logger.error("Received packet type {}. Ignoring packet {}".format(incommingPacket.msgType, incommingPacket))

		self.logger.info("Ending networkLink monitor".format(self.networkLink))


	def sendPacket(self, packet):
		acquired_networkSendLock = self.networkSendLock.acquire(timeout=self.lockTimeout)
		if (acquired_networkSendLock):
			self.logger.info("OUTBOUND {}".format(packet))
			self.networkLink.sendPipe.send(packet)
			self.networkSendLock.release()
		else:
			self.logger.error("{}.sendPacket() Lock networkSendLock acquire timeout".format(self.agentId))


	#########################
	# Currency transfer functions
	#########################
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
			if (incommingPacket):
				respPayload = {"paymentId": incommingPacket.payload["paymentId"], "transferSuccess": transferSuccess}
				responsePacket = NetworkPacket(senderId=self.agentId, destinationId=incommingPacket.senderId, msgType="CURRENCY_TRANSFER_ACK", payload=respPayload, transactionId=incommingPacket.transactionId)
				self.sendPacket(responsePacket)

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
				transferPacket = NetworkPacket(senderId=self.agentId, destinationId=recipientId, msgType="CURRENCY_TRANSFER", payload=transferPayload, transactionId=paymentId)
				self.sendPacket(transferPacket)

				#Wait for transaction response
				while not (paymentId in self.responseBuffer):
					time.sleep(0.0001)
					pass
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
	# Item transfer functions
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
				else:
					self.inventory[itemId] += itemPackage

				self.inventoryLock.release()  #<== release inventoryLock

				received = True
				#Send ITEM_TRANSFER_ACK
				if (incommingPacket):
					respPayload = {"transferId": incommingPacket.payload["transferId"], "transferSuccess": received}
					responsePacket = NetworkPacket(senderId=self.agentId, destinationId=incommingPacket.senderId, msgType="ITEM_TRANSFER_ACK", payload=respPayload, transactionId=incommingPacket.transactionId)
					self.sendPacket(responsePacket)
			else:
				self.logger.error("receiveItem() Lock \"inventoryLock\" acquisition timeout")
				received = False

			#Return status
			self.logger.debug("{}.receiveItem({}) return {}".format(self.agentId, itemPackage, received))
			return received

		except Exception as e:
			self.logger.critical("receiveItem() Exception")
			self.logger.critical("selg.agentId={}, itemPackage={}, incommingPacket={}".format(self.agentId, itemPackage, incommingPacket))
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
					transferPacket = NetworkPacket(senderId=self.agentId, destinationId=recipientId, msgType="ITEM_TRANSFER", payload=transferPayload, transactionId=transferId)
					self.sendPacket(transferPacket)

				#Wait for transaction response
				while not (transferId in self.responseBuffer):
					time.sleep(0.00001)
					pass
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
						self.logger.error("sendCurrency() Lock \"responseBufferLock\" acquisition timeout")
						transferSuccess = False

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


	#########################
	# Trading functions
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

			if (self.agentId == request.sellerId):
				#We are the seller. Send item package
				itemSent = self.sendItem(request.itemPackage, request.buyerId, transactionId=request.reqId)
				if (not itemSent):
					self.logger.error("Item transfer failed {}".format(request))
					
				tradeCompleted = itemSent

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
		try:
			self.tradeRequestLock.acquire()  #<== acquire tradeRequestLock

			tradeCompleted = False

			#Evaluate offer
			offerAccepted = False
			if (senderId != request.sellerId) and (senderId != request.buyerId):
				#This request was sent by a third party. Reject it
				offerAccepted = False
			else:
				#Offer is valid. Evaluate offer
				self.logger.debug("Fowarding {} to controller {}".format(request, self.controller.name))
				offerAccepted = self.controller.evalTradeRequest(request)

			#Notify counter party of response
			respPayload = {"tradeRequest": request, "accepted": offerAccepted}
			responsePacket = NetworkPacket(senderId=self.agentId, destinationId=senderId, msgType="TRADE_REQ_ACK", payload=respPayload, transactionId=request.reqId)
			self.sendPacket(responsePacket)

			#Execute trade if offer accepted
			if (offerAccepted):
				self.logger.debug("{} accepted".format(request))
				tradeCompleted = self.executeTrade(request)
			else:
				self.logger.debug("{} rejected".format(request))

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
			self.tradeRequestLock.acquire()  #<== acquire tradeRequestLock

			self.logger.debug("{}.sendTradeRequest({}, {}) start".format(self.agentId, request, recipientId))
			tradeCompleted = False

			#Send trade offer
			tradeId = request.reqId
			tradePacket = NetworkPacket(senderId=self.agentId, destinationId=recipientId, msgType="TRADE_REQ", payload=request, transactionId=tradeId)
			self.sendPacket(tradePacket)
			
			#Wait for trade response
			while not (tradeId in self.responseBuffer):
				time.sleep(0.00001)
				pass
			responsePacket = self.responseBuffer[tradeId]

			#Execute trade if request accepted
			offerAccepted = bool(responsePacket.payload["accepted"])
			if (offerAccepted):
				#Execute trade
				tradeCompleted = self.executeTrade(request)
			else:
				self.logger.info("{} was rejected".format(request))
				tradeCompleted = offerAccepted

			self.tradeRequestLock.release()  #<== release tradeRequestLock
			self.logger.debug("{}.sendTradeRequest({}, {}) return {}".format(self.agentId, request, recipientId, tradeCompleted))
			return tradeCompleted

		except Exception as e:
			self.logger.critical("sendTradeRequest() Exception")
			self.logger.critical("selg.agentId={}, request={}, recipientId={}".format(self.agentId, request, recipientId))
			raise ValueError("sendTradeRequest() Exception")

	#########################
	# Labor functions
	#########################
	def fulfillAllLaborContracts(self):
		'''
		Fulfills all non-expired labor contracts
		'''
		for endStep in list(self.laborContracts.keys()):
			if (self.stepNum > endStep):
				self.logger.debug("Removing all contracts that expire on step {}".format(endStep))

				self.commitedTicksLock.acquire()
				for laborContractHash in self.laborContracts[endStep]:
					self.commitedTicks -= self.laborContracts[endStep][laborContractHash].ticksPerStep
				self.commitedTicksLock.release()

				self.laborContractsLock.acquire()
				del self.laborContracts[endStep]
				self.laborContractsLock.release()
			else:
				for laborContractHash in self.laborContracts[endStep]:
					self.fulfillLaborContract(self.laborContracts[endStep][laborContractHash])


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
					ticksSpent = self.useTimeTicks(ticks)
					if (ticksSpent):
						payload = {"ticks": ticks, "skillLevel": self.skillLevel}
						laborId = "LaborSend_{}(agentId={}, employerId={}, ticks={})".format(contractHash, self.agentId, employerId, ticks, contractHash)
						laborPacket = NetworkPacket(senderId=self.agentId, destinationId=laborContract.employerId, transactionId=laborId, payload=payload, msgType="LABOR_TIME_SEND")
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
				paymentId = "LaborPayment_{}".format(laborContract.hash)

				paymentSent = self.sendCurrency(netPayment, laborContract.workerId, transactionId=paymentId)
				if not (paymentSent):
					self.logger.error("{} failed".format(paymentId))

				contractFulfilled = paymentSent
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
				self.logger.debug("Fowarding {} to controller {}".format(laborContract, self.controller.name))
				applicationAccepted = self.controller.evalJobApplication(laborContract)

			#Notify counter party of response
			respPayload = {"laborContract": laborContract, "accepted": applicationAccepted}
			responsePacket = NetworkPacket(senderId=self.agentId, destinationId=senderId, msgType="LABOR_APPLICATION_ACK", payload=respPayload, transactionId=applicationId)
			self.sendPacket(responsePacket)

			#If accepted, add to existing labor contracts
			if (applicationAccepted):
				self.logger.debug("{} accepted".format(laborContract))
				self.laborContractsLock.acquire()
				
				if not (laborContract.endStep in self.laborContracts):
					self.laborContracts[laborContract.endStep] = {}
				self.laborContracts[laborContract.endStep][laborContract.hash] = laborContract

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
			applicationPacket = NetworkPacket(senderId=self.agentId, destinationId=laborListing.employerId, msgType="LABOR_APPLICATION", payload=applicationPayload, transactionId=applicationId)
			self.sendPacket(applicationPacket)
			
			#Wait for application response
			while not (applicationId in self.responseBuffer):
				time.sleep(0.00001)
				pass
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
				applicationAccepted = True

				self.laborContractsLock.release()
				
				#Reserve ticks for this job
				self.commitedTicks_nextStepLock.acquire()
				self.commitedTicks_nextStep += laborContract.ticksPerStep
				self.commitedTicks_nextStepLock.release()
			else:
				self.logger.info("{} was rejected".format(applicationId))
				applicationAccepted = False

			self.logger.debug("{}.sendJobApplication({}) return {}".format(self.agentId, laborListing, applicationAccepted))
			return applicationAccepted

		except Exception as e:
			self.logger.critical("sendJobApplication() Exception")
			self.logger.critical("selg.agentId={}, listing={}".format(self.agentId, laborListing))
			raise ValueError("sendJobApplication() Exception")

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
			updatePacket = NetworkPacket(senderId=self.agentId, transactionId=transactionId, msgType="ITEM_MARKET_UPDATE", payload=itemListing)
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
			updatePacket = NetworkPacket(senderId=self.agentId, transactionId=transactionId, msgType="ITEM_MARKET_REMOVE", payload=itemListing)
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
		requestPacket = NetworkPacket(senderId=self.agentId, transactionId=transactionId, msgType="ITEM_MARKET_SAMPLE", payload=requestPayload)
		self.sendPacket(requestPacket)

		#Wait for response from itemMarket
		while not (transactionId in self.responseBuffer):
			time.sleep(0.0001)
			pass
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
			updatePacket = NetworkPacket(senderId=self.agentId, transactionId=transactionId, msgType="LABOR_MARKET_UPDATE", payload=laborListing)
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
			updatePacket = NetworkPacket(senderId=self.agentId, transactionId=transactionId, msgType="LABOR_MARKET_REMOVE", payload=laborListing)
			self.sendPacket(updatePacket)
			updateSuccess = True

		else:
			#We are not the employer
			self.logger.error("{}.removeLaborListing({}) failed. {} is not the itemMarket or the seller".format(self.agentId, laborListing, self.agentId))
			updateSuccess = False

		#Return status
		self.logger.debug("{}.removeLaborListing({}) return {}".format(self.agentId, laborListing, updateSuccess))
		return updateSuccess

	def sampleLaborListings(self, sampleSize=3, delResponse=True):
		'''
		Returns a list of sampled labor listings that agent qualifies for (listing.minSkillLevel <= agent.skillLevel).
		Will sample listings in order of decreasing skill level, returning the highest possible skill-level listings. Samples are randomized within skill levels.
		'''
		sampledListings = []
		
		#Send request to itemMarketAgent
		transactionId = "LABOR_MARKET_SAMPLE_{}_{}".format(self.agentId, time.time())
		requestPayload = {"agentSkillLevel": self.skillLevel, "sampleSize": sampleSize}
		requestPacket = NetworkPacket(senderId=self.agentId, transactionId=transactionId, msgType="LABOR_MARKET_SAMPLE", payload=requestPayload)
		self.sendPacket(requestPacket)

		#Wait for response from itemMarket
		while not (transactionId in self.responseBuffer):
			time.sleep(0.0001)
			pass
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
	# Utility functions
	#########################
	def getMarginalUtility(self, itemId):
		'''
		Returns the current marginal utility of an itemId
		'''
		quantity = 1
		if (itemId in self.inventory):
			quantity = self.inventory[itemId].quantity

		utilityFunction = self.utilityFunctions[itemId]

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

		acquired_timeTickLock = self.timeTickLock.acquire(timeout=self.lockTimeout)  #<== timeTickLock acquire
		if (acquired_timeTickLock):
			if (self.timeTicks >= amount):
				#We have enought ticks. Decrement tick counter
				self.logger.debug("Using {} time ticks".format(amount))
				self.timeTicks -= amount
				self.logger.debug("Time tick balance = {}".format(self.timeTicks))
				useSuccess = True

				if (self.timeTicks == 0):
					#We are out of time ticks. Set blocked flag
					acquired_tickBlockFlag_Lock = self.tickBlockFlag_Lock.acquire(timeout=self.lockTimeout)  #<== tickBlockFlag_Lock acquire
					if (acquired_tickBlockFlag_Lock):
						self.tickBlockFlag = True
						self.tickBlockFlag_Lock.release()  #<== tickBlockFlag_Lock release
					else:
						self.logger.error("TICK_GRANT tickBlockFlag_Lock acquire timeout")

					#Send blocked signal to sim manager
					self.logger.debug("We're tick blocked. Sending TICK_BLOCKED to simManager")

					tickBlocked = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="TICK_BLOCKED")
					tickBlockPacket = NetworkPacket(senderId=self.agentId, destinationId=self.simManagerId, msgType="CONTROLLER_MSG", payload=tickBlocked)
					self.logger.info("OUTBOUND {}->{}".format(tickBlocked, tickBlockPacket))
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

		self.logger.debug("{}.useTimeTicks({}) return {}".format(self.agentId, amount, useSuccess))
		return useSuccess


	def relinquishTimeTicks(self):
		'''
		Relinquish all time ticks for this sim step
		'''
		self.logger.debug("{}.relinquishTimeTicks() start".format(self.agentId))
		self.useTimeTicks(self.ticksPerStep-self.commitedTicks)


	#########################
	# Misc functions
	#########################
	def handleInfoRequest(self, infoRequest):
		if (self.agentId == infoRequest.agentId):
			infoKey = infoRequest.infoKey
			if (infoKey == "currencyBalance"):
				infoRequest.info = self.currencyBalance
			if (infoKey == "inventory"):
				infoRequest.info = self.inventory
			if (infoKey == "debtBalance"):
				infoRequest.info = self.debtBalance
			
			infoRespPacket = NetworkPacket(senderId=self.agentId, destinationId=infoRequest.requesterId, msgType="INFO_RESP", payload=infoRequest)
			self.sendPacket(infoRespPacket)
		else:
			self.logger.warning("Received infoRequest for another agent {}".format(infoRequest))

	def __str__(self):
		return str(self.agentInfo)

'''
Item Json format
{
	"id": <str> itemId,
	"unit": <str> itemUnit,
	"category": <str> itemCategory,
	"ProductionInputs": {
		"FixedCosts": {
			"FixedLandCosts": {
				"MaxYield": <float> or <bool>, #How many units of itemId can 1 unit of land (1 hectare) produce in 1 time tick (1 hour). Can be set to <bool> false if it does not apply.
				"MinQuantity": <float>,        #What is the smallest amount of land you need before you can start production.
				"Quantized": <bool>            #If True, land can only be productive in increments of MinQuantity
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
				<float> MinSkillLevel_a: <int> ticks, #How many ticks of labor with skill >= MinSkillLevel_a it takes to enable production of itemId
				<float> MinSkillLevel_b: <int> ticks, #How many ticks of labor with skill >= MinSkillLevel_b it takes to enable production of itemId
				...
			}, 
			"FixedTimeCosts": <int>    #How many ticks of time must you wait before you can start producting itemId
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
	"UtilityFunctions": {
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