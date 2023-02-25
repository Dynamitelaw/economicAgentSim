'''
The SimulationManager controls and manages the simulation using network commands
'''
import json
import os
import logging
import time
import traceback
import threading
from datetime import timedelta
from tqdm import tqdm
import math

from EconAgent import *
from NetworkClasses import *
from TradeClasses import *
import utils


class SimulationManagerSeed:
	'''
	Used to spawn a simulation manager
	'''
	def __init__(self, managerId, allAgentDict, allProcDict, logFile=True, logLevel="INFO", outputDir="OUTPUT", checkpointFrequency=None, initialCheckpoint=None):
		self.managerId = managerId
		self.agentType = "SimulationManager"
		self.agentInfo = AgentInfo(self.managerId, self.agentType)
		self.logFile = logFile
		self.outputDir = outputDir
		self.logLevel = logLevel
		self.checkpointFrequency = checkpointFrequency
		self.initialCheckpoint = initialCheckpoint

		self.allAgentDict = allAgentDict
		self.allProcDict = allProcDict

		networkPipeRecv, agentPipeSend = multiprocessing.Pipe()
		agentPipeRecv, networkPipeSend = multiprocessing.Pipe()

		self.networkLink = Link(sendPipe=networkPipeSend, recvPipe=networkPipeRecv)
		self.agentLink = Link(sendPipe=agentPipeSend, recvPipe=agentPipeRecv)

	def spawnManager(self):
		return SimulationManager(self.agentInfo, allAgentDict=self.allAgentDict, allProcDict=self.allProcDict, networkLink=self.agentLink, logFile=self.logFile, logLevel=self.logLevel, outputDir=self.outputDir, checkpointFrequency=self.checkpointFrequency, initialCheckpoint=self.initialCheckpoint)


class SimulationManager:
	'''
	The master object that controls and manages the simulation using network commands
	'''
	def __init__(self, agentInfo, allAgentDict, allProcDict, networkLink=None, logFile=True, logLevel="INFO", outputDir="OUTPUT", controller=None, checkpointFrequency=None, initialCheckpoint=None):
		self.info = agentInfo
		self.agentId = agentInfo.agentId
		self.agentType = agentInfo.agentType

		self.logger = utils.getLogger("{}:{}".format("SimulationManager", self.agentId), outputdir=os.path.join(outputDir, "LOGS"), console="INFO", logFile=logFile, fileLevel=logLevel)
		self.logger.info("{} instantiated".format(self.info))

		self.agentDict = allAgentDict
		self.procDict = allProcDict

		self.procReadyDict = {}
		self.procReadyDictLock = threading.Lock()
		self.procErrors = {}

		self.allAgentsReady = False
		self.checkpointFrequency = checkpointFrequency
		self.initialCheckpoint = initialCheckpoint

		#Spawn agent
		self.agent = Agent(self.info, networkLink=networkLink, logFile=logFile, controller=self, outputDir=outputDir)


	def runSim(self, settingsDict):
		'''
		Runs a single simulation
		'''

		#Wait for all agents to be instantiated
		self.logger.info("Waiting for all agents to be instantiated")
		agentsInstantiated = False
		while True:
			self.procReadyDictLock.acquire()
			if (len(self.procReadyDict) == len(self.procDict)):
				agentsInstantiated = True
			self.procReadyDictLock.release()

			if (agentsInstantiated):
				break

			time.sleep(0.001)

		if (len(self.procErrors) > 0):
			#There were errors during instantiation
			self.logger.error("Could not instantiate all agents. Will not run simulation")
			for procName in self.procErrors:
				self.logger.error("Error in {}".format(procName))
				self.logger.error(self.procErrors[procName])

			agentsInstantiated = False


		#Determine initial startup wait time
		sleepTime = 2
		if (len(self.agentDict) > 0):
			sleepTime = math.ceil(pow(len(self.agentDict)/len(self.procDict), 0.25))
			if (sleepTime < 2):
				sleepTime = 2

		if (agentsInstantiated):
			self.logger.info("All agents are instantiated")

			#Start all agent controllers
			self.logger.info("Starting all agent controllers")
			controllerStartBroadcast = NetworkPacket(senderId=self.agentId, msgType=PACKET_TYPE.CONTROLLER_START_BROADCAST)
			self.agent.sendPacket(controllerStartBroadcast)
			time.sleep(sleepTime)  #Sleep to give controllers time to start blocking protocols

			#Load initial checkpoint if specified
			if (self.initialCheckpoint):
				if (os.path.exists(self.initialCheckpoint)):
					self.logger.info("Loading initial state from checkpoint \"{}\"".format(self.initialCheckpoint))
					loadCheckpointBroadcast = NetworkPacket(senderId=self.agentId, msgType=PACKET_TYPE.LOAD_CHECKPOINT_BROADCAST, payload=self.initialCheckpoint)
					self.agent.sendPacket(loadCheckpointBroadcast)
					time.sleep(sleepTime*3)
				else:
					self.logger.warning("Initial checkpoint path \"{}\" not found. Ignoring checkpoint load".format(self.initialCheckpoint))

			#Run simulation for specified time
			startTime = time.time()
			skipSimulation = False
			if ((not "SimulationSteps" in settingsDict) or (not "TicksPerStep" in settingsDict)):
				self.logger.error("Missing SimulationSteps and/or TicksPerStep from settings. Won't run simulation")
				skipSimulation = True

			if (not skipSimulation):
				simulationSteps = int(settingsDict["SimulationSteps"])
				ticksPerStep = int(settingsDict["TicksPerStep"])

				self.logger.info("Starting Simulation (Steps={}, TicksPerStep={})".format(simulationSteps, ticksPerStep))
				print("\n")
				avgStepTime = 0
				for stepNum in tqdm (range (simulationSteps), ascii=False, ncols=80):
					stepStart = time.time()
					#Start new simulation day
					self.logger.debug("Running simulation step {}".format(stepNum))
					self.allAgentsReady = False

					#Distribute ticks to agents
					tickGrantPacket = NetworkPacket(senderId=self.agentId, msgType=PACKET_TYPE.TICK_GRANT_BROADCAST, payload=ticksPerStep)
					self.logger.debug("OUTBOUND {}".format(tickGrantPacket))
					self.agent.sendPacket(tickGrantPacket)

					#Wait for all tick blockers to be set before advancing to next day
					self.logger.debug("Waiting for all agents to be tick blocked")
					pollCntr = 0
					warningSent = False
					while (not self.allAgentsReady):
						time.sleep(0.001)
						pollCntr += 1
						if (pollCntr >= 1000):
							currentStepTime = time.time() - stepStart
							if ((currentStepTime > (20*avgStepTime)) and (avgStepTime > 0)):
								self.logger.debug("Still waiting for agents to be unblocked")
							if ((currentStepTime > sleepTime*60) and (not warningSent) and (avgStepTime == 0)):
								self.logger.warning("Still waiting for agents to be unblocked")
								warningSent = True
							pollCntr = 0

					#End simulation day
					self.logger.debug("Ending simulation step {}".format(stepNum))
					stepEnd = time.time()
					stepTime = stepEnd - stepStart
					alpha = 0.3
					avgStepTime = ((1-alpha)*avgStepTime) + (alpha*stepTime)

					#Save checkpoint
					if (self.checkpointFrequency):
						if ((stepNum > 0) and (stepNum%self.checkpointFrequency == 0)):
							self.logger.debug("Saving simulation checkpoint")
							checkpointPacket = NetworkPacket(senderId=self.agentId, msgType=PACKET_TYPE.SAVE_CHECKPOINT_BROADCAST)
							self.agent.sendPacket(checkpointPacket)

			#Calculate runtime
			print("\n")
			endTime = time.time()
			elapsedSeconds = endTime - startTime
			elapsedSring = str(timedelta(seconds=elapsedSeconds))
			self.logger.info("Simulation (Steps={}, TicksPerStep={}) took {} to run".format(simulationSteps, ticksPerStep, elapsedSring))
			sleepTime = int(elapsedSeconds/simulationSteps)+1


		#Stop all trading
		try:
			self.logger.info("Stopping all trading activity")
			controllerMsg = NetworkPacket(senderId=self.agentId, msgType=PACKET_TYPE.STOP_TRADING)
			networkPacket = NetworkPacket(senderId=self.agentId, msgType=PACKET_TYPE.CONTROLLER_MSG_BROADCAST, payload=controllerMsg)
			self.agent.sendPacket(networkPacket)
			time.sleep(sleepTime)
		except Exception as e:
			self.logger.error("Error while sending STOP_TRADING command to agents")
			self.logger.error(traceback.format_exc())

		#Notify all controllers of simulation ending 
		try:
			self.logger.info("Ending simulation")
			controllerMsg = NetworkPacket(senderId=self.agentId, msgType=PACKET_TYPE.SIM_END)
			networkPacket = NetworkPacket(senderId=self.agentId, msgType=PACKET_TYPE.CONTROLLER_MSG_BROADCAST, payload=controllerMsg)
			self.agent.sendPacket(networkPacket)
			time.sleep(sleepTime)
		except Exception as e:
			self.logger.error("Error while sending SIM_END notification to agents")
			self.logger.error(traceback.format_exc())

		#Broadcast kill command
		try:
			self.logger.info("Killing all network connections")
			killPacket = NetworkPacket(senderId=self.agentId, msgType=PACKET_TYPE.KILL_ALL_BROADCAST)
			self.agent.sendPacket(killPacket)
			time.sleep(sleepTime)
		except Exception as e:
			self.logger.error("Error while killing network link")
			self.logger.error(traceback.format_exc())

		self.logger.info("Simulation complete")
		return


	def terminate(self):
		'''
		Terminate this simulation
		'''
		print("###################### SimulationManager.{}.INTERUPT  ######################".format(self.agentId))
		#Stop all trading
		try:
			self.logger.critical("Stopping all trading activity")
			controllerMsg = NetworkPacket(senderId=self.agentId, msgType=PACKET_TYPE.STOP_TRADING)
			networkPacket = NetworkPacket(senderId=self.agentId, msgType=PACKET_TYPE.CONTROLLER_MSG_BROADCAST, payload=controllerMsg)
			self.logger.critical("OUTBOUND {}".format(networkPacket))
			self.agent.sendPacket(networkPacket)
			time.sleep(1)
		except Exception as e:
			self.logger.error("Error while sending STOP_TRADING command to agents")
			self.logger.error(traceback.format_exc())

		#Broadcast kill command
		try:
			self.logger.critical("Killing all network connections")
			killPacket = NetworkPacket(senderId=self.agentId, msgType=PACKET_TYPE.KILL_ALL_BROADCAST)
			self.logger.critical("OUTBOUND {}".format(killPacket))
			self.agent.sendPacket(killPacket)
			time.sleep(1)
		except Exception as e:
			self.logger.error("Error while killing network link")
			self.logger.error(traceback.format_exc())


	def controllerStart(self, incommingPacket):
		return

	def receiveMsg(self, incommingPacket):
		self.logger.debug("INBOUND {}".format(incommingPacket))

		if ((incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG) or (incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG_BROADCAST)):
			controllerMsg = incommingPacket.payload
			self.logger.debug("INBOUND {}".format(controllerMsg))

			#Handle process messages
			if (controllerMsg.msgType == PACKET_TYPE.PROC_READY):
				self.procReadyDictLock.acquire()
				self.procReadyDict[controllerMsg.senderId] = True
				self.procReadyDictLock.release()
			if (controllerMsg.msgType == PACKET_TYPE.PROC_ERROR):
				self.procReadyDictLock.acquire()
				self.procReadyDict[controllerMsg.senderId] = False
				self.procErrors[controllerMsg.senderId] = controllerMsg.payload
				self.procReadyDictLock.release()

			#Handle time tick messages
			if (controllerMsg.msgType == PACKET_TYPE.ADVANCE_STEP):
				self.allAgentsReady = True

			#Handle error messages
			if (controllerMsg.msgType == PACKET_TYPE.TERMINATE_SIMULATION):
				self.terminate()

	def evalTradeRequest(self, request):
		return False
