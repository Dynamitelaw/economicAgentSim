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

from EconAgent import *
from NetworkClasses import *
from TradeClasses import *
import utils


class SimulationManagerSeed:
	'''
	Used to spawn a simulation manager
	'''
	def __init__(self, managerId, allAgentDict, allProcDict, logFile=True):
		self.managerId = managerId
		self.agentType = "SimulationManager"
		self.agentInfo = AgentInfo(self.managerId, self.agentType)
		self.logFile = logFile

		self.allAgentDict = allAgentDict
		self.allProcDict = allProcDict

		networkPipeRecv, agentPipeSend = multiprocessing.Pipe()
		agentPipeRecv, networkPipeSend = multiprocessing.Pipe()

		self.networkLink = Link(sendPipe=networkPipeSend, recvPipe=networkPipeRecv)
		self.agentLink = Link(sendPipe=agentPipeSend, recvPipe=agentPipeRecv)

	def spawnManager(self):
		return SimulationManager(self.agentInfo, allAgentDict=self.allAgentDict, allProcDict=self.allProcDict, networkLink=self.agentLink, logFile=self.logFile)


class SimulationManager:
	'''
	The master object that controls and manages the simulation using network commands
	'''
	def __init__(self, agentInfo, allAgentDict, allProcDict, networkLink=None, logFile=True, controller=None):
		self.info = agentInfo
		self.agentId = agentInfo.agentId
		self.agentType = agentInfo.agentType

		self.logger = utils.getLogger("{}:{}".format("SimulationManager", self.agentId), console="INFO", logFile=logFile)
		self.logger.info("{} instantiated".format(self.info))

		self.agentDict = allAgentDict
		self.procDict = allProcDict

		self.procReadyDict = {}
		self.procReadyDictLock = threading.Lock()
		self.procErrors = {}

		self.timeTickBlockers = {}
		self.timeTickBlockers_Lock = threading.Lock()

		#Spawn agent
		self.agent = Agent(self.info, networkLink=networkLink, logFile=logFile, controller=self)


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


		if (agentsInstantiated):
			self.logger.info("All agents are instantiated")

			#Start all agent controllers
			self.logger.info("Starting all agent controllers")
			controllerStartBroadcast = NetworkPacket(senderId=self.agentId, msgType="CONTROLLER_START_BROADCAST")
			self.agent.sendPacket(controllerStartBroadcast)
			time.sleep(3)  #Sleep to give controllers time to start blocking protocols #TODO: calculate sleep time based on size of agentDict

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
				for stepNum in tqdm (range (simulationSteps), ascii=False, ncols=80):
					#Start new simulation day
					self.logger.debug("Running simulation step {}".format(stepNum))

					#Set all tick blockers to False
					self.timeTickBlockers_Lock.acquire()
					for agentId in self.timeTickBlockers:
						self.timeTickBlockers[agentId] = False  #this agent is no longer blocked by time ticks
					self.timeTickBlockers_Lock.release()

					#Distribute ticks to agents
					tickGrantPacket = NetworkPacket(senderId=self.agentId, msgType="TICK_GRANT_BROADCAST", payload=ticksPerStep)
					self.logger.debug("OUTBOUND {}".format(tickGrantPacket))
					self.agent.sendPacket(tickGrantPacket)

					#Wait for all tick blockers to be set before advancing to next day
					self.logger.debug("Waiting for all agents to be tick blocked")
					allAgentsBlocked = False
					while True:
						allAgentsBlocked = True
						for agentId in self.timeTickBlockers:
							agentBlocked = self.timeTickBlockers[agentId]
							if (not agentBlocked):
								#self.logger.debug("Still waiting for {} to be tick blocked".format(agentId))
								allAgentsBlocked = False
								break

						if (allAgentsBlocked):
							self.logger.debug("All agents are tick blocked")
							break

					#End simulation day
					self.logger.debug("Ending simulation step {}".format(stepNum))

			#Calculate runtime
			print("\n")
			endTime = time.time()
			elapsedSeconds = endTime - startTime
			elapsedSring = str(timedelta(seconds=elapsedSeconds))
			self.logger.info("Simulation (Steps={}, TicksPerStep={}) took {} to run".format(simulationSteps, ticksPerStep, elapsedSring))


		#Stop all trading
		try:
			self.logger.info("Stopping all trading activity")
			controllerMsg = NetworkPacket(senderId=self.agentId, msgType="STOP_TRADING")
			networkPacket = NetworkPacket(senderId=self.agentId, msgType="CONTROLLER_MSG_BROADCAST", payload=controllerMsg)
			self.agent.sendPacket(networkPacket)
			time.sleep(3)
		except Exception as e:
			self.logger.error("Error while sending STOP_TRADING command to agents")
			self.logger.error(traceback.format_exc())

		#Broadcast kill command
		try:
			self.logger.info("Killing all network connections")
			killPacket = NetworkPacket(senderId=self.agentId, msgType="KILL_ALL_BROADCAST")
			self.agent.sendPacket(killPacket)
			time.sleep(3)
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
			controllerMsg = NetworkPacket(senderId=self.agentId, msgType="STOP_TRADING")
			networkPacket = NetworkPacket(senderId=self.agentId, msgType="CONTROLLER_MSG_BROADCAST", payload=controllerMsg)
			self.logger.critical("OUTBOUND {}".format(networkPacket))
			self.agent.sendPacket(networkPacket)
			time.sleep(1)
		except Exception as e:
			self.logger.error("Error while sending STOP_TRADING command to agents")
			self.logger.error(traceback.format_exc())

		#Broadcast kill command
		try:
			self.logger.critical("Killing all network connections")
			killPacket = NetworkPacket(senderId=self.agentId, msgType="KILL_ALL_BROADCAST")
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

		if ((incommingPacket.msgType == "CONTROLLER_MSG") or (incommingPacket.msgType == "CONTROLLER_MSG_BROADCAST")):
			controllerMsg = incommingPacket.payload
			self.logger.debug("INBOUND {}".format(controllerMsg))

			#Handle process messages
			if (controllerMsg.msgType == "PROC_READY"):
				self.procReadyDictLock.acquire()
				self.procReadyDict[controllerMsg.senderId] = True
				self.procReadyDictLock.release()
			if (controllerMsg.msgType == "PROC_ERROR"):
				self.procReadyDictLock.acquire()
				self.procReadyDict[controllerMsg.senderId] = False
				self.procErrors[controllerMsg.senderId] = controllerMsg.payload
				self.procReadyDictLock.release()

			#Handle time tick messages
			if (controllerMsg.msgType == "TICK_BLOCK_SUBSCRIBE"):
				self.logger.debug("{} has subscribed to tick blocking".format(controllerMsg.senderId))
				self.timeTickBlockers_Lock.acquire()
				self.timeTickBlockers[controllerMsg.senderId] = True
				self.timeTickBlockers_Lock.release()
			if (controllerMsg.msgType == "TICK_BLOCKED"):
				#self.timeTickBlockers_Lock.acquire()
				self.timeTickBlockers[controllerMsg.senderId] = True  #This agent is now blocked by time ticks
				#self.timeTickBlockers_Lock.release()

			#Handle error messages
			if (controllerMsg.msgType == "TERMINATE_SIMULATION"):
				self.terminate()

	def evalTradeRequest(self, request):
		return False
