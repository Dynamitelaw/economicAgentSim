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
from TradeClasses import *
import utils

#logPath = os.path.join("LOGS", "simulation_{}.log".format(time.time()))
#logging.basicConfig(format='%(asctime)s.%(msecs)03d\t%(levelname)s:\t%(name)s:\t%(message)s', level=logging.DEBUG, datefmt='%m/%d/%Y %H:%M:%S', filename=logPath)
#logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))

#Congregate items into into a single dict
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
			agentObj = launchDict[agentId].spawnAgent()
			procAgentDict[agentId] = agentObj

		procAgentList = list(procAgentDict.keys())
		agentsInstantiated = True
		time.sleep(2)
	except Exception as e:
		logger.error("Error while instantiating agents")
		logger.error(traceback.format_exc())


	#Start agent controllers
	controllerStartBroadcast = NetworkPacket(senderId=procName, msgType="CONTROLLER_START_BROADCAST")
	managementPipe.sendPipe.send(controllerStartBroadcast)

	#Wait while agents trade amongst themselves
	waitTime = 30
	logger.info("Waiting {} min {} sec for trading to continue".format(int(waitTime/60), waitTime%60))
	time.sleep(waitTime)

	#Send commands for all controllers to stop trading
	try:
		logger.info("Broadcasting STOP_TRADING command")
		controllerMsg = NetworkPacket(senderId=procName, msgType="STOP_TRADING")
		networkPacket = NetworkPacket(senderId=procName, msgType="CONTROLLER_MSG_BROADCAST", payload=controllerMsg)
		logger.debug("OUTBOUND {}".format(networkPacket))
		managementPipe.sendPipe.send(networkPacket)

		stopWaitTime = 5
		logger.info("Waiting {} sec for all trades to finish".format(stopWaitTime))
		time.sleep(stopWaitTime)
	except Exception as e:
		logger.error("Error while sending STOP_TRADING command to agents")
		logger.error(traceback.format_exc())

	#Send kill commands for all pipes connected to this batch of agents
	try:
		logger.info("Broadcasting kill command")
		killPacket = NetworkPacket(senderId=procName, msgType="KILL_ALL_BROADCAST")
		logger.debug("OUTBOUND {}".format(killPacket))
		managementPipe.sendPipe.send(killPacket)
	except Exception as e:
		logger.error("Error while sending kill commands to agents")
		logger.error(traceback.format_exc())

	#Send kill command for management pipe
	try:
		logger.info("Killing network connection")
		time.sleep(1)
		killPacket = NetworkPacket(senderId=procName, destinationId=procName, msgType="KILL_PIPE_NETWORK")
		logger.debug("OUTBOUND {}".format(killPacket))
		managementPipe.sendPipe.send(killPacket)
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
	#Spawn buyers
	numBuyers = 10
	for i in range(numBuyers):
		agentId = "buyer_{}".format(i)
		allAgentList.append(agentId)
		procNum = i%numProcess

		spawnDict[procNum][agentId] = AgentSeed(agentId, "TestBuyer", itemDict=allItemsDict)

	#Spawn sellers
	numSellers = 10
	for i in range(numSellers):
		agentId = "seller_{}".format(i)
		allAgentList.append(agentId)
		procNum = i%numProcess

		spawnDict[procNum][agentId] = AgentSeed(agentId, "TestSeller", itemDict=allItemsDict)

	#Spawn a snooper agent
	snooperId = "Snooper0"
	spawnDict[0][snooperId] = AgentSeed(snooperId, "TestSnooper")
	
	#Instantiate network
	xactNetwork = ConnectionNetwork()
	for procNum in spawnDict:
		for agentId in spawnDict[procNum]:
			xactNetwork.addConnection(agentId=agentId, networkLink=spawnDict[procNum][agentId].networkLink)

	#Spawn subprocesses
	for procNum in spawnDict:
		procName = "Simulation_Proc{}".format(procNum)

		networkPipeRecv, managementPipeSend = multiprocessing.Pipe()
		managementPipeRecv, networkPipeSend = multiprocessing.Pipe()
		networkLink = Link(sendPipe=networkPipeSend, recvPipe=networkPipeRecv)
		managementLink = Link(sendPipe=managementPipeSend, recvPipe=managementPipeRecv)

		xactNetwork.addConnection(agentId=procName, networkLink=networkLink)

		proc = multiprocessing.Process(target=launchAgents, args=(spawnDict[procNum], allAgentList, procName, managementLink))
		proc.start()

	#Launch network
	xactNetwork.startMonitors()
