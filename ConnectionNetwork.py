'''
The ConnectionNetwork is how all agents in the simulation communicate with each other.

It's set up as a hub and spoke topology, where all agents have a single connection to the ConnectionNetwork object.
Each agent connection is monitored with it's own thread. 
Agents communicate using NetworkPacket objects. Each agent has a unique id to identify it on the network.

The ConnectionNetwork routes all packets to the specified recipient, or to all agents if msgTpye ends with "_BROADCAST"
The network also supports packet snooping, where an agent controller can request to be sent all packets of a specified type, regardless of recipient.

The network will route any packet with a valid destination, regardless of content.
A list of all currently-implemented packet types can be found at the bottom of this file.
'''
import multiprocessing
import threading
import hashlib
import time
import traceback

import utils


class NetworkPacket:
	def __init__(self, senderId, msgType, destinationId=None, payload=None, transactionId=None):
		self.msgType = msgType
		self.payload = payload
		self.senderId = senderId
		self.destinationId = destinationId
		self.transactionId = transactionId

		hashStr = "{}{}{}{}{}{}".format(msgType, payload, senderId, destinationId, transactionId, time.time())
		self.hash = hashlib.sha256(hashStr.encode('utf-8')).hexdigest()[:8 ]

	def __str__(self):
		return "({}_{}, {}, {}, {})".format(self.msgType, self.hash, self.senderId, self.destinationId, self.transactionId)

class Link:
	def __init__(self, sendPipe, recvPipe):
		self.sendPipe = sendPipe
		self.recvPipe = recvPipe

class ConnectionNetwork:
	def __init__(self, logFile=True):
		self.id = "ConnectionNetwork"

		self.logger = utils.getLogger("{}".format(__name__), logFile=logFile)
		self.lockTimeout = 5

		self.agentConnections = {}
		self.agentConnectionsLock = threading.Lock()
		self.sendLocks = {}

		self.snoopDict = {}
		self.snoopDictLock = threading.Lock()

		self.killAllFlag = False
		self.killAllLock = threading.Lock()

	def addConnection(self, agentId, networkLink):
		self.logger.info("Adding connection to {}".format(agentId))
		self.agentConnections[agentId] = networkLink
		self.sendLocks[agentId] = threading.Lock()

	def startMonitors(self):
		for agentId in self.agentConnections:
			monitorThread = threading.Thread(target=self.monitorLink, args=(agentId,))
			monitorThread.start()

	def sendPacket(self, pipeId, packet):
		self.logger.debug("ConnectionNetwork.sendPacket({}, {}) start".format(pipeId, packet))
		if (pipeId in self.agentConnections):
			self.logger.debug("Requesting lock sendLocks[{}]".format(pipeId))
			acquired_sendLock = self.sendLocks[pipeId].acquire()
			if (acquired_sendLock):
				self.logger.debug("Acquired lock sendLocks[{}]".format(pipeId))
				self.logger.info("OUTBOUND {}".format(packet))
				self.agentConnections[pipeId].sendPipe.send(packet)
				self.sendLocks[pipeId].release()
				self.logger.debug("Release lock sendLocks[{}]".format(pipeId))
			else:
				self.logger.error("ConnectionNetwork.sendPacket() Lock sendLocks[{}] acquire timeout".format(pipeId))
		else:
			self.logger.warning("Cannot send {}. Pipe[{}] already killed".format(packet, pipeId))

	def setupSnoop(self, incommingPacket):
		'''
		Add this snoop request to snoop dict
		'''
		self.logger.debug("Handling snoop request {}".format(incommingPacket))
		self.snoopDictLock.acquire()  #<== snoopDictLock acquire
		try:
			snooperId = incommingPacket.senderId
			snoopTypeDict = incommingPacket.payload
			for msgType in snoopTypeDict:
				if (not msgType in self.snoopDict):
					self.snoopDict[msgType] = {}

				self.logger.debug("Adding snoop {} > {} ({})".format(msgType, snooperId, incommingPacket.payload[msgType]))
				self.snoopDict[msgType][snooperId] = incommingPacket.payload[msgType]

		except Exception as e:
			self.logger.error("Could not setup snoop {} | {}".format(incommingPacket, e))

		self.snoopDictLock.release()  #<== snoopDictLock release

	def handleSnoop(self,snooperId, incommingPacket):
		'''
		Fowards incomming packet to snooper if snoop criteria are met (currently, there are no criteria set up)
		'''
		snoopPacket = NetworkPacket(senderId=self.id, destinationId=snooperId, msgType="SNOOP", payload=incommingPacket)
		self.sendPacket(snooperId, snoopPacket)


	def monitorLink(self, agentId):
		agentLink = self.agentConnections[agentId]
		while True:
			self.logger.info("Monitoring {} link {}".format(agentId, agentLink))
			incommingPacket = agentLink.recvPipe.recv()
			self.logger.info("INBOUND {} {}".format(agentId, incommingPacket))
			destinationId = incommingPacket.destinationId

			if (incommingPacket.msgType == "KILL_PIPE_NETWORK"):
					#We've received a kill command for this pipe. Remove destPipe from connections, then kill this monitor thread
					self.logger.info("Killing pipe {} {}".format(agentId, agentLink))
					acquired_agentConnectionsLock = self.agentConnectionsLock.acquire(timeout=self.lockTimeout)  #<== acquire agentConnectionsLock
					if (acquired_agentConnectionsLock):
						del self.agentConnections[incommingPacket.senderId]
						del self.sendLocks[incommingPacket.senderId]
						self.agentConnectionsLock.release()  #<== release agentConnectionsLock
						break
					else:
						self.logger.error("monitorLink() Lock \"agentConnectionsLock\" acquisition timeout")
						break

			elif ("_BROADCAST" in incommingPacket.msgType):
					#Check if this is a KILL_ALL broadcast
					if (incommingPacket.msgType == "KILL_ALL_BROADCAST"):
						self.killAllLock.acquire()
						if (self.killAllFlag):
							#All agents were already killed by another thread. Skip this broadcast
							self.logger.debug("killAllFlag has already been set. Ignoring {}".format(incommingPacket))
							continue

					#We've received a broadcast message. Foward to all pipes
					self.logger.debug("Fowarding broadcast")
					acquired_agentConnectionsLock = self.agentConnectionsLock.acquire()  #<== acquire agentConnectionsLock
					pipeIdList = list(self.agentConnections.keys())
					self.agentConnectionsLock.release()  #<== release agentConnectionsLock

					for pipeId in pipeIdList:
						sendThread = threading.Thread(target=self.sendPacket, args=(pipeId, incommingPacket))
						sendThread.start()

					self.logger.debug("Ending broadcast")

					#CSet killAllFlag
					if (incommingPacket.msgType == "KILL_ALL_BROADCAST"):
						self.logger.debug("Setting killAllFlag")
						self.killAllFlag = True
						self.killAllLock.release()

			elif ("SNOOP_START" in incommingPacket.msgType):
					#We've received a snoop start request. Add to snooping dict
					snoopStartThread = threading.Thread(target=self.setupSnoop, args=(incommingPacket, ))
					snoopStartThread.start()

			elif (destinationId in self.agentConnections):
				#Foward packet to destination
				sendThread = threading.Thread(target=self.sendPacket, args=(destinationId, incommingPacket))
				sendThread.start()

				#Check for active snoops
				if (incommingPacket.msgType in self.snoopDict):
					for snooperId in self.snoopDict[incommingPacket.msgType]:
						snoopThread = threading.Thread(target=self.handleSnoop, args=(snooperId, incommingPacket))
						snoopThread.start()

			else:
				#Invalid packet destination
				errorMsg = "Destination \"{}\" not connected to network".format(destinationId)
				responsePacket = NetworkPacket(senderId=self.id, destinationId=incommingPacket.senderId, msgType="ERROR", payload=errorMsg, transactionId=incommingPacket.transactionId)

				sendThread = threading.Thread(target=self.sendPacket, args=(agentId, responsePacket))
				sendThread.start()

'''
#Format
NetworkPacket.msgType
	Info

#########################
# Network Packets
#########################

KILL_PIPE_AGENT
	If sent to an agent, the agent will send a KILL_PIPE_NETWORK packet to the network, then kill it's monitoring thread

KILL_ALL_BROADCAST
	Equivalent to sending a KILL_PIPE_AGENT to every agent on the network

KILL_PIPE_NETWORK
	If sent from an agent, the connection network will delete it's connection to the agent and kill it's monitoring thread

SNOOP_START
	payload = <dict> {msgType: <bool>, ...}
	If sent from an agent, the network will set up a snoop protocol. Afterwards, all packets with the specified msgTypes (incommingPacket) will be fowarded to the snooper
	in the following format.
		NetworkPacket(destinationId=snooperId, msgType="SNOOP", payload=incommingPacket)

SNOOP
	payload = <NetworkPacket>
	Sent to a snooping controller

ERROR
	If send to an agent, the agent will print out the packet in an error logger. Currently only used for network errors.

#########################
# Trade Packets
#########################

CURRENCY_TRANSFER
	payload = <dict> {"paymentId": <str>, "cents": <int>}
	Transfer currency (amount="cents") from packet sender to packet recipient

CURRENCY_TRANSFER_ACK
	payload = <dict> {"paymentId": <str>, "transferSuccess": <bool>}
	Sent from currency recipient to currency sender

ITEM_TRANSFER
	payload = <dict> {"transferId": <str>, "item": <ItemContainer>}
	Transfer an item from sender to recipient

ITEM_TRANSFER_ACK
	payload = <dict> {"transferId": <str>, "transferSuccess": <bool>}
	Sent from item recipient to item sender

TRADE_REQ
	payload = <TradeRequest>

TRADE_REQ_ACK
	payload = <dict> {"tradeRequest": <TradeRequest>, "accepted": <bool>}

ITEM_MARKET_UPDATE_BROADCAST
	payload = <ItemListing>
	Will update all agent's ItemMarket dictionaries with the included listing info

ITEM_MARKET_REMOVE_BROADCAST
	payload = <ItemListing>
	Will remove an ItemListing from all agent's ItemMarket dictionaries

#########################
# Other Packets
#########################

INFO_REQ
	payload = <InfoRequest>
	Request information from an agent

INFO_RESP
	payload = <InfoRequest>
	Response to information request

CONTROLLER_START
	Tells the agent to start it's controller by caling controller.controllerStart()

CONTROLLER_START_BROADCAST
	Tells all agents to start their controllers by caling controller.controllerStart()

ERROR_CONTROLLER_START
	Sent by an agent if they could not start their controller

CONTROLLER_MSG
	The recipient agent will foward this packet to it's controller

CONTROLLER_MSG_BROADCAST
	All agents will foward this packet to their controller
'''