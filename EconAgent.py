import math
import threading
import logging
import time

from ConnectionNetwork import *
from BasicControllers import *
from TradeClasses import *
import utils


class UtilityFunction:
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


class AgentInfo:
	def __init__(self, agentId, agentType):
		self.agentId = agentId
		self.agentType = agentType

	def __str__(self):
		return "AgentInfo(ID={}, Type={})".format(self.agentId, self.agentType)


def getAgentController(agent, logFile=True):
	agentInfo = agent.info

	if (agentInfo.agentType == "PushoverController"):
		#Return pushover controller
		return PushoverController(agent, logFile=logFile)
	if (agentInfo.agentType == "TestSeller"):
		#Return pushover controller
		return TestSeller(agent, logFile=logFile)
	if (agentInfo.agentType == "TestBuyer"):
		#Return pushover controller
		return TestBuyer(agent, logFile=logFile)

	#Unhandled agent type. Return default controller
	return None


class AgentSeed:
	def __init__(self, agentId, agentType, itemDict=None, allAgentDict=None, logFile=True):
		self.agentInfo = AgentInfo(agentId, agentType)
		self.itemDict = itemDict
		self.allAgentDict = allAgentDict
		self.logFile = logFile

		networkPipeRecv, agentPipeSend = multiprocessing.Pipe()
		agentPipeRecv, networkPipeSend = multiprocessing.Pipe()

		self.networkLink = Link(sendPipe=networkPipeSend, recvPipe=networkPipeRecv)
		self.agentLink = Link(sendPipe=agentPipeSend, recvPipe=agentPipeRecv)

	def spawnAgent(self):
		return Agent(self.agentInfo, itemDict=self.itemDict, allAgentDict=self.allAgentDict, networkLink=self.agentLink, logFile=self.logFile)


class Agent:
	def __init__(self, agentInfo, itemDict=None, allAgentDict=None, networkLink=None, logFile=True):
		self.info = agentInfo
		self.agentId = agentInfo.agentId
		self.agentType = agentInfo.agentType
		self.logger = utils.getLogger("{}:{}".format(__name__, self.agentId), logFile=logFile)
		self.logger.debug("{} instantiated".format(self.info))

		self.lockTimeout = 5

		#Keep track of other agents
		self.allAgentDict = allAgentDict

		#Marketplaces
		self.itemMarket = {}
		self.itemMarketLock = threading.Lock()
		if (itemDict):
			for itemName in itemDict:
				self.itemMarket[itemName] = {}

		#Keep track of agent assets
		self.currencyBalance = 0  #(int) cents  #This prevents accounting errors due to float arithmetic (plus it's faster)
		self.currencyBalanceLock = threading.Lock()
		self.inventory = {}
		self.inventoryLock = threading.Lock()
		self.debtBalance = 0
		self.debtBalanceLock = threading.Lock()

		#Pipe connections to the transaction supervisor
		self.networkLink = networkLink
		self.networkSendLock = threading.Lock()
		self.responseBuffer = {}
		self.responseBufferLock = threading.Lock()
		
		#Instantiate agent preferences (utility functions)
		self.utilityFunctions = {}
		if (itemDict):
			for itemName in itemDict:
				itemFunctionParams = itemDict[itemName]["UtilityFunctions"]
				self.utilityFunctions[itemName] = UtilityFunction(itemFunctionParams["BaseUtility"]["mean"], itemFunctionParams["BaseUtility"]["stdDev"], itemFunctionParams["DiminishingFactor"]["mean"], itemFunctionParams["DiminishingFactor"]["stdDev"])

		#Instantiate AI agent controller
		self.controller = getAgentController(self, logFile=logFile)
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

			elif ((incommingPacket.msgType == "CONTROLLER_MSG") or (incommingPacket.msgType == "CONTROLLER_MSG_BROADCAST")):
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

			#Handle incoming item marketplace updates
			elif (incommingPacket.msgType == "ITEM_MARKET_UPDATE_BROADCAST"):
				itemListing = incommingPacket.payload
				updateThread =  threading.Thread(target=self.updateItemListing, args=(itemListing, incommingPacket))
				updateThread.start()
			elif (incommingPacket.msgType == "ITEM_MARKET_REMOVE_BROADCAST"):
				itemListing = incommingPacket.payload
				updateThread =  threading.Thread(target=self.removeItemListing, args=(itemListing, incommingPacket))
				updateThread.start()

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

			self.logger.debug("{}.sendTradeRequest({}, {}) return {}".format(self.agentId, request, recipientId, tradeCompleted))
			return tradeCompleted

		except Exception as e:
			self.logger.critical("sendTradeRequest() Exception")
			self.logger.critical("selg.agentId={}, request={}, recipientId={}".format(self.agentId, request, recipientId))
			raise ValueError("sendTradeRequest() Exception")

	#########################
	# Market functions
	#########################
	def updateItemListing(self, itemListing, incommingPacket=None):
		'''
		Update the item marketplace.
		Returns True if succesful, False otherwise
		'''
		self.logger.debug("{}.updateItemListing({}) start".format(self.agentId, itemListing))

		updateSuccess = False
		
		#Update local item market with listing
		acquired_itemMarketLock = self.itemMarketLock.acquire(timeout=self.lockTimeout)  # <== itemMarketLock acquire
		if (acquired_itemMarketLock):
			if not (itemListing.itemId in self.itemMarket):
				self.itemMarket[itemListing.itemId] = {}
			self.itemMarket[itemListing.itemId][itemListing.sellerId] = itemListing

			self.itemMarketLock.release()  # <== itemMarketLock release
			updateSuccess = True
		else:
			self.logger.error("updateItemListing() Lock \"itemMarketLock\" acquisition timeout")
			updateSuccess = False

		#If we're the seller, send out update broadcast to other agents
		if ((itemListing.sellerId == self.agentId) and (incommingPacket==None)):
			updatePacket = NetworkPacket(senderId=self.agentId, msgType="ITEM_MARKET_UPDATE_BROADCAST", payload=itemListing)
			self.sendPacket(updatePacket)

		#Return status
		self.logger.debug("{}.updateItemListing({}) return {}".format(self.agentId, itemListing, updateSuccess))
		return updateSuccess

	def removeItemListing(self, itemListing, incommingPacket=None):
		'''
		Remove a listing from the item marketplace
		Returns True if succesful, False otherwise
		'''
		self.logger.debug("{}.removeItemListing({}) start".format(self.agentId, itemListing))

		updateSuccess = False
		
		#Update local item market with listing
		acquired_itemMarketLock = self.itemMarketLock.acquire(timeout=self.lockTimeout)  # <== itemMarketLock acquire
		if (acquired_itemMarketLock):
			if (itemListing.itemId in self.itemMarket):
				del self.itemMarket[itemListing.itemId][itemListing.sellerId]

			self.itemMarketLock.release()  # <== itemMarketLock release
			updateSuccess = True
		else:
			self.logger.error("removeItemListing() Lock \"itemMarketLock\" acquisition timeout")
			updateSuccess = False

		#If we're the seller, and this is not a rebound broadcast, send out update broadcast to other agents
		if ((itemListing.sellerId == self.agentId) and (incommingPacket==None)):
			updatePacket = NetworkPacket(senderId=self.agentId, msgType="ITEM_MARKET_REMOVE_BROADCAST", payload=itemListing)
			self.sendPacket(tradePacket)

		#Return status
		self.logger.debug("{}.removeItemListing({}) return {}".format(self.agentId, itemListing, updateSuccess))
		return updateSuccess

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
	# Misc functions
	#########################
	def __str__(self):
		return "Agent(ID={}, Type={})".format(self.agentId, self.agentType)

