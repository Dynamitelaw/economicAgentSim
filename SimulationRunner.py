'''
Contains the functions needed to run a single simulation
'''
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
from NetworkClasses import *
from ConnectionNetwork import *
from TradeClasses import *
from SimulationManager import *
from StatisticsGatherer import *
import utils


def launchSimulation(simManagerSeed, statisticsGathererSeed, settingsDict):
	try:
		statsGatherer = statisticsGathererSeed.spawnGatherer()
		simManager = simManagerSeed.spawnManager()
		simManager.runSim(settingsDict)
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
	'''
	Instantiate all agents in launchDict, then wait for a kill message from Simulation Manager before exiting
	'''
	try:
		logger = utils.getLogger("{}:{}".format(__name__, procName), console="INFO")

		curr_proc = multiprocessing.current_process()
		logger.info("{} started".format(procName))

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


def RunSimulation(settingsDict, logLevel="INFO"):
	'''
	Run's a single simulation with the specified settings
	'''
	logger = utils.getLogger("SimulationRunner:RunSimulation")
	logger.info("settingsDict={}".format(settingsDict))

	childProcesses = []
	try:
		######################
		# Parse All Items
		######################
		logger.info("Parsing items")

		#Congregate items into into a single dict
		allItemsDict = {}
		for fileName in os.listdir("Items"):
			try:
				path = os.path.join("Items", fileName)
				if (os.path.isfile(path)):
					itemDictFile = open(path, "r")
					itemDict = json.load(itemDictFile)
					itemDictFile.close()

					allItemsDict[itemDict["id"]] = itemDict
				elif (os.path.isdir(path)):
					for subFileName in os.listdir(path):
						subPath = os.path.join(path, subFileName)
						if (os.path.isfile(subPath)):
							itemDictFile = open(subPath, "r")
							itemDict = json.load(itemDictFile)
							itemDictFile.close()

							allItemsDict[itemDict["id"]] = itemDict
			except:
				pass

		########################################
		# Create AgentSeeds for each subprocess
		########################################
		managerId = "simManager"
		if ((not "SimulationSteps" in settingsDict) or (not "TicksPerStep" in settingsDict)):
			logger.error("Missing \"SimulationSteps\" and/or \"TicksPerStep\" from settings. Won't run simulation")

		logger.debug("SimulationSteps = {}".format(settingsDict["SimulationSteps"]))
		print("SimulationSteps = {}".format(settingsDict["SimulationSteps"]))
		logger.debug("TicksPerStep = {}".format(settingsDict["TicksPerStep"]))
		print("TicksPerStep = {}".format(settingsDict["TicksPerStep"]))


		#Setup spawn and process dicts
		spawnDict = {}
		procDict = {}
		allAgentDict = {}

		if not ("AgentNumProcesses" in settingsDict):
			logger.error("\"AgentNumProcesses\" missing from settings. Won't run simulation")
			return None

		numProcess = settingsDict["AgentNumProcesses"]
		logger.debug("AgentNumProcesses={}".format(numProcess))
		print("Agent Processes = {}\n".format(numProcess))
		for procNum in range(numProcess):
			spawnDict[procNum] = {}

			procName = "Simulation_Proc{}".format(procNum)
			procDict[procName] = True

		#Create agent seeds
		for agentName in settingsDict["AgentSpawns"]:
			for agentType in settingsDict["AgentSpawns"][agentName]:
				agentSettings = settingsDict["AgentSpawns"][agentName][agentType]

				if not ("quantity" in agentSettings):
					logger.error("\"quantity\" missing from \"{}\" settings. Won't run simulation".format(agentType))
					return None

				numAgents = agentSettings["quantity"]
				logger.debug("{}.{} Agents = {}".format(agentName, agentType, numAgents))
				print("{}.{} Agents = {}".format(agentName, agentType, numAgents))

				for i in range(numAgents):
					agentId = "{}.{}.{}".format(agentName, agentType, i)
					procNum = i%numProcess

					spawnSettings = {}
					if ("settings" in agentSettings):
						spawnSettings = agentSettings["settings"]
					agentSeed = AgentSeed(agentId, agentType, ticksPerStep=settingsDict["TicksPerStep"], settings=spawnSettings, simManagerId=managerId, itemDict=allItemsDict, fileLevel=logLevel)
					spawnDict[procNum][agentId] = agentSeed
					allAgentDict[agentId] = agentSeed.agentInfo
		print("\n")
		
		###########################
		# Setup Simulation Manager
		###########################
		simManagerSeed = SimulationManagerSeed(managerId, allAgentDict, procDict)

		###########################
		# Setup Statistics Gatherer
		###########################
		statsGathererId = "StatSlurper"
		statisticsGathererSeed = StatisticsGathererSeed(statsGathererId, settings=settingsDict, simManagerId=managerId, itemDict=allItemsDict, allAgentDict=allAgentDict)

		##########################
		# Setup ConnectionNetwork
		##########################
		xactNetwork = ConnectionNetwork(itemDict=allItemsDict, simManagerId=managerId)
		xactNetwork.addConnection(agentId=managerId, networkLink=simManagerSeed.networkLink)
		xactNetwork.addConnection(agentId=statsGathererId, networkLink=statisticsGathererSeed.networkLink)
		for procNum in spawnDict:
			for agentId in spawnDict[procNum]:
				xactNetwork.addConnection(agentId=agentId, networkLink=spawnDict[procNum][agentId].networkLink)

		##########################
		# Launch subprocesses
		##########################

		#Launch agent processes
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
		managerProc = multiprocessing.Process(target=launchSimulation, args=(simManagerSeed, statisticsGathererSeed, settingsDict))
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

