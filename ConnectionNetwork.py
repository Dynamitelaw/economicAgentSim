import multiprocessing
import threading
import hashlib
import time

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
		return "({}_{}, {}, {})".format(self.msgType, self.hash, self.destinationId, self.transactionId)

class Link:
	def __init__(self, sendPipe, recvPipe):
		self.sendPipe = sendPipe
		self.recvPipe = recvPipe

class ConnectionNetwork:
	def __init__(self, logFile=True):
		self.id = "TransactionNetwork"

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
			for msgType in snoopTypeList:
				if (not msgType in self.snoopDict):
					self.snoopDict[msgType] = {}

				self.logger.debug("Adding snoop {} > {} ({})".format(msgType, snooperId, incommingPacket.payload[msgType]))
				self.snoopDict[msgType][snooperId] = incommingPacket.payload[msgType]

		except Exception as e:
			self.logger.error("Could not setup snoop {} | {}".format(incommingPacket, e))

		self.snoopDictLock.release()  #<== snoopDictLock release

	def handleSnoop(snooperId, incommingPacket):
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
						del self.agentConnections[destinationId]
						del self.sendLocks[destinationId]
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
					snoopStartThread = threading.Thread(target=self.startSnoop, args=(incommingPacket, ))
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


def childWait(conn):
	while True:
		incommingPacket = conn.recv()
		if (incommingPacket == "END"):
			break
		print(incommingPacket.payload)


if __name__ == '__main__':
	parent_conn, child_conn = multiprocessing.Pipe(duplex=True)
	
	childProc = multiprocessing.Process(target=childWait, args=(child_conn,))
	childProc.start()

	#parent_conn.sendPipe.send("Hello")
	#parent_conn.sendPipe.send("World")
	#parent_conn.sendPipe.send("!")
	packet = NetworkPacket("telegram", {"message": "good tidings"})
	parent_conn.sendPipe.send(packet)
	parent_conn.sendPipe.send("END")
	parent_conn.sendPipe.send("Don't see me")

	childProc.join()