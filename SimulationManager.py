import json
import os
import logging
import time
import traceback
import threading

from EconAgent import *
from ConnectionNetwork import *
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
	The master object that controls and manages the a simulation using network commands
	'''
	def __init__(self, agentInfo, allAgentDict, allProcDict, networkLink=None, logFile=True, controller=None):
		self.info = agentInfo
		self.agentId = agentInfo.agentId
		self.agentType = agentInfo.agentType

		self.logger = utils.getLogger("{}:{}".format("SimulationManager", self.agentId), console="INFO", logFile=logFile)
		self.logger.debug("{} instantiated".format(self.info))

		self.agentDict = allAgentDict
		self.procDict = allProcDict

		self.procReadyDict = {}
		self.procReadyDictLock = threading.Lock()
		self.procErrors = {}

		#Spawn agent
		self.agent = Agent(self.info, networkLink=networkLink, logFile=logFile, controller=self)


	def runSim(self, simSettings=None):
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
			self.logger.error("Could not instantiate all agents")
			for procName in self.procErrors:
				self.logger.error("Error in {}".format(procName))
				self.logger.error(self.procErrors[procName])

			agentsInstantiated = False


		if (agentsInstantiated):
			self.logger.info("All agents are instantiated")
			#Initialize agent values
			pass

			#Start all agent controllers
			self.logger.info("Starting all agent controllers")
			controllerStartBroadcast = NetworkPacket(senderId=self.agentId, msgType="CONTROLLER_START_BROADCAST")
			self.agent.sendPacket(controllerStartBroadcast)
			time.sleep(3)  #TODO: calculate sleep time based on size of agentDict

			#Wait while agents trade amongst themselves
			waitTime = 60
			self.logger.info("Waiting {} min {} sec for trading to continue".format(int(waitTime/60), waitTime%60))
			time.sleep(waitTime)

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
		print("###################### SimulationManager.{}.INTERUPT ######################".format(self.agentId))
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
		controllerMsg = incommingPacket.payload
		self.logger.debug("INBOUND {}".format(controllerMsg))

		if (controllerMsg.msgType == "PROC_READY"):
			self.procReadyDictLock.acquire()
			self.procReadyDict[controllerMsg.senderId] = True
			self.procReadyDictLock.release()
		if (controllerMsg.msgType == "PROC_ERROR"):
			self.procReadyDictLock.acquire()
			self.procReadyDict[controllerMsg.senderId] = False
			self.procErrors[controllerMsg.senderId] = controllerMsg.payload
			self.procReadyDictLock.release()

	def evalTradeRequest(self, request):
		return False
