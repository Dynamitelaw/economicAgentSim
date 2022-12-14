import math
import threading
import logging
import time

from ConnectionNetwork import *
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
		return "(BaseUtility: {}, DiminishingFactor: {})".format(self.baseUtility, self.diminishingFactor)

	def __repr__(self):
		return str(self)


class InventoryEntry:
	def __init__(self, itemId, itemQuantity):
		self.id = itemId
		self.quantity = itemQuantity

	def __repr__(self):
		return str(self)

	def __str__(self):
		return "InventoryEntry(ID={}, Quant={})".format(self.id, self.quantity)

	def __add__(self, other):
		typeOther = type(other)
		if (typeOther == type(self)):
			otherId = other.id
			if (self.id != otherId):
				raise ValueError("Cannot add inventory entries of different items {} and {}".format(self.id, otherId))

			newEntry = InventoryEntry(self.id, self.quantity+other.quantity)
			return newEntry
		elif ((typeOther == int) or (typeOther == float)):
			newEntry = InventoryEntry(self.id, self.quantity+other)
			return newEntry
		else:
			raise ValueError("Cannot add {} and {}".format(typeOther, type(self)))

	def __sub__(self, other):
		typeOther = type(other)
		if (typeOther == type(self)):
			otherId = other.id
			if (self.id != otherId):
				raise ValueError("Cannot add inventory entries of different items {} and {}".format(self.id, otherId))

			newEntry = InventoryEntry(self.id, self.quantity-other.quantity)
			return newEntry
		elif ((typeOther == int) or (typeOther == float)):
			newEntry = InventoryEntry(self.id, self.quantity-other)
			return newEntry
		else:
			raise ValueError("Cannot subtract {} and {}".format(typeOther, type(self)))

	def __iadd__(self, other):
		typeOther = type(other)
		if (typeOther == type(self)):
			otherId = other.id
			if (self.id != otherId):
				raise ValueError("Cannot add inventory entries of different items {} and {}".format(self.id, otherId))

			self.quantity += other.quantity
			return self
		elif ((typeOther == int) or (typeOther == float)):
			self.quantity += other
			return self
		else:
			raise ValueError("Cannot add {} and {}".format(typeOther, type(self)))

	def __isub__(self, other):
		typeOther = type(other)
		if (typeOther == type(self)):
			otherId = other.id
			if (self.id != otherId):
				raise ValueError("Cannot subtract inventory entries of different items {} and {}".format(self.id, otherId))

			self.quantity -= other.quantity
			return self
		elif ((typeOther == int) or (typeOther == float)):
			self.quantity -= other
			return self
		else:
			raise ValueError("Cannot subtract {} and {}".format(typeOther, type(self)))


class AgentInfo:
	def __init__(self, agentId, agentType):
		self.agentId = agentId
		self.agentType = agentType

	def __str__(self):
		return "AgentInfo(ID={}, Type={})".format(self.agentId, self.agentType)


class Agent:
	def __init__(self, agentInfo, itemDict=None, allAgentDict=None, networkLink=None):
		self.info = agentInfo
		self.agentId = agentInfo.agentId
		self.agentType = agentInfo.agentType
		self.logger = utils.getLogger("{}:{}".format(__name__, self.agentId))
		self.logger.debug("{} instantiated".format(self.info))

		self.lockTimeout = 5

		#Keep track of other agents
		self.allAgentDict = allAgentDict

		#Keep track of agent assets
		self.currencyBalance = 0  #(int) cents  #This prevents accounting errors due to float arithmetic (plus it's faster)
		self.currencyBalanceLock = threading.Lock()
		self.inventory = {}
		self.inventoryLock = threading.Lock()

		#Pipe connections to the transaction supervisor
		self.networkLink = networkLink
		self.responseBuffer = {}
		self.responseBufferLock = threading.Lock()
		
		#Instantiate agent preferences (utility functions)
		self.utilityFunctions = {}
		for itemName in itemDict:
			itemFunctionParams = itemDict[itemName]["UtilityFunctions"]
			self.utilityFunctions[itemName] = UtilityFunction(itemFunctionParams["BaseUtility"]["mean"], itemFunctionParams["BaseUtility"]["stdDev"], itemFunctionParams["DiminishingFactor"]["mean"], itemFunctionParams["DiminishingFactor"]["stdDev"])

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
			incommingPacket = self.networkLink.recv()
			self.logger.info("INBOUND {}".format(incommingPacket))
			if (incommingPacket.msgType == "KILL_PIPE_AGENT"):
				#Kill the network pipe before exiting monitor
				killPacket = NetworkPacket(senderId=self.agentId, destinationId=self.agentId, msgType="KILL_PIPE_NETWORK")
				self.sendPacket(killPacket)
				self.logger.info("Killing networkLink {}".format(self.networkLink))
				break

			#Handle incoming acks
			if ("_ACK" in incommingPacket.msgType):
				#Place incoming acks into the response buffer
				acquired_responseBufferLock = self.responseBufferLock.acquire(timeout=self.lockTimeout)  #<== acquire responseBufferLock
				if (acquired_responseBufferLock):
					self.responseBuffer[incommingPacket.transactionId] = incommingPacket
					self.responseBufferLock.release()  #<== release responseBufferLock
				else:
					self.logger.error("monitorNetworkLink() Lock \"responseBufferLock\" acquisition timeout")
					break

			#Handle errors
			if ("ERROR" in incommingPacket.msgType):
				self.logger.error("{} {}".format(incommingPacket, incommingPacket.payload))

			#Handle incoming payments
			if (incommingPacket.msgType == "CURRENCY_TRANSFER"):
				amount = incommingPacket.payload["cents"]
				transferThread =  threading.Thread(target=self.receiveCurrency, args=(amount, incommingPacket))
				transferThread.start()

			#Handle incoming items
			if (incommingPacket.msgType == "ITEM_TRANSFER"):
				itemPackage = incommingPacket.payload["item"]
				transferThread =  threading.Thread(target=self.receiveItem, args=(itemPackage, incommingPacket))
				transferThread.start()

		self.logger.info("Ending networkLink monitor".format(self.networkLink))


	def sendPacket(self, packet):
		self.logger.info("OUTBOUND {}".format(packet))
		self.networkLink.send(packet)


	#########################
	# Currency functions
	#########################
	def receiveCurrency(self, cents, incommingPacket=None):
		'''
		Returns True if transfer was succesful, False if not
		'''
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


	def sendCurrency(self, cents, recipientId, transactionId=None, delResponse=True):
		'''
		Send currency to another agent. 
		Returns True if transfer was succesful, False if not
		'''
		self.logger.debug("{}.sendCurrency({}, {}) start".format(self.agentId, cents, recipientId))

		#Check for valid transfers
		if (cents == 0):
			self.logger.debug("{}.sendCurrency({}, {}) return {}".format(self.agentId, cents, recipientId, False))
			return True
		if (recipientId == self.agentId):
			self.logger.debug("{}.sendCurrency({}, {}) return {}".format(self.agentId, cents, recipientId, True))
			return True
		if (cents > self.currencyBalance):
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
			paymentId = transactionId
			if (not paymentId):
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

	#########################
	# Trading functions
	#########################
	def receiveItem(self, itemPackage, incommingPacket=None):
		'''
		Add an item to agent inventory.
		Returns True if item was successfully added, False if not
		'''
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


	def sendItem(self, itemPackage, recipientId, transactionId=None, delResponse=True):
		'''
		Send an item to another agent.
		Returns True if item was successfully sent, False if not
		'''
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
			transferId = transactionId
			if (not transferId):
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

	#########################
	# Utility functions
	#########################
	def __str__(self):
		return "Agent(ID={}, Type={})".format(self.agentId, self.agentType)

