import json
from random import *
import multiprocessing
import os
import numpy as np
import logging
import time
import sys
import traceback

from EconAgent import *
from ConnectionNetwork import *
import utils

#logPath = os.path.join("LOGS", "simulation_{}.log".format(time.time()))
#logging.basicConfig(format='%(asctime)s.%(msecs)03d\t%(levelname)s:\t%(name)s:\t%(message)s', level=logging.DEBUG, datefmt='%m/%d/%Y %H:%M:%S', filename=logPath)
#logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))

#Congregate item into into a single dict
allItemsDict = {}
for fileName in os.listdir("Items"):
	try:
		filePath = os.path.join("Items", fileName)
		itemDictFile = open(filePath, "r")
		itemDict = json.load(itemDictFile)
		itemDictFile.close()

		allItemsDict[itemDict["id"]] = itemDict
	except:
		pass


def launchAgents(launchDict, allAgentList, procName, managementPipe):
	logger = utils.getLogger("{}:{}".format(__name__, procName), console="INFO")

	logger.debug("launchAgents() start")
	logger.debug("launchDict = {}".format(launchDict))
	logger.debug("allAgentList = {}".format(allAgentList))
	logger.debug("procName = {}".format(procName))
	logger.debug("managementPipe = {}".format(managementPipe))

	#Instantiate agents
	agentsInstantiated = False
	try:
		logger.info("Instantiating agents")
		procAgentDict = {}
		for agentId in launchDict:
			agentObj = Agent(agentInfo=launchDict[agentId]["agentInfo"], itemDict=allItemsDict, networkLink=launchDict[agentId]["agentPipe"])
			procAgentDict[agentId] = agentObj

			#Start each agent off with $100
			agentObj.receiveCurrency(1000000)

			#Start each agent off with 10000 apples
			startingApples = ItemContainer("apple", 10000)
			agentObj.receiveItem(startingApples)

		procAgentList = list(procAgentDict.keys())
		agentsInstantiated = True
		time.sleep(2)
	except Exception as e:
		logger.error("Error while instantiating agents")
		logger.error(traceback.format_exc())

	#Send random trades between agents
	if (agentsInstantiated):
		try:
			logger.info("Initiating random trades")

			repeats = 100
			for i in range(repeats):
				numXact = 50
				transfersCents = sample(range(0, 1001), numXact)
				transfersApples = sample(range(0, 50), numXact)
				
				transfersRecipients = np.random.choice(allAgentList, size=numXact, replace=True)
				transferSenders = np.random.choice(procAgentList, size=numXact, replace=True)

				for i in range(numXact):
					#Create trade request
					senderAgent = procAgentDict[transferSenders[i]]
					senderId = senderAgent.agentId
					recipientId = transfersRecipients[i]
					currencyAmount = transfersCents[i]	
					applePackage = ItemContainer("apple", transfersApples[i])

					tradeRequest = TradeRequest(sellerId=recipientId, buyerId=senderId, currencyAmount=currencyAmount, itemPackage=applePackage)

					#Send trade request
					logger.debug("Sending trade request{}".format(tradeRequest))
					senderAgent.sendTradeRequest(request=tradeRequest, recipientId=recipientId)

			logger.info("Trading complete")
		except Exception as e:
			logger.error("Error while sending trades")
			logger.error(traceback.format_exc())

	#Send kill commands for all pipes connected to this batch of agents
	try:
		time.sleep(10)  #temp fix until we can track status of other managers
		logger.info("Broadcasting kill command")
		killPacket = NetworkPacket(senderId=procName, msgType="KILL_ALL_BROADCAST")
		logger.debug("OUTBOUND {}".format(killPacket))
		managementPipe.send(killPacket)
	except Exception as e:
		logger.error("Error while sending kill commands to agents")
		logger.error(traceback.format_exc())

	#Send kill command for management pipe
	try:
		logger.info("Killing network connection")
		time.sleep(1)
		killPacket = NetworkPacket(senderId=procName, destinationId=procName, msgType="KILL_PIPE_NETWORK")
		logger.debug("OUTBOUND {}".format(killPacket))
		managementPipe.send(killPacket)
		time.sleep(1)
	except Exception as e:
		logger.error("Error while killing network link")
		logger.error(traceback.format_exc())

	logger.debug("Exiting launchAgents()")

	return

if __name__ == "__main__":
	#Generate agent IDs and network pipes
	spawnDict = {}
	numProcess = 2
	for procNum in range(numProcess):
		spawnDict[procNum] = {}

	allAgentList = []
	numAgents = 7
	for i in range(numAgents):
		agentId = "agent_{}".format(i)
		allAgentList.append(agentId)
		networkPipe, agentPipe = multiprocessing.Pipe(duplex=True)
		procNum = i%numProcess

		spawnDict[procNum][agentId] = {"agentInfo": AgentInfo(agentId, "pushover"), "networkPipe": networkPipe, "agentPipe": agentPipe}
	
	#Instantiate network
	xactNetwork = ConnectionNetwork()
	for procNum in spawnDict:
		for agentId in spawnDict[procNum]:
			xactNetwork.addConnection(agentId=agentId, networkPipe=spawnDict[procNum][agentId]["networkPipe"])

	#Spawn subprocesses
	for procNum in spawnDict:
		procName = "Simulation_Proc{}".format(procNum)

		managementPipe_manager, managementPipe_network = multiprocessing.Pipe(duplex=True)
		xactNetwork.addConnection(agentId=procName, networkPipe=managementPipe_network)

		proc = multiprocessing.Process(target=launchAgents, args=(spawnDict[procNum], allAgentList, procName, managementPipe_manager))
		proc.start()

	#Launch network
	xactNetwork.startMonitors()