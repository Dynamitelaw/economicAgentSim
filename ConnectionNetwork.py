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
		return "({}, {}, {}, {})".format(self.msgType, self.destinationId, self.transactionId, self.hash)

class Link:
	def __init__(self, sendPipe, recvPipe):
		self.sendPipe = sendPipe
		self.recvPipe = recvPipe

class ConnectionNetwork:
	def __init__(self, logFile=True):
		self.logger = utils.getLogger("{}".format(__name__), logFile=logFile)
		self.lockTimeout = 5

		self.agentConnections = {}
		self.agentConnectionsLock = threading.Lock()
		self.sendLocks = {}

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
					#We've received a broadcast message. Foward to all pipes
					self.logger.debug("Fowarding broadcast")
					for pipeId in self.agentConnections:
						sendThread = threading.Thread(target=self.sendPacket, args=(pipeId, incommingPacket))
						sendThread.start()
					self.logger.debug("Ending broadcast")

			elif (destinationId in self.agentConnections):
				#Foward packet to destination
				sendThread = threading.Thread(target=self.sendPacket, args=(destinationId, incommingPacket))
				sendThread.start()

			else:
				#Invalid packet destination
				errorMsg = "Destination \"{}\" not connected to network".format(destinationId)
				responsePacket = NetworkPacket(senderId="TransactionNetwork", destinationId=incommingPacket.sendPipe.senderId, msgType="ERROR", payload=errorMsg, transactionId=incommingPacket.transactionId)

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