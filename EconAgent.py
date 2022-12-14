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


class Agent:
	def __init__(self, agentId, itemDict, networkLink=None):
		self.agentId = agentId
		self.logger = utils.getLogger("{}:{}".format(__name__, self.agentId))
		self.logger.debug("{} instantiated".format(agentId))

		self.lockTimeout = 5

		#Keep track of hunger
		self.foodSatiation = {"satiation": 100}

		#Keep track of agent assets
		self.currencyBalance = 0  #(int) cents  #This prevents accounting errors due to float arithmetic (plus it's faster)
		self.currencyBalanceLock = threading.Lock()

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

	def monitorNetworkLink(self):
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
			if (incommingPacket.msgType == "PAYMENT"):
				amount = incommingPacket.payload["cents"]
				transferThread =  threading.Thread(target=self.receiveCurrency, args=(amount, incommingPacket))
				transferThread.start()

		self.logger.info("Ending networkLink monitor".format(self.networkLink))


	def sendPacket(self, packet):
		self.logger.info("OUTBOUND {}".format(packet))
		self.networkLink.send(packet)


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

		#Send PAYMENT_ACK
		if (incommingPacket):
			respPayload = {"paymentId": incommingPacket.payload["paymentId"], "transferSuccess": transferSuccess}
			responsePacket = NetworkPacket(senderId=self.agentId, destinationId=incommingPacket.senderId, msgType="PAYMENT_ACK", payload=respPayload, transactionId=incommingPacket.transactionId)
			self.sendPacket(responsePacket)

		#Return transfer status
		self.logger.debug("{}.receiveCurrency({}) return {}".format(self.agentId, cents, transferSuccess))
		return transferSuccess


	def sendCurrency(self, cents, recipientId):
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
			paymentId = "{}_{}_{}".format(self.agentId, recipientId, cents)
			transferPayload = {"paymentId": paymentId, "cents": cents}
			transferPacket = NetworkPacket(senderId=self.agentId, destinationId=recipientId, msgType="PAYMENT", payload=transferPayload, transactionId=paymentId)
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
			acquired_responseBufferLock = self.responseBufferLock.acquire(timeout=self.lockTimeout)  #<== acquire responseBufferLock
			if (acquired_responseBufferLock):
				del self.responseBuffer[paymentId]
				self.responseBufferLock.release()  #<== release responseBufferLock
			else:
				self.logger.error("sendCurrency() Lock \"responseBufferLock\" acquisition timeout")
				transferSuccess = False
			
		else:
			self.logger.error("sendCurrency() Lock \"currencyBalanceLock\" acquisition timeout")
			transferSuccess = False

		self.logger.debug("{}.sendCurrency({}, {}) return {}".format(self.agentId, cents, recipientId, False))
		return transferSuccess

