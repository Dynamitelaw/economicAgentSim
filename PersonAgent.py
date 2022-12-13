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


class PersonAgent:
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
		self.sendLock = threading.Lock()
		self.possesions = {}

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
				self.logger.info("OUTBOUND {}".format(killPacket))
				self.networkLink.send(killPacket)
				self.logger.info("Killing networkLink {}".format(self.networkLink))
				break

			#Handle incoming acks
			if ("_ACK" in incommingPacket.msgType):
				#Place incoming acks into the response buffer
				self.logger.debug("monitorNetworkLink() Lock \"responseBufferLock\" requested")
				acquired_responseBufferLock = self.responseBufferLock.acquire(timeout=self.lockTimeout)
				if (acquired_responseBufferLock):
					self.logger.debug("monitorNetworkLink() Lock \"responseBufferLock\" acquired")
					self.responseBuffer[incommingPacket.transactionId] = incommingPacket
					self.logger.debug("monitorNetworkLink() Lock \"responseBufferLock\" release")
					self.responseBufferLock.release()
				else:
					self.logger.error("monitorNetworkLink() Lock \"responseBufferLock\" acquisition timeout")
					break

			#Handle errors
			if ("ERROR" in incommingPacket.msgType):
				self.logger.error("{} {}".format(incommingPacket, incommingPacket.payload))

			#Handle incoming payments
			if (incommingPacket.msgType == "PAYMENT"):
				amount = incommingPacket.payload["cents"]
				transferSuccess = self.receiveCurrency(amount)

				respPayload = {"paymentId": incommingPacket.payload["paymentId"], "transferSuccess": transferSuccess}
				responsePacket = NetworkPacket(senderId=self.agentId, destinationId=incommingPacket.senderId, msgType="PAYMENT_ACK", payload=respPayload, transactionId=incommingPacket.transactionId)
				self.networkLink.send(responsePacket)

		self.logger.info("Ending networkLink monitor".format(self.networkLink))


	def receiveCurrency(self, cents):
		'''
		Returns True if transfer was succesful, 0 if not
		'''
		self.logger.debug("{}.receiveCurrency({}) start".format(self.agentId, cents))

		if (cents < 0):
			self.logger.debug("{}.receiveCurrency({}) return {}".format(self.agentId, cents, False))
			return False
		if (cents == 0):
			self.logger.debug("{}.receiveCurrency({}) return {}".format(self.agentId, cents, True))
			return True

		self.logger.debug("receiveCurrency() Lock \"currencyBalanceLock\" requested")
		acquired_currencyBalanceLock = self.currencyBalanceLock.acquire(timeout=self.lockTimeout)  #wait to aquire balance lock
		if (acquired_currencyBalanceLock):
			self.logger.debug("receiveCurrency() Lock \"currencyBalanceLock\" acquired")
			self.currencyBalance = self.currencyBalance + int(cents)
			self.logger.debug("receiveCurrency() Lock \"currencyBalanceLock\" release")
			self.currencyBalanceLock.release()

			self.logger.debug("{}.receiveCurrency({}) return {}".format(self.agentId, cents, True))
			return True
		else:
			self.logger.error("receiveCurrency() Lock \"currencyBalanceLock\" acquisition timeout")
			self.logger.debug("{}.receiveCurrency({}) return {}".format(self.agentId, cents, False))
			return False

	def sendCurrency(self, cents, recipientId):
		self.logger.debug("{}.sendCurrency({}, {}) start".format(self.agentId, cents, recipientId))

		if (cents == 0):
			self.logger.debug("{}.sendCurrency({}, {}) return {}".format(self.agentId, cents, recipientId, False))
			return True
		if (recipientId == self.agentId):
			self.logger.debug("{}.sendCurrency({}, {}) return {}".format(self.agentId, cents, recipientId, True))
			return True

		transferSuccess = False

		self.logger.debug("sendCurrency() Lock \"currencyBalanceLock\" requested")
		acquired_currencyBalanceLock = self.currencyBalanceLock.acquire(timeout=self.lockTimeout)
		if (acquired_currencyBalanceLock):
			self.logger.debug("sendCurrency() Lock \"currencyBalanceLock\" acquired")
			currencyBalanceTemp = self.currencyBalance - int(cents)
			if (currencyBalanceTemp < 0):
				transferSuccess = False
			else:
				#Send payment packet
				paymentId = "{}_{}_{}".format(self.agentId, recipientId, cents)
				transferPayload = {"paymentId": paymentId, "cents": cents}
				transferPacket = NetworkPacket(senderId=self.agentId, destinationId=recipientId, msgType="PAYMENT", payload=transferPayload, transactionId=paymentId)
				self.logger.info("OUTBOUND {}".format(transferPacket))
				self.networkLink.send(transferPacket)

				#Wait for transaction response
				while not (paymentId in self.responseBuffer):
					time.sleep(0.0001)
					pass
				responsePacket = self.responseBuffer[paymentId]

				#Modify balance if successful
				transferSuccess = bool(responsePacket.payload["transferSuccess"])
				if (transferSuccess):
					self.currencyBalance = currencyBalanceTemp

				#Remove transaction from response buffer
				self.logger.debug("sendCurrency() Lock \"responseBufferLock\" requested")
				acquired_responseBufferLock = self.responseBufferLock.acquire(timeout=self.lockTimeout)
				if (acquired_responseBufferLock):
					self.logger.debug("sendCurrency() Lock \"responseBufferLock\" acquired")
					del self.responseBuffer[paymentId]
					self.logger.debug("sendCurrency() Lock \"responseBufferLock\" release")
					self.responseBufferLock.release()
				else:
					self.logger.error("sendCurrency() Lock \"responseBufferLock\" acquisition timeout")
					self.logger.debug("{}.sendCurrency({}, {}) return {}".format(self.agentId, cents, recipientId, False))
					return False

			self.logger.debug("sendCurrency() Lock \"currencyBalanceLock\" release")
			self.currencyBalanceLock.release()
			
			self.logger.debug("{}.sendCurrency({}, {}) return {}".format(self.agentId, cents, recipientId, transferSuccess))
			return transferSuccess
		else:
			self.logger.error("sendCurrency() Lock \"currencyBalanceLock\" acquisition timeout")
			self.logger.debug("{}.sendCurrency({}, {}) return {}".format(self.agentId, cents, recipientId, False))
			return False

