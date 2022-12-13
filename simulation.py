import json
from random import *
import multiprocessing
import os
import numpy as np
import logging
import time

from PersonAgent import *
from TransactionNetwork import *


logging.basicConfig(format='%(asctime)s.%(msecs)03d\t%(levelname)s:\t%(name)s:\t%(message)s', level=logging.DEBUG, datefmt='%m/%d/%Y %H:%M:%S')

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
	logger = logging.getLogger("{}:{}".format(__name__, procName))

	logger.debug("Starting launchAgents()")

	procAgentDict = {}
	for agentId in launchDict:
		agentObj = PersonAgent(agentId=agentId, itemDict=allItemsDict, networkLink=launchDict[agentId]["agentPipe"])
		procAgentDict[agentId] = agentObj

		#Start each agent off with $100
		agentObj.currencyBalance = 100000

	procAgentList = list(procAgentDict.keys())

	#Send random transactions to other agents
	numXact = 5
	transfersCents = sample(range(0, 500), numXact)
	#transfersCents = [20, 6, 80, 33, 49]
	transfersRecipients = np.random.choice(allAgentList, size=numXact, replace=True)
	transferSenders = np.random.choice(procAgentList, size=numXact, replace=True)

	for i in range(numXact):
		senderAgent = procAgentDict[transferSenders[i]]
		senderId = senderAgent.agentId
		recipientId = transfersRecipients[i]
		amount = transfersCents[i]

		logger.info("Sending funds ({}, {}, ${})".format(senderId, recipientId, amount))
		senderAgent.sendCurrency(cents=amount, recipientId=recipientId)

	#Send kill commands for all pipes connected to this batch of agents
	logger.info("Sending kill commands to agents")
	for agentId in procAgentDict:
		killPacket = NetworkPacket(senderId=procName, destinationId=agentId, msgType="KILL_PIPE_AGENT")
		logger.info("OUTBOUND {}".format(killPacket))
		managementPipe.send(killPacket)

	#Send kill command for management pipe
	time.sleep(1)
	killPacket = NetworkPacket(senderId=procName, destinationId=procName, msgType="KILL_PIPE_NETWORK")
	logger.info("OUTBOUND {}".format(killPacket))
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

		spawnDict[procNum][agentId] = {"agentId": agentId, "networkPipe": networkPipe, "agentPipe": agentPipe}
	
	#Instantiate network
	xactNetwork = TransactionNetwork()
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