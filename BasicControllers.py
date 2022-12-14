from EconAgent import *


class PushoverController:
	'''
	This controller will accept all valid trade requests, and will not take any other action. Used for testing.
	'''
	def __init__(self, agent):
		self.agent = agent
		self.agentId = agent.agentId
		self.name = "{}_PushoverController".format(agent.agentId)

		self.logger = utils.getLogger("{}:{}".format(__name__, self.agentId))

		#Keep track of other agents
		self.allAgentDict = agent.allAgentDict

		#Keep track of agent assets
		self.currencyBalance = agent.currencyBalance  #(int) cents  #This prevents accounting errors due to float arithmetic (plus it's faster)
		self.inventory = agent.inventory

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