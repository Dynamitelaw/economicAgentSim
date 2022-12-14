import json
from random import *
import multiprocessing
import os
import numpy as np
import logging
import time
import sys

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

	logger.info("Instantiating agents")
	procAgentDict = {}
	for agentId in launchDict:
		agentObj = Agent(agentInfo=launchDict[agentId]["agentInfo"], itemDict=allItemsDict, networkLink=launchDict[agentId]["agentPipe"])
		procAgentDict[agentId] = agentObj

		#Start each agent off with $100
		agentObj.receiveCurrency(1000000)

		#Start each agent off with 100 apples and 200 potatos
		startingApples = InventoryEntry("apple", 100)
		startingPotatos = InventoryEntry("potato", 100)

		agentObj.receiveItem(startingApples)
		agentObj.receiveItem(startingPotatos)

	procAgentList = list(procAgentDict.keys())
	time.sleep(2)

	#Send random transactions to other agents
	logger.info("Sending random transactions")
	numXact = 5
	transfersCents = sample(range(0, 1001), numXact)
	transfersApples = sample(range(0, 7), numXact)
	transfersPotatos = sample(range(0, 14), numXact)
	
	transfersRecipients = np.random.choice(allAgentList, size=numXact, replace=True)
	transferSenders = np.random.choice(procAgentList, size=numXact, replace=True)

	for i in range(numXact):
		senderAgent = procAgentDict[transferSenders[i]]
		senderId = senderAgent.agentId
		recipientId = transfersRecipients[i]
		amount = transfersCents[i]
		applePackage = InventoryEntry("apple", transfersApples[i])
		potatoPackage = InventoryEntry("potato", transfersPotatos[i])

		logger.debug("Sending funds ({}, {}, ${})".format(senderId, recipientId, amount))
		senderAgent.sendCurrency(cents=amount, recipientId=recipientId)
		senderAgent.sendItem(itemPackage=applePackage, recipientId=recipientId)
		senderAgent.sendItem(itemPackage=potatoPackage, recipientId=recipientId)

	#Send kill commands for all pipes connected to this batch of agents
	time.sleep(10)  #temp fix until we can track status of other managers
	logger.info("Sending kill commands to agents")
	for agentId in procAgentDict:
		killPacket = NetworkPacket(senderId=procName, destinationId=agentId, msgType="KILL_PIPE_AGENT")
		logger.debug("OUTBOUND {}".format(killPacket))
		managementPipe.send(killPacket)

	#Send kill command for management pipe
	logger.info("Killing network connection")
	time.sleep(1)
	killPacket = NetworkPacket(senderId=procName, destinationId=procName, msgType="KILL_PIPE_NETWORK")
	logger.debug("OUTBOUND {}".format(killPacket))
	managementPipe.send(killPacket)
	time.sleep(1)

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

		spawnDict[procNum][agentId] = {"agentInfo": AgentInfo(agentId, "human"), "networkPipe": networkPipe, "agentPipe": agentPipe}
	
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