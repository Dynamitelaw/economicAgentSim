'''
These controllers are use for AI training or sim parameter optimization
'''
import random
import os
import threading
import math
import traceback

import utils
from TradeClasses import *
from NetworkClasses import *


####################
# AI Performance Calc
####################
class AITracker:
	'''
	This controller will collect performance stats at the end of each simulation to provide feedback to AI performance
	'''
	def __init__(self, agent, settings={}, logFile=True, fileLevel="INFO", outputDir="OUTPUT"):
		self.agent = agent
		self.agentId = agent.agentId
		self.simManagerId = agent.simManagerId

		self.name = "{}_AITracker".format(agent.agentId)

		self.logger = utils.getLogger("Controller_{}".format(self.agentId), logFile=logFile, outputdir=os.path.join(outputDir, "LOGS", "Controller_Logs"), fileLevel=fileLevel)

		#Which agent types are we training?
		self.aiAgentFilter = "AI"
		if ("AIFilter" in settings):
			self.aiAgentFilter = settings["AIFilter"]

		#Which agent types are the control?
		self.controlAgentFilter = "Basic"
		if ("ControlFilter" in settings):
			self.controlAgentFilter = settings["ControlFilter"]

		#Keep track of performance stats
		self.aiAccountingStats = {}
		self.controlAccountingStats = {}


	def controllerStart(self, incommingPacket):
		pass


	def receiveMsg(self, incommingPacket):
		self.logger.info("INBOUND {}".format(incommingPacket))

		#Handle new tick grants
		if (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT) or (incommingPacket.msgType == PACKET_TYPE.TICK_GRANT_BROADCAST):
			if (self.agent.stepNum == 0):
				#Tell all controllers to reset their accounting totals
				resetAccountingMsg = NetworkPacket(senderId=self.agentId, msgType=PACKET_TYPE.RESET_ACCOUNTING)
				resetPacket = NetworkPacket(senderId=self.agentId, msgType=PACKET_TYPE.CONTROLLER_MSG_BROADCAST, payload=resetAccountingMsg)
				self.agent.sendPacket(resetPacket)

		#Hande info responses
		if (incommingPacket.msgType == PACKET_TYPE.INFO_RESP):
			if (incommingPacket.payload.transactionId == "AIBusinessPerformace"):
				self.aiAccountingStats[incommingPacket.senderId] = incommingPacket.payload.info
			if (incommingPacket.payload.transactionId == "ControlBusinessPerformace"):
				self.controlAccountingStats[incommingPacket.senderId] = incommingPacket.payload.info

		#Handle controller messages
		if ((incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG) or (incommingPacket.msgType == PACKET_TYPE.CONTROLLER_MSG_BROADCAST)):
			controllerMsg = incommingPacket.payload
			self.logger.info("INBOUND {}".format(controllerMsg))
			
			#Handle STOP_TRADING packets
			if (controllerMsg.msgType == PACKET_TYPE.STOP_TRADING):
				self.logger.info("Gathering performance stats")
				#The simulation is ending. Gather AI agent performance data
				aiInfoReq = InfoRequest(requesterId=self.agentId, transactionId="AIBusinessPerformace", infoKey="acountingStats", agentFilter=self.aiAgentFilter)
				aiInfoReqPacket = NetworkPacket(senderId=self.agentId, msgType=PACKET_TYPE.INFO_REQ_BROADCAST, payload=aiInfoReq)
				self.agent.sendPacket(aiInfoReqPacket)

				#Gather control agent performance data
				controlInfoReq = InfoRequest(requesterId=self.agentId, transactionId="ControlBusinessPerformace", infoKey="acountingStats", agentFilter=self.controlAgentFilter)
				controlInfoReqPacket = NetworkPacket(senderId=self.agentId, msgType=PACKET_TYPE.INFO_REQ_BROADCAST, payload=controlInfoReq)
				self.agent.sendPacket(controlInfoReqPacket)

			#Handle SIM_END packets
			if (controllerMsg.msgType == PACKET_TYPE.SIM_END):
				#Simulation has ended

				#Print AI stats into log
				self.logger.info("### AI Accounting Stats ###")
				for agentName in self.aiAccountingStats:
					self.logger.info("{} performance = {}".format(agentName, self.aiAccountingStats[agentName]))

				#Print control stats into log
				self.logger.info("### Control Accounting Stats ###")
				for agentName in self.controlAccountingStats:
					self.logger.info("{} performance = {}".format(agentName, self.controlAccountingStats[agentName]))
			