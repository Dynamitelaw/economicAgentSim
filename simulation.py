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
from SimulationManager import *
import utils


def launchSimulation(simManagerSeed):
	try:
		simManager = simManagerSeed.spawnManager()
		simManager.runSim()
	except KeyboardInterrupt:
		curr_proc = multiprocessing.current_process()

		print("###################### INTERUPT {} ######################".format(curr_proc))
		simManager.terminate()

		try:	
			curr_proc.terminate()
		except Exception as e:
			print("### {} Error when terminating proc {}".format(e, curr_proc))
			print(traceback.format_exc())


def launchAgents(launchDict, allAgentDict, procName, managerId, managementPipe):
	try:
		logger = utils.getLogger("{}:{}".format(__name__, procName), console="INFO")

		curr_proc = multiprocessing.current_process()
		logger.info("{}".format(curr_proc.name))

		logger.debug("launchAgents() start")
		logger.debug("launchDict = {}".format(launchDict))
		logger.debug("allAgentDict = {}".format(allAgentDict))
		logger.debug("procName = {}".format(procName))
		logger.debug("managerId = {}".format(managerId))
		logger.debug("managementPipe = {}".format(managementPipe))

		try:
			#Instantiate agents
			logger.info("Instantiating agents")
			procAgentDict = {}
			for agentId in launchDict:
				logger.debug("Instantiating {}".format(launchDict[agentId]))
				agentObj = launchDict[agentId].spawnAgent()
				procAgentDict[agentId] = agentObj

			procAgentList = list(procAgentDict.keys())

			#All agents instantiated. Notify manager
			managerPacket = NetworkPacket(senderId=procName, destinationId=managerId, msgType="PROC_READY")
			networkPacket = NetworkPacket(senderId=procName, destinationId=managerId, msgType="CONTROLLER_MSG", payload=managerPacket)
			managementPipe.sendPipe.send(networkPacket)
			
		except Exception as e:
			logger.error("Error while instantiating agents")
			logger.error(traceback.format_exc())

			#Notify manager of error
			managerPacket = NetworkPacket(senderId=procName, destinationId=managerId, msgType="PROC_ERROR", payload=traceback.format_exc())
			networkPacket = NetworkPacket(senderId=procName, destinationId=managerId, msgType="CONTROLLER_MSG", payload=managerPacket)
			managementPipe.sendPipe.send(networkPacket)


		#Wait for manager to end us
		while True:
			logger.debug("Waiting for stop command or kill command")

			incommingPacket = managementPipe.recvPipe.recv()
			logger.debug("INBOUND {}".format(incommingPacket))
			if ((incommingPacket.msgType == "PROC_STOP") or (incommingPacket.msgType == "KILL_ALL_BROADCAST")):
				logger.info("Stoppinng process")

				networkPacket = NetworkPacket(senderId=procName, msgType="KILL_PIPE_NETWORK")
				logger.debug("OUTBOUND {}".format(networkPacket))
				managementPipe.sendPipe.send(networkPacket)

				break

		return
	except KeyboardInterrupt:
		curr_proc = multiprocessing.current_process()
		print("###################### INTERUPT {} ######################".format(curr_proc))

		controllerMsg = NetworkPacket(senderId=procName, msgType="STOP_TRADING")
		networkPacket = NetworkPacket(senderId=procName, msgType="CONTROLLER_MSG_BROADCAST", payload=controllerMsg)
		logger.critical("OUTBOUND {}".format(networkPacket))
		managementPipe.sendPipe.send(networkPacket)
		time.sleep(1)

		networkPacket = NetworkPacket(senderId=procName, msgType="KILL_ALL_BROADCAST")
		logger.critical("OUTBOUND {}".format(networkPacket))
		managementPipe.sendPipe.send(networkPacket)
		networkPacket = NetworkPacket(senderId=procName, msgType="KILL_PIPE_NETWORK")
		logger.critical("OUTBOUND {}".format(networkPacket))
		managementPipe.sendPipe.send(networkPacket)
		time.sleep(1)

		try:	
			curr_proc.terminate()
		except Exception as e:
			print("### {} Error when terminating proc {}".format(e, curr_proc))
			print(traceback.format_exc())


if __name__ == "__main__":
	childProcesses = []
	try:
		######################
		# Parse All Items
		######################
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

		########################################
		# Create AgentSeeds for each subprocess
		########################################
		spawnDict = {}
		procDict = {}
		allAgentDict = {}

		numProcess = 2
		for procNum in range(numProcess):
			spawnDict[procNum] = {}

			procName = "Simulation_Proc{}".format(procNum)
			procDict[procName] = True

		#Create buyer seeds
		numBuyers = 10
		for i in range(numBuyers):
			agentId = "buyer_{}".format(i)
			procNum = i%numProcess

			agentSeed = AgentSeed(agentId, "TestBuyer", itemDict=allItemsDict)
			spawnDict[procNum][agentId] = agentSeed
			allAgentDict[agentId] = agentSeed.agentInfo

		#Create seller seeds
		numSellers = 10
		for i in range(numSellers):
			agentId = "seller_{}".format(i)
			procNum = i%numProcess

			agentSeed = AgentSeed(agentId, "TestSeller", itemDict=allItemsDict)
			spawnDict[procNum][agentId] = agentSeed
			allAgentDict[agentId] = agentSeed.agentInfo
		
		###########################
		# Setup Simulation Manager
		###########################
		managerId = "simManager"
		simManagerSeed = SimulationManagerSeed(managerId, allAgentDict, procDict)

		##########################
		# Setup ConnectionNetwork
		##########################
		#Instantiate network
		xactNetwork = ConnectionNetwork()
		xactNetwork.addConnection(agentId=managerId, networkLink=simManagerSeed.networkLink)
		for procNum in spawnDict:
			for agentId in spawnDict[procNum]:
				xactNetwork.addConnection(agentId=agentId, networkLink=spawnDict[procNum][agentId].networkLink)

		##########################
		# Launch subprocesses
		##########################

		#Launch agent procs
		for procNum in spawnDict:
			procName = "Simulation_Proc{}".format(procNum)

			networkPipeRecv, managementPipeSend = multiprocessing.Pipe()
			managementPipeRecv, networkPipeSend = multiprocessing.Pipe()
			networkLink = Link(sendPipe=networkPipeSend, recvPipe=networkPipeRecv)
			managementLink = Link(sendPipe=managementPipeSend, recvPipe=managementPipeRecv)

			xactNetwork.addConnection(agentId=procName, networkLink=networkLink)

			proc = multiprocessing.Process(target=launchAgents, args=(spawnDict[procNum], allAgentDict, procName, managerId, managementLink))
			childProcesses.append(proc)
			proc.start()

		#Launch connection network
		xactNetwork.startMonitors()

		##########################
		# Start simulation
		##########################
		managerProc = multiprocessing.Process(target=launchSimulation, args=(simManagerSeed,))
		childProcesses.append(managerProc)
		managerProc.start()
		#managerProc.join()  #DO NOT use a join statment here, or anywhere else in this function. It breaks interrupt handling

	except KeyboardInterrupt:
		for proc in childProcesses:
			try:
				print("### TERMINATE {}".format(proc.name))
				proc.terminate()
				print("### TERMINATED {}".format(proc.name))
			except Exception as e:
				print("### FAILED_TERMINANE, error = {}".format(e))

