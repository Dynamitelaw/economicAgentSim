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
import gc
#import tracemalloc

from EconAgent import *
from NetworkClasses import *
from ConnectionNetwork import *
from TradeClasses import *
from SimulationManager import *
import utils


def launchSimulation(simManagerSeed, settingsDict):
	try:
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
			#print(traceback.format_exc())


def launchAgents(launchDict, allAgentDict, procName, managerId, managementPipe, outputDir="OUTPUT", logLevel="WARNING"):
	'''
	Instantiate all agents in launchDict, then wait for a kill message from Simulation Manager before exiting
	'''
	try:
		outputDirPath = outputDir
		logger = utils.getLogger("{}:{}".format(__name__, procName), console="INFO", outputdir=os.path.join(outputDirPath, "LOGS"), fileLevel=logLevel)

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
			managerPacket = NetworkPacket(senderId=procName, destinationId=managerId, msgType=PACKET_TYPE.PROC_READY)
			networkPacket = NetworkPacket(senderId=procName, destinationId=managerId, msgType=PACKET_TYPE.CONTROLLER_MSG, payload=managerPacket)
			managementPipe.sendPipe.send(networkPacket)

			#Memory leak finder
			# tracemalloc.start(10)
			# warmupSnapshot = None

			#Wait for manager to end us
			stepCounter = -1
			garbageCollectionFrequency = 20
			while True:
				logger.debug("Monitoring network link")

				incommingPacket = managementPipe.recvPipe.recv()
				logger.debug("INBOUND {}".format(incommingPacket))
				if ((incommingPacket.msgType == PACKET_TYPE.PROC_STOP) or (incommingPacket.msgType == PACKET_TYPE.KILL_ALL_BROADCAST)):
					logger.info("Stoppinng process")

					networkPacket = NetworkPacket(senderId=procName, msgType=PACKET_TYPE.KILL_PIPE_NETWORK)
					logger.debug("OUTBOUND {}".format(networkPacket))
					managementPipe.sendPipe.send(networkPacket)

					break
				elif ((incommingPacket.msgType == PACKET_TYPE.TICK_GRANT) or (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT_BROADCAST)):
					#This is the start of a new step.
					stepCounter += 1
					if (stepCounter%garbageCollectionFrequency == 0):
						#Manually call the garbage collector to prevent persistent memory leaks
						logger.debug("Running garbage collector")
						gc.collect()

					# #Memory leak finder
					# warmupStep = 50
					# snapshotStep = 500
					# if (stepCounter == warmupStep):
					# 	gc.collect()
					# 	warmupSnapshot = tracemalloc.take_snapshot()
					# 	logger.debug("Allocation snapshot taken")
					# elif (stepCounter == snapshotStep):
					# 	gc.collect()
					# 	#top_stats = tracemalloc.take_snapshot().compare_to(warmupSnapshot, 'lineno')
					# 	top_stats = tracemalloc.take_snapshot().compare_to(warmupSnapshot, 'traceback')
					# 	logger.debug("Allocation snapshot taken")
					# 	allocatingLines = []
					# 	statNumber = 50
					# 	logger.debug("### Top {} new memory allocations\n".format(statNumber))
					# 	statCounter = 0
					# 	for stat in top_stats[:statNumber]:
					# 		allocatingLines.append(str(stat))
					# 		statString = "## {} ##\n{}".format(statCounter, stat)
					# 		for line in stat.traceback.format():
					# 			statString = statString + "\n{}".format(line)
					# 		logger.debug(statString)
					# 		statCounter += 1

			
		except Exception as e:
			logger.error("Error while instantiating agents")
			logger.error(traceback.format_exc())

			#Notify manager of error
			managerPacket = NetworkPacket(senderId=procName, destinationId=managerId, msgType=PACKET_TYPE.PROC_ERROR, payload=traceback.format_exc())
			networkPacket = NetworkPacket(senderId=procName, destinationId=managerId, msgType=PACKET_TYPE.CONTROLLER_MSG, payload=managerPacket)
			managementPipe.sendPipe.send(networkPacket)

		return
	except KeyboardInterrupt:
		curr_proc = multiprocessing.current_process()
		print("###################### INTERUPT {} ######################".format(curr_proc))

		controllerMsg = NetworkPacket(senderId=procName, msgType=PACKET_TYPE.STOP_TRADING)
		networkPacket = NetworkPacket(senderId=procName, msgType=PACKET_TYPE.CONTROLLER_MSG_BROADCAST, payload=controllerMsg)
		logger.critical("OUTBOUND {}".format(networkPacket))
		managementPipe.sendPipe.send(networkPacket)
		time.sleep(1)

		networkPacket = NetworkPacket(senderId=procName, msgType=PACKET_TYPE.KILL_ALL_BROADCAST)
		logger.critical("OUTBOUND {}".format(networkPacket))
		managementPipe.sendPipe.send(networkPacket)
		networkPacket = NetworkPacket(senderId=procName, msgType=PACKET_TYPE.KILL_PIPE_NETWORK)
		logger.critical("OUTBOUND {}".format(networkPacket))
		managementPipe.sendPipe.send(networkPacket)
		time.sleep(1)

		try:	
			curr_proc.terminate()
		except Exception as e:
			print("### {} Error when terminating proc {}".format(e, curr_proc))
			#print(traceback.format_exc())


def RunSimulation(settingsDict, logLevel="INFO", outputDir=None):
	'''
	Run's a single simulation with the specified settings
	'''
	#Set output directory
	outputDirPath = outputDir
	if not (outputDirPath):
		outputDirPath = os.path.join("OUTPUT", utils.getTimeStamp())
	utils.createFolderPath(outputDirPath)
	print("Output directory = {}".format(outputDirPath))

	logger = utils.getLogger("SimulationRunner:RunSimulation", outputdir=os.path.join(outputDirPath, "LOGS"))
	logger.info("settingsDict={}".format(settingsDict))
	logger.info("Output directory = {}".format(os.path.abspath(outputDirPath)))
	utils.dictToJsonFile({"settings": settingsDict}, os.path.join(outputDirPath, "settings.json"))

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
		procCounter = 0
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
					procNum = procCounter%numProcess
					procCounter += 1

					spawnSettings = {}
					if ("settings" in agentSettings):
						spawnSettings = agentSettings["settings"]
					agentSeed = AgentSeed(agentId, agentType, ticksPerStep=settingsDict["TicksPerStep"], settings=spawnSettings, simManagerId=managerId, itemDict=allItemsDict, fileLevel=logLevel, outputDir=outputDirPath)
					spawnDict[procNum][agentId] = agentSeed
					allAgentDict[agentId] = agentSeed.agentInfo
		print("\n")
		
		###########################
		# Setup Simulation Manager
		###########################
		checkpointFrequency = None
		if ("CheckpointFrequency" in settingsDict):
			try:
				checkpointFrequency = int(settingsDict["CheckpointFrequency"])
			except:
				raise ValueError("Invalid CheckpointFrequency \"{}\"\n{}".format(settingsDict["CheckpointFrequency"], traceback.format_exc()))

		initialCheckpoint = None
		if ("InitialCheckpoint" in settingsDict):
			try:
				initialCheckpoint = os.path.normpath(settingsDict["InitialCheckpoint"])
			except:
				raise ValueError("Invalid InitialCheckpoint \"{}\"\n{}".format(settingsDict["InitialCheckpoint"], traceback.format_exc()))

		simManagerSeed = SimulationManagerSeed(managerId, allAgentDict, procDict, outputDir=outputDirPath, logLevel=logLevel, checkpointFrequency=checkpointFrequency, initialCheckpoint=initialCheckpoint)

		##########################
		# Setup ConnectionNetwork
		##########################
		xactNetwork = ConnectionNetwork(itemDict=allItemsDict, simManagerId=managerId, simulationSettings=settingsDict, outputDir=outputDirPath, logLevel=logLevel)
		xactNetwork.addConnection(agentId=managerId, networkLink=simManagerSeed.networkLink)
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

			proc = multiprocessing.Process(target=launchAgents, args=(spawnDict[procNum], allAgentDict, procName, managerId, managementLink, outputDirPath, logLevel))
			childProcesses.append(proc)
			proc.start()

		#Launch connection network
		xactNetwork.startMonitors()

		##########################
		# Start simulation
		##########################
		managerProc = multiprocessing.Process(target=launchSimulation, args=(simManagerSeed, settingsDict))
		childProcesses.append(managerProc)
		managerProc.start()
		#managerProc.join()  #DO NOT use a join statment here, or anywhere else in this function. It breaks interrupt handling
		#launchSimulation(simManagerSeed, settingsDict)

	except KeyboardInterrupt:
		for proc in childProcesses:
			try:
				print("### TERMINATE {}".format(proc.name))
				proc.terminate()
				print("### TERMINATED {}".format(proc.name))
			except Exception as e:
				print("### FAILED_TERMINANE, error = {}".format(e))

